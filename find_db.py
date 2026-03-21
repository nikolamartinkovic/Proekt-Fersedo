import sqlite3
import os
import glob

# Пребарај ги сите .db фајлови во проектот
project_dir = os.path.dirname(__file__)
db_files = glob.glob(os.path.join(project_dir, "**", "*.db"), recursive=True)
db_files += glob.glob(os.path.join(project_dir, "**", "*.sqlite"), recursive=True)
db_files += glob.glob(os.path.join(project_dir, "**", "*.sqlite3"), recursive=True)

print("Пронајдени бази:")
for i, f in enumerate(db_files):
    print(f"  [{i}] {f}")

if not db_files:
    print("Нема пронајдено .db/.sqlite фајлови!")
    exit()

# Провери која база ги содржи набавки табелите
for f in db_files:
    try:
        conn = sqlite3.connect(f)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        print(f"\n  → {os.path.basename(f)}: {tables}")
    except:
        pass