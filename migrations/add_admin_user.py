import logging
import sqlite3
from argon2 import PasswordHasher

# Setup logging (за production – print-овите ќе бидат во лог)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # печати во конзола
    ]
)
logger = logging.getLogger(__name__)

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

def add_admin_user():
    ph = PasswordHasher()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 1. Креирај табела ако не постои
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            hashed_password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
        """)

        # 2. Додади index ако не постои (за побрзо пребарување)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_username ON users (username)")

        # 3. Провери дали admin постои
        cursor.execute("SELECT * FROM users WHERE username = 'admin'")
        admin_exists = cursor.fetchone()

        if not admin_exists:
            hashed = ph.hash("admin2025")  # СМЕНИ ЈА ЛОЗИНКАТА ВО PRODUCTION!!!
            cursor.execute("INSERT INTO users (username, hashed_password, is_admin) VALUES (?, ?, ?)",
                           ('admin', hashed, 1))
            conn.commit()
            logger.info("Admin е успешно додаден со Argon2 хеш!")
        else:
            logger.info("Admin веќе постои во базата.")

        conn.close()
        logger.info("Готово! Сега можеш да се логираш со admin / admin2025")

    except sqlite3.Error as e:
        logger.error(f"SQLite грешка: {e}")
    except Exception as e:
        logger.error(f"Општа грешка: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    add_admin_user()