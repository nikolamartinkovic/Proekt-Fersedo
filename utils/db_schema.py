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
    ensure_column(cursor, "users", "email", "email TEXT DEFAULT ''", "email во users")


def ensure_common_indexes(cursor):
    ensure_index(cursor, "idx_users_username", "users", "username", unique=True)
    ensure_index(cursor, "idx_parts_part_number", "parts", "part_number", unique=True)
    ensure_index(cursor, "idx_nabavki_requests_status", "nabavki_requests", "status")
    ensure_index(cursor, "idx_nabavki_requests_prevzemeno", "nabavki_requests", "prevzemeno_od")
    ensure_index(cursor, "idx_nabavki_comments_req_id", "nabavki_comments", "req_id")
    ensure_index(cursor, "idx_zaliha_dodadi_artikl_plateno", "zaliha_dodadi", "artikl_id, plateno, datum")
    ensure_index(cursor, "idx_zaliha_izvoz_pending_status", "zaliha_izvoz_pending", "status, datum_izvoz")
    ensure_index(cursor, "idx_zaliha_izvoz_log_datum", "zaliha_izvoz_log", "datum")
    ensure_index(cursor, "idx_baranja_odmor_vraboten", "baranja_odmor", "vraboten_id, status")
    ensure_index(cursor, "idx_odmor_salda_vraboten_godina", "odmor_salda", "vraboten_id, godina", unique=True)
