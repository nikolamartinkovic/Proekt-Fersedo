# config.py
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "database.db"))
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-env")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 400 * 1024 * 1024
    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", os.getenv("APP_URL_SCHEME", "http"))

    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "")

    EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

    AUTO_ASSIGN_INTERVAL_SECONDS = int(os.getenv("AUTO_ASSIGN_INTERVAL_SECONDS", "14400"))
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT = int(os.getenv("APP_PORT", "8080"))
    APP_URL_SCHEME = os.getenv("APP_URL_SCHEME", "http")
    WAITRESS_THREADS = int(os.getenv("WAITRESS_THREADS", "8"))
    HTTPS_CERT_PATH = os.getenv("HTTPS_CERT_PATH", str(BASE_DIR / "192.168.0.20.pem"))
    HTTPS_KEY_PATH = os.getenv("HTTPS_KEY_PATH", str(BASE_DIR / "192.168.0.20-key.pem"))
    APP_LOG_DIR = os.getenv("APP_LOG_DIR", str(BASE_DIR / "instance" / "logs"))
    APP_LOG_LEVEL = os.getenv("APP_LOG_LEVEL", "INFO")

    # Додадени патеки (ако ги користиш)
    STATIC_FOLDER = str(BASE_DIR / "static")
    TEMPLATE_FOLDER = str(BASE_DIR / "templates")
    PARTS_EXCEL = str(BASE_DIR / "parts_database.xlsx")
    POZICII_FOLDER = str(BASE_DIR / "static" / "pozicii")
    FONT_DIR = str(BASE_DIR / "static" / "fonts")
