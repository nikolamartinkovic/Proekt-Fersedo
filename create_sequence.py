import sqlite3
import os

# Патека до твојата база - промени ако треба
DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "database.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 1. Креирај ја табелата за бројач
cursor.execute("""
    CREATE TABLE IF NOT EXISTS fer_sequence (
        id       INTEGER PRIMARY KEY CHECK (id = 1),
        last_num INTEGER NOT NULL DEFAULT 0
    )
""")

# 2. Вметни почетен ред (само ако не постои)
cursor.execute("INSERT OR IGNORE INTO fer_sequence (id, last_num) VALUES (1, 0)")

# 3. Земи го максималниот број само од табелите кои постојат
max_num = 0

# Провери nabavki_requests
try:
    row = cursor.execute("""
        SELECT MAX(CAST(SUBSTR(nalog_broj, 4) AS INTEGER)) as num
        FROM nabavki_requests WHERE nalog_broj LIKE 'Fer%'
    """).fetchone()
    if row and row[0]:
        max_num = max(max_num, row[0])
    print(f"nabavki_requests → max: {row[0] if row else 'нема'}")
except Exception as e:
    print(f"nabavki_requests не постои: {e}")

# Провери nabavki_archive (може да не постои уште)
try:
    row = cursor.execute("""
        SELECT MAX(CAST(SUBSTR(nalog_broj, 4) AS INTEGER)) as num
        FROM nabavki_archive WHERE nalog_broj LIKE 'Fer%'
    """).fetchone()
    if row and row[0]:
        max_num = max(max_num, row[0])
    print(f"nabavki_archive → max: {row[0] if row else 'нема'}")
except Exception as e:
    print(f"nabavki_archive не постои (нормално): {e}")

# 4. Постави го бројачот
cursor.execute("UPDATE fer_sequence SET last_num = ? WHERE id = 1", (max_num,))
conn.commit()

# Прикажи го резултатот
row = cursor.execute("SELECT last_num FROM fer_sequence WHERE id = 1").fetchone()
print(f"\n✅ Табелата fer_sequence е креирана!")
print(f"✅ Тековен бројач: {row[0]} (следниот налог ќе биде Fer{row[0]+1:03d})")

conn.close()