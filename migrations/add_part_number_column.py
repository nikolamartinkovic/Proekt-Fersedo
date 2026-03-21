import sqlite3
import logging

# Setup logging (за production – print-овите ќе бидат во лог)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

conn = None
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Додај колоната ако не постои
    cursor.execute("ALTER TABLE performance ADD COLUMN part_number TEXT")
    conn.commit()
    logger.info("Колоната 'part_number' е успешно додадена во performance!")

except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        logger.info("Колоната 'part_number' веќе постои – нема промена")
    else:
        logger.error(f"SQLite OperationalError: {e}")
except sqlite3.Error as e:
    logger.error(f"SQLite грешка: {e}")
except Exception as e:
    logger.error(f"Општа грешка: {e}")
finally:
    if conn:
        conn.close()
        logger.info("Конекцијата до базата е затворена")