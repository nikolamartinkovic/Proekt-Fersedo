import sqlite3

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number TEXT UNIQUE NOT NULL,
    kamin TEXT NOT NULL,
    slika TEXT
)
""")

conn.commit()
conn.close()
print("Табелата 'parts' е креирана!")