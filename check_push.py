import sqlite3

db_path = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"  # или промени на твојата патека

conn = sqlite3.connect(db_path)
conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
cur = conn.cursor()

print("=== Проверка на push_subscriptions ===")
cur.execute("SELECT * FROM push_subscriptions")
rows = cur.fetchall()

if rows:
    for row in rows:
        print(f"Корисник: {row['user']}")
        print(f"Subscription: {row['subscription'][:100]}...")  # првите 100 знаци
        print("-" * 60)
else:
    print("Нема зачувани subscription-и во базата.")

conn.close()