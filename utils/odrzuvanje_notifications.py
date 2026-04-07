import smtplib
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app, url_for

from utils.db import get_db
from utils.notifications import send_push_to_user


def _maintenance_users(cursor):
    rows = cursor.execute(
        """
        SELECT username, COALESCE(email, '') AS email, is_admin,
               COALESCE(user_group, '') AS user_group,
               COALESCE(allowed_modules, '') AS allowed_modules
        FROM users
        ORDER BY username
        """
    ).fetchall()
    result = []
    for row in rows:
        allowed = {item.strip() for item in (row["allowed_modules"] or "").split(",") if item.strip()}
        group_name = (row["user_group"] or "").strip().lower()
        if row["is_admin"] or "odrzuvanje" in allowed or "odrzuvanje_nalozi" in allowed:
            result.append({"username": row["username"], "email": row["email"]})
            continue
        if group_name in {"odrzuvanje", "maintenance", "servis"}:
            result.append({"username": row["username"], "email": row["email"]})
    return result


def _send_email(to_email, subject, html):
    if not to_email:
        return False
    host = current_app.config.get("EMAIL_HOST", "")
    port = int(current_app.config.get("EMAIL_PORT", 587) or 587)
    username = current_app.config.get("EMAIL_HOST_USER", "")
    password = current_app.config.get("EMAIL_HOST_PASSWORD", "")
    from_email = current_app.config.get("EMAIL_FROM", username)
    from_name = current_app.config.get("EMAIL_FROM_NAME", "Info Fersedo")
    from_header = formataddr((from_name, from_email))
    if not host or not username or not password:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = from_header
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.sendmail(username, [to_email], msg.as_string())
        return True
    except Exception as exc:
        print(f"[ODRZUVANJE EMAIL] Error while sending to {to_email}: {exc}")
        return False


def _email_wrapper(title, intro_html, body_html, accent="#1d4ed8"):
    return f"""<!DOCTYPE html>
<html lang="mk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:16px;background:#f5f7fb;font-family:Arial,sans-serif;color:#0f172a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 10px 28px rgba(15,23,42,.08);">
    <tr>
      <td style="padding:22px 28px;background:linear-gradient(135deg,#0f172a 0%,{accent} 100%);color:#fff;">
        <div style="font-size:14px;letter-spacing:.08em;text-transform:uppercase;opacity:.78;margin-bottom:8px;">Одржување</div>
        <div style="font-size:28px;font-weight:800;line-height:1.15;">{title}</div>
      </td>
    </tr>
    <tr>
      <td style="padding:24px 28px 10px 28px;font-size:15px;line-height:1.6;color:#334155;">
        {intro_html}
      </td>
    </tr>
    <tr>
      <td style="padding:0 28px 28px 28px;">
        {body_html}
      </td>
    </tr>
    <tr>
      <td style="padding:14px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">
        Info Fersedo · Автоматско системско известување
      </td>
    </tr>
  </table>
</body>
</html>"""


def _order_summary_table(order_row, machine_name, machine_code):
    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background:#f8fbff;border:1px solid #dbeafe;border-radius:14px;overflow:hidden;">
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;width:34%;">Работен налог</td>
        <td style="padding:10px 14px;font-weight:800;color:#1d4ed8;">{order_row.get('broj') or '—'}</td>
      </tr>
      <tr style="background:#ffffff;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Машина</td>
        <td style="padding:10px 14px;">{machine_name} · {machine_code}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Тип / приоритет</td>
        <td style="padding:10px 14px;">{order_row.get('tip') or '—'} · {order_row.get('prioritet') or '—'}</td>
      </tr>
      <tr style="background:#ffffff;">
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Пријавил</td>
        <td style="padding:10px 14px;">{order_row.get('prijavil') or order_row.get('created_by') or '—'}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:700;color:#64748b;">Наслов</td>
        <td style="padding:10px 14px;">{order_row.get('naslov') or '—'}</td>
      </tr>
    </table>
    """


def notify_new_order(order_id):
    conn = get_db()
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT n.*, m.naziv AS masina_naziv, m.kod AS masina_kod
        FROM odrzuvanje_nalozi n
        JOIN odrzuvanje_masini m ON m.id = n.masina_id
        WHERE n.id = ?
        """,
        (order_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"push": 0, "email": 0}
    order = dict(row)
    recipients = []
    assignee = (order.get("dodeleno_na") or "").strip()
    if assignee:
        assignee_row = cursor.execute(
            "SELECT COALESCE(email,'') AS email FROM users WHERE username = ?",
            (assignee,),
        ).fetchone()
        recipients.append(
            {
                "username": assignee,
                "email": assignee_row["email"] if assignee_row else "",
            }
        )
    else:
        recipients.extend(_maintenance_users(cursor))
    conn.close()

    internal_url = url_for("odrzuvanje.order_detail", order_id=order_id)
    intro = f"Креиран е нов работен налог за машината <strong>{order['masina_naziv']}</strong>."
    if order.get("opis_defekt"):
        intro += f"<br><br><strong>Опис на дефект:</strong> {order['opis_defekt']}"
    body = _order_summary_table(order, order["masina_naziv"], order["masina_kod"])
    email_html = _email_wrapper("Нов работен налог", intro, body, "#1d4ed8")

    sent_push = 0
    sent_email = 0
    seen = set()
    for recipient in recipients:
        username = (recipient.get("username") or "").strip()
        email = (recipient.get("email") or "").strip()
        if not username or username in seen:
            continue
        seen.add(username)
        if send_push_to_user(
            username,
            f"Нов налог {order['broj']}",
            f"{order['masina_naziv']} · {order.get('naslov') or order.get('tip') or 'Одржување'}",
            url=internal_url,
            category="odrzuvanje",
        ):
            sent_push += 1
        if _send_email(email, f"Нов работен налог · {order['broj']}", email_html):
            sent_email += 1
    return {"push": sent_push, "email": sent_email}


def notify_order_assignment(order_id, assignee, previous_assignee=""):
    assignee = (assignee or "").strip()
    if not assignee:
        return {"push": 0, "email": 0}
    conn = get_db()
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT n.*, m.naziv AS masina_naziv, m.kod AS masina_kod
        FROM odrzuvanje_nalozi n
        JOIN odrzuvanje_masini m ON m.id = n.masina_id
        WHERE n.id = ?
        """,
        (order_id,),
    ).fetchone()
    email_row = cursor.execute(
        "SELECT COALESCE(email,'') AS email FROM users WHERE username = ?",
        (assignee,),
    ).fetchone()
    conn.close()
    if not row:
        return {"push": 0, "email": 0}
    order = dict(row)
    internal_url = url_for("odrzuvanje.order_detail", order_id=order_id)
    title = f"Доделен налог {order['broj']}"
    body = f"{order['masina_naziv']} · {order.get('naslov') or order.get('tip') or 'Одржување'}"
    intro = f"На тебе ти е доделен работниот налог <strong>{order['broj']}</strong>."
    if previous_assignee and previous_assignee != assignee:
        intro += f"<br><br>Претходно бил доделен на <strong>{previous_assignee}</strong>."
    email_html = _email_wrapper("Ти е доделен работен налог", intro, _order_summary_table(order, order["masina_naziv"], order["masina_kod"]), "#0f766e")
    sent_push = 1 if send_push_to_user(assignee, title, body, url=internal_url, category="odrzuvanje") else 0
    sent_email = 1 if _send_email(email_row["email"] if email_row else "", title, email_html) else 0
    return {"push": sent_push, "email": sent_email}


def notify_due_maintenance_plans():
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT p.*, m.naziv AS masina_naziv, m.kod AS masina_kod
        FROM odrzuvanje_planovi p
        JOIN odrzuvanje_masini m ON m.id = p.masina_id
        WHERE p.aktivno = 1
          AND p.sledno_izvrsuvanje IS NOT NULL
          AND p.sledno_izvrsuvanje <= date('now', 'localtime')
        ORDER BY p.sledno_izvrsuvanje ASC, p.id ASC
        """
    ).fetchall()
    if not rows:
        conn.close()
        return {"plans": 0, "push": 0, "email": 0}

    maintenance_users = _maintenance_users(cursor)
    email_map = {item["username"]: item["email"] for item in maintenance_users}
    grouped = {}
    fallback_users = [item["username"] for item in maintenance_users]
    for row in rows:
        responsible = (row["odgovoren"] or "").strip()
        if responsible:
            grouped.setdefault(responsible, []).append(dict(row))
        else:
            for username in fallback_users:
                grouped.setdefault(username, []).append(dict(row))
    conn.close()

    plan_url = "/odrzuvanje/plan"
    sent_push = 0
    sent_email = 0
    for username, plans in grouped.items():
        if not plans:
            continue
        lines = "".join(
            f"<tr><td style='padding:9px 12px;border-bottom:1px solid #e2e8f0;'>{plan['naziv']}</td>"
            f"<td style='padding:9px 12px;border-bottom:1px solid #e2e8f0;'>{plan['masina_naziv']} · {plan['masina_kod']}</td>"
            f"<td style='padding:9px 12px;border-bottom:1px solid #e2e8f0;'>{plan['sledno_izvrsuvanje'] or '—'}</td></tr>"
            for plan in plans[:8]
        )
        html = _email_wrapper(
            "Доспеани планови за одржување",
            f"Имаш <strong>{len(plans)}</strong> план(ови) што бараат сервисна активност денес.",
            f"""
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background:#fff;border:1px solid #dbeafe;border-radius:14px;overflow:hidden;">
              <tr style="background:#eef4ff;font-weight:700;color:#0f172a;">
                <td style="padding:10px 12px;">План</td>
                <td style="padding:10px 12px;">Машина</td>
                <td style="padding:10px 12px;">Датум</td>
              </tr>
              {lines}
            </table>
            """,
            "#0f766e",
        )
        if send_push_to_user(
            username,
            f"Доспеани планови: {len(plans)}",
            "Провери го планерот за одржување.",
            url=plan_url,
            category="odrzuvanje",
        ):
            sent_push += 1
        if _send_email(email_map.get(username, ""), f"Доспеани планови за одржување ({len(plans)})", html):
            sent_email += 1

    return {"plans": len(rows), "push": sent_push, "email": sent_email}
