# config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    SECRET_KEY = "твоја_многу_тајна_шифра_2025!@#"
    SQLALCHEMY_DATABASE_URI = r'sqlite:///C:\Users\Server\Desktop\Proekt Fersedo\instance\database.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Додадени патеки (ако ги користиш)
    STATIC_FOLDER = str(BASE_DIR / "static")
    TEMPLATE_FOLDER = str(BASE_DIR / "templates")
    PARTS_EXCEL = str(BASE_DIR / "parts_database.xlsx")
    POZICII_FOLDER = str(BASE_DIR / "static" / "pozicii")
    FONT_DIR = str(BASE_DIR / "static" / "fonts")