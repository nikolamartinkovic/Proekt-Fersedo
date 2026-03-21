# add_cena_po_cas.py
import sqlite3
import os

# Твоја патека до базата (провери дали е точна!)
PROJECT_ROOT = r"C:\Users\Server\Desktop\Proekt Fersedo\instance"
DB_PATH = os.path.join(PROJECT_ROOT, "database.db")

def add_cena_columns():
    if not os.path.exists(DB_PATH):
        print(f"Базата не постои на патеката: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Листа на колони за цени по час (REAL = decimal)
    cena_columns = [
        "cena_po_cas_laser REAL DEFAULT 70.0",
        "cena_po_cas_apkant REAL DEFAULT 30.0",
        "cena_po_cas_rolovanje REAL DEFAULT 30.0",
        "cena_po_cas_zavaruvanje REAL DEFAULT 45.0",
        "cena_po_cas_brusenje REAL DEFAULT 45.0",
        "cena_po_cas_drvara REAL DEFAULT 45.0",
        "cena_po_cas_sachmara REAL DEFAULT 55.0",
        "cena_po_cas_farbara REAL DEFAULT 55.0",
    ]

    for col in cena_columns:
        try:
            cursor.execute(f"ALTER TABLE parts ADD COLUMN {col}")
            print(f"Додадена колона: {col.split()[0]}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"Колоната '{col.split()[0]}' веќе постои – прескокнато")
            else:
                print(f"Грешка: {e}")

    conn.commit()
    conn.close()
    print("\nГотово! Провери во DB Browser со: PRAGMA table_info(parts);")
    print("Сега можеш да ја избришеш оваа скрипта.")

if __name__ == '__main__':
    add_cena_columns()