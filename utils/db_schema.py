import sqlite3


def table_exists(cursor, table_name):
    row = cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def get_table_columns(cursor, table_name):
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def column_exists(cursor, table_name, column_name):
    if not table_exists(cursor, table_name):
        return False
    return column_name in get_table_columns(cursor, table_name)


def ensure_column(cursor, table_name, column_name, column_sql, description):
    if column_exists(cursor, table_name, column_name):
        print(f"[MIGRATION] Веќе постои: {description}")
        return False

    try:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
        print(f"[MIGRATION] Успешно: {description}")
        return True
    except sqlite3.OperationalError as exc:
        print(f"[MIGRATION ERROR] {description}: {exc}")
        return False


def ensure_index(cursor, index_name, table_name, columns, *, unique=False, where=None):
    unique_sql = "UNIQUE " if unique else ""
    where_sql = f" WHERE {where}" if where else ""
    cursor.execute(
        f"""
        CREATE {unique_sql}INDEX IF NOT EXISTS {index_name}
        ON {table_name} ({columns}){where_sql}
        """
    )


def apply_standard_migrations(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kvalitet_odgovori_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kontrola_id INTEGER NOT NULL,
            odgovor_id INTEGER,
            podcekor_id INTEGER,
            cekor_naslov TEXT,
            podcekor_opis TEXT,
            status INTEGER,
            zabeleska TEXT,
            slika TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (kontrola_id) REFERENCES kvalitet_kontrola(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kvalitet_vlezna_kontrola (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum_kontrola TEXT NOT NULL,
            dokument_broj TEXT NOT NULL,
            dokument_tip TEXT NOT NULL,
            dobavuvac TEXT DEFAULT '',
            status TEXT DEFAULT 'DOBAR',
            username TEXT NOT NULL,
            pdf_file TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kvalitet_vlezna_stavki (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kontrola_id INTEGER NOT NULL,
            materijal TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DOBAR',
            zabeleska TEXT DEFAULT '',
            slika TEXT DEFAULT '',
            redosled INTEGER DEFAULT 0,
            FOREIGN KEY (kontrola_id) REFERENCES kvalitet_vlezna_kontrola(id) ON DELETE CASCADE
        )
        """
    )

    ensure_column(cursor, "parts", "slika", "slika TEXT", "slika во parts")
    ensure_column(cursor, "parts", "ime", "ime TEXT", "ime во parts")
    ensure_column(
        cursor,
        "nabavki_archive",
        "arhiva_broj",
        "arhiva_broj TEXT",
        "arhiva_broj во nabavki_archive",
    )
    ensure_column(
        cursor,
        "kvalitet_template_cekori",
        "redosled",
        "redosled INTEGER DEFAULT 0",
        "redosled во kvalitet_template_cekori",
    )
    ensure_column(
        cursor,
        "kvalitet_kontrola",
        "original_pdf_file",
        "original_pdf_file TEXT",
        "original_pdf_file во kvalitet_kontrola",
    )
    ensure_column(
        cursor,
        "kvalitet_kontrola",
        "vnatresen_broj",
        "vnatresen_broj TEXT DEFAULT ''",
        "vnatresen_broj во kvalitet_kontrola",
    )
    ensure_column(
        cursor,
        "kvalitet_vlezna_stavki",
        "slika",
        "slika TEXT DEFAULT ''",
        "slika во kvalitet_vlezna_stavki",
    )
    ensure_column(
        cursor,
        "baranja_odmor",
        "zabeleska",
        "zabeleska TEXT DEFAULT ''",
        "zabeleska во baranja_odmor",
    )
    ensure_column(
        cursor,
        "baranja_odmor",
        "podneseno_od",
        "podneseno_od TEXT",
        "podneseno_od во baranja_odmor",
    )
    ensure_column(
        cursor,
        "baranja_odmor",
        "podneseno_na",
        "podneseno_na TEXT DEFAULT CURRENT_TIMESTAMP",
        "podneseno_na во baranja_odmor",
    )
    ensure_column(
        cursor,
        "baranja_odmor",
        "kolektiven_grupa",
        "kolektiven_grupa TEXT DEFAULT ''",
        "kolektiven_grupa во baranja_odmor",
    )
    ensure_column(cursor, "users", "email", "email TEXT DEFAULT ''", "email во users")
    ensure_column(
        cursor,
        "users",
        "must_change_password",
        "must_change_password INTEGER DEFAULT 0",
        "must_change_password во users",
    )
    ensure_column(
        cursor,
        "odrzuvanje_planovi",
        "auto_kreiraj_nalog",
        "auto_kreiraj_nalog INTEGER DEFAULT 1",
        "auto_kreiraj_nalog во odrzuvanje_planovi",
    )
    ensure_column(
        cursor,
        "odrzuvanje_nalozi",
        "plan_id",
        "plan_id INTEGER",
        "plan_id во odrzuvanje_nalozi",
    )
    ensure_column(
        cursor,
        "odrzuvanje_nalozi",
        "auto_kreirano",
        "auto_kreirano INTEGER DEFAULT 0",
        "auto_kreirano во odrzuvanje_nalozi",
    )
    ensure_column(
        cursor,
        "vraboteni",
        "datum_posleden_sistematski",
        "datum_posleden_sistematski DATE",
        "datum_posleden_sistematski во vraboteni",
    )

    if (
        table_exists(cursor, "kvalitet_kontrola")
        and table_exists(cursor, "kvalitet_odgovori")
        and table_exists(cursor, "kvalitet_odgovori_snapshot")
    ):
        cursor.execute(
            """
            INSERT INTO kvalitet_odgovori_snapshot (
                kontrola_id,
                odgovor_id,
                podcekor_id,
                cekor_naslov,
                podcekor_opis,
                status,
                zabeleska,
                slika
            )
            SELECT
                o.kontrola_id,
                o.id,
                o.podcekor_id,
                COALESCE(c.naslov, ''),
                COALESCE(p.opis, ''),
                COALESCE(o.status, 0),
                COALESCE(o.zabeleska, ''),
                COALESCE(o.slika, '')
            FROM kvalitet_odgovori o
            LEFT JOIN kvalitet_template_podcekori p ON p.id = o.podcekor_id
            LEFT JOIN kvalitet_template_cekori c ON c.id = p.cekor_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM kvalitet_odgovori_snapshot s
                WHERE s.kontrola_id = o.kontrola_id
            )
            """
        )


def ensure_common_indexes(cursor):
    ensure_index(cursor, "idx_users_username", "users", "username", unique=True)
    ensure_index(cursor, "idx_parts_part_number", "parts", "part_number", unique=True)
    ensure_index(cursor, "idx_nabavki_requests_status", "nabavki_requests", "status")
    ensure_index(cursor, "idx_nabavki_requests_prevzemeno", "nabavki_requests", "prevzemeno_od")
    ensure_index(cursor, "idx_nabavki_comments_req_id", "nabavki_comments", "req_id")
    ensure_index(cursor, "idx_zaliha_dodadi_artikl_plateno", "zaliha_dodadi", "artikl_id, plateno, datum")
    ensure_index(cursor, "idx_zaliha_izvoz_pending_status", "zaliha_izvoz_pending", "status, datum_izvoz")
    ensure_index(cursor, "idx_zaliha_izvoz_log_datum", "zaliha_izvoz_log", "datum")
    ensure_index(cursor, "idx_dashboard_izvozi_datum", "dashboard_izvozi", "datum")
    if table_exists(cursor, "dashboard_izvozi_targets"):
        ensure_index(cursor, "idx_dashboard_izvozi_targets_year", "dashboard_izvozi_targets", "year", unique=True)
    ensure_index(cursor, "idx_baranja_odmor_vraboten", "baranja_odmor", "vraboten_id, status")
    ensure_index(cursor, "idx_baranja_odmor_kolektivna_grupa", "baranja_odmor", "kolektiven_grupa")
    ensure_index(cursor, "idx_odmor_salda_vraboten_godina", "odmor_salda", "vraboten_id, godina", unique=True)
    if table_exists(cursor, "kvalitet_kontrola"):
        ensure_index(
            cursor,
            "idx_kvalitet_kontrola_vnatresen_broj",
            "kvalitet_kontrola",
            "vnatresen_broj",
            unique=True,
            where="vnatresen_broj IS NOT NULL AND vnatresen_broj <> ''",
        )
    if table_exists(cursor, "kvalitet_odgovori_snapshot"):
        ensure_index(
            cursor,
            "idx_kvalitet_snapshot_kontrola",
            "kvalitet_odgovori_snapshot",
            "kontrola_id",
        )
        ensure_index(
            cursor,
            "idx_kvalitet_snapshot_status",
            "kvalitet_odgovori_snapshot",
            "status, kontrola_id",
        )
    if table_exists(cursor, "odrzuvanje_planovi"):
        ensure_index(
            cursor,
            "idx_odrzuvanje_planovi_due_auto",
            "odrzuvanje_planovi",
            "aktivno, auto_kreiraj_nalog, sledno_izvrsuvanje",
        )
    if table_exists(cursor, "odrzuvanje_nalozi"):
        ensure_index(
            cursor,
            "idx_odrzuvanje_nalozi_plan_status",
            "odrzuvanje_nalozi",
            "plan_id, status",
        )
    if table_exists(cursor, "performance_error_images"):
        ensure_index(cursor, "idx_perf_error_images_perf", "performance_error_images", "performance_id")
        ensure_index(
            cursor,
            "idx_perf_error_images_perf_idx",
            "performance_error_images",
            "performance_id, error_index",
            unique=True,
        )
    if table_exists(cursor, "kvalitet_vlezna_kontrola"):
        ensure_index(
            cursor,
            "idx_kvalitet_vlezna_datum",
            "kvalitet_vlezna_kontrola",
            "datum_kontrola DESC, id DESC",
        )
        ensure_index(
            cursor,
            "idx_kvalitet_vlezna_dokument",
            "kvalitet_vlezna_kontrola",
            "dokument_broj, dokument_tip",
        )
        ensure_index(
            cursor,
            "idx_kvalitet_vlezna_status",
            "kvalitet_vlezna_kontrola",
            "status",
        )
    if table_exists(cursor, "kvalitet_vlezna_stavki"):
        ensure_index(
            cursor,
            "idx_kvalitet_vlezna_stavki_kontrola",
            "kvalitet_vlezna_stavki",
            "kontrola_id, redosled",
        )
