import sqlite3
import os
from flask import current_app
from extensions import ph  # За хеширање на лозинка за default admin
from utils.db_schema import apply_standard_migrations, ensure_common_indexes

# Глобална променлива за патека до базата (ќе ја поставиме од app.py)
DATABASE_PATH = None
DEFAULT_DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance", "database.db"),
)


def _configure_connection(conn):
    """Apply SQLite pragmas that make concurrent access more tolerant."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        pass

def get_db():
    """Отвора SQLite конекција со dict row factory."""
    global DATABASE_PATH

    if DATABASE_PATH is None:
        try:
            DATABASE_PATH = current_app.config['DATABASE_PATH']
        except RuntimeError:
            DATABASE_PATH = DEFAULT_DATABASE_PATH

    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=10,
        check_same_thread=False,
    )
    _configure_connection(conn)
    conn.row_factory = lambda cursor, row: dict(
        zip([col[0] for col in cursor.description], row)
    )
    return conn


# ─────────────────────────────────────────────────────────────
# ЦЕНТРАЛИЗИРАНА ИНИЦИЈАЛИЗАЦИЈА НА БАЗАТА
# ─────────────────────────────────────────────────────────────
def init_db():
    """Креира сите табели, извршува миграции и додава default admin ако нема корисници."""
    conn = get_db()
    cursor = conn.cursor()

    print("[INIT DB] Почнува иницијализација на базата...")

    # ─────────────────────────────────────────────────────────────
    # КРЕИРАЊЕ НА СИТЕ ТАБЕЛИ (IF NOT EXISTS)
    # ─────────────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            user_group TEXT DEFAULT '',
            allowed_modules TEXT DEFAULT ''
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kamini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ime TEXT UNIQUE NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_number TEXT UNIQUE NOT NULL,
            ime TEXT,
            kamin TEXT,
            slika TEXT,
            vid_artikal TEXT,
            odobren INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            oddel TEXT NOT NULL,
            proizvod TEXT NOT NULL,
            proizvedeni INTEGER NOT NULL,
            greski INTEGER DEFAULT 0,
            vid_greska TEXT DEFAULT '-',
            zabeleska TEXT,
            username TEXT NOT NULL,
            kamin TEXT,
            part_number TEXT,
            tip_proizvod TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS planovi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kamin TEXT NOT NULL,
            plan_kolicina INTEGER NOT NULL,
            datum_od DATE NOT NULL,
            datum_do DATE NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            subscription TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mobile_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            url TEXT DEFAULT '/',
            category TEXT DEFAULT 'general',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_release_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_key TEXT NOT NULL UNIQUE,
            version_name TEXT NOT NULL,
            version_code INTEGER NOT NULL,
            push_sent_at TEXT DEFAULT NULL,
            email_sent_at TEXT DEFAULT NULL,
            push_count INTEGER DEFAULT 0,
            email_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
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
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nabavki_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            naslov TEXT NOT NULL,
            kolicina INTEGER NOT NULL,
            opis TEXT,
            slika TEXT,
            datum_kreiranje TEXT NOT NULL,
            status TEXT DEFAULT 'креирано',
            datum_naracka TEXT,
            datum_priem TEXT,
            admin_naracal TEXT,
            datum_itnost TEXT,
            nalog_broj TEXT UNIQUE,
            prevzemeno_od TEXT,
            datum_prevzemanje TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nabavki_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            req_id INTEGER NOT NULL,
            user TEXT NOT NULL,
            comment TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nabavki_archive (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            naslov TEXT NOT NULL,
            kolicina INTEGER NOT NULL,
            opis TEXT,
            slika TEXT,
            datum_kreiranje TEXT,
            status TEXT,
            datum_naracka TEXT,
            datum_priem TEXT,
            admin_naracal TEXT,
            datum_itnost TEXT,
            nalog_broj TEXT UNIQUE,
            prevzemeno_od TEXT,
            datum_prevzemanje TEXT,
            arhivirano_na TEXT DEFAULT CURRENT_TIMESTAMP,
            arhivirano_od TEXT NOT NULL,
            arhiva_broj TEXT
        )
    """)

    # ── Секвенца за генерирање Fer001, Fer002... броеви ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fer_sequence (
            id INTEGER PRIMARY KEY,
            last_num INTEGER DEFAULT 0
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO fer_sequence (id, last_num) VALUES (1, 0)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nabavki_assign_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            assigned_to TEXT,
            assigned_at TEXT,
            from_thread TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS zaliha_dodadi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artikl_id INTEGER NOT NULL,
            kolicina INTEGER NOT NULL,
            cena REAL DEFAULT 0,
            datum TEXT NOT NULL,
            plateno INTEGER DEFAULT 0,
            username TEXT NOT NULL,
            zabeleska TEXT,
            FOREIGN KEY (artikl_id) REFERENCES parts(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS zaliha_izvoz (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artikl_id INTEGER NOT NULL,
            kolicina INTEGER NOT NULL,
            datum TEXT NOT NULL,
            username TEXT NOT NULL,
            FOREIGN KEY (artikl_id) REFERENCES parts(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS zaliha_dodadi_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            username TEXT NOT NULL,
            pn TEXT NOT NULL,
            ime TEXT NOT NULL,
            kolicina INTEGER NOT NULL,
            tip TEXT NOT NULL,
            zabeleska TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS zaliha_izvoz_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            username TEXT NOT NULL,
            pn TEXT NOT NULL,
            ime TEXT NOT NULL,
            kolicina INTEGER NOT NULL,
            tip TEXT NOT NULL
        )
    """)

    cursor.execute("""
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
            odobren_od TEXT,
            FOREIGN KEY (artikl_id) REFERENCES parts(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            tip TEXT NOT NULL DEFAULT 'to',
            aktiven INTEGER DEFAULT 1,
            dodaden_od TEXT,
            datum_dodavanje TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vraboteni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ime TEXT NOT NULL,
            prezime TEXT NOT NULL,
            maticen_broj TEXT UNIQUE NOT NULL,
            email TEXT,
            pozicija TEXT,
            datum_vrabotuvanje DATE,
            oddel TEXT,
            prekin_staz INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS baranja_odmor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vraboten_id INTEGER,
            datum_od DATE NOT NULL,
            datum_do DATE NOT NULL,
            status TEXT DEFAULT 'pending',
            zabeleska TEXT,
            podneseno_od TEXT,
            podneseno_na TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vraboten_id) REFERENCES vraboteni(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odmor_salda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vraboten_id INTEGER NOT NULL,
            godina INTEGER NOT NULL,
            vkupno_dena INTEGER DEFAULT 20,
            UNIQUE(vraboten_id, godina),
            FOREIGN KEY(vraboten_id) REFERENCES vraboteni(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sekojdnevni_otsustva (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vraboten_id INTEGER NOT NULL,
            datum DATE NOT NULL,
            tip TEXT NOT NULL,
            casovi REAL DEFAULT 8.0,
            plateno INTEGER DEFAULT 1,
            zabeleska TEXT,
            FOREIGN KEY (vraboten_id) REFERENCES vraboteni(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nerabotni_deni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum DATE UNIQUE NOT NULL,
            ime TEXT NOT NULL
        )
    """)

    # ── Email примачи за извештаи за отсуства (менаџери) ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otsustva_manager_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            ime TEXT DEFAULT '',
            aktiven INTEGER DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otsustva_email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip TEXT NOT NULL,
            status TEXT NOT NULL,
            subject TEXT NOT NULL,
            recipients TEXT NOT NULL,
            message TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS procesni_pozicii (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kamin TEXT NOT NULL,
            pozicija_broj INTEGER NOT NULL,
            part_number TEXT,
            slika TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kvalitet_kontrola (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kamin TEXT NOT NULL,
            seriski_broj TEXT NOT NULL,
            naslov TEXT NOT NULL,
            datum TEXT NOT NULL,
            username TEXT NOT NULL,
            status TEXT DEFAULT 'VO_TEK',
            pdf_file TEXT,
            original_pdf_file TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kvalitet_odgovori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kontrola_id INTEGER,
            podcekor_id INTEGER,
            status INTEGER,
            zabeleska TEXT,
            slika TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kvalitet_template (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kamin TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kvalitet_template_cekori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER,
            naslov TEXT,
            redosled INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kvalitet_template_podcekori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cekor_id INTEGER,
            opis TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kvalitet_pdf_verzii (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kontrola_id INTEGER NOT NULL,
            pdf_file TEXT NOT NULL,
            verzija INTEGER NOT NULL,
            datum TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (kontrola_id) REFERENCES kvalitet_kontrola(id)
        )
    """)
    cursor.execute("""CREATE TABLE IF NOT EXISTS chat_rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tip TEXT NOT NULL DEFAULT 'global',
    ime TEXT, user1 TEXT, user2 TEXT)""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL, sender TEXT NOT NULL,
    text TEXT NOT NULL, timestamp TEXT NOT NULL, tip TEXT DEFAULT 'global')""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS chat_read (
    room_id INTEGER NOT NULL, username TEXT NOT NULL,
    last_read_id INTEGER DEFAULT 0,
    PRIMARY KEY (room_id, username))""")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_sequences (
            name TEXT PRIMARY KEY,
            last_num INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_masini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kod TEXT UNIQUE,
            naziv TEXT NOT NULL,
            linija TEXT,
            lokacija TEXT,
            seriski_broj TEXT,
            proizvoditel TEXT,
            model TEXT,
            datum_pustanje TEXT,
            status TEXT DEFAULT 'работи',
            servis_interval_dena INTEGER DEFAULT 0,
            servis_interval_casovi INTEGER DEFAULT 0,
            posleden_servis_na TEXT,
            sledna_proverka_na TEXT,
            belezka TEXT,
            slika TEXT,
            manual_file TEXT,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_checklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            masina_id INTEGER NOT NULL,
            naziv TEXT NOT NULL,
            opis TEXT DEFAULT '',
            aktivna INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (masina_id) REFERENCES odrzuvanje_masini(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_checklist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checklist_id INTEGER NOT NULL,
            naslov TEXT NOT NULL,
            opis TEXT DEFAULT '',
            redosled INTEGER DEFAULT 0,
            FOREIGN KEY (checklist_id) REFERENCES odrzuvanje_checklists(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_nalozi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broj TEXT UNIQUE,
            masina_id INTEGER NOT NULL,
            tip TEXT NOT NULL,
            prioritet TEXT DEFAULT 'среден',
            status TEXT DEFAULT 'креиран',
            naslov TEXT NOT NULL,
            opis_defekt TEXT DEFAULT '',
            simptom TEXT DEFAULT '',
            prijavil TEXT DEFAULT '',
            dodeleno_na TEXT DEFAULT '',
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            pocetok_at TEXT,
            kraj_at TEXT,
            zastoj_minuti INTEGER DEFAULT 0,
            trosok REAL DEFAULT 0,
            potvrdil TEXT DEFAULT '',
            resenie TEXT DEFAULT '',
            FOREIGN KEY (masina_id) REFERENCES odrzuvanje_masini(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_nalog_aktivnosti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nalog_id INTEGER NOT NULL,
            tip TEXT DEFAULT 'note',
            poraka TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (nalog_id) REFERENCES odrzuvanje_nalozi(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_nalog_delovi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nalog_id INTEGER NOT NULL,
            part_number TEXT DEFAULT '',
            opis TEXT NOT NULL,
            kolicina REAL DEFAULT 1,
            source_type TEXT DEFAULT 'рачна ставка',
            nabavka_request_id INTEGER,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (nalog_id) REFERENCES odrzuvanje_nalozi(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_planovi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            masina_id INTEGER NOT NULL,
            naziv TEXT NOT NULL,
            tip TEXT DEFAULT 'превентивно',
            interval_dena INTEGER DEFAULT 0,
            interval_casovi INTEGER DEFAULT 0,
            posledno_izvrseno TEXT,
            sledno_izvrsuvanje TEXT,
            odgovoren TEXT DEFAULT '',
            checklist_id INTEGER,
            aktivno INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (masina_id) REFERENCES odrzuvanje_masini(id),
            FOREIGN KEY (checklist_id) REFERENCES odrzuvanje_checklists(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odrzuvanje_nalog_nabavki (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nalog_id INTEGER NOT NULL,
            nabavka_request_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (nalog_id) REFERENCES odrzuvanje_nalozi(id),
            FOREIGN KEY (nabavka_request_id) REFERENCES nabavki_requests(id)
        )
    """)
    # ─────────────────────────────────────────────────────────────
    # МИГРАЦИИ (ALTER TABLE) - безбедно со try-except
    # ─────────────────────────────────────────────────────────────
    apply_standard_migrations(cursor)
    ensure_common_indexes(cursor)
    conn.commit()

    # DEFAULT ADMIN АКО НЕМА КОРИСНИЦИ
    # ─────────────────────────────────────────────────────────────
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='users'
    """)
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        print("[INIT] Табелата 'users' НЕ е креирана — прескокнување default admin")
    else:
        cursor.execute("SELECT COUNT(*) AS cnt FROM users")
        row = cursor.fetchone()
        user_count = row["cnt"] if row else 0
        print(f"[DEBUG] Табела users постои, број на корисници: {user_count}")

        if user_count == 0:
            default_username = "admin"
            default_password = "admin123"
            try:
                cursor.execute("""
                    INSERT INTO users (username, hashed_password, is_admin, user_group, allowed_modules)
                    VALUES (?, ?, 1, 'Admin', ?)
                """, (
                    default_username,
                    ph.hash(default_password),
                    "select_kamin,add_part,moj_zapisi,artikli,nabavki,dashboard,"
                    "pregled_greski,admin_users,izvestaj,procesni_cekori,"
                    "odmori,baranje_odmor,odmori_vraboteni,odmori_kalendar,odmori_pregled_odmori,"
                    "odmori_manager_emails,zalihi,kvalitet,odrzuvanje,odrzuvanje_masini,"
                    "odrzuvanje_nalozi,odrzuvanje_plan,odrzuvanje_istorija"
                ))
                conn.commit()
                print(f"[INIT] Креиран default admin: username='{default_username}', password='{default_password}'")
            except Exception as e:
                print(f"[INIT ADMIN ERROR] {e}")

    conn.commit()
    conn.close()
    print("[INIT DB] Завршена целосна иницијализација на базата!")


# ─────────────────────────────────────────────────────────────
# ОСТАНАТИТЕ ФУНКЦИИ (за компатибилност)
# ─────────────────────────────────────────────────────────────

def init_zaliha_log_table():
    pass  # Покриено во init_db

def init_pozicii_table():
    pass  # Покриено во init_db

def init_odmori_tables():
    pass  # Покриено во init_db

def init_nabavki_table():
    pass  # Покриено во init_db

def init_add_ime_column():
    pass  # Покриено во миграциите

def init_zaliha_dodadi_log():
    pass  # Покриено во init_db
