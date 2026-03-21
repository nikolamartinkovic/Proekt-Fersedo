# migrate_add_user_group.py
import sqlite3
import os

PROJECT_ROOT = r"C:\Users\Server\Desktop\Proekt Fersedo"
DB_PATH = os.path.join(PROJECT_ROOT, "database.db")

def add_user_group_column():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Провери дали колоната веќе постои
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'user_group' in columns:
            print("Колоната 'user_group' веќе постои во табелата 'users'. Нема промена.")
            return

        # Додај ја колоната
        cursor.execute("ALTER TABLE users ADD COLUMN user_group TEXT DEFAULT ''")
        conn.commit()
        print("Колоната 'user_group' е успешно додадена во табелата 'users' со default вредност ''!")

    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("Колоната 'user_group' веќе постои – нема промена.")
        else:
            print(f"Грешка при додавање на колоната: {e}")
    except Exception as e:
        print(f"Општа грешка: {e}")
    finally:
        if conn:
            conn.close()
            print("Конекцијата до базата е затворена.")

if __name__ == '__main__':
    add_user_group_column()