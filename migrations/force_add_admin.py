import sqlite3
from argon2 import PasswordHasher

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

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

ph = PasswordHasher()

# 2. Форсирај додавање на admin (ако постои – ќе го замени)
hashed = ph.hash("admin2025")  # Твојата лозинка

# Прво избриши стар admin ако постои
cursor.execute("DELETE FROM users WHERE username = 'admin'")

# Додај нов
cursor.execute("INSERT INTO users (username, hashed_password, is_admin) VALUES (?, ?, ?)",
               ('admin', hashed, 1))
conn.commit()

print("Admin е успешно додаден/обновен со Argon2 хеш!")
print("Сега можеш да се логираш со:")
print("Username: admin")
print("Password: admin2025")

conn.close()
print("Готово!")