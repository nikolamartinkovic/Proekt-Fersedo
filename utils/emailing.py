import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import current_app


def send_html_email(recipient_email, subject, html_body, text_body=""):
    if not recipient_email:
        raise ValueError("Недостасува email примач.")

    email_host = current_app.config.get("EMAIL_HOST", "")
    email_port = int(current_app.config.get("EMAIL_PORT", 587) or 587)
    email_user = current_app.config.get("EMAIL_HOST_USER", "")
    email_password = current_app.config.get("EMAIL_HOST_PASSWORD", "")
    email_from_name = current_app.config.get("EMAIL_FROM_NAME", "Info Fersedo")

    if not email_host or not email_user or not email_password:
        raise RuntimeError("Email конфигурацијата не е целосно поставена.")

    message = MIMEMultipart("alternative")
    message["From"] = formataddr((email_from_name, email_user))
    message["To"] = recipient_email
    message["Subject"] = subject

    if text_body:
        message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(email_host, email_port, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(email_user, email_password)
        server.sendmail(email_user, [recipient_email], message.as_string())


def send_new_user_credentials_email(recipient_email, username, temporary_password, login_url=""):
    subject = f"Fersedo - Ваши пристапни податоци ({username})"

    login_button_html = ""
    login_text_html = ""
    login_text_body = ""
    if login_url:
        login_button_html = f"""
                <p style="margin:24px 0 16px;">
                    <a href="{login_url}" style="display:inline-block;padding:14px 24px;border-radius:999px;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:700;">
                        Најави се во системот
                    </a>
                </p>
        """
        login_text_html = f"""
                <p style="margin:0 0 16px;color:#475569;">
                    Линк за најава:
                    <a href="{login_url}" style="color:#2563eb;text-decoration:none;font-weight:600;">{login_url}</a>
                </p>
        """
        login_text_body = f"\nЛинк за најава: {login_url}\n"

    html_body = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#0f172a;background:#f8fafc;padding:24px;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #dbe3f0;border-radius:18px;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#162240,#314c82);padding:24px 28px;color:#ffffff;">
                <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.9;">Fersedo</div>
                <h2 style="margin:8px 0 0;font-size:28px;line-height:1.1;">Добредојдовте во системот</h2>
            </div>
            <div style="padding:28px;">
                <p>За вас е креиран кориснички профил во Fersedo.</p>
                <p>Подолу се вашите почетни пристапни податоци:</p>

                <div style="margin:22px 0;padding:18px;border:1px solid #dbe3f0;border-radius:14px;background:#f8fbff;">
                    <div style="margin-bottom:8px;"><strong>Корисничко име:</strong> {username}</div>
                    <div><strong>Привремена лозинка:</strong> {temporary_password}</div>
                </div>

                {login_button_html}
                {login_text_html}

                <p style="margin-bottom:0;">
                    При првото најавување системот автоматски ќе побара да ја промените лозинката
                    пред да продолжите со работа.
                </p>
            </div>
        </div>
    </div>
    """
    text_body = (
        "Добредојдовте во Fersedo.\n\n"
        f"Корисничко име: {username}\n"
        f"Привремена лозинка: {temporary_password}\n"
        f"{login_text_body}\n"
        "При првото најавување ќе треба задолжително да ја промените лозинката."
    )
    send_html_email(recipient_email, subject, html_body, text_body=text_body)


def send_password_change_verification_email(recipient_email, username, verification_url, expires_minutes=30):
    subject = f"Fersedo - Потврда за промена на лозинка ({username})"
    html_body = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.6;color:#0f172a;background:#f8fafc;padding:24px;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #dbe3f0;border-radius:18px;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#162240,#314c82);padding:24px 28px;color:#ffffff;">
                <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.9;">Fersedo</div>
                <h2 style="margin:8px 0 0;font-size:28px;line-height:1.1;">Потврда за промена на лозинка</h2>
            </div>
            <div style="padding:28px;">
                <p>Примивме барање за промена на лозинка за корисникот <strong>{username}</strong>.</p>
                <p>За да потврдите дека навистина вие ја барате оваа промена, кликнете на копчето подолу:</p>
                <p style="margin:24px 0;">
                    <a href="{verification_url}" style="display:inline-block;padding:14px 24px;border-radius:999px;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:700;">
                        Потврди и промени лозинка
                    </a>
                </p>
                <p>Овој линк важи <strong>{expires_minutes} минути</strong>.</p>
                <p style="margin-bottom:0;color:#64748b;">
                    Ако не сте побарале промена на лозинка, слободно игнорирајте го овој email.
                </p>
            </div>
        </div>
    </div>
    """
    text_body = (
        "Потврда за промена на лозинка во Fersedo.\n\n"
        f"Корисник: {username}\n"
        f"Отворете го следниот линк за да ја потврдите промената:\n{verification_url}\n\n"
        f"Линкот важи {expires_minutes} минути.\n"
        "Ако не сте побарале промена на лозинка, игнорирајте го овој email."
    )
    send_html_email(recipient_email, subject, html_body, text_body=text_body)
