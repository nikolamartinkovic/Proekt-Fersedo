import os

from PIL import Image as PILImage

from utils.config import POZICII_FOLDER

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMG_MAX_SIZE = (1200, 1200)
IMG_QUALITY = 72
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def is_allowed_image_extension(filename):
    return os.path.splitext((filename or "").strip())[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def validate_uploaded_image(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise ValueError("Нема избрана слика.")
    if not is_allowed_image_extension(file_storage.filename):
        raise ValueError("Дозволени се само JPG, PNG и WEBP слики.")

    content_length = getattr(file_storage, "content_length", None)
    if content_length and content_length > MAX_IMAGE_BYTES:
        raise ValueError("Сликата е преголема. Максимум е 10MB.")

    stream = file_storage.stream
    current_position = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size > MAX_IMAGE_BYTES:
        raise ValueError("Сликата е преголема. Максимум е 10MB.")

    try:
        with PILImage.open(stream) as img:
            img.verify()
    except Exception as exc:
        raise ValueError("Датотеката не е валидна слика.") from exc
    finally:
        stream.seek(current_position)


def _sanitize_camera_filename(camera_filename):
    safe_name = os.path.basename((camera_filename or "").strip())
    if not safe_name or safe_name != (camera_filename or "").strip():
        return None
    if not is_allowed_image_extension(safe_name):
        return None
    return safe_name


def save_compressed_image(file_storage, save_dir, filename_base):
    try:
        validate_uploaded_image(file_storage)
        os.makedirs(save_dir, exist_ok=True)
        final_name = f"{filename_base}.jpg"
        save_path = os.path.join(save_dir, final_name)

        file_storage.stream.seek(0)
        img = PILImage.open(file_storage)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        img.thumbnail(IMG_MAX_SIZE, PILImage.Resampling.LANCZOS)
        img.save(save_path, format="JPEG", quality=IMG_QUALITY, optimize=True)
        print(f"[SLIKA] Зачувана: {save_path}")
        return final_name
    except Exception as e:
        print(f"[SLIKA] Грешка при зачувување: {e}")
        return None


def save_camera_image(camera_filename, save_dir, filename_base):
    safe_name = _sanitize_camera_filename(camera_filename)
    if not safe_name:
        return None

    src = os.path.join(POZICII_FOLDER, safe_name)
    if not os.path.exists(src):
        return None

    os.makedirs(save_dir, exist_ok=True)
    dst_name = f"{filename_base}_cam.jpg"
    dst = os.path.join(save_dir, dst_name)

    try:
        img = PILImage.open(src)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        img.thumbnail(IMG_MAX_SIZE, PILImage.Resampling.LANCZOS)
        img.save(dst, format="JPEG", quality=IMG_QUALITY, optimize=True)
        return dst_name
    except Exception as e:
        print(f"[SLIKA] Грешка при камера слика: {e}")
        return None


def ensure_comment_slika_column(cursor):
    try:
        cursor.execute("ALTER TABLE nabavki_comments ADD COLUMN slika TEXT DEFAULT NULL")
    except Exception:
        pass


def ensure_archive_comments_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nabavki_archive_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_req_id INTEGER NOT NULL,
            user TEXT,
            comment TEXT,
            slika TEXT,
            timestamp TEXT
        )
        """
    )
