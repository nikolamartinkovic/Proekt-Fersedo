# routes/main.py
import os
import smtplib
import sqlite3
from datetime import date, datetime, timedelta
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Blueprint, flash, redirect, render_template, request, session, url_for, send_from_directory
from utils.db import get_db
from utils.decorators import login_required, admin_required, module_required
from utils.config import STATIC_FOLDER, POZICII_FOLDER
from utils.odmori_helpers import isprati_izvestuvanje_za_novo_baranje

main_bp = Blueprint('main', __name__)

WELCOME_MODULES = [
    {"value": "dashboard", "label": "Dashboard", "description": "Преглед на системот и клучните податоци.", "endpoint": "admin.dashboard", "icon": "fas fa-chart-line", "group": "Админ"},
    {"value": "system_logs", "label": "Системски логови", "description": "Следење на runtime, audit и email логови.", "endpoint": "admin.system_logs", "icon": "fas fa-wave-square", "group": "Админ"},
    {"value": "pregled_greski", "label": "Грешки", "description": "Преглед и анализа на внесените грешки.", "endpoint": "admin.pregled_greski", "icon": "fas fa-triangle-exclamation", "group": "Админ"},
    {"value": "admin_users", "label": "Корисници", "description": "Управување со корисници и дозволи.", "endpoint": "admin.admin_users", "icon": "fas fa-users-cog", "group": "Админ"},
    {"value": "email_recipients", "label": "Email примачи", "description": "Поставки за системски и автоматски email известувања.", "endpoint": "admin.email_recipients", "icon": "fas fa-envelope-open-text", "group": "Админ"},
    {"value": "procesni_cekori", "label": "Процесни чекори", "description": "Шаблони и чекори за производни процеси.", "endpoint": "admin.procesni_cekori", "icon": "fas fa-cogs", "group": "Админ"},
    {"value": "select_kamin", "label": "Нов запис", "description": "Брз влез за нов производствен запис.", "endpoint": "main.select_kamin", "icon": "fas fa-plus-circle", "group": "Производство"},
    {"value": "add_part", "label": "Отвори нов артикл", "description": "Креирање на нов артикл и негови параметри.", "endpoint": "artikli.add", "icon": "fas fa-box-open", "group": "Производство"},
    {"value": "moj_zapisi", "label": "Мои записи", "description": "Лична листа на внесени записи.", "endpoint": "main.moj_zapisi", "icon": "fas fa-list", "group": "Производство"},
    {"value": "kalkulacija", "label": "Калкулација", "description": "Пресметки и работни цени по операции.", "endpoint": "main.kalkulacija", "icon": "fas fa-calculator", "group": "Производство"},
    {"value": "artikli", "label": "Артикли", "description": "Преглед и уредување на артикли.", "endpoint": "artikli.artikli", "icon": "fas fa-boxes-stacked", "group": "Производство"},
    {"value": "plan_proizvodstvo", "label": "План за производство", "description": "Планирање и следење на производни активности.", "endpoint": "main.plan_proizvodstvo", "icon": "fas fa-calendar-check", "group": "Производство"},
    {"value": "izvestaj", "label": "Извештај", "description": "Извештаи и пресек на работата.", "endpoint": "main.izvestaj", "icon": "fas fa-file-alt", "group": "Производство"},
    {"value": "zalihi", "label": "Залихи", "description": "Состојба и движења на залихите.", "endpoint": "zalihi.zalihi", "icon": "fas fa-warehouse", "group": "Залихи"},
    {"value": "kvalitet", "label": "Квалитет", "description": "Преглед на активни контроли за квалитет.", "endpoint": "kvalitet.kvalitet", "icon": "fas fa-check-circle", "group": "Квалитет"},
    {"value": "kvalitet_nova", "label": "Нова контрола", "description": "Започни нова контрола за квалитет.", "endpoint": "kvalitet.kvalitet_select_kamin", "icon": "fas fa-clipboard-check", "group": "Квалитет"},
    {"value": "kvalitet_arhiva", "label": "Архива на контроли", "description": "Историја на претходно завршени контроли.", "endpoint": "kvalitet.kvalitet_arhiva", "icon": "fas fa-folder-open", "group": "Квалитет"},
    {"value": "kvalitet_template", "label": "QC шаблони", "description": "Управување со шаблони за контрола.", "endpoint": "kvalitet.kvalitet_template_manager", "icon": "fas fa-sliders", "group": "Квалитет"},
    {"value": "nabavki", "label": "Набавки", "description": "Тековни барања и процес на набавки.", "endpoint": "nabavki.nabavki", "icon": "fas fa-shopping-cart", "group": "Набавки"},
    {"value": "nabavki_arhiva", "label": "Архива на набавки", "description": "Архивирани барања и историја на набавки.", "endpoint": "nabavki.arhiva", "icon": "fas fa-archive", "group": "Набавки"},
    {"value": "ponudi", "label": "Понуди", "description": "Активни понуди и нивно следење.", "endpoint": "ponudi.ponudi", "icon": "fas fa-file-invoice-dollar", "group": "Набавки"},
    {"value": "ponudi_arhiva", "label": "Архива на понуди", "description": "Историја на стари понуди.", "endpoint": "ponudi.arhiva", "icon": "fas fa-box-archive", "group": "Набавки"},
    {"value": "sostanoci", "label": "Состаноци", "description": "Записи и преглед на состаноци.", "endpoint": "sostanoci.lista", "icon": "fas fa-microphone", "group": "Комуникација"},
    {"value": "chat", "label": "Чат", "description": "Внатрешна комуникација со тимот.", "endpoint": "chat.chat_page", "icon": "fas fa-comments", "group": "Комуникација"},
    {"value": "odmori", "label": "Одмори", "description": "Главен екран за управување со одмори.", "endpoint": "main.odmori", "icon": "fas fa-umbrella-beach", "group": "Одмори"},
    {"value": "baranje_odmor", "label": "Барање за одмор", "description": "Поднесување ново барање за одмор.", "endpoint": "main.baranje_odmor", "icon": "fas fa-file-signature", "group": "Одмори"},
    {"value": "odmori_vraboteni", "label": "Вработени", "description": "Листа на вработени во модулот за одмори.", "endpoint": "odmori.odmori_vraboteni", "icon": "fas fa-users", "group": "Одмори"},
    {"value": "odmori_kalendar", "label": "Календар", "description": "Календарски приказ на одмори и отсуства.", "endpoint": "odmori.odmori_kalendar", "icon": "fas fa-calendar-alt", "group": "Одмори"},
    {"value": "odmori_pregled_odmori", "label": "Преглед на одмори", "description": "Преглед и одобрување на поднесени барања.", "endpoint": "odmori.odmori_pregled_odmori", "icon": "fas fa-list-check", "group": "Одмори"},
    {"value": "odmori_sekojdnevni_otsustva", "label": "Секојдневни отсуства", "description": "Дневен приказ на присуства и отсуства.", "endpoint": "odmori.odmori_sekojdnevni_otsustva", "icon": "fas fa-user-clock", "group": "Одмори"},
    {"value": "odmori_manager_emails", "label": "Email за менаџери", "description": "Поставки и тестирање на известувања за менаџери.", "endpoint": "odmori.odmori_manager_emails", "icon": "fas fa-envelope-open-text", "group": "Одмори"},
]


def _get_welcome_module_cards():
    if session.get("is_admin"):
        return [
            {**item, "href": url_for(item["endpoint"])}
            for item in WELCOME_MODULES
        ]

    allowed = {
        module.strip()
        for module in (session.get("allowed_modules") or "").split(",")
        if module.strip()
    }
    return [
        {**item, "href": url_for(item["endpoint"])}
        for item in WELCOME_MODULES
        if item["value"] in allowed
    ]

# ─────────────────────────────────────────────────────────────
# EMAIL КОНФИГУРАЦИЈА
# ─────────────────────────────────────────────────────────────
_EMAIL_HOST     = "smtp.gmail.com"
_EMAIL_PORT     = 587
_EMAIL_USER     = "fersedoo@gmail.com"
_EMAIL_PASSWORD = "ejvu srce tvls wqtw"
_EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Info Fersedo")


def _get_odmor_notification_targets(cursor):
    targets = []
    seen_emails = set()

    try:
        ensure_manager_emails_table(cursor)
        manager_rows = cursor.execute(
            """
            SELECT id, ime, email
            FROM otsustva_manager_emails
            WHERE aktiven = 1
            ORDER BY ime, email
            """
        ).fetchall()
        for row in manager_rows:
            email = (row["email"] or "").strip()
            if not email or email.lower() in seen_emails:
                continue
            seen_emails.add(email.lower())
            name = (row["ime"] or "").strip() or email
            targets.append(
                {
                    "key": f"manager:{row['id']}",
                    "email": email,
                    "name": name,
                    "label": f"{name} ({email})",
                    "source": "manager_email",
                }
            )
    except Exception:
        pass

    user_rows = cursor.execute(
        """
        SELECT username, email
        FROM users
        WHERE email IS NOT NULL AND TRIM(email) != ''
        ORDER BY username
        """
    ).fetchall()
    for row in user_rows:
        email = (row["email"] or "").strip()
        if not email or email.lower() in seen_emails:
            continue
        seen_emails.add(email.lower())
        username = (row["username"] or "").strip() or email
        targets.append(
            {
                "key": f"user:{username}",
                "email": email,
                "name": username,
                "label": f"{username} ({email})",
                "source": "user",
            }
        )

    return targets


