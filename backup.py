import shutil
import os
from datetime import datetime

# ── Патеки ──
DB_PATH    = r"C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db"  # ← смени ако се вика поинаку
BACKUP_DIR = r"D:\Backup Fersedo app"

# ── Создај backup папка ако не постои ──
os.makedirs(BACKUP_DIR, exist_ok=True)

# ── Генерирај ime со датум и време ──
timestamp   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup_name = f"fersedo_backup_{timestamp}.db"
backup_path = os.path.join(BACKUP_DIR, backup_name)

# ── Копирај ──
shutil.copy2(DB_PATH, backup_path)
print(f"✅ Backup зачуван: {backup_path}")

# ── Задржи само последните 30 backup-и ──
backups = sorted([
    f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")
])
if len(backups) > 30:
    for old in backups[:-30]:
        os.remove(os.path.join(BACKUP_DIR, old))
        print(f"🗑️  Избришан стар backup: {old}")