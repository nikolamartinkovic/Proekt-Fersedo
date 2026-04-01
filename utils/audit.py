from flask import request, session

from utils.db import get_db


def ensure_audit_log_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'info',
            username TEXT DEFAULT '',
            details TEXT DEFAULT '',
            ip_address TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def log_audit_event(category, action, status="info", details="", username=None, ip_address=None):
    try:
        resolved_username = username
        if resolved_username is None:
            try:
                resolved_username = session.get("user", "")
            except RuntimeError:
                resolved_username = ""

        resolved_ip = ip_address
        if resolved_ip is None:
            try:
                resolved_ip = (
                    request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or request.headers.get("X-Real-IP", "").strip()
                    or request.remote_addr
                    or ""
                )
            except RuntimeError:
                resolved_ip = ""

        conn = get_db()
        cursor = conn.cursor()
        ensure_audit_log_table(cursor)
        cursor.execute(
            """
            INSERT INTO audit_log (category, action, status, username, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                action,
                status,
                resolved_username or "",
                details or "",
                resolved_ip or "",
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[AUDIT] Грешка: {exc}")


def get_audit_log(limit=50):
    try:
        conn = get_db()
        cursor = conn.cursor()
        ensure_audit_log_table(cursor)
        conn.commit()
        rows = cursor.execute(
            """
            SELECT id, category, action, status, username, details, ip_address, created_at
            FROM audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        return rows
    except Exception as exc:
        print(f"[AUDIT] Грешка при читање: {exc}")
        return []
