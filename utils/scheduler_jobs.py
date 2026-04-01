import random
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from utils.db import get_db
from utils.odmori_notifications import (
    isprati_dnevni_izvestaj_otsustva,
    isprati_nedelen_izvestaj_otsustva,
)
from utils.stock_reports import isprati_zaliha_email

assign_lock = threading.Lock()


def auto_assign_nabavki():
    with assign_lock:
        try:
            conn = get_db()
            cursor = conn.cursor()
            nabavki_users = [r["username"] for r in cursor.execute("SELECT username FROM users WHERE user_group='Nabavki'").fetchall()]
            if not nabavki_users:
                conn.close()
                return

            pending = [
                r["id"]
                for r in cursor.execute(
                    """
                    SELECT id FROM nabavki_requests
                    WHERE prevzemeno_od IS NULL AND status='РєСЂРµРёСЂР°РЅРѕ'
                    ORDER BY datum_kreiranje ASC LIMIT 5
                    """
                ).fetchall()
            ]
            assigned_count = 0
            for req_id in pending:
                chosen_user = min(
                    nabavki_users,
                    key=lambda u: (cursor.execute("SELECT COUNT(*) AS c FROM nabavki_requests WHERE prevzemeno_od=?", (u,)).fetchone() or {}).get("c", 0),
                    default=None,
                ) or random.choice(nabavki_users)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    """
                    UPDATE nabavki_requests
                    SET prevzemeno_od=?, datum_prevzemanje=?, status='Videno'
                    WHERE id=? AND prevzemeno_od IS NULL
                    """,
                    (chosen_user, now_str, req_id),
                )
                if cursor.rowcount > 0:
                    cursor.execute(
                        """
                        INSERT INTO nabavki_assign_log (request_id, assigned_to, assigned_at, from_thread)
                        VALUES (?,?,?,?)
                        """,
                        (req_id, chosen_user, now_str, threading.current_thread().name),
                    )
                    conn.commit()
                    assigned_count += 1
                    print(f"[AUTO ASSIGN] {req_id} -> {chosen_user}")
            print(f"[AUTO ASSIGN] {assigned_count} барања доделени." if assigned_count else "[AUTO ASSIGN] Нема pending.")
            conn.close()
        except Exception as e:
            print(f"[AUTO ASSIGN ERROR] {e}")


def _with_app_context(app, fn):
    def wrapped():
        with app.app_context():
            return fn()

    return wrapped


def init_scheduler(app, auto_assign_interval_seconds):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _with_app_context(app, auto_assign_nabavki),
        trigger=IntervalTrigger(seconds=auto_assign_interval_seconds),
        id="nabavki_auto_assign",
        replace_existing=True,
    )
    scheduler.add_job(
        _with_app_context(app, isprati_zaliha_email),
        trigger="cron",
        day_of_week="wed",
        hour=8,
        minute=0,
        id="zaliha_email_sreda",
        replace_existing=True,
    )
    scheduler.add_job(
        _with_app_context(app, isprati_dnevni_izvestaj_otsustva),
        trigger="cron",
        day_of_week="mon-fri",
        hour=8,
        minute=0,
        id="otsustva_dnevni",
        replace_existing=True,
    )
    scheduler.add_job(
        _with_app_context(app, isprati_nedelen_izvestaj_otsustva),
        trigger="cron",
        day_of_week="fri",
        hour=15,
        minute=0,
        id="otsustva_nedelen",
        replace_existing=True,
    )
    scheduler.start()
    print("[SCHEDULER] Auto-assign started - interval 4 hours")
    print("[SCHEDULER] Zaliha email started - every Wednesday at 08:00")
    print("[SCHEDULER] Otsustva dnevni started - every day at 08:00")
    print("[SCHEDULER] Otsustva nedelen started - every Friday at 15:00")
    return scheduler
