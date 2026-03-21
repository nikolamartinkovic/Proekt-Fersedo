import sqlite3
import logging

# Setup logging (за production – print-овите ќе бидат во лог)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

conn = None
added_count = 0

try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Креирај табела ако не постои
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kamini (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT NOT NULL UNIQUE
    )
    """)

    # Листа на камини
    kamini = [
        "Elise",
        "Elizabeth",
        "Luca Cook",
        "Koko X-tra",
        "Flok"
    ]

    # Додади камини ако не постојат
    for ime in kamini:
        try:
            cursor.execute("INSERT INTO kamini (ime) VALUES (?)", (ime,))
            added_count += 1
        except sqlite3.IntegrityError:
            pass  # веќе постои

    conn.commit()

    if added_count > 0:
        logger.info(f"Успешно додадени {added_count} нови камини!")
    else:
        logger.info("Сите камини веќе постојат – нема промени")

except sqlite3.Error as e:
    logger.error(f"SQLite грешка: {e}")
except Exception as e:
    logger.error(f"Општа грешка: {e}")
finally:
    if conn:
        conn.close()
        logger.info("Конекцијата до базата е затворена")

print("Готово! Камините се додадени/проверини.")