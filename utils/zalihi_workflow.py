from datetime import datetime

from utils.db import get_db


def ensure_pending_exports_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS zaliha_izvoz_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artikl_id INTEGER NOT NULL,
            pn TEXT NOT NULL,
            ime TEXT NOT NULL,
            kolicina INTEGER NOT NULL,
            tip TEXT NOT NULL,
            datum_izvoz TEXT NOT NULL,
            username TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            datum_odobren TEXT,
            odobren_od TEXT
        )
        """
    )


def ensure_storno_log_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS zaliha_storno_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            datum     TEXT    NOT NULL,
            username  TEXT    NOT NULL,
            artikl_id INTEGER NOT NULL,
            pn        TEXT    NOT NULL,
            ime       TEXT,
            kolicina  INTEGER NOT NULL,
            plateno   INTEGER NOT NULL,
            tip       TEXT    NOT NULL,
            zabeleska TEXT    NOT NULL
        )
        """
    )


def _decrement_stock_fifo(cursor, artikl_id, plateno, kolicina):
    remaining = kolicina
    rows = cursor.execute(
        """
        SELECT id, kolicina FROM zaliha_dodadi
        WHERE artikl_id = ? AND plateno = ? AND kolicina > 0
        ORDER BY datum ASC
        """,
        (artikl_id, plateno),
    ).fetchall()

    for row in rows:
        if remaining <= 0:
            break
        row_id = row["id"]
        row_qty = int(row["kolicina"])
        if row_qty <= remaining:
            cursor.execute("DELETE FROM zaliha_dodadi WHERE id = ?", (row_id,))
            remaining -= row_qty
        else:
            cursor.execute(
                "UPDATE zaliha_dodadi SET kolicina = kolicina - ? WHERE id = ?",
                (remaining, row_id),
            )
            remaining = 0


def submit_pending_exports(data, username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_pending_exports_table(cursor)
        artikli = (data or {}).get("artikli", [])
        total_pending = 0
        errors = []

        for art in artikli:
            art_id = int(art.get("id", 0))
            pn = str(art.get("pn", "")).strip()
            izvoz_platena = int(art.get("platena", 0))
            izvoz_neplatena = int(art.get("neplatena", 0))

            if izvoz_platena <= 0 and izvoz_neplatena <= 0:
                continue

            part_row = cursor.execute("SELECT ime FROM parts WHERE id = ?", (art_id,)).fetchone()
            ime = part_row["ime"] if part_row and part_row["ime"] else "—"

            if izvoz_platena > 0:
                avail = cursor.execute(
                    """
                    SELECT COALESCE(SUM(kolicina), 0) AS total
                    FROM zaliha_dodadi WHERE artikl_id = ? AND plateno = 1
                    """,
                    (art_id,),
                ).fetchone()
                avail_qty = int(avail["total"]) if avail else 0
                if izvoz_platena > avail_qty:
                    errors.append(f"❌ {pn}: Немате доволно платена залиха! (Расположливо: {avail_qty})")
                else:
                    _decrement_stock_fifo(cursor, art_id, 1, izvoz_platena)
                    cursor.execute(
                        """
                        INSERT INTO zaliha_izvoz_pending
                            (artikl_id, pn, ime, kolicina, tip, datum_izvoz, username, status)
                        VALUES (?, ?, ?, ?, 'Извоз - Платена', ?, ?, 'pending')
                        """,
                        (art_id, pn, ime, izvoz_platena, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username),
                    )
                    total_pending += izvoz_platena

            if izvoz_neplatena > 0:
                avail = cursor.execute(
                    """
                    SELECT COALESCE(SUM(kolicina), 0) AS total
                    FROM zaliha_dodadi WHERE artikl_id = ? AND plateno = 0
                    """,
                    (art_id,),
                ).fetchone()
                avail_qty = int(avail["total"]) if avail else 0
                if izvoz_neplatena > avail_qty:
                    errors.append(f"❌ {pn}: Немате доволно неплатена залиха! (Расположливо: {avail_qty})")
                else:
                    _decrement_stock_fifo(cursor, art_id, 0, izvoz_neplatena)
                    cursor.execute(
                        """
                        INSERT INTO zaliha_izvoz_pending
                            (artikl_id, pn, ime, kolicina, tip, datum_izvoz, username, status)
                        VALUES (?, ?, ?, ?, 'Извоз - Неплатена', ?, ?, 'pending')
                        """,
                        (art_id, pn, ime, izvoz_neplatena, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username),
                    )
                    total_pending += izvoz_neplatena

        if errors:
            conn.rollback()
            return {"success": False, "message": "\n".join(errors)}, 400

        if total_pending <= 0:
            return {"success": False, "message": "Не избра количина за извоз!"}, 400

        conn.commit()
        return {
            "success": True,
            "message": f"Испратено {total_pending} единици на одобрување (pending извози)!",
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()


def get_pending_exports():
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_pending_exports_table(cursor)
        conn.commit()
        return cursor.execute(
            """
            SELECT id, artikl_id, pn, ime, kolicina, tip, status, datum_izvoz, username
            FROM zaliha_izvoz_pending
            WHERE status = 'pending'
            ORDER BY datum_izvoz DESC
            """
        ).fetchall()
    finally:
        conn.close()


def approve_pending_export(pending_id, username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_pending_exports_table(cursor)
        item = cursor.execute(
            "SELECT * FROM zaliha_izvoz_pending WHERE id = ? AND status = 'pending'",
            (pending_id,),
        ).fetchone()
        if not item:
            return {"success": False, "message": "Не е пронајден pending извоз"}, 404

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            UPDATE zaliha_izvoz_pending
            SET status = 'odobren', datum_odobren = ?, odobren_od = ?
            WHERE id = ?
            """,
            (now, username, pending_id),
        )
        cursor.execute(
            """
            INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now, username, item["pn"], item["ime"], item["kolicina"], item["tip"]),
        )
        conn.commit()
        return {
            "success": True,
            "message": f'Одобрен извоз на {item["kolicina"]} единици од {item["pn"]}!',
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()


def reject_pending_export(pending_id, username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_pending_exports_table(cursor)
        item = cursor.execute(
            "SELECT * FROM zaliha_izvoz_pending WHERE id = ? AND status = 'pending'",
            (pending_id,),
        ).fetchone()
        if not item:
            return {"success": False, "message": "Не е пронајден pending извоз"}, 404

        plateno = 1 if "Платена" in item["tip"] else 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_date = datetime.now().strftime("%Y-%m-%d")

        cursor.execute(
            """
            INSERT INTO zaliha_dodadi (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
            VALUES (?, ?, 0, ?, ?, ?, ?)
            """,
            (item["artikl_id"], item["kolicina"], now_date, plateno, username, f"Вратено (одбиен извоз #{pending_id})"),
        )
        cursor.execute(
            """
            UPDATE zaliha_izvoz_pending
            SET status = 'odbijen', datum_odobren = ?, odobren_od = ?
            WHERE id = ?
            """,
            (now_str, username, pending_id),
        )
        conn.commit()
        return {
            "success": True,
            "message": f'Одбиен извоз и вратени {item["kolicina"]} единици во залиха!',
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()


def approve_all_pending_exports(username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_pending_exports_table(cursor)
        items = cursor.execute("SELECT * FROM zaliha_izvoz_pending WHERE status = 'pending'").fetchall()
        if not items:
            return {"success": False, "message": "Нема pending извози за одобрување"}, 400

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = 0
        for item in items:
            cursor.execute(
                """
                UPDATE zaliha_izvoz_pending
                SET status = 'odobren', datum_odobren = ?, odobren_od = ?
                WHERE id = ?
                """,
                (now, username, item["id"]),
            )
            cursor.execute(
                """
                INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, username, item["pn"], item["ime"], item["kolicina"], item["tip"]),
            )
            total += item["kolicina"]

        conn.commit()
        return {
            "success": True,
            "message": f"Одобрени сите {len(items)} pending извози ({total} единици)!",
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()


def execute_storno(data, username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        artikl_id = int((data or {}).get("artikl_id", 0))
        pn = str((data or {}).get("pn", "")).strip().upper()
        kolicina = int((data or {}).get("kolicina", 0))
        plateno = int((data or {}).get("plateno", 0))
        zabeleska = str((data or {}).get("zabeleska", "")).strip()

        if artikl_id <= 0 or kolicina <= 0:
            return {"success": False, "message": "Невалиден артикл или количина!"}, 400
        if not zabeleska:
            return {"success": False, "message": "Забелешката е задолжителна!"}, 400

        avail = cursor.execute(
            """
            SELECT COALESCE(SUM(kolicina), 0) AS total
            FROM zaliha_dodadi
            WHERE artikl_id = ? AND plateno = ?
            """,
            (artikl_id, plateno),
        ).fetchone()
        avail_qty = int(avail["total"]) if avail else 0
        if kolicina > avail_qty:
            tip_str = "платена" if plateno else "неплатена"
            return {
                "success": False,
                "message": f"Немате доволно {tip_str} залиха! Расположливо: {avail_qty}",
            }, 400

        _decrement_stock_fifo(cursor, artikl_id, plateno, kolicina)

        part = cursor.execute("SELECT ime FROM parts WHERE id = ?", (artikl_id,)).fetchone()
        ime = part["ime"] if part and part["ime"] else "—"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tip_log = f"Сторно - {'Платена' if plateno else 'Неплатена'}"

        cursor.execute(
            """
            INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now_str, username, pn, ime, kolicina, tip_log),
        )
        ensure_storno_log_table(cursor)
        cursor.execute(
            """
            INSERT INTO zaliha_storno_log
                (datum, username, artikl_id, pn, ime, kolicina, plateno, tip, zabeleska)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_str, username, artikl_id, pn, ime, kolicina, plateno, tip_log, zabeleska),
        )
        conn.commit()
        tip_str = "платена" if plateno else "неплатена"
        return {
            "success": True,
            "message": f"Сторно успешно! Одземени {kolicina} ед. ({tip_str}) од {pn}.",
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()


def get_storno_history(limit=50):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_storno_log_table(cursor)
        conn.commit()
        return cursor.execute(
            """
            SELECT datum, username, pn, ime, kolicina, plateno, tip, zabeleska
            FROM zaliha_storno_log
            ORDER BY datum DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
