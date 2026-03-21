import sqlite3

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 1. Избриши ја старата табела users (ако постои) за да почнеме чисто
cursor.execute("DROP TABLE IF EXISTS users")

# 2. Креирај нова табела само со hashed_password (без старата password)
cursor.execute("""
CREATE TABLE users (
    username TEXT PRIMARY KEY,
    hashed_password TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0
)
""")

# 3. Додај го admin
from argon2 import PasswordHasher
ph = PasswordHasher()
hashed = ph.hash("admin2025")

cursor.execute("INSERT INTO users (username, hashed_password, is_admin) VALUES (?, ?, ?)",
               ('admin', hashed, 1))

conn.commit()
conn.close()

print("Табела 'users' е ресетирана и admin е додаден со Argon2 хеш!")
print("Сега можеш да се логираш со admin / admin2025")