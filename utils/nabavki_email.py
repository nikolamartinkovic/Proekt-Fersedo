# utils/nabavki_email.py
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from utils.db import get_db

_EMAIL_HOST     = "smtp.gmail.com"
_EMAIL_PORT     = 587
_EMAIL_USER     = "fersedoo@gmail.com"
_EMAIL_PASSWORD = "ejvu srce tvls wqtw"


def _isprati(to_emails, subject, html):
    """Помошна — испрати HTML email до листа на адреси."""
    if not to_emails:
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = _EMAIL_USER
        msg["To"]      = ", ".join(to_emails)
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(_EMAIL_HOST, _EMAIL_PORT, timeout=15) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(_EMAIL_USER, _EMAIL_PASSWORD)
            s.sendmail(_EMAIL_USER, to_emails, msg.as_string())
        print(f"[NABAVKI EMAIL] ✅ Испратено до: {to_emails}")
    except Exception as e:
        print(f"[NABAVKI EMAIL] ❌ Грешка: {e}")


def _get_emails_nabavki_group():
    """Врати email адреси САМО на корисници со user_group = 'Nabavki' или is_admin = 1."""
    try:
        conn  = get_db()
        # Дебаг — испечати ги сите корисници и нивни групи
        all_rows = conn.execute(
            "SELECT username, user_group, is_admin, email FROM users"
        ).fetchall()
        print("[NABAVKI EMAIL DEBUG] Сите корисници:")
        for r in all_rows:
            print(f"  → {r['username']} | group={r['user_group']} | admin={r['is_admin']} | email={r['email']}")

        rows  = conn.execute("""
    SELECT email FROM users
    WHERE user_group = 'Nabavki'
      AND email IS NOT NULL AND email != ''
""").fetchall()
        conn.close()
        result = [r["email"] for r in rows]
        print(f"[NABAVKI EMAIL DEBUG] Ќе се испрати до: {result}")
        return result
    except Exception as e:
        print(f"[NABAVKI EMAIL] Грешка при земање emails: {e}")
        return []

def _get_email_of_user(username):
    """Врати email на конкретен корисник."""
    try:
        conn = get_db()
        row  = conn.execute(
            "SELECT email FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()
        if row and row["email"]:
            return row["email"]
    except Exception as e:
        print(f"[NABAVKI EMAIL] Грешка при земање email за {username}: {e}")
    return None


def _html_wrapper(content, boja="#1e40af"):
    """Обвивка за HTML email."""
    return f"""<!DOCTYPE html>
<html lang="mk"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="font-family:Arial,sans-serif;background:#f4f4f7;margin:0;padding:12px;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;
     overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.1);">
  <div style="background:linear-gradient(135deg,{boja},{boja}cc);
              color:#fff;padding:22px 28px;">
    <h2 style="margin:0;font-size:18px;">Fersedo — Набавки</h2>
  </div>
  <div style="padding:24px 28px;">{content}</div>
  <div style="background:#f8fafc;border-top:1px solid #e2e8f0;
              padding:12px 28px;font-size:11px;color:#94a3b8;">
    Fersedo Production System &bull; Автоматска порака
  </div>
</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# ЈАВНИ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────

def notify_novo_baranje(nalog, naslov, kolicina, datum_itnost, kreator):
    """Email до целата група Набавки при ново барање."""
    emails = _get_emails_nabavki_group()
    if not emails:
        return

    content = f"""
    <p style="font-size:15px;">Креирано е <strong>ново барање за набавка</strong>.</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;">
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;width:40%;">Број на налог</td>
        <td style="padding:10px 14px;font-weight:800;color:#1e40af;font-size:16px;">{nalog}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Наслов</td>
        <td style="padding:10px 14px;">{naslov}</td>
      </tr>
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Количина</td>
        <td style="padding:10px 14px;">{kolicina}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Датум на итност</td>
        <td style="padding:10px 14px;color:#dc2626;font-weight:600;">{datum_itnost}</td>
      </tr>
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Креирал</td>
        <td style="padding:10px 14px;">{kreator}</td>
      </tr>
    </table>
    <p style="color:#64748b;font-size:13px;">
      Најавете се во системот за да го превземете барањето.
    </p>"""

    _isprati(
        emails,
        f"🛒 Ново барање за набавка — {nalog}: {naslov}",
        _html_wrapper(content, "#1e40af")
    )


def notify_promena_status(nalog, naslov, star_status, nov_status, kreator, promeneto_od):
    """Email до креаторот при промена на статус."""
    email = _get_email_of_user(kreator)
    if not email or kreator == promeneto_od:
        return

    status_boi = {
        "Videno":    "#3b82f6",
        "Naracano":  "#f59e0b",
        "Dostaveno": "#8b5cf6",
        "Zavrseno":  "#10b981",
        "Prevzemeno":"#10b981",
    }
    boja = status_boi.get(nov_status, "#6b7280")

    content = f"""
    <p style="font-size:15px;">Статусот на вашето барање е <strong>сменет</strong>.</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;">
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;width:40%;">Број на налог</td>
        <td style="padding:10px 14px;font-weight:800;color:#1e40af;font-size:16px;">{nalog}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Наслов</td>
        <td style="padding:10px 14px;">{naslov}</td>
      </tr>
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Стар статус</td>
        <td style="padding:10px 14px;color:#6b7280;">{star_status}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Нов статус</td>
        <td style="padding:10px 14px;">
          <span style="background:{boja}22;color:{boja};padding:4px 12px;
                border-radius:12px;font-weight:700;font-size:14px;">{nov_status}</span>
        </td>
      </tr>
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Сменето од</td>
        <td style="padding:10px 14px;">{promeneto_od}</td>
      </tr>
    </table>"""

    _isprati(
        [email],
        f"🔄 Барање {nalog} — статус сменет на {nov_status}",
        _html_wrapper(content, boja)
    )


def notify_nov_komentar(nalog, naslov, komentar_tekst, od_korisnik, do_korisnik):
    """
    Email до соодветниот корисник при нов коментар.
    - Ако коментира Набавки → email до креаторот
    - Ако коментира креаторот → email до превземачот (ако постои)
    """
    if od_korisnik == do_korisnik:
        return
    email = _get_email_of_user(do_korisnik)
    if not email:
        return

    content = f"""
    <p style="font-size:15px;">Нов <strong>коментар</strong> на барање за набавка.</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;">
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;width:40%;">Број на налог</td>
        <td style="padding:10px 14px;font-weight:800;color:#1e40af;font-size:16px;">{nalog}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Наслов</td>
        <td style="padding:10px 14px;">{naslov}</td>
      </tr>
      <tr style="background:#f8fafc;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Од корисник</td>
        <td style="padding:10px 14px;font-weight:600;">{od_korisnik}</td>
      </tr>
    </table>
    <div style="background:#f1f5f9;border-left:4px solid #3b82f6;
                border-radius:4px;padding:14px 18px;margin:16px 0;
                color:#1e293b;font-size:14px;line-height:1.6;">
      {komentar_tekst}
    </div>
    <p style="color:#64748b;font-size:13px;">
      Најавете се во системот за да одговорите.
    </p>"""

    _isprati(
        [email],
        f"💬 Нов коментар на барање {nalog} — од {od_korisnik}",
        _html_wrapper(content, "#3b82f6")
    )