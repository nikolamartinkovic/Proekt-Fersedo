import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import current_app

backup_lock = threading.Lock()


def _backup_dir() -> Path:
    backup_dir = current_app.config.get(
        "BACKUP_DIR",
        str(Path(current_app.root_path) / "instance" / "backups"),
    )
    path = Path(backup_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _database_path() -> Path:
    return Path(current_app.config["DATABASE_PATH"]).resolve()


def _sanitize_filename(name: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", "."))
    return safe or ""


def list_backups(limit: int = 100) -> list[dict]:
    items: list[dict] = []
    for path in sorted(_backup_dir().glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified_ts": int(stat.st_mtime),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m-%Y %H:%M:%S"),
            }
        )
        if len(items) >= limit:
            break
    return items


def _prune_old_backups(keep_count: int) -> int:
    files = sorted(_backup_dir().glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    if keep_count < 1:
        keep_count = 1
    removed = 0
    for old_path in files[keep_count:]:
        try:
            old_path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def create_backup(reason: str = "manual", keep_count: int | None = None) -> dict:
    reason_safe = _sanitize_filename(reason.replace(" ", "_").lower())
    db_path = _database_path()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = _backup_dir() / f"fersedo_{reason_safe}_{timestamp}.db"

    with backup_lock:
        src_conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        dst_conn = sqlite3.connect(str(target), timeout=30, check_same_thread=False)
        try:
            src_conn.execute("PRAGMA busy_timeout = 5000")
            dst_conn.execute("PRAGMA busy_timeout = 5000")
            src_conn.backup(dst_conn, pages=0)
            dst_conn.commit()
        finally:
            dst_conn.close()
            src_conn.close()

    keep_target = keep_count
    if keep_target is None:
        keep_target = int(current_app.config.get("AUTO_BACKUP_KEEP", 30))
    removed = _prune_old_backups(keep_target)
    size = target.stat().st_size if target.exists() else 0
    return {"name": target.name, "path": str(target), "size": size, "removed": removed}


def restore_backup(backup_name: str, retries: int = 5) -> dict:
    safe_name = _sanitize_filename(backup_name)
    if not safe_name:
        raise ValueError("Invalid backup name.")

    src_path = (_backup_dir() / safe_name).resolve()
    backup_root = _backup_dir().resolve()
    if backup_root not in src_path.parents or not src_path.exists():
        raise FileNotFoundError("Backup file not found.")

    db_path = _database_path()

    # Always create a safety backup before restore.
    safety = create_backup(reason="pre_restore")

    with backup_lock:
        last_exc = None
        for attempt in range(retries):
            src_conn = None
            dst_conn = None
            try:
                src_conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=30, check_same_thread=False)
                dst_conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
                src_conn.execute("PRAGMA busy_timeout = 5000")
                dst_conn.execute("PRAGMA busy_timeout = 5000")
                src_conn.backup(dst_conn, pages=0)
                dst_conn.commit()
                return {"restored_from": safe_name, "safety_backup": safety["name"]}
            except sqlite3.OperationalError as exc:
                last_exc = exc
                if "locked" not in str(exc).lower() or attempt == retries - 1:
                    break
                time.sleep(0.5 * (attempt + 1))
            finally:
                if dst_conn:
                    dst_conn.close()
                if src_conn:
                    src_conn.close()

    raise sqlite3.OperationalError(
        f"Restore failed due to database lock. Last error: {last_exc}"
    )


def backup_path(name: str) -> Path:
    safe_name = _sanitize_filename(name)
    path = (_backup_dir() / safe_name).resolve()
    if _backup_dir().resolve() not in path.parents or not path.exists():
        raise FileNotFoundError("Backup file not found.")
    return path
