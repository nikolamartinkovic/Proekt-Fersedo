# Направи нова датотека, на пр. fix_db.py
import sqlite3

conn = sqlite3.connect(r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db")
conn.execute("ALTER TABLE performance ADD COLUMN username TEXT")
conn.execute("ALTER TABLE performance ADD COLUMN efektivnost REAL")
conn.commit()
conn.close()

print("Колоната 'username' е додадена!")