from datetime import datetime

from utils.db import get_db


def ensure_profakturi_tables(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profakturi (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            broj            TEXT    NOT NULL,
            datum           TEXT    NOT NULL,
            username        TEXT    NOT NULL,
            status          TEXT    DEFAULT 'pending',
            datum_odobrena  TEXT,
            odobrena_od     TEXT,
            napomena        TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profaktura_stavki (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            profaktura_id INTEGER NOT NULL,
            artikl_id     INTEGER NOT NULL,
            pn            TEXT    NOT NULL,
            ime           TEXT,
            kolicina      INTEGER NOT NULL
        )
        """
    )


def get_izvoz_artikli():
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_profakturi_tables(cursor)
        conn.commit()

        artikli_rows = cursor.execute(
            """
            SELECT a.id, a.part_number, a.ime,
                   COALESCE(SUM(CASE WHEN d.plateno=1 THEN d.kolicina ELSE 0 END), 0) AS kolicina_platena,
                   COALESCE(SUM(CASE WHEN d.plateno=0 THEN d.kolicina ELSE 0 END), 0) AS kolicina_neplatena
            FROM parts a
            LEFT JOIN zaliha_dodadi d ON a.id = d.artikl_id
            GROUP BY a.id
            HAVING (kolicina_platena + kolicina_neplatena) > 0
            ORDER BY a.part_number
            """
        ).fetchall()

        profaktura_reserved = cursor.execute(
            """
            SELECT s.artikl_id, SUM(s.kolicina) AS kolicina_profaktura
            FROM profaktura_stavki s
            JOIN profakturi p ON s.profaktura_id = p.id
            WHERE p.status = 'pending'
            GROUP BY s.artikl_id
            """
        ).fetchall()
        reserved_map = {row["artikl_id"]: row["kolicina_profaktura"] for row in profaktura_reserved}

        artikli = []
        existing_ids = set()
        for row in artikli_rows:
            item = dict(row)
            item["kolicina_profaktura"] = reserved_map.get(item["id"], 0)
            artikli.append(item)
            existing_ids.add(item["id"])

        for art_id, qty in reserved_map.items():
            if art_id not in existing_ids:
                part = cursor.execute(
                    "SELECT id, part_number, ime FROM parts WHERE id = ?",
                    (art_id,),
                ).fetchone()
                if part:
                    artikli.append(
                        {
                            "id": part["id"],
                            "part_number": part["part_number"],
                            "ime": part["ime"],
                            "kolicina_platena": 0,
                            "kolicina_neplatena": 0,
                            "kolicina_profaktura": qty,
                        }
                    )

        artikli.sort(key=lambda item: item["part_number"])
        return artikli
    finally:
        conn.close()


def get_pregled_data():
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_profakturi_tables(cursor)
        conn.commit()

        plateni = cursor.execute(
            """
            SELECT a.id, a.part_number, a.ime,
                   SUM(d.kolicina) AS kolicina_platena
            FROM zaliha_dodadi d
            JOIN parts a ON d.artikl_id = a.id
            WHERE d.plateno = 1
            GROUP BY a.id HAVING SUM(d.kolicina) > 0
            ORDER BY a.part_number
            """
        ).fetchall()

        neplateni = cursor.execute(
            """
            SELECT a.id, a.part_number, a.ime,
                   SUM(d.kolicina) AS kolicina_neplatena
            FROM zaliha_dodadi d
            JOIN parts a ON d.artikl_id = a.id
            WHERE d.plateno = 0
            GROUP BY a.id HAVING SUM(d.kolicina) > 0
            ORDER BY a.part_number
            """
        ).fetchall()

        profaktura_zaliha_rows = cursor.execute(
            """
            SELECT s.artikl_id, s.pn, s.ime,
                   SUM(s.kolicina) AS kolicina_reserved,
                   GROUP_CONCAT(p.broj, ', ') AS profakturi_broevi,
                   GROUP_CONCAT(p.username, ', ') AS korisnici_raw
            FROM profaktura_stavki s
            JOIN profakturi p ON s.profaktura_id = p.id
            WHERE p.status = 'pending'
            GROUP BY s.artikl_id
            ORDER BY s.pn
            """
        ).fetchall()

        profaktura_zaliha = []
        for row in profaktura_zaliha_rows:
            item = dict(row)
            if item.get("korisnici_raw"):
                users = sorted(set(user.strip() for user in item["korisnici_raw"].split(",")))
                item["korisnici"] = ", ".join(users)
            else:
                item["korisnici"] = "—"
            profaktura_zaliha.append(item)

        return plateni, neplateni, profaktura_zaliha
    finally:
        conn.close()


def get_profakturi_nova_artikli():
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_profakturi_tables(cursor)
        conn.commit()
        return cursor.execute(
            """
            SELECT a.id, a.part_number, a.ime,
                   COALESCE(SUM(d.kolicina), 0) AS kolicina_neplatena
            FROM parts a
            LEFT JOIN zaliha_dodadi d ON a.id = d.artikl_id AND d.plateno = 0
            GROUP BY a.id
            HAVING kolicina_neplatena > 0
            ORDER BY a.part_number
            """
        ).fetchall()
    finally:
        conn.close()


def create_profaktura(data, username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_profakturi_tables(cursor)
        conn.commit()

        artikli = data.get("artikli", [])
        napomena = data.get("napomena", "").strip()

        if not artikli:
            return {"success": False, "message": "Не избра ниеден артикл!"}, 400

        last = cursor.execute(
            "SELECT COUNT(*) AS cnt FROM profakturi WHERE datum LIKE ?",
            (datetime.now().strftime("%Y-%m-%d") + "%",),
        ).fetchone()
        seq = (last["cnt"] if last else 0) + 1
        broj = f"PF-{datetime.now().strftime('%Y%m%d')}-{seq:03d}"

        errors = []
        valid = []

        for art in artikli:
            art_id = int(art.get("id", 0))
            pn = str(art.get("pn", "")).strip()
            kolicina = int(art.get("kolicina", 0))

            if kolicina <= 0:
                continue

            avail = cursor.execute(
                """
                SELECT COALESCE(SUM(kolicina), 0) AS total
                FROM zaliha_dodadi
                WHERE artikl_id = ? AND plateno = 0
                """,
                (art_id,),
            ).fetchone()
            avail_qty = int(avail["total"]) if avail else 0

            if kolicina > avail_qty:
                errors.append(
                    f"❌ {pn}: Немате доволно неплатена залиха! (Расположливо: {avail_qty})"
                )
                continue

            valid.append({"id": art_id, "pn": pn, "kolicina": kolicina})

        if errors:
            conn.rollback()
            return {"success": False, "message": "\n".join(errors)}, 400

        if not valid:
            return {"success": False, "message": "Не избра количина за ниеден артикл!"}, 400

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO profakturi (broj, datum, username, status, napomena)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (broj, now_str, username, napomena),
        )
        profaktura_id = cursor.lastrowid

        for art in valid:
            art_id = art["id"]
            pn = art["pn"]
            kolicina = art["kolicina"]

            part_row = cursor.execute("SELECT ime FROM parts WHERE id = ?", (art_id,)).fetchone()
            ime = part_row["ime"] if part_row and part_row["ime"] else "—"

            remaining = kolicina
            rows = cursor.execute(
                """
                SELECT id, kolicina FROM zaliha_dodadi
                WHERE artikl_id = ? AND plateno = 0 AND kolicina > 0
                ORDER BY datum ASC
                """,
                (art_id,),
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

            cursor.execute(
                """
                INSERT INTO profaktura_stavki (profaktura_id, artikl_id, pn, ime, kolicina)
                VALUES (?, ?, ?, ?, ?)
                """,
                (profaktura_id, art_id, pn, ime, kolicina),
            )

        conn.commit()
        return {
            "success": True,
            "message": f"✅ Профактурата {broj} е креирана и чека одобрување!",
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()


def get_pending_profakturi():
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_profakturi_tables(cursor)
        conn.commit()

        profakturi = cursor.execute(
            """
            SELECT p.id, p.broj, p.datum, p.username, p.napomena,
                   SUM(s.kolicina) AS vkupno_kolicina,
                   COUNT(s.id) AS broj_stavki
            FROM profakturi p
            LEFT JOIN profaktura_stavki s ON p.id = s.profaktura_id
            WHERE p.status = 'pending'
            GROUP BY p.id
            ORDER BY p.datum DESC
            """
        ).fetchall()

        result = []
        for profaktura in profakturi:
            stavki = cursor.execute(
                """
                SELECT pn, ime, kolicina FROM profaktura_stavki
                WHERE profaktura_id = ?
                """,
                (profaktura["id"],),
            ).fetchall()
            result.append(
                {
                    "id": profaktura["id"],
                    "broj": profaktura["broj"],
                    "datum": profaktura["datum"][:16],
                    "username": profaktura["username"],
                    "napomena": profaktura["napomena"] or "—",
                    "vkupno_kolicina": profaktura["vkupno_kolicina"] or 0,
                    "broj_stavki": profaktura["broj_stavki"] or 0,
                    "stavki": [dict(stavka) for stavka in stavki],
                }
            )

        return result
    finally:
        conn.close()


def approve_profaktura(profaktura_id, username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_profakturi_tables(cursor)

        profaktura = cursor.execute(
            "SELECT * FROM profakturi WHERE id = ? AND status = 'pending'",
            (profaktura_id,),
        ).fetchone()
        if not profaktura:
            return {"success": False, "message": "Профактурата не е пронајдена"}, 404

        stavki = cursor.execute(
            "SELECT * FROM profaktura_stavki WHERE profaktura_id = ?",
            (profaktura_id,),
        ).fetchall()

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_date = datetime.now().strftime("%Y-%m-%d")

        for stavka in stavki:
            cursor.execute(
                """
                INSERT INTO zaliha_dodadi
                    (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
                VALUES (?, ?, 0, ?, 1, ?, ?)
                """,
                (
                    stavka["artikl_id"],
                    stavka["kolicina"],
                    now_date,
                    username,
                    f"Одобрена профактура {profaktura['broj']}",
                ),
            )
            cursor.execute(
                """
                INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now_str,
                    username,
                    stavka["pn"],
                    stavka["ime"],
                    stavka["kolicina"],
                    f"Профактура {profaktura['broj']} – Платена",
                ),
            )

        cursor.execute(
            """
            UPDATE profakturi
            SET status = 'odobrena', datum_odobrena = ?, odobrena_od = ?
            WHERE id = ?
            """,
            (now_str, username, profaktura_id),
        )

        conn.commit()
        return {
            "success": True,
            "message": f"✅ Профактурата {profaktura['broj']} е одобрена! Залихата е префрлена во Платена.",
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()


def reject_profaktura(profaktura_id, username):
    conn = get_db()
    cursor = conn.cursor()
    try:
        ensure_profakturi_tables(cursor)

        profaktura = cursor.execute(
            "SELECT * FROM profakturi WHERE id = ? AND status = 'pending'",
            (profaktura_id,),
        ).fetchone()
        if not profaktura:
            return {"success": False, "message": "Профактурата не е пронајдена"}, 404

        stavki = cursor.execute(
            "SELECT * FROM profaktura_stavki WHERE profaktura_id = ?",
            (profaktura_id,),
        ).fetchall()

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_date = datetime.now().strftime("%Y-%m-%d")

        for stavka in stavki:
            cursor.execute(
                """
                INSERT INTO zaliha_dodadi
                    (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
                VALUES (?, ?, 0, ?, 0, ?, ?)
                """,
                (
                    stavka["artikl_id"],
                    stavka["kolicina"],
                    now_date,
                    username,
                    f"Вратено (одбиена профактура {profaktura['broj']})",
                ),
            )

        cursor.execute(
            """
            UPDATE profakturi
            SET status = 'odbiena', datum_odobrena = ?, odobrena_od = ?
            WHERE id = ?
            """,
            (now_str, username, profaktura_id),
        )

        conn.commit()
        return {
            "success": True,
            "message": f"↩️ Профактурата {profaktura['broj']} е одбиена. Залихата е вратена во Неплатена.",
        }, 200
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {exc}"}, 500
    finally:
        conn.close()
