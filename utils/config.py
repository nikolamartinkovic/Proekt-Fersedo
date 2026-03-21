import os

# Динамичка патека — работи за сите корисници
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATIC_FOLDER   = os.path.join(PROJECT_ROOT, "static")
TEMPLATE_FOLDER = os.path.join(PROJECT_ROOT, "templates")
PARTS_EXCEL     = os.path.join(PROJECT_ROOT, "parts_database.xlsx")
POZICII_FOLDER  = os.path.join(STATIC_FOLDER, "pozicii")
FONT_DIR        = os.path.join(STATIC_FOLDER, "fonts")
DATABASE_PATH   = os.path.join(PROJECT_ROOT, "instance", "database.db")