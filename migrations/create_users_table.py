import sqlite3
from argon2 import PasswordHasher

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 1. Креирај табела со ТОЧНИ имиња на колони
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    hashed_password TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0
)
""")

ph = PasswordHasher()

# 2. Додај го admin ако не постои
try:
    hashed = ph.hash("admin2025")
    cursor.execute("""
        INSERT INTO users (username, hashed_password, is_admin)
        VALUES (?, ?, ?)
    """, ('admin', hashed, 1))
    conn.commit()
    print("Admin е успешно креиран со Argon2 хеш!")
except sqlite3.IntegrityError:
    print("Admin веќе постои во базата.")

conn.close()
print("Табела 'users' е готова!")