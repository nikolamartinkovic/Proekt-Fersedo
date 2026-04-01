import json

from flask import current_app
from pywebpush import webpush

from utils.db import get_db


def queue_mobile_notification(username, title, body, url="/nabavki", category="general"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO mobile_notifications (username, title, body, url, category)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, title, body, url, category),
    )
    conn.commit()
    conn.close()
    return True


def fetch_mobile_notifications(username, since_id=0, limit=20):
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT id, title, body, url, category, created_at
        FROM mobile_notifications
        WHERE username = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (username, since_id, limit),
    ).fetchall()
    conn.close()
    return rows


def send_push_to_user(username, title, body, url="/nabavki", category="general"):
    queued_mobile = queue_mobile_notification(username, title, body, url, category)

    conn = get_db()
    cursor = conn.cursor()
    sub_row = cursor.execute(
        "SELECT subscription FROM push_subscriptions WHERE user = ?",
        (username,),
    ).fetchone()
    conn.close()

    if not sub_row or not sub_row["subscription"]:
        return queued_mobile

    try:
        webpush(
            subscription_info=json.loads(sub_row["subscription"]),
            data=json.dumps(
                {
                    "title": title,
                    "body": body,
                    "icon": "/static/logo.webp",
                    "url": url,
                }
            ),
            vapid_private_key=current_app.config["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": current_app.config["VAPID_SUBJECT"]},
        )
        return True
    except Exception as exc:
        print(f"[PUSH] Грешка при испраќање до {username}: {exc}")
        return queued_mobile


def send_push_to_nabavki_group(title, body, url="/nabavki", category="nabavki"):
    conn = get_db()
    cursor = conn.cursor()
    users = cursor.execute(
        """
        SELECT username FROM users
        WHERE user_group = 'Nabavki' OR is_admin = 1
        """
    ).fetchall()
    conn.close()

    sent = 0
    for user in users:
        if send_push_to_user(user["username"], title, body, url, category=category):
            sent += 1
    return sent