def _isprati_baranje_notification_email(
    recipient_email,
    recipient_name,
    ime_prezime,
    datum_od,
    datum_do,
    working_days,
    zabeleska,
    podneseno_od,
    podneseno_na,
):
    if not recipient_email:
        return

    def fmt(datum_text):
        try:
            return datetime.strptime(datum_text, "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            return datum_text

    subject = f"Ново барање за одмор - {ime_prezime}"
    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;background:#f5f7fb;padding:24px;color:#1f2b43;">
        <div style="max-width:720px;margin:auto;background:#ffffff;border-radius:16px;padding:28px;border:1px solid #d7e0f0;">
            <h2 style="margin-top:0;color:#1f2b43;">Ново барање за одмор</h2>
            <p style="font-size:15px;line-height:1.6;">
                До <strong>{recipient_name or recipient_email}</strong> е испратено известување за ново поднесено барање.
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

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((_EMAIL_FROM_NAME, _EMAIL_USER))
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(_EMAIL_HOST, _EMAIL_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(_EMAIL_USER, _EMAIL_PASSWORD)
            server.sendmail(_EMAIL_USER, [recipient_email], msg.as_string())
        print(f"[EMAIL ODMOR NOTIFY] Испратено до {recipient_email}")
    except Exception as exc:
        flash(f"Известувањето до {recipient_email} не беше испратено: {exc}", "warning")
        print(f"[EMAIL ODMOR NOTIFY] Грешка: {exc}")


# ─────────────────────────────────────────────────────────────
# STATIC FILE ROUTES
# ─────────────────────────────────────────────────────────────

KAMINI_FOLDER = r"C:\Users\Server\Desktop\Proekt Fersedo\static\kamini"

@main_bp.route("/kamini-img/<path:filename>")
def kamin_static(filename):
    return send_from_directory(KAMINI_FOLDER, filename)

@main_bp.route("/pozicii/<path:filename>")
def pozicii_static(filename):
    return send_from_directory(POZICII_FOLDER, filename)


@main_bp.route("/welcome")
@login_required
def welcome():
    module_cards = _get_welcome_module_cards()
    if not session.get("is_admin") and not module_cards:
        flash("Немате дозволен пристап до ниту еден модул. Контактирајте го администраторот.", "warning")
        return redirect(url_for("auth.login"))

    return render_template(
        "welcome.html",
        module_cards=module_cards,
        user_name=session.get("user", ""),
        is_admin=session.get("is_admin", False),
        user_group=session.get("user_group", ""),
    )


# ─────────────────────────────────────────────────────────────
# SELECT KAMIN
# ─────────────────────────────────────────────────────────────
@main_bp.route("/select_kamin")
@login_required
def select_kamin():
    conn = get_db()
    kamini = [k["ime"] for k in conn.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()]
    conn.close()
    return render_template("select_kamin.html", kamini=kamini)

@main_bp.route("/select_kamin_type/<kamin>")
@login_required
def select_kamin_type(kamin):
    return render_template("select_kamin_type.html", kamin=kamin)

@main_bp.route("/add_kamin", methods=["GET", "POST"])
@login_required
def add_kamin():
    conn = get_db()
    cursor = conn.cursor()
    if request.method == "POST":
        ime = request.form.get("ime", "").strip()
        if ime:
            try:
                cursor.execute("INSERT INTO kamini (ime) VALUES (?)", (ime,))
                conn.commit()
                flash(f'Каминот "{ime}" е успешно додаден!', "success")
                conn.close()
                return redirect(url_for("main.select_kamin"))
            except sqlite3.IntegrityError:
                flash(f'Каминот "{ime}" веќе постои!', "error")
        else:
            flash("Внеси ime на камин!", "error")
    conn.close()
    return render_template("add_kamin.html")

@main_bp.route("/delete_kamin", methods=["GET", "POST"])
@login_required
def delete_kamin():
    conn = get_db()
    cursor = conn.cursor()
    if request.method == "POST":
        selected = request.form.getlist("selected_kamini")
        if selected:
            placeholders = ",".join("?" for _ in selected)
            cursor.execute(f"DELETE FROM kamini WHERE ime IN ({placeholders})", selected)
            conn.commit()
            flash(f"Избраните {len(selected)} камини се успешно избришани!", "success")
        else:
            flash("Нема избрани камини за бришење", "error")
        conn.close()
        return redirect(url_for("main.select_kamin"))
    kamini = [r["ime"] for r in cursor.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()]
    conn.close()
    return render_template("delete_kamin.html", kamini=kamini)


# ─────────────────────────────────────────────────────────────
# PRODUCTION INPUT
# ─────────────────────────────────────────────────────────────
@main_bp.route("/add_gotov/<kamin>", methods=["GET", "POST"])
@login_required
def add_gotov(kamin):
    conn = get_db()
    cursor = conn.cursor()
    plan_exists = cursor.execute("SELECT plan_kolicina FROM planovi WHERE kamin = ?", (kamin,)).fetchone()
    has_plan = plan_exists is not None and plan_exists["plan_kolicina"] > 0
    if request.method == "POST":
        if not has_plan:
            flash("Нема поставен план за производство! Прво додај план.", "error")
            conn.close()
            return redirect(url_for("main.select_kamin"))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO performance
                (datum, oddel, proizvod, proizvedeni, greski, vid_greska, zabeleska,
                 username, timestamp, kamin, part_number, tip_proizvod)
                VALUES (?, ?, ?, ?, 0, '-', ?, ?, ?, ?, ?, 'gotov')
            """, (
                request.form.get("datum", date.today().isoformat()),
                request.form.get("oddel", ""),
                request.form.get("proizvod", kamin),
                int(request.form.get("proizvedeni", 0)),
                request.form.get("zabeleska", ""),
                session["user"], now, kamin,
                request.form.get("part_number", ""),
            ))
            conn.commit()
            flash(f"Готов производ зачуван за {kamin}!", "success")
            conn.close()
            return redirect(url_for("main.select_kamin"))
        except Exception as e:
            flash(f"Грешка: {e}", "error")
        finally:
            conn.close()
    conn.close()
    return render_template("add_gotov.html", today=date.today().isoformat(), kamin=kamin, has_plan=has_plan)

@main_bp.route("/add_polugotov/<kamin>", methods=["GET", "POST"])
@login_required
def add_polugotov(kamin):
    conn = get_db()
    cursor = conn.cursor()
    if request.method == "POST":
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO performance
                (datum, oddel, proizvod, proizvedeni, greski, vid_greska, zabeleska,
                 username, timestamp, kamin, part_number, tip_proizvod)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'polugotov')
            """, (
                request.form.get("datum", date.today().isoformat()),
                request.form.get("oddel", "").strip(),
                kamin,
                int(request.form.get("proizvedeni", 0)),
                int(request.form.get("greski", 0)),
                request.form.get("vid_greska", "-").strip(),
                request.form.get("zabeleska", "").strip(),
                session["user"], now, kamin,
                request.form.get("part_number", "").strip(),
            ))
            conn.commit()
            flash(f"Полуготов производ зачуван за {kamin}!", "success")
            conn.close()
            return redirect(url_for("main.select_kamin"))
        except Exception as e:
            flash(f"Грешка при зачувување: {e}", "error")
            conn.rollback()
        finally:
            conn.close()
    conn.close()
    return render_template("add_polugotov.html", today=date.today().isoformat(), kamin=kamin)

@main_bp.route("/moj_zapisi", methods=["GET", "POST"])
@login_required
def moj_zapisi():
    conn = get_db()
    cursor = conn.cursor()
    if request.method == "POST" and request.form.get("action") == "delete":
        tip = request.form.get("tip")
        selected_ids = request.form.getlist("selected_ids")
        if selected_ids:
            placeholders = ",".join("?" for _ in selected_ids)
            cursor.execute(
                f"DELETE FROM performance WHERE id IN ({placeholders}) AND username = ? AND tip_proizvod = ?",
                (*selected_ids, session["user"], tip),
            )
            conn.commit()
            flash(f"Успешно избришани {cursor.rowcount} записи!", "success")
        else:
            flash("Нема избрани записи за бришење", "error")
    gotivi = cursor.execute("""
        SELECT id, datum, timestamp, oddel, proizvod, proizvedeni, greski, vid_greska,
               zabeleska, username, kamin, part_number
        FROM performance WHERE username = ? AND tip_proizvod = 'gotov' ORDER BY timestamp DESC
    """, (session["user"],)).fetchall()
    polugotovi = cursor.execute("""
        SELECT id, datum, timestamp, oddel, proizvod, proizvedeni, greski, vid_greska,
               zabeleska, username, kamin, part_number
        FROM performance WHERE username = ? AND tip_proizvod = 'polugotov' ORDER BY timestamp DESC
    """, (session["user"],)).fetchall()
    conn.close()
    return render_template("moj_zapisi.html", gotivi=gotivi, polugotovi=polugotovi)


# ─────────────────────────────────────────────────────────────
# ОДМОРИ — главна страница
# ─────────────────────────────────────────────────────────────

@main_bp.route("/odmori")
@login_required
def odmori():
    if not session.get("is_admin"):
        allowed = {
            module.strip()
            for module in (session.get("allowed_modules") or "").split(",")
            if module.strip()
        }
        if "odmori" not in allowed:
            redirect_map = [
                ("baranje_odmor", "main.baranje_odmor"),
                ("odmori_vraboteni", "odmori.odmori_vraboteni"),
                ("odmori_kalendar", "odmori.odmori_kalendar"),
                ("odmori_pregled_odmori", "odmori.odmori_pregled_odmori"),
                ("odmori_sekojdnevni_otsustva", "odmori.odmori_sekojdnevni_otsustva"),
                ("odmori_manager_emails", "odmori.odmori_manager_emails"),
            ]
            for module_name, endpoint in redirect_map:
                if module_name in allowed:
                    return redirect(url_for(endpoint))
            flash("Немате дозвола за пристап до модулот Одмори.", "warning")
            return redirect(url_for("auth.index"))
    return render_template("odmori.html")

# ─────────────────────────────────────────────────────────────
# КАЛКУЛАЦИЈА
# ─────────────────────────────────────────────────────────────
@main_bp.route("/kalkulacija", methods=["GET", "POST"])
@login_required
@admin_required
def kalkulacija():
    conn = get_db()
    cursor = conn.cursor()
    if request.method == "POST":
        if "update_cene" in request.form:
            price_fields = ["laser", "apkant", "rolovanje", "zavaruvanje", "brusenje", "drvara", "sachmara", "farbara"]
            for field in price_fields:
                cursor.execute(f"UPDATE parts SET cena_po_cas_{field} = ?", (float(request.form.get(f"cena_{field}", 0)),))
            conn.commit()
            flash("Цените по час се успешно зачувани!", "success")
            conn.close()
            return redirect(url_for("main.kalkulacija"))
        for artikal_id in request.form.getlist("artikal_id"):
            laser = 1 if request.form.get(f"laser_{artikal_id}") else 0
            apkant = 1 if request.form.get(f"apkant_{artikal_id}") else 0
            cursor.execute("""
                UPDATE parts SET laser=?, laser_vreme=?, apkant=?, apkant_vreme=? WHERE id=?
            """, (laser, int(request.form.get(f"laser_vreme_{artikal_id}", 0)) if laser else 0,
                  apkant, int(request.form.get(f"apkant_vreme_{artikal_id}", 0)) if apkant else 0,
                  artikal_id))
        conn.commit()
        flash("Калкулацијата е успешно зачувана!", "success")
        conn.close()
        return redirect(url_for("main.kalkulacija"))
    artikli_list = cursor.execute("""
        SELECT id, part_number, kamin, vid_artikal,
               laser, laser_vreme, apkant, apkant_vreme,
               mashina_rolovanje, mashina_rolovanje_vreme,
               zavaruvanje, zavaruvanje_vreme, brusenje, brusenje_vreme,
               drvara, drvara_vreme, sachmara, sachmara_vreme, farbara, farbara_vreme,
               cena_po_cas_laser, cena_po_cas_apkant, cena_po_cas_rolovanje,
               cena_po_cas_zavaruvanje, cena_po_cas_brusenje, cena_po_cas_drvara,
               cena_po_cas_sachmara, cena_po_cas_farbara
        FROM parts ORDER BY part_number
    """).fetchall()
    ceni = artikli_list[0] if artikli_list else {}
    conn.close()
    return render_template("kalkulacija.html", artikli=artikli_list, ceni=ceni)


# ─────────────────────────────────────────────────────────────
# ПЛАН ЗА ПРОИЗВОДСТВО
# ─────────────────────────────────────────────────────────────
@main_bp.route("/plan_proizvodstvo", methods=["GET", "POST"])
@login_required
@admin_required
def plan_proizvodstvo():
    conn = get_db()
    cursor = conn.cursor()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            kamin = request.form.get("kamin")
            plan_kolicina = int(request.form.get("plan_kolicina", 0))
            datum_od = request.form.get("datum_od")
            datum_do = request.form.get("datum_do")
            if kamin and plan_kolicina > 0 and datum_od and datum_do:
                cursor.execute(
                    "UPDATE planovi SET plan_kolicina=?, datum_od=?, datum_do=? WHERE kamin=?",
                    (plan_kolicina, datum_od, datum_do, kamin),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO planovi (kamin, plan_kolicina, datum_od, datum_do) VALUES (?, ?, ?, ?)",
                        (kamin, plan_kolicina, datum_od, datum_do),
                    )
                conn.commit()
                flash(f"Планот за {kamin} е зачуван!", "success")
            else:
                flash("Пополни ги сите полиња!", "error")
        elif action == "delete":
            selected_ids = request.form.getlist("selected_ids")
            if selected_ids:
                placeholders = ",".join("?" for _ in selected_ids)
                cursor.execute(f"DELETE FROM planovi WHERE id IN ({placeholders})", selected_ids)
                conn.commit()
                flash(f"Избришани {len(selected_ids)} планови!", "success")
    kamini = [r["ime"] for r in cursor.execute("SELECT ime FROM kamini").fetchall()]
    planovi = cursor.execute("""
        SELECT p.id, p.kamin, p.plan_kolicina, p.datum_od, p.datum_do,
               COALESCE(SUM(pe.proizvedeni), 0) AS proizvedeni,
               p.plan_kolicina - COALESCE(SUM(pe.proizvedeni), 0) AS razlika
        FROM planovi p
        LEFT JOIN performance pe
            ON p.kamin = pe.kamin AND pe.tip_proizvod = 'gotov'
            AND pe.datum >= p.datum_od AND pe.datum <= p.datum_do
        GROUP BY p.id, p.kamin, p.plan_kolicina, p.datum_od, p.datum_do
        ORDER BY p.kamin, p.datum_od
    """).fetchall()
    conn.close()
    return render_template("plan_proizvodstvo.html", kamini=kamini, planovi=planovi)


# ─────────────────────────────────────────────────────────────
# ИЗВЕШТАЈ
# ─────────────────────────────────────────────────────────────
@main_bp.route("/izvestaj")
@login_required
@admin_required
def izvestaj():
    from datetime import timedelta
    period = request.args.get("period", "week")
    today = datetime.today().date()
    if period == "week":
        datum_od = today - timedelta(days=today.weekday() + 7)
        datum_do = today - timedelta(days=today.weekday() + 1)
        title = "Извештај за последната недела"
    elif period == "current_week":
        datum_od = today - timedelta(days=today.weekday())
        datum_do = today
        title = "Извештај за тековната недела"
    elif period == "month":
        datum_od = (today - timedelta(days=today.day)).replace(day=1)
        datum_do = today - timedelta(days=today.day)
        title = "Извештај за последниот месец"
    else:
        q = (today.month - 1) // 3 + 1
        q_start_month = (q - 1) * 3 + 1
        q_end_month = q_start_month + 2
        datum_od = datetime(today.year, q_start_month, 1).date()
        next_month = q_end_month + 1 if q_end_month < 12 else 1
        next_year = today.year if q_end_month < 12 else today.year + 1
        datum_do = datetime(next_year, next_month, 1).date() - timedelta(days=1)
        title = "Квартален извештај"
    datum_od_str = datum_od.isoformat()
    datum_do_str = datum_do.isoformat()
    datum_do_plus = (datum_do + timedelta(days=1)).isoformat()
    conn = get_db()
    cursor = conn.cursor()
    summary = cursor.execute("""
        SELECT SUM(proizvedeni) AS total_proizvedeni, SUM(greski) AS total_greski,
               ROUND(AVG(100 - (greski / NULLIF(proizvedeni, 0) * 100)), 1) AS pros_efektivnost
        FROM performance
        WHERE datum >= ? AND datum < ? AND tip_proizvod = 'polugotov'
    """, (datum_od_str, datum_do_plus)).fetchone()
    po_oddel = cursor.execute("""
        SELECT oddel, SUM(proizvedeni) AS proizvedeni, SUM(greski) AS greski,
               ROUND(AVG(100 - (greski / NULLIF(proizvedeni, 0) * 100)), 1) AS efektivnost
        FROM performance
        WHERE datum >= ? AND datum < ? AND tip_proizvod = 'polugotov'
        GROUP BY oddel
    """, (datum_od_str, datum_do_plus)).fetchall()
    conn.close()
    return render_template("izvestaj.html", title=title, datum_od=datum_od_str,
                           datum_do=datum_do_str, summary=summary, po_oddel=po_oddel)


# ─────────────────────────────────────────────────────────────
# БАРАЊЕ ЗА ОДМОР
# ─────────────────────────────────────────────────────────────

@main_bp.route("/baranje_odmor", methods=["GET", "POST"])
@login_required
@module_required("baranje_odmor")
def baranje_odmor():
    from datetime import date as dt_date
    conn   = get_db()
    cursor = conn.cursor()
    vraboteni = cursor.execute("SELECT id, ime, prezime FROM vraboteni ORDER BY prezime, ime").fetchall()
    if request.method == "POST":
        _email_data = None

        try:
            vraboten_id = request.form.get("vraboten_id")
            datum_od    = request.form.get("datum_od")
            datum_do    = request.form.get("datum_do")
            zabeleska   = request.form.get("zabeleska", "").strip()

            if not vraboten_id:
                flash("Мора да изберете вработен!", "danger")
                raise ValueError()
            if not datum_od or not datum_do:
                flash("Мора да ги внесете двата датуми!", "danger")
                raise ValueError()

            od_date = datetime.strptime(datum_od, "%Y-%m-%d").date()
            do_date = datetime.strptime(datum_do, "%Y-%m-%d").date()
            today   = dt_date.today()

            if od_date < today:
                flash("Не можете да барате одмор во минатото!", "danger")
                raise ValueError()
            if od_date > do_date:
                flash('Датумот "Од" не може да биде после "До"!', "danger")
                raise ValueError()

            conflict = cursor.execute("""
                SELECT id FROM baranja_odmor
                WHERE vraboten_id=? AND status='approved'
                  AND (datum_od <= ? AND datum_do >= ?)
            """, (vraboten_id, datum_do, datum_od)).fetchone()
            if conflict:
                flash("Вработениот веќе има одобрен одмор во избраниот период!", "danger")
                raise ValueError()

            cursor.execute("""
                INSERT INTO baranja_odmor
                    (vraboten_id, datum_od, datum_do, status, zabeleska, podneseno_od, podneseno_na)
                VALUES (?,?,?,'pending',?,?,CURRENT_TIMESTAMP)
            """, (vraboten_id, datum_od, datum_do, zabeleska, session["user"]))
            conn.commit()
            flash("Барањето е успешно поднесено и чека одобрување!", "success")

            praznici = {
                r["datum"] for r in
                cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()
            }
            working_days = 0
            cur = od_date
            while cur <= do_date:
                if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in praznici:
                    working_days += 1
                cur += timedelta(days=1)

            v_row = cursor.execute(
                "SELECT ime, prezime, email FROM vraboteni WHERE id=?", (vraboten_id,)
            ).fetchone()

            godina      = od_date.year
            saldo_row   = cursor.execute(
                "SELECT vkupno_dena FROM odmor_salda WHERE vraboten_id=? AND godina=?",
                (vraboten_id, godina)
            ).fetchone()
            vkupno_dena = saldo_row["vkupno_dena"] if saldo_row else 20

            iskoristeni_rows = cursor.execute("""
                SELECT datum_od, datum_do FROM baranja_odmor
                WHERE vraboten_id=? AND status='approved'
                  AND strftime('%Y', datum_od)=?
            """, (vraboten_id, str(godina))).fetchall()
            iskoristeni = 0
            praznici_set = praznici
            for r in iskoristeni_rows:
                s = datetime.strptime(r["datum_od"], "%Y-%m-%d").date()
                e = datetime.strptime(r["datum_do"], "%Y-%m-%d").date()
                c = s
                while c <= e:
                    if c.weekday() < 5 and c.strftime("%Y-%m-%d") not in praznici_set:
                        iskoristeni += 1
                    c += timedelta(days=1)
            preostanati_po_baranje = max(0, vkupno_dena - iskoristeni - working_days)

            _email_data = {
                "vraboten_email":         (v_row["email"] or "").strip() if v_row else "",
                "ime_prezime":            f"{v_row['ime']} {v_row['prezime']}" if v_row else "",
                "datum_od":               datum_od,
                "datum_do":               datum_do,
                "working_days":           working_days,
                "zabeleska":              zabeleska,
                "podneseno_od":           session["user"],
                "podneseno_na":           datetime.now().strftime("%d-%m-%Y %H:%M"),
                "vkupno_dena":            vkupno_dena,
                "iskoristeni":            iskoristeni,
                "preostanati":            preostanati_po_baranje,
                "godina":                 godina,
            }

        except ValueError:
            pass
        except Exception as e:
            flash(f"Грешка: {e}", "danger")
            conn.rollback()
        finally:
            conn.close()

        if _email_data:
            _isprati_odmor_email(**_email_data)
            notify_result = isprati_izvestuvanje_za_novo_baranje(
                ime_prezime=_email_data["ime_prezime"],
                datum_od=_email_data["datum_od"],
                datum_do=_email_data["datum_do"],
                working_days=_email_data["working_days"],
                zabeleska=_email_data["zabeleska"],
                podneseno_od=_email_data["podneseno_od"],
                podneseno_na=_email_data["podneseno_na"],
            )
            if notify_result.get("success"):
                print(f"[ODMOR BARAЊE] {notify_result['message']}")

        return redirect(url_for("main.baranje_odmor"))

    conn.close()
    return render_template(
        "baranje_odmor.html",
        vraboteni=vraboteni,
        today=dt_date.today().isoformat(),
    )


# ─────────────────────────────────────────────────────────────
# TEST RUTA
# ─────────────────────────────────────────────────────────────
@main_bp.route("/test_odmor_email")
@login_required
def test_odmor_email():
    conn    = get_db()
    vraboteni = conn.execute(
        "SELECT ime, prezime, email FROM vraboteni WHERE email IS NOT NULL AND email != ''"
    ).fetchall()
    conn.close()

    if not vraboteni:
        return "<h2>❌ Нема вработени со email адреса во базата!</h2><p>Додај email на вработените.</p>"

    results = []
    for v in vraboteni:
        try:
            with smtplib.SMTP(_EMAIL_HOST, _EMAIL_PORT, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(_EMAIL_USER, _EMAIL_PASSWORD)
                msg = MIMEMultipart("alternative")
                msg["From"]    = formataddr((_EMAIL_FROM_NAME, _EMAIL_USER))
                msg["To"]      = v["email"]
                msg["Subject"] = "✅ Тест email — Fersedo систем"
                msg.attach(MIMEText(
                    f"<h2>Тест email</h2><p>Ова е тест порака за <strong>{v['ime']} {v['prezime']}</strong>.</p>"
                    f"<p>Ако го добивате овој email, SMTP конфигурацијата работи правилно.</p>",
                    "html", "utf-8"
                ))
                server.sendmail(_EMAIL_USER, [v["email"]], msg.as_string())
            results.append(f"<li>✅ <strong>{v['ime']} {v['prezime']}</strong> → {v['email']}</li>")
        except Exception as e:
            results.append(f"<li>❌ <strong>{v['ime']} {v['prezime']}</strong> ({v['email']}) — Грешка: <code>{e}</code></li>")

    html = f"""
    <h2>📧 Тест email резултати</h2>
    <ul>{''.join(results)}</ul>
    <p><a href="/baranje_odmor">← Назад</a></p>
    """
    return html


# ─────────────────────────────────────────────────────────────
# EMAIL HELPER — одмор барање
# ─────────────────────────────────────────────────────────────
def _isprati_odmor_email(vraboten_email, ime_prezime, datum_od, datum_do,
                         working_days, zabeleska, podneseno_od, podneseno_na,
                         vkupno_dena=20, iskoristeni=0, preostanati=20, godina=None):
    if not vraboten_email:
        flash("⚠️ Барањето е поднесено, но вработениот нема email — email не е испратен.", "warning")
        return

    if godina is None:
        godina = datetime.now().year

    def fmt(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            return d

    datum_od_fmt = fmt(datum_od)
    datum_do_fmt = fmt(datum_do)
    zabeleska    = zabeleska or "Нема забелешка"

    preos_color = "#ef4444" if preostanati <= 0 else ("#d97706" if preostanati <= 5 else "#16a34a")
    preos_bg    = "#fef2f2" if preostanati <= 0 else ("#fefce8" if preostanati <= 5 else "#f0fdf4")

    subject = f"Барањето за одмор е примено — {datum_od_fmt} – {datum_do_fmt}"

    html = f"""<!DOCTYPE html>
<html lang="mk"><head><meta charset="UTF-8">
<style>
  body{{font-family:Arial,sans-serif;background:#f4f4f7;margin:0;padding:20px}}
  .wrap{{max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.10)}}
  .hdr{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:32px 36px}}
  .hdr h1{{margin:0;font-size:22px}} .hdr p{{margin:6px 0 0;opacity:.85;font-size:14px}}
  .bdy{{padding:32px 36px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:20px 0}}
  .box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px 18px}}
  .lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;margin-bottom:4px}}
  .val{{font-size:15px;font-weight:700;color:#1e293b}}
  .status{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px 18px;margin:18px 0;display:flex;align-items:center;gap:12px}}
  .saldo-box{{border-radius:10px;padding:18px 20px;margin:18px 0;border:2px solid {preos_color}44;background:{preos_bg}}}
  .saldo-title{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:{preos_color};margin-bottom:12px;font-weight:700}}
  .saldo-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;text-align:center}}
  .s-num{{font-size:28px;font-weight:800;color:{preos_color}}}
  .s-lbl{{font-size:11px;color:#64748b;margin-top:2px}}
  .note{{background:#fefce8;border-left:4px solid #eab308;border-radius:4px;padding:12px 16px;color:#713f12;font-size:14px;margin-top:8px}}
  .ftr{{background:#f8fafc;border-top:1px solid #e2e8f0;padding:14px 36px;font-size:12px;color:#94a3b8}}
</style>
</head><body>
<div class="wrap">
  <div class="hdr">
    <h1>Барањето за одмор е примено</h1>
    <p>Поднесено на {podneseno_na}</p>
  </div>
  <div class="bdy">
    <p style="font-size:16px;color:#334155">Почитуван/а <strong>{ime_prezime}</strong>,</p>
    <p style="color:#475569;font-size:14px;line-height:1.6">Вашето барање за годишен одмор е успешно примено и чека одобрување.</p>
    <div class="status">
      <div style="font-size:26px">&#9203;</div>
      <div>
        <div style="font-weight:700;color:#166534">Статус: Чека одобрување</div>
        <div style="font-size:13px;color:#16a34a;margin-top:2px">Во процес на разгледување</div>
      </div>
    </div>
    <div class="grid">
      <div class="box"><div class="lbl">Од датум</div><div class="val">{datum_od_fmt}</div></div>
      <div class="box"><div class="lbl">До датум</div><div class="val">{datum_do_fmt}</div></div>
      <div class="box"><div class="lbl">Работни денови</div><div class="val">{working_days} ден</div></div>
      <div class="box"><div class="lbl">Поднесено од</div><div class="val">{podneseno_od}</div></div>
    </div>
    <div class="saldo-box">
      <div class="saldo-title">Салдо на годишен одмор за {godina}</div>
      <div class="saldo-grid">
        <div><div class="s-num">{vkupno_dena}</div><div class="s-lbl">Вкупно</div></div>
        <div><div class="s-num">{iskoristeni + working_days}</div><div class="s-lbl">Искористено</div></div>
        <div><div class="s-num" style="color:{preos_color}">{preostanati}</div><div class="s-lbl">Преостанати</div></div>
      </div>
      <p style="font-size:11px;color:#94a3b8;margin:10px 0 0;text-align:center">* По одобрување на ова барање</p>
    </div>
    <p style="color:#64748b;font-size:13px;margin-bottom:6px">Забелешка:</p>
    <div class="note">{zabeleska}</div>
  </div>
  <div class="ftr">Fersedo Production System &bull; Автоматска порака</div>
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = formataddr((_EMAIL_FROM_NAME, _EMAIL_USER))
        msg["To"]      = vraboten_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(_EMAIL_HOST, _EMAIL_PORT, timeout=15) as server:
            server.ehlo(); server.starttls(); server.ehlo()
            server.login(_EMAIL_USER, _EMAIL_PASSWORD)
            server.sendmail(_EMAIL_USER, [vraboten_email], msg.as_string())
        flash(f"✅ Email испратен до {vraboten_email}", "success")
        print(f"[EMAIL ODMOR] ✅ До: {vraboten_email}")
    except smtplib.SMTPAuthenticationError:
        flash("❌ Email: Грешка при автентикација — провери App Password.", "danger")
    except Exception as e:
        flash(f"❌ Email грешка: {e}", "danger")
        print(f"[EMAIL ODMOR] ❌ {e}")


def _isprati_odobruvanje_email(vraboten_email, ime_prezime, datum_od, datum_do,
                               working_days, zabeleska, odobren_od,
                               vkupno_dena=20, preostanati=20, godina=None):
    if not vraboten_email:
        print(f"[EMAIL ODOBR] Нема email за '{ime_prezime}' — прескокнато.")
        return

    if godina is None:
        godina = datetime.now().year

    def fmt(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            return d

    datum_od_fmt = fmt(datum_od)
    datum_do_fmt = fmt(datum_do)
    zabeleska    = zabeleska or "Нема забелешка"
    odobren_na   = datetime.now().strftime("%d-%m-%Y %H:%M")

    preos_color = "#ef4444" if preostanati <= 0 else ("#d97706" if preostanati <= 5 else "#16a34a")
    preos_bg    = "#fef2f2" if preostanati <= 0 else ("#fefce8" if preostanati <= 5 else "#f0fdf4")

    subject = f"✅ Одморот е одобрен — {datum_od_fmt} – {datum_do_fmt}"

    html = f"""<!DOCTYPE html>
<html lang="mk"><head><meta charset="UTF-8">
<style>
  body{{font-family:Arial,sans-serif;background:#f4f4f7;margin:0;padding:20px}}
  .wrap{{max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.10)}}
  .hdr{{background:linear-gradient(135deg,#10b981,#059669);color:#fff;padding:32px 36px}}
  .hdr h1{{margin:0;font-size:22px}} .hdr p{{margin:6px 0 0;opacity:.85;font-size:14px}}
  .bdy{{padding:32px 36px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:20px 0}}
  .box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px 18px}}
  .lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;margin-bottom:4px}}
  .val{{font-size:15px;font-weight:700;color:#1e293b}}
  .approved{{background:#f0fdf4;border:2px solid #10b981;border-radius:10px;padding:18px 20px;margin:18px 0;text-align:center}}
  .saldo-box{{border-radius:10px;padding:18px 20px;margin:18px 0;border:2px solid {preos_color}44;background:{preos_bg}}}
  .saldo-title{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:{preos_color};margin-bottom:12px;font-weight:700}}
  .saldo-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;text-align:center}}
  .s-num{{font-size:28px;font-weight:800;color:{preos_color}}}
  .s-lbl{{font-size:11px;color:#64748b;margin-top:2px}}
  .note{{background:#fefce8;border-left:4px solid #eab308;border-radius:4px;padding:12px 16px;color:#713f12;font-size:14px;margin-top:8px}}
  .ftr{{background:#f8fafc;border-top:1px solid #e2e8f0;padding:14px 36px;font-size:12px;color:#94a3b8}}
</style>
</head><body>
<div class="wrap">
  <div class="hdr">
    <h1>&#10003; Одморот е одобрен!</h1>
    <p>Одобрено на {odobren_na} од {odobren_od}</p>
  </div>
  <div class="bdy">
    <p style="font-size:16px;color:#334155">Почитуван/а <strong>{ime_prezime}</strong>,</p>
    <p style="color:#475569;font-size:14px;line-height:1.6">Со задоволство Ве известуваме дека вашето барање за годишен одмор е <strong style="color:#059669">одобрено</strong>.</p>
    <div class="approved">
      <div style="font-size:48px">&#127955;</div>
      <div style="font-size:20px;font-weight:800;color:#059669;margin-top:8px">ОДОБРЕНО</div>
      <div style="font-size:14px;color:#047857;margin-top:4px">{datum_od_fmt} – {datum_do_fmt} &bull; {working_days} работни дена</div>
    </div>
    <div class="grid">
      <div class="box"><div class="lbl">Од датум</div><div class="val">{datum_od_fmt}</div></div>
      <div class="box"><div class="lbl">До датум</div><div class="val">{datum_do_fmt}</div></div>
      <div class="box"><div class="lbl">Работни денови</div><div class="val">{working_days} ден</div></div>
      <div class="box"><div class="lbl">Одобрено од</div><div class="val">{odobren_od}</div></div>
    </div>
    <div class="saldo-box">
      <div class="saldo-title">Салдо на годишен одмор за {godina}</div>
      <div class="saldo-grid">
        <div><div class="s-num">{vkupno_dena}</div><div class="s-lbl">Вкупно дена</div></div>
        <div><div class="s-num" style="color:{preos_color}">{preostanati}</div><div class="s-lbl">Преостанати</div></div>
      </div>
    </div>
    <p style="color:#64748b;font-size:13px;margin-bottom:6px">Забелешка:</p>
    <div class="note">{zabeleska}</div>
  </div>
  <div class="ftr">Fersedo Production System &bull; Автоматска порака</div>
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = formataddr((_EMAIL_FROM_NAME, _EMAIL_USER))
        msg["To"]      = vraboten_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(_EMAIL_HOST, _EMAIL_PORT, timeout=15) as server:
            server.ehlo(); server.starttls(); server.ehlo()
            server.login(_EMAIL_USER, _EMAIL_PASSWORD)
            server.sendmail(_EMAIL_USER, [vraboten_email], msg.as_string())
        print(f"[EMAIL ODOBR] ✅ До: {vraboten_email}")
    except Exception as e:
        print(f"[EMAIL ODOBR] ❌ {e}")
