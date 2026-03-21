# utils/helpers.py
import os
import io
from datetime import datetime, timedelta
from collections import defaultdict
from flask import current_app
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, Image, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

# Глобални патеки (земени од current_app.config)
def get_static_folder():
    return current_app.config['STATIC_FOLDER']

def get_pozicii_folder():
    return current_app.config['POZICII_FOLDER']

STATIC_FOLDER = get_static_folder
POZICII_FOLDER = get_pozicii_folder

def add_page_number(canvas, doc):
    canvas.setFont("DejaVuSans", 9)
    canvas.setFillColor(colors.gray)
    canvas.drawRightString(
        190 * mm, 10 * mm,
        f"Страна {canvas.getPageNumber()} • {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    )

def get_compressed_image_buffer(slika_path, max_size=(450, 450), quality=68):
    try:
        img = PILImage.open(slika_path)
        img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"[IMAGE] Compression error for {slika_path}: {e}")
        return None

# ← Ова е новото што го додаваме
def _format_cet(dt_str):
    """
    Форматира датум/време од UTC во CET (+1 час).
    Ако не успее – враќа оригиналниот стринг.
    """
    try:
        dt_utc = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return (dt_utc + timedelta(hours=1)).strftime("%d-%m-%Y %H:%M")
    except Exception:
        return dt_str