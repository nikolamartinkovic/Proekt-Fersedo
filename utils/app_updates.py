import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import current_app

from utils.db import get_db
from utils.notifications import send_push_to_user


def _send_release_email(recipients, subject, html_body):
    if not recipients:
        return 0

    email_host = current_app.config["EMAIL_HOST"]
    email_port = current_app.config["EMAIL_PORT"]
    email_user = current_app.config["EMAIL_HOST_USER"]
    email_password = current_app.config["EMAIL_HOST_PASSWORD"]
    email_from_name = current_app.config.get("EMAIL_FROM_NAME", "Info Fersedo")

    if not email_host or not email_port or not email_user or not email_password:
        return 0

    sent_count = 0
    try:
        with smtplib.SMTP(email_host, email_port, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_user, email_password)

            for recipient in recipients:
                msg = MIMEMultipart()
                msg["From"] = formataddr((email_from_name, email_user))
                msg["To"] = recipient
                msg["Subject"] = subject
                msg.attach(MIMEText(html_body, "html", "utf-8"))
                server.sendmail(email_user, [recipient], msg.as_string())
                sent_count += 1
    except Exception as exc:
        current_app.logger.warning("Android release email send failed: %s", exc)
        raise

    return sent_count


def announce_android_release_if_needed(metadata, download_url):
    result = {"push_sent": False, "email_sent": False}
    if not metadata or not metadata.get("available") or not metadata.get("version_key"):
        return result

    conn = get_db()
    try:
        cursor = conn.cursor()
        version_key = metadata["version_key"]
        version_name = metadata.get("version_name") or "Нова верзија"
        version_code = int(metadata.get("version_code") or 0)

        cursor.execute(
            """
            INSERT OR IGNORE INTO app_release_announcements (version_key, version_name, version_code)
            VALUES (?, ?, ?)
            """,
            (version_key, version_name, version_code),
        )
        conn.commit()

        row = cursor.execute(
            """
            SELECT *
            FROM app_release_announcements
            WHERE version_key = ?
            """,
            (version_key,),
        ).fetchone()

        if row and not row.get("push_sent_at"):
            users = cursor.execute(
                """
                SELECT username
                FROM users
                WHERE COALESCE(username, '') <> ''
                ORDER BY username
                """
            ).fetchall()

            push_count = 0
            for user in users:
                username = (user.get("username") or "").strip()
                if not username:
                    continue
                try:
                    if send_push_to_user(
                        username,
                        "Нова Fersedo верзија е достапна",
                        f"Достапна е Android верзија {version_name}. Отвори ја апликацијата и ажурирај.",
                        url="/welcome",
                        category="app_update",
                    ):
                        push_count += 1
                except Exception as exc:
                    current_app.logger.warning(
                        "Android release push failed for %s: %s",
                        username,
                        exc,
                    )

            cursor.execute(
                """
                UPDATE app_release_announcements
                SET push_sent_at = CURRENT_TIMESTAMP,
                    push_count = ?
                WHERE version_key = ?
                """,
                (push_count, version_key),
            )
            conn.commit()
            result["push_sent"] = True

        row = cursor.execute(
            """
            SELECT *
            FROM app_release_announcements
            WHERE version_key = ?
            """,
            (version_key,),
        ).fetchone()

        if row and not row.get("email_sent_at"):
            email_rows = cursor.execute(
                """
                SELECT DISTINCT LOWER(TRIM(email)) AS email
                FROM users
                WHERE COALESCE(TRIM(email), '') <> ''
                ORDER BY email
                """
            ).fetchall()

            recipients = [entry["email"] for entry in email_rows if entry.get("email")]
            subject = f"Нова Android верзија на Fersedo ({version_name})"
            html_body = f"""
            <div style="font-family:Arial,Helvetica,sans-serif; line-height:1.6; color:#111827;">
                <h2 style="margin:0 0 12px 0;">Достапна е нова Android верзија на Fersedo</h2>
                <p>Објавена е нова верзија <strong>{version_name}</strong> на мобилната апликација.</p>
                <p>Ако веќе ја користите Fersedo APK апликацијата, при отворање ќе добиете и известување за ажурирање.</p>
                <p style="margin:20px 0;">
                    <a href="{download_url}" style="background:#1d4ed8; color:#ffffff; text-decoration:none; padding:12px 18px; border-radius:8px; display:inline-block;">
                        Преземи ја новата APK верзија
                    </a>
                </p>
                <p>Линк: <a href="{download_url}">{download_url}</a></p>
                <p>Поздрав,<br>Fersedo систем</p>
            </div>
            """

            try:
                email_count = _send_release_email(recipients, subject, html_body)
                cursor.execute(
                    """
                    UPDATE app_release_announcements
                    SET email_sent_at = CURRENT_TIMESTAMP,
                        email_count = ?
                    WHERE version_key = ?
                    """,
                    (email_count, version_key),
                )
                conn.commit()
                result["email_sent"] = True
            except Exception as exc:
                conn.rollback()
                current_app.logger.warning("Android release email announcement failed: %s", exc)

        return result
    except Exception as exc:
        conn.rollback()
        current_app.logger.warning("Android release announce failed: %s", exc)
        return result
    finally:
        conn.close()
