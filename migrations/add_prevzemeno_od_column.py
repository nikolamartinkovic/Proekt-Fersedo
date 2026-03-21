# add_prevzemeno_od_column.py
import sqlite3

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("Проверка на колоната 'prevzemeno_od'...")

cursor.execute("PRAGMA table_info(nabavki_requests)")
columns = [row[1] for row in cursor.fetchall()]

if 'prevzemeno_od' not in columns:
    print("Колоната 'prevzemeno_od' не постои – додавам ја...")
    cursor.execute("ALTER TABLE nabavki_requests ADD COLUMN prevzemeno_od TEXT")
    conn.commit()
    print("Колоната 'prevzemeno_od' е додадена (може да биде NULL).")
else:
    print("Колоната 'prevzemeno_od' веќе постои.")

conn.close()
print("Готово!")