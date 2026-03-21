# utils/notifications.py
from pywebpush import webpush, WebPushException
import json
from flask import current_app
from utils.db import get_db   # ← Ова е вистинскиот импорт!

def send_push_to_user(username, title, body, url="/nabavki"):
    """Испрати push нотификација до еден конкретен корисник"""
    conn = get_db()
    cursor = conn.cursor()
    sub_row = cursor.execute(
        "SELECT subscription FROM push_subscriptions WHERE user = ?",
        (username,)
    ).fetchone()
    conn.close()

    if not sub_row or not sub_row["subscription"]:
        return False

    try:
        webpush(
            subscription_info=json.loads(sub_row["subscription"]),
            data=json.dumps({
                "title": title,
                "body": body,
                "icon": "/static/logo.webp",
                "url": url
            }),
            vapid_private_key=current_app.config['VAPID_PRIVATE_KEY'],
            vapid_claims={"sub": current_app.config['VAPID_SUBJECT']},
        )
        return True
    except Exception as e:
        print(f"[PUSH] Грешка при испраќање до {username}: {e}")
        return False


def send_push_to_nabavki_group(title, body, url="/nabavki"):
    """Испрати push до сите корисници од групата Nabavki + админи"""
    conn = get_db()
    cursor = conn.cursor()
    users = cursor.execute("""
        SELECT username FROM users 
        WHERE user_group = 'Nabavki' OR is_admin = 1
    """).fetchall()
    conn.close()

    sent = 0
    for u in users:
        if send_push_to_user(u["username"], title, body, url):
            sent += 1
    return sent