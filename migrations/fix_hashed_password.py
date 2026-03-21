import sqlite3

DB_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Провери дали колоната постои
cursor.execute("PRAGMA table_info(users)")
columns = [col[1] for col in cursor.fetchall()]
print("Колони во табела 'users':", columns)

if 'hashed_password' not in columns:
    print("Колоната 'hashed_password' НЕ постои – додавам ја...")
    cursor.execute("ALTER TABLE users ADD COLUMN hashed_password TEXT")
    conn.commit()
    print("Колоната е додадена!")
else:
    print("Колоната 'hashed_password' веќе постои.")

conn.close()