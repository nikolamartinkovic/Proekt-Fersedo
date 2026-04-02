import os
import smtplib
from collections import defaultdict
from datetime import datetime, timedelta
from email.utils import formataddr
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

from utils.config import STATIC_FOLDER
from utils.db import get_db


_EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
_EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
_EMAIL_USER = os.getenv("EMAIL_HOST_USER", "")
_EMAIL_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
_EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Info Fersedo")

_LOGO_PATH = os.path.join(STATIC_FOLDER, "logo2.png")


def _get_logo_path():
    if os.path.exists(_LOGO_PATH):
        return _LOGO_PATH
    for name in ("logo2.png", "logo.png", "logo.webp"):
        path = os.path.join(STATIC_FOLDER, name)
        if os.path.exists(path):
            return path
    return None


def _build_email_with_logo(subject, html_body):
    email_user = current_app.config.get("EMAIL_HOST_USER", _EMAIL_USER)
    email_from_name = current_app.config.get("EMAIL_FROM_NAME", _EMAIL_FROM_NAME)
    logo_path = _get_logo_path()
    if logo_path:
        msg_root = MIMEMultipart("related")
        msg_root["From"] = formataddr((email_from_name, email_user))
        msg_root["Subject"] = subject
        msg_alt = MIMEMultipart("alternative")
        msg_alt.attach(MIMEText(html_body, "html", "utf-8"))
        msg_root.attach(msg_alt)
        try:
            with open(logo_path, "rb") as file_obj:
                img_data = file_obj.read()
            img = MIMEImage(img_data)
            img.add_header("Content-ID", "<fersedo_logo>")
            img.add_header("Content-Disposition", "inline", filename="logo.png")
            msg_root.attach(img)
            print(f"[LOGO] Вчитано: {logo_path}")
            return msg_root, True
        except Exception as exc:
            print(f"[LOGO] Грешка при читање: {exc}")
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((email_from_name, email_user))
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg, False


def ensure_odmor_salda_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS odmor_salda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vraboten_id INTEGER NOT NULL,
            godina INTEGER NOT NULL,
            vkupno_dena INTEGER DEFAULT 20,
            UNIQUE(vraboten_id, godina),
            FOREIGN KEY(vraboten_id) REFERENCES vraboteni(id) ON DELETE CASCADE
        )
        """
    )


def ensure_manager_emails_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS otsustva_manager_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            ime TEXT DEFAULT '',
            aktiven INTEGER DEFAULT 1
        )
        """
    )
    columns = {
        row["name"]
        for row in cursor.execute("PRAGMA table_info(otsustva_manager_emails)").fetchall()
    }
    if "dobiva_baranja" not in columns:
        cursor.execute(
            "ALTER TABLE otsustva_manager_emails ADD COLUMN dobiva_baranja INTEGER DEFAULT 0"
        )


def ensure_email_log_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS otsustva_email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip TEXT NOT NULL,
            status TEXT NOT NULL,
            subject TEXT NOT NULL,
            recipients TEXT NOT NULL,
            message TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def log_email_event(email_type, success, subject, recipients, message=""):
    try:
        conn = get_db()
        cursor = conn.cursor()
        ensure_email_log_table(cursor)
        cursor.execute(
            """
            INSERT INTO otsustva_email_log (tip, status, subject, recipients, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                email_type,
                "success" if success else "error",
                subject,
                ", ".join(recipients or []),
                message or "",
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[EMAIL LOG] Грешка: {exc}")


def get_email_log(limit=20):
    try:
        conn = get_db()
        cursor = conn.cursor()
        ensure_email_log_table(cursor)
        conn.commit()
        rows = cursor.execute(
            """
            SELECT id, tip, status, subject, recipients, message, created_at
            FROM otsustva_email_log
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        return rows
    except Exception as exc:
        print(f"[EMAIL LOG] Грешка при читање: {exc}")
        return []


def ensure_salda_for_all(cursor, godina):
    ensure_odmor_salda_table(cursor)
    vraboteni = cursor.execute("SELECT id FROM vraboteni").fetchall()
    for vraboten in vraboteni:
        cursor.execute(
            """
            INSERT OR IGNORE INTO odmor_salda (vraboten_id, godina, vkupno_dena)
            VALUES (?, ?, 20)
            """,
            (vraboten["id"], godina),
        )


def calc_working_days(datum_od, datum_do, praznici):
    try:
        start = datetime.strptime(datum_od, "%Y-%m-%d").date()
        end = datetime.strptime(datum_do, "%Y-%m-%d").date()
    except Exception:
        return 0
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current.strftime("%Y-%m-%d") not in praznici:
            count += 1
        current += timedelta(days=1)
    return count


def get_saldo_all(cursor, godina):
    ensure_salda_for_all(cursor, godina)
    praznici = {row["datum"] for row in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}
    baranja = cursor.execute(
        """
        SELECT vraboten_id, datum_od, datum_do
        FROM baranja_odmor
        WHERE status = 'approved' AND strftime('%Y', datum_od) = ?
        """,
        (str(godina),),
    ).fetchall()
    iskoristeni = defaultdict(int)
    for baranje in baranja:
        iskoristeni[baranje["vraboten_id"]] += calc_working_days(
            baranje["datum_od"], baranje["datum_do"], praznici
        )
    salda = cursor.execute(
        "SELECT vraboten_id, vkupno_dena FROM odmor_salda WHERE godina = ?",
        (godina,),
    ).fetchall()
    result = {}
    for saldo in salda:
        vraboten_id = saldo["vraboten_id"]
        vkupno = saldo["vkupno_dena"]
        iskoristeni_dena = iskoristeni.get(vraboten_id, 0)
        result[vraboten_id] = {
            "vkupno": vkupno,
            "iskoristeni": iskoristeni_dena,
            "preostanati": max(0, vkupno - iskoristeni_dena),
        }
    return result


def _get_manager_emails():
    try:
        conn = get_db()
        cursor = conn.cursor()
        ensure_manager_emails_table(cursor)
        conn.commit()
        rows = cursor.execute(
            "SELECT email FROM otsustva_manager_emails WHERE aktiven = 1"
        ).fetchall()
        conn.close()
        return [row["email"] for row in rows]
    except Exception as exc:
        print(f"[MANAGER EMAIL] Грешка: {exc}")
        return []


def get_baranje_notification_target():
    try:
        conn = get_db()
        cursor = conn.cursor()
        ensure_manager_emails_table(cursor)
        conn.commit()
        row = cursor.execute(
            """
            SELECT ime, email
            FROM otsustva_manager_emails
            WHERE aktiven = 1 AND COALESCE(dobiva_baranja, 0) = 1
            ORDER BY ime, email
            LIMIT 1
            """
        ).fetchone()
        conn.close()
        if not row or not (row["email"] or "").strip():
            return None
        return {"ime": (row["ime"] or "").strip(), "email": (row["email"] or "").strip()}
    except Exception as exc:
        print(f"[BARANJE EMAIL] Грешка: {exc}")
        return None


def _isprati_email_do_menadzeri(emails, subject, html, log_prefix="[EMAIL]"):
    if not emails:
        print(f"{log_prefix} \u041d\u0435\u043c\u0430 \u043f\u0440\u0438\u043c\u0430\u0447\u0438.")
        return {"success": False, "message": "\u041d\u0435\u043c\u0430 \u0430\u043a\u0442\u0438\u0432\u043d\u0438 \u043f\u0440\u0438\u043c\u0430\u0447\u0438."}

    try:
        email_host = current_app.config.get("EMAIL_HOST", _EMAIL_HOST)
        email_port = current_app.config.get("EMAIL_PORT", _EMAIL_PORT)
        email_user = current_app.config.get("EMAIL_HOST_USER", _EMAIL_USER)
        email_password = current_app.config.get("EMAIL_HOST_PASSWORD", _EMAIL_PASSWORD)
        msg, has_logo = _build_email_with_logo(subject, html)
        msg["To"] = ", ".join(emails)

        with smtplib.SMTP(email_host, email_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_user, email_password)
            server.sendmail(email_user, emails, msg.as_string())

        print(f"{log_prefix} \u0418\u0441\u043f\u0440\u0430\u0442\u0435\u043d\u043e \u0434\u043e: {emails} (\u043b\u043e\u0433\u043e: {'\u0434\u0430' if has_logo else '\u043d\u0435'})")
        return {"success": True, "message": f"\u0418\u0441\u043f\u0440\u0430\u0442\u0435\u043d\u043e \u0434\u043e {', '.join(emails)}."}
    except Exception as exc:
        print(f"{log_prefix} \u0413\u0440\u0435\u0448\u043a\u0430: {exc}")
        return {"success": False, "message": str(exc)}


def isprati_izvestuvanje_za_novo_baranje(
    ime_prezime,
    datum_od,
    datum_do,
    working_days,
    zabeleska,
    podneseno_od,
    podneseno_na,
):
    recipient = get_baranje_notification_target()
    if not recipient or not recipient.get("email"):
        return {
            "success": False,
            "message": "Нема активни примачи за известување за ново барање.",
        }

    def fmt(datum_text):
        try:
            return datetime.strptime(datum_text, "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            return datum_text

    recipient_name = recipient["ime"] or recipient["email"]
    subject = f"Ново барање за одмор - {ime_prezime}"
    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;background:#f5f7fb;padding:24px;color:#1f2b43;">
        <div style="max-width:720px;margin:auto;background:#ffffff;border-radius:16px;padding:28px;border:1px solid #d7e0f0;">
            <h2 style="margin-top:0;color:#1f2b43;">Ново барање за одмор</h2>
            <p style="font-size:15px;line-height:1.6;">
                Поднесено е ново барање за одмор и ова известување е испратено до:
                <strong>{recipient_name}</strong>.
            </p>
            <table style="width:100%;border-collapse:collapse;margin-top:18px;">
                <tr><td style="padding:10px;border-bottom:1px solid #e6ebf5;"><strong>Вработен:</strong></td><td style="padding:10px;border-bottom:1px solid #e6ebf5;">{ime_prezime}</td></tr>
                <tr><td style="padding:10px;border-bottom:1px solid #e6ebf5;"><strong>Од:</strong></td><td style="padding:10px;border-bottom:1px solid #e6ebf5;">{fmt(datum_od)}</td></tr>
                <tr><td style="padding:10px;border-bottom:1px solid #e6ebf5;"><strong>До:</strong></td><td style="padding:10px;border-bottom:1px solid #e6ebf5;">{fmt(datum_do)}</td></tr>
                <tr><td style="padding:10px;border-bottom:1px solid #e6ebf5;"><strong>Работни денови:</strong></td><td style="padding:10px;border-bottom:1px solid #e6ebf5;">{working_days}</td></tr>
                <tr><td style="padding:10px;border-bottom:1px solid #e6ebf5;"><strong>Поднесено од:</strong></td><td style="padding:10px;border-bottom:1px solid #e6ebf5;">{podneseno_od}</td></tr>
                <tr><td style="padding:10px;border-bottom:1px solid #e6ebf5;"><strong>Поднесено на:</strong></td><td style="padding:10px;border-bottom:1px solid #e6ebf5;">{podneseno_na}</td></tr>
                <tr><td style="padding:10px;vertical-align:top;"><strong>Забелешка:</strong></td><td style="padding:10px;">{zabeleska or '-'}</td></tr>
            </table>
        </div>
    </body>
    </html>
    """
    return _isprati_email_do_menadzeri(
        [recipient["email"]],
        subject,
        html,
        log_prefix="[EMAIL ODMOR БАРАЊЕ]",
    )


def _get_odmori_for_date(cursor, date_str, praznici):
    rows = cursor.execute(
        """
        SELECT v.ime, v.prezime, b.datum_od, b.datum_do, b.zabeleska
        FROM baranja_odmor b
        JOIN vraboteni v ON b.vraboten_id = v.id
        WHERE b.status = 'approved'
          AND b.datum_od <= ?
          AND b.datum_do >= ?
        ORDER BY v.prezime, v.ime
        """,
        (date_str, date_str),
    ).fetchall()

    result = []
    for row in rows:
        working_days = calc_working_days(row["datum_od"], row["datum_do"], praznici)
        result.append(
            {
                "ime": row["ime"],
                "prezime": row["prezime"],
                "datum_od": row["datum_od"],
                "datum_do": row["datum_do"],
                "working_days": working_days,
                "zabeleska": row["zabeleska"] or "",
            }
        )
    return result


def _get_odmori_for_range(cursor, date_from_str, date_to_str, praznici):
    rows = cursor.execute(
        """
        SELECT v.ime, v.prezime, b.datum_od, b.datum_do, b.zabeleska
        FROM baranja_odmor b
        JOIN vraboteni v ON b.vraboten_id = v.id
        WHERE b.status = 'approved'
          AND b.datum_od <= ?
          AND b.datum_do >= ?
        ORDER BY b.datum_od ASC, v.prezime, v.ime
        """,
        (date_to_str, date_from_str),
    ).fetchall()

    result = []
    for row in rows:
        working_days = calc_working_days(row["datum_od"], row["datum_do"], praznici)
        result.append(
            {
                "ime": row["ime"],
                "prezime": row["prezime"],
                "datum_od": row["datum_od"],
                "datum_do": row["datum_do"],
                "working_days": working_days,
                "zabeleska": row["zabeleska"] or "",
            }
        )
    return result
