import os
import sqlite3
import time
from datetime import datetime

from flask import (
    Blueprint, flash, redirect, render_template,
    request, session, url_for
)
from PIL import Image as PILImage
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from werkzeug.utils import secure_filename

from utils.db import get_db
from utils.config import STATIC_FOLDER, FONT_DIR
from utils.decorators import admin_required, login_required, module_required

kvalitet_bp = Blueprint("kvalitet", __name__, url_prefix="/kvalitet")


# ─────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────
def generiraj_kvalitet_pdf(kontrola, cekori):
    folder = os.path.join(STATIC_FOLDER, "kvalitet_pdf")
    os.makedirs(folder, exist_ok=True)
    filename = f"kontrola_{kontrola['id']}_{int(time.time())}.pdf"
    filepath = os.path.join(folder, filename)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
    except Exception:
        pass

    logo_path = os.path.join(STATIC_FOLDER, "logo2.png")
    if os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, width - 220, height - 170, width=160, height=80, preserveAspectRatio=True)
        except Exception as e:
            print(f"[PDF LOGO ERROR] {e}")

    c.setFillColorRGB(0.05, 0.35, 0.65)
    c.rect(0, height - 100, width, 100, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("DejaVuSans-Bold", 24)
    c.drawCentredString(width / 2, height - 65, "КОНТРОЛА НА КВАЛИТЕТ")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("DejaVuSans-Bold", 14)
    c.drawString(50, height - 130, "Информации за контролата:")
    c.setFont("DejaVuSans", 11)
    y = height - 155
    c.drawString(50, y, f"Камин: {kontrola['kamin']}")
    y -= 18
    c.drawString(50, y, f"Внатрешен број: {kontrola.get('vnatresen_broj') or '-'}")
    y -= 18
    c.drawString(50, y, f"Сериски број: {kontrola.get('seriski_broj') or '-'}")
    y -= 18
    c.drawString(50, y, f"Датум и време: {kontrola['datum']}")
    y -= 18
    c.drawString(50, y, f"ID контрола: {kontrola['id']}")
    y -= 35
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(50, y, width - 50, y)
    y -= 30
    c.setFont("DejaVuSans-Bold", 14)
    c.setFillColorRGB(0.05, 0.35, 0.65)
    c.drawString(50, y, "РЕЗУЛТАТИ ОД ПРОВЕРКА:")
    y -= 25
    c.setFillColorRGB(0, 0, 0)
    c.setFont("DejaVuSans", 11)

    for item in cekori:
        if item.get("is_cekor"):
            c.setFont("DejaVuSans-Bold", 12)
            c.setFillColorRGB(0.1, 0.4, 0.7)
            c.drawString(50, y, item["naslov"])
            c.setFillColorRGB(0, 0, 0)
            y -= 22
            c.setStrokeColorRGB(0.9, 0.9, 0.9)
            c.line(50, y, width - 50, y)
            y -= 18
            c.setFont("DejaVuSans", 11)
        else:
            status_text  = "✔ ПОМИНАЛ" if item["status"] == 1 else "✖ НЕ ПОМИНАЛ"
            status_color = (0, 0.6, 0) if item["status"] == 1 else (0.8, 0, 0)
            c.setFillColorRGB(*status_color)
            c.drawString(65, y, f"• {item['naslov']} {status_text}")
            c.setFillColorRGB(0, 0, 0)
            y -= 18
            if item.get("zabeleska"):
                c.setFont("DejaVuSans", 10)
                zab_color = (0.8, 0, 0) if item["status"] == 0 else (0.3, 0.3, 0.3)
                c.setFillColorRGB(*zab_color)
                c.drawString(80, y, f"Забелешка: {item['zabeleska']}")
                c.setFillColorRGB(0, 0, 0)
                y -= 22
                c.setFont("DejaVuSans", 11)
            if item.get("slika_path") and os.path.exists(item["slika_path"]):
                try:
                    img_width  = 100 * mm
                    img_height = 75 * mm
                    c.drawImage(item["slika_path"], 80, y - img_height,
                                width=img_width, height=img_height, preserveAspectRatio=True)
                    y -= img_height + 10
                except Exception as e:
                    print(f"[PDF SLIKA ERROR] {e}")
                    y -= 20
            y -= 10

        if y < 80:
            c.showPage()
            y = height - 60
            c.setFillColorRGB(0.05, 0.35, 0.65)
            c.rect(0, height - 100, width, 100, fill=1)
            c.setFillColorRGB(1, 1, 1)
            c.setFont("DejaVuSans-Bold", 20)
            c.drawCentredString(width / 2, height - 65, "КОНТРОЛА НА КВАЛИТЕТ (продолжение)")
            c.setFont("DejaVuSans", 11)
            c.setFillColorRGB(0, 0, 0)
            y = height - 145

    c.setFont("DejaVuSans", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(50, 40, f"Генерирано на {datetime.now().strftime('%d-%m-%Y %H:%M')} од {session.get('user', 'Корисник')}")
    c.drawString(width - 200, 40, "Fersedo Production System")
    c.save()
    print(f"[PDF CREATED] {filepath}")
    return filename


def generiraj_kvalitet_pdf_v2(kontrola, cekori):
    folder = os.path.join(STATIC_FOLDER, "kvalitet_pdf")
    os.makedirs(folder, exist_ok=True)
    filename = f"kontrola_{kontrola['id']}_{int(time.time())}.pdf"
    filepath = os.path.join(folder, filename)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    regular_font = "Helvetica"
    bold_font = "Helvetica-Bold"

    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
        regular_font = "DejaVuSans"
        bold_font = "DejaVuSans-Bold"
    except Exception:
        pass

    logo_path = os.path.join(STATIC_FOLDER, "logo2.png")
    left_margin = 50
    right_margin = 50
    bottom_margin = 60
    content_width = width - left_margin - right_margin
    y = height - 120

    def wrap_text(text, font_name, font_size, max_width):
        text = str(text or "").replace("\r\n", "\n")
        lines = []

        def split_long_token(token):
            parts = []
            current = ""
            for char in token:
                candidate = current + char
                if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                    parts.append(current)
                    current = char
                else:
                    current = candidate
            if current:
                parts.append(current)
            return parts or [token]

        for paragraph in text.split("\n"):
            if not paragraph.strip():
                lines.append("")
                continue

            current_line = ""
            for raw_word in paragraph.split():
                for piece in split_long_token(raw_word):
                    candidate = piece if not current_line else f"{current_line} {piece}"
                    if current_line and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                        lines.append(current_line)
                        current_line = piece
                    else:
                        current_line = candidate
            if current_line:
                lines.append(current_line)

        return lines or [""]

    def start_page(continuation=False):
        nonlocal y
        c.setFillColorRGB(0.05, 0.35, 0.65)
        c.rect(0, height - 100, width, 100, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(bold_font, 24 if not continuation else 20)
        title = "КОНТРОЛА НА КВАЛИТЕТ" if not continuation else "КОНТРОЛА НА КВАЛИТЕТ (продолжение)"
        c.drawCentredString(width / 2, height - 65, title)
        c.setFillColorRGB(0, 0, 0)
        y = height - 135

    def ensure_space(required_height):
        nonlocal y
        if y - required_height < bottom_margin:
            c.showPage()
            start_page(continuation=True)

    start_page(continuation=False)

    if os.path.exists(logo_path):
        try:
            c.drawImage(
                logo_path,
                width - 210,
                height - 215,
                width=145,
                height=70,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception as exc:
            print(f"[PDF LOGO ERROR] {exc}")

    c.setFont(bold_font, 14)
    c.drawString(left_margin, y, "Информации за контролата:")
    y -= 24
    c.setFont(regular_font, 11)

    info_lines = [
        f"Камин: {kontrola['kamin']}",
        f"Внатрешен број: {kontrola.get('vnatresen_broj') or '-'}",
        f"Сериски број: {kontrola.get('seriski_broj') or '-'}",
        f"Датум и време: {kontrola['datum']}",
        f"ID контрола: {kontrola['id']}",
    ]

    for info_line in info_lines:
        for wrapped_line in wrap_text(info_line, regular_font, 11, 310):
            c.drawString(left_margin, y, wrapped_line)
            y -= 16

    y = min(y, height - 260)
    y -= 10
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(left_margin, y, width - right_margin, y)
    y -= 28

    c.setFont(bold_font, 15)
    c.setFillColorRGB(0.05, 0.35, 0.65)
    c.drawString(left_margin, y, "РЕЗУЛТАТИ ОД ПРОВЕРКА:")
    y -= 24
    c.setFillColorRGB(0, 0, 0)

    for item in cekori:
        if item.get("is_cekor"):
            section_lines = wrap_text(item["naslov"], bold_font, 12, content_width)
            ensure_space((len(section_lines) * 18) + 24)
            c.setFont(bold_font, 12)
            c.setFillColorRGB(0.1, 0.4, 0.7)
            for line in section_lines:
                c.drawString(left_margin, y, line)
                y -= 18
            c.setFillColorRGB(0, 0, 0)
            c.setStrokeColorRGB(0.9, 0.9, 0.9)
            c.line(left_margin, y, width - right_margin, y)
            y -= 18
            continue

        status_text = "ПОМИНАЛ" if item["status"] == 1 else "НЕ ПОМИНАЛ"
        status_color = (0, 0.55, 0.16) if item["status"] == 1 else (0.82, 0.05, 0.05)
        main_lines = wrap_text(f"• {item['naslov']} — {status_text}", regular_font, 11, content_width - 15)
        note_lines = []
        if item.get("zabeleska"):
            note_lines = wrap_text(f"Забелешка: {item['zabeleska']}", regular_font, 10, content_width - 30)

        image_height = (75 * mm) + 10 if item.get("slika_path") and os.path.exists(item["slika_path"]) else 0
        required_height = (len(main_lines) * 16) + (len(note_lines) * 14) + image_height + 12
        ensure_space(required_height)

        c.setFont(regular_font, 11)
        c.setFillColorRGB(*status_color)
        for line in main_lines:
            c.drawString(left_margin + 15, y, line)
            y -= 16

        if note_lines:
            c.setFont(regular_font, 10)
            c.setFillColorRGB(0.5, 0.08, 0.08)
            for line in note_lines:
                c.drawString(left_margin + 30, y, line)
                y -= 14

        c.setFillColorRGB(0, 0, 0)

        if item.get("slika_path") and os.path.exists(item["slika_path"]):
            try:
                max_img_width = min(content_width - 40, 100 * mm)
                max_img_height = 75 * mm
                ensure_space(max_img_height + 10)
                c.drawImage(
                    item["slika_path"],
                    left_margin + 30,
                    y - max_img_height,
                    width=max_img_width,
                    height=max_img_height,
                    preserveAspectRatio=True,
                    mask="auto",
                    anchor="sw",
                )
                y -= max_img_height + 10
            except Exception as exc:
                print(f"[PDF SLIKA ERROR] {exc}")
                y -= 10

        y -= 8

    c.setFont(regular_font, 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(50, 40, f"Генерирано на {datetime.now().strftime('%d-%m-%Y %H:%M')} од {session.get('user', 'Корисник')}")
    c.drawString(width - 200, 40, "Fersedo Production System")
    c.save()
    print(f"[PDF CREATED] {filepath}")
    return filename

def _format_vnatresen_broj(kontrola_id):
    return f"QC-{int(kontrola_id):06d}"


def _next_vnatresen_broj_preview(cursor):
    row = cursor.execute(
        "SELECT seq + 1 AS next_id FROM sqlite_sequence WHERE name = 'kvalitet_kontrola'"
    ).fetchone()
    next_id = 1
    if row and row.get("next_id"):
        next_id = int(row["next_id"])
    return _format_vnatresen_broj(next_id)


def _insert_kvalitet_snapshot(cursor, *, kontrola_id, odgovor_id, podcekor_id, cekor_naslov, podcekor_opis, status, zabeleska, slika):
    cursor.execute(
        """
        INSERT INTO kvalitet_odgovori_snapshot (
            kontrola_id,
            odgovor_id,
            podcekor_id,
            cekor_naslov,
            podcekor_opis,
            status,
            zabeleska,
            slika
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kontrola_id,
            odgovor_id,
            podcekor_id,
            cekor_naslov or "",
            podcekor_opis or "",
            status,
            zabeleska or "",
            slika or "",
        ),
    )


def _format_mk_date(date_value):
    text = str(date_value or "").strip()
    if not text:
        return "-"

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%d-%m-%Y %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            if "H" in fmt or "%H" in fmt:
                return parsed.strftime("%d-%m-%Y %H:%M")
            return parsed.strftime("%d-%m-%Y")
        except ValueError:
            continue
    return text


def _normalize_vlezna_dokument_tip(value):
    raw = str(value or "").strip().lower()
    if raw == "faktura":
        return "faktura"
    return "ispratnica"


def _label_vlezna_dokument_tip(value):
    return "Фактура" if str(value or "").strip().lower() == "faktura" else "Испратница"


def _normalize_vlezna_status(value):
    raw = str(value or "").strip().upper()
    return "NE_DOBAR" if raw == "NE_DOBAR" else "DOBAR"


def _label_vlezna_status(value):
    return "Не е добар" if _normalize_vlezna_status(value) == "NE_DOBAR" else "Добар"


def _vlezna_image_folder():
    folder = os.path.join(STATIC_FOLDER, "kvalitet_vlezna_sliki")
    os.makedirs(folder, exist_ok=True)
    return folder


def _vlezna_image_path(filename):
    if not filename:
        return ""
    path = os.path.join(_vlezna_image_folder(), filename)
    return path if os.path.exists(path) else ""


def _save_vlezna_image(file_storage, kontrola_id, redosled):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return ""

    safe_name = secure_filename(file_storage.filename or "")
    if not safe_name:
        return ""

    save_name = f"vlezna_{kontrola_id}_{redosled}_{int(time.time() * 1000)}.jpg"
    save_path = os.path.join(_vlezna_image_folder(), save_name)

    try:
        image = PILImage.open(file_storage)
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((1600, 1600), PILImage.Resampling.LANCZOS)
        image.save(save_path, format="JPEG", quality=84, optimize=True)
        return save_name
    except Exception:
        try:
            ext = os.path.splitext(safe_name)[1].lower() or ".jpg"
            fallback_name = f"vlezna_{kontrola_id}_{redosled}_{int(time.time() * 1000)}{ext}"
            fallback_path = os.path.join(_vlezna_image_folder(), fallback_name)
            file_storage.stream.seek(0)
            file_storage.save(fallback_path)
            return fallback_name
        except Exception:
            return ""


def generiraj_vlezna_kontrola_pdf(kontrola, stavki):
    folder = os.path.join(STATIC_FOLDER, "kvalitet_vlezna_pdf")
    os.makedirs(folder, exist_ok=True)
    filename = f"vlezna_{kontrola['id']}_{int(time.time())}.pdf"
    filepath = os.path.join(folder, filename)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    regular_font = "Helvetica"
    bold_font = "Helvetica-Bold"

    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(FONT_DIR, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")))
        regular_font = "DejaVuSans"
        bold_font = "DejaVuSans-Bold"
    except Exception:
        pass

    logo_path = os.path.join(STATIC_FOLDER, "logo2.png")
    left_margin = 40
    right_margin = 40
    bottom_margin = 44
    content_width = width - left_margin - right_margin
    logo_width = 168
    logo_height = 84
    info_wrap_width = content_width - logo_width - 38
    y = height - 120

    def wrap_text(text, font_name, font_size, max_width):
        text = str(text or "").replace("\r\n", "\n")
        lines = []

        def split_long_token(token):
            parts = []
            current = ""
            for char in token:
                candidate = current + char
                if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                    parts.append(current)
                    current = char
                else:
                    current = candidate
            if current:
                parts.append(current)
            return parts or [token]

        for paragraph in text.split("\n"):
            if not paragraph.strip():
                lines.append("")
                continue
            current_line = ""
            for raw_word in paragraph.split():
                for piece in split_long_token(raw_word):
                    candidate = piece if not current_line else f"{current_line} {piece}"
                    if current_line and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                        lines.append(current_line)
                        current_line = piece
                    else:
                        current_line = candidate
            if current_line:
                lines.append(current_line)

        return lines or [""]

    def start_page(continuation=False):
        nonlocal y
        c.setFillColorRGB(0.05, 0.35, 0.65)
        c.rect(0, height - 95, width, 95, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(bold_font, 23 if not continuation else 18)
        title = "ВЛЕЗНА КОНТРОЛА" if not continuation else "ВЛЕЗНА КОНТРОЛА (продолжение)"
        c.drawCentredString(width / 2, height - 58, title)
        c.setFillColorRGB(0, 0, 0)
        y = height - 125
        if os.path.exists(logo_path):
            try:
                c.drawImage(
                    logo_path,
                    width - right_margin - logo_width,
                    height - 180,
                    width=logo_width,
                    height=logo_height,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception as exc:
                print(f"[VLEZNA PDF LOGO ERROR] {exc}")

    def ensure_space(required_height):
        nonlocal y
        if y - required_height < bottom_margin:
            c.showPage()
            start_page(continuation=True)
            draw_table_header()

    def draw_centered_lines(lines, x_left, x_right, y_top, row_height, font_name, font_size, fill_rgb=(0, 0, 0)):
        safe_lines = lines or ["-"]
        line_gap = 13
        total_height = max(font_size, ((len(safe_lines) - 1) * line_gap) + font_size)
        start_y = y_top - ((row_height - total_height) / 2) - (font_size - 2)
        center_x = x_left + ((x_right - x_left) / 2)
        c.setFont(font_name, font_size)
        c.setFillColorRGB(*fill_rgb)
        current_y = start_y
        for line in safe_lines:
            c.drawCentredString(center_x, current_y, line)
            current_y -= line_gap
        c.setFillColorRGB(0, 0, 0)

    def draw_table_header():
        nonlocal y
        header_height = 24
        x_positions = [left_margin, left_margin + 36, left_margin + 208, left_margin + 308, left_margin + 430, width - right_margin]
        headers = ["Р.Б.", "Материјал", "Статус", "Забелешка"]

        x_positions = [left_margin, left_margin + 36, left_margin + 208, left_margin + 308, left_margin + 430, width - right_margin]
        headers = ["Р.бр.", "Материјал", "Статус", "Забелешка", "Слика"]
        c.setFillColorRGB(0.09, 0.15, 0.32)
        c.rect(left_margin, y - header_height, content_width, header_height, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(bold_font, 10)
        for idx, label in enumerate(headers):
            c.drawString(x_positions[idx] + 6, y - 16, label)
        c.setFillColorRGB(0, 0, 0)
        y -= header_height

    start_page(continuation=False)

    c.setFont(bold_font, 14)
    c.drawString(left_margin, y, "Податоци за документот:")
    y -= 24
    c.setFont(regular_font, 11)

    info_lines = [
        f"Датум на контрола: {_format_mk_date(kontrola.get('datum_kontrola'))}",
        f"Број на документ: {kontrola.get('dokument_broj') or '-'}",
        f"Тип на документ: {_label_vlezna_dokument_tip(kontrola.get('dokument_tip'))}",
        f"Добавувач: {kontrola.get('dobavuvac') or '-'}",
        f"Вкупен статус: {_label_vlezna_status(kontrola.get('status'))}",
        f"Внесено од: {kontrola.get('username') or '-'}",
        f"ID на влезна контрола: {kontrola.get('id') or '-'}",
    ]

    for info_line in info_lines:
        for wrapped in wrap_text(info_line, regular_font, 11, info_wrap_width):
            c.drawString(left_margin, y, wrapped)
            y -= 16

    y -= 6
    c.setStrokeColorRGB(0.84, 0.86, 0.9)
    c.line(left_margin, y, width - right_margin, y)
    y -= 26

    c.setFont(bold_font, 14)
    c.setFillColorRGB(0.05, 0.35, 0.65)
    c.drawString(left_margin, y, "Материјали и резултати:")
    c.setFillColorRGB(0, 0, 0)
    y -= 18

    draw_table_header()

    x1 = left_margin
    x2 = left_margin + 36
    x3 = left_margin + 208
    x4 = left_margin + 308
    x5 = left_margin + 430
    x6 = width - right_margin

    for index, stavka in enumerate(stavki, start=1):
        material_lines = wrap_text(stavka.get("materijal") or "-", regular_font, 10, (x3 - x2) - 12)
        status_label = _label_vlezna_status(stavka.get("status"))
        status_lines = wrap_text(status_label, bold_font, 10, (x4 - x3) - 12)
        note_lines = wrap_text(stavka.get("zabeleska") or "-", regular_font, 10, (x5 - x4) - 12)
        image_path = _vlezna_image_path(stavka.get("slika"))
        has_image = bool(image_path)
        image_height = 88 if has_image else 0
        line_count = max(len(material_lines), len(status_lines), len(note_lines), 1)
        text_height = max(28, (line_count * 13) + 12)
        row_height = max(text_height, image_height + 18 if has_image else 36)

        ensure_space(row_height + 2)

        c.setStrokeColorRGB(0.85, 0.88, 0.92)
        c.rect(left_margin, y - row_height, content_width, row_height, fill=0, stroke=1)
        for separator_x in (x2, x3, x4, x5):
            c.line(separator_x, y, separator_x, y - row_height)

        c.setFont(regular_font, 10)
        c.drawString(x1 + 6, y - 17, str(index))

        draw_centered_lines(material_lines, x2, x3, y, row_height, regular_font, 10, (0, 0, 0))
        status_color = (0.0, 0.55, 0.16) if _normalize_vlezna_status(stavka.get("status")) == "DOBAR" else (0.78, 0.05, 0.05)
        draw_centered_lines(status_lines, x3, x4, y, row_height, bold_font, 10, status_color)

        c.setFont(regular_font, 10)
        current_y = y - 17
        for line in note_lines:
            c.drawString(x4 + 6, current_y, line)
            current_y -= 13

        if has_image:
            try:
                c.drawImage(
                    image_path,
                    x5 + 6,
                    y - row_height + 6,
                    width=(x6 - x5) - 12,
                    height=row_height - 12,
                    preserveAspectRatio=True,
                    mask="auto",
                    anchor="c",
                )
            except Exception:
                pass
        else:
            c.setFont(regular_font, 10)
            c.setFillColorRGB(0.45, 0.5, 0.58)
            c.drawString(x5 + 8, y - 17, "Нема")
            c.setFillColorRGB(0, 0, 0)

        y -= row_height

    c.setFont(regular_font, 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(left_margin, 30, f"Генерирано на {datetime.now().strftime('%d-%m-%Y %H:%M')} од {session.get('user', 'Корисник')}")
    c.drawRightString(width - right_margin, 30, "Fersedo Production System")
    c.save()
    return filename


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@kvalitet_bp.route("/")
@login_required
def kvalitet():
    """Главна страница — прикажува само картички за кои корисникот има дозвола."""
    return render_template("kvalitet.html")


@kvalitet_bp.route("/izvestaj-problemi", methods=["GET"])
@login_required
@module_required("kvalitet_izvestaj_problemi")
def kvalitet_izvestaj_problemi():
    active_tip = (request.args.get("tip") or "vnatresen").strip().lower()
    if active_tip not in {"vnatresen", "nadvoresen"}:
        active_tip = "vnatresen"

    tip_meta = {
        "vnatresen": {
            "title": "Внатрешен извештај",
            "subtitle": "Евиденција за проблеми откриени внатре во производството, контролата или интерната проверка.",
            "badge": "Внатрешен тек",
            "icon": "fa-industry",
        },
        "nadvoresen": {
            "title": "Надворешен извештај",
            "subtitle": "Евиденција за проблеми пријавени од клиент, терен, сервис или надворешен партнер.",
            "badge": "Надворешен тек",
            "icon": "fa-globe",
        },
    }

    return render_template(
        "kvalitet_izvestaj_problemi.html",
        active_tip=active_tip,
        tip_meta=tip_meta,
    )


@kvalitet_bp.route("/vlezna", methods=["GET"])
@login_required
@module_required("kvalitet_vlezna")
def kvalitet_vlezna():
    conn = get_db()
    cursor = conn.cursor()

    query = request.args.get("q", "").strip()
    status_filter = _normalize_vlezna_status(request.args.get("status", "").strip()) if request.args.get("status") else ""

    filters = []
    params = []

    if query:
        like_term = f"%{query}%"
        filters.append(
            """
            (
                k.dokument_broj LIKE ?
                OR k.dobavuvac LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM kvalitet_vlezna_stavki s2
                    WHERE s2.kontrola_id = k.id
                      AND (s2.materijal LIKE ? OR s2.zabeleska LIKE ?)
                )
            )
            """
        )
        params.extend([like_term, like_term, like_term, like_term])

    if status_filter:
        filters.append("k.status = ?")
        params.append(status_filter)

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    kontroli = cursor.execute(
        f"""
        SELECT
            k.id,
            k.datum_kontrola,
            k.dokument_broj,
            k.dokument_tip,
            k.dobavuvac,
            k.status,
            k.username,
            k.pdf_file,
            k.created_at,
            COUNT(s.id) AS broj_stavki,
            SUM(CASE WHEN s.status = 'NE_DOBAR' THEN 1 ELSE 0 END) AS broj_nedobri
        FROM kvalitet_vlezna_kontrola k
        LEFT JOIN kvalitet_vlezna_stavki s ON s.kontrola_id = k.id
        {where_clause}
        GROUP BY k.id, k.datum_kontrola, k.dokument_broj, k.dokument_tip, k.dobavuvac, k.status, k.username, k.pdf_file, k.created_at
        ORDER BY date(k.datum_kontrola) DESC, k.id DESC
        """,
        params,
    ).fetchall()

    summary = cursor.execute(
        """
        SELECT
            COUNT(*) AS total_records,
            SUM(CASE WHEN status = 'DOBAR' THEN 1 ELSE 0 END) AS good_records,
            SUM(CASE WHEN status = 'NE_DOBAR' THEN 1 ELSE 0 END) AS bad_records
        FROM kvalitet_vlezna_kontrola
        """
    ).fetchone()

    conn.close()
    return render_template(
        "kvalitet_vlezna.html",
        kontroli=kontroli,
        query=query,
        status_filter=status_filter,
        total_records=int(summary["total_records"] or 0),
        good_records=int(summary["good_records"] or 0),
        bad_records=int(summary["bad_records"] or 0),
        format_date=_format_mk_date,
        label_status=_label_vlezna_status,
        label_document_type=_label_vlezna_dokument_tip,
    )


@kvalitet_bp.route("/vlezna/nova", methods=["GET", "POST"])
@login_required
@module_required("kvalitet_vlezna")
def kvalitet_vlezna_nova():
    defaults = {
        "datum_kontrola": datetime.now().strftime("%Y-%m-%d"),
        "dokument_broj": "",
        "dokument_tip": "ispratnica",
        "dobavuvac": "",
    }
    stavki_view = [{"materijal": "", "status": "DOBAR", "zabeleska": "", "slika": ""}]

    if request.method == "POST":
        datum_kontrola = request.form.get("datum_kontrola", "").strip()
        dokument_broj = request.form.get("dokument_broj", "").strip()
        dokument_tip = _normalize_vlezna_dokument_tip(request.form.get("dokument_tip", ""))
        dobavuvac = request.form.get("dobavuvac", "").strip()

        materijali = request.form.getlist("materijal[]")
        statuses = request.form.getlist("status[]")
        zabeleski = request.form.getlist("zabeleska[]")
        sliki = request.files.getlist("slika[]")

        defaults.update(
            {
                "datum_kontrola": datum_kontrola,
                "dokument_broj": dokument_broj,
                "dokument_tip": dokument_tip,
                "dobavuvac": dobavuvac,
            }
        )

        stavki = []
        stavki_view = []
        for idx, materijal in enumerate(materijali):
            material_text = (materijal or "").strip()
            status_text = _normalize_vlezna_status(statuses[idx] if idx < len(statuses) else "DOBAR")
            zabeleska_text = (zabeleski[idx] if idx < len(zabeleski) else "").strip()
            slika_file = sliki[idx] if idx < len(sliki) else None
            has_image = bool(slika_file and getattr(slika_file, "filename", ""))

            if material_text or zabeleska_text or has_image:
                stavki.append(
                    {
                        "materijal": material_text,
                        "status": status_text,
                        "zabeleska": zabeleska_text,
                        "slika_file": slika_file if has_image else None,
                    }
                )
            stavki_view.append(
                {
                    "materijal": material_text,
                    "status": status_text,
                    "zabeleska": zabeleska_text,
                    "slika": getattr(slika_file, "filename", "") if has_image else "",
                }
            )

        if not datum_kontrola or not dokument_broj:
            flash("Датумот и бројот на документот се задолжителни.", "danger")
            return render_template(
                "kvalitet_vlezna_nova.html",
                defaults=defaults,
                stavki=stavki_view,
            )

        if not stavki:
            flash("Мора да внесете барем еден материјал за влезна контрола.", "danger")
            return render_template(
                "kvalitet_vlezna_nova.html",
                defaults=defaults,
                stavki=stavki_view,
            )

        if any(not stavka["materijal"] for stavka in stavki):
            flash("Секој ред мора да има име на материјал.", "danger")
            return render_template(
                "kvalitet_vlezna_nova.html",
                defaults=defaults,
                stavki=stavki_view,
            )

        conn = get_db()
        cursor = conn.cursor()
        try:
            overall_status = "NE_DOBAR" if any(stavka["status"] == "NE_DOBAR" for stavka in stavki) else "DOBAR"
            cursor.execute(
                """
                INSERT INTO kvalitet_vlezna_kontrola (
                    datum_kontrola,
                    dokument_broj,
                    dokument_tip,
                    dobavuvac,
                    status,
                    username
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datum_kontrola,
                    dokument_broj,
                    dokument_tip,
                    dobavuvac,
                    overall_status,
                    session["user"],
                ),
            )
            kontrola_id = cursor.lastrowid

            for redosled, stavka in enumerate(stavki, start=1):
                slika_filename = _save_vlezna_image(stavka.get("slika_file"), kontrola_id, redosled)
                cursor.execute(
                    """
                    INSERT INTO kvalitet_vlezna_stavki (
                        kontrola_id,
                        materijal,
                        status,
                        zabeleska,
                        slika,
                        redosled
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kontrola_id,
                        stavka["materijal"],
                        stavka["status"],
                        stavka["zabeleska"],
                        slika_filename,
                        redosled,
                    ),
                )
                stavka["slika"] = slika_filename

            conn.commit()

            kontrola = {
                "id": kontrola_id,
                "datum_kontrola": datum_kontrola,
                "dokument_broj": dokument_broj,
                "dokument_tip": dokument_tip,
                "dobavuvac": dobavuvac,
                "status": overall_status,
                "username": session["user"],
            }
            pdf_filename = generiraj_vlezna_kontrola_pdf(kontrola, stavki)
            cursor.execute(
                "UPDATE kvalitet_vlezna_kontrola SET pdf_file = ? WHERE id = ?",
                (pdf_filename, kontrola_id),
            )
            conn.commit()
            flash("Влезната контрола е успешно зачувана и PDF документот е генериран.", "success")
            return redirect(url_for("kvalitet.kvalitet_vlezna_detali", kontrola_id=kontrola_id))
        except Exception as exc:
            conn.rollback()
            import traceback; traceback.print_exc()
            flash(f"Грешка при зачувување: {exc}", "danger")
        finally:
            conn.close()

    return render_template(
        "kvalitet_vlezna_nova.html",
        defaults=defaults,
        stavki=stavki_view,
    )


@kvalitet_bp.route("/vlezna/<int:kontrola_id>", methods=["GET"])
@login_required
@module_required("kvalitet_vlezna")
def kvalitet_vlezna_detali(kontrola_id):
    conn = get_db()
    cursor = conn.cursor()

    kontrola = cursor.execute(
        """
        SELECT *
        FROM kvalitet_vlezna_kontrola
        WHERE id = ?
        """,
        (kontrola_id,),
    ).fetchone()
    if not kontrola:
        conn.close()
        flash("Влезната контрола не постои.", "warning")
        return redirect(url_for("kvalitet.kvalitet_vlezna"))

    stavki = cursor.execute(
        """
        SELECT *
        FROM kvalitet_vlezna_stavki
        WHERE kontrola_id = ?
        ORDER BY redosled, id
        """,
        (kontrola_id,),
    ).fetchall()
    conn.close()

    return render_template(
        "kvalitet_vlezna_detali.html",
        kontrola=kontrola,
        stavki=stavki,
        format_date=_format_mk_date,
        label_status=_label_vlezna_status,
        label_document_type=_label_vlezna_dokument_tip,
    )


@kvalitet_bp.route("/vlezna/<int:kontrola_id>/delete", methods=["POST"])
@login_required
@admin_required
def kvalitet_vlezna_delete(kontrola_id):
    conn = get_db()
    cursor = conn.cursor()

    kontrola = cursor.execute(
        """
        SELECT id, dokument_broj, pdf_file
        FROM kvalitet_vlezna_kontrola
        WHERE id = ?
        """,
        (kontrola_id,),
    ).fetchone()
    if not kontrola:
        conn.close()
        flash("Влезната контрола не постои.", "warning")
        return redirect(url_for("kvalitet.kvalitet_vlezna"))

    image_rows = cursor.execute(
        """
        SELECT slika
        FROM kvalitet_vlezna_stavki
        WHERE kontrola_id = ?
        """,
        (kontrola_id,),
    ).fetchall()

    pdf_file = (kontrola["pdf_file"] or "").strip()
    image_files = [(row["slika"] or "").strip() for row in image_rows if (row["slika"] or "").strip()]

    try:
        cursor.execute("DELETE FROM kvalitet_vlezna_stavki WHERE kontrola_id = ?", (kontrola_id,))
        cursor.execute("DELETE FROM kvalitet_vlezna_kontrola WHERE id = ?", (kontrola_id,))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        flash(f"Грешка при бришење: {exc}", "danger")
        return redirect(url_for("kvalitet.kvalitet_vlezna_detali", kontrola_id=kontrola_id))
    finally:
        conn.close()

    if pdf_file:
        try:
            pdf_path = os.path.join(STATIC_FOLDER, "kvalitet_vlezna_pdf", pdf_file)
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass

    for image_name in image_files:
        try:
            image_path = os.path.join(_vlezna_image_folder(), image_name)
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception:
            pass

    flash(f"Влезната контрола за документ {kontrola['dokument_broj']} е избришана.", "success")
    return redirect(url_for("kvalitet.kvalitet_vlezna"))


@kvalitet_bp.route("/greski_statistika", methods=["GET"])
@login_required
@module_required("kvalitet_greski_statistika")
def kvalitet_greski_statistika():
    conn = get_db()
    cursor = conn.cursor()

    selected_kamin = request.args.get("kamin", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    kamini = [k["ime"] for k in cursor.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()]

    shared_filters = []
    shared_params = []

    if selected_kamin:
        shared_filters.append("k.kamin = ?")
        shared_params.append(selected_kamin)
    if date_from:
        shared_filters.append("date(k.datum) >= date(?)")
        shared_params.append(date_from)
    if date_to:
        shared_filters.append("date(k.datum) <= date(?)")
        shared_params.append(date_to)

    control_where = f"WHERE {' AND '.join(shared_filters)}" if shared_filters else ""
    error_where = f"WHERE s.status = 0 AND {' AND '.join(shared_filters)}" if shared_filters else "WHERE s.status = 0"

    total_controls_row = cursor.execute(
        f"SELECT COUNT(*) AS total_controls FROM kvalitet_kontrola k {control_where}",
        shared_params,
    ).fetchone()
    total_controls = int(total_controls_row["total_controls"] or 0)

    summary = cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total_nok,
            COUNT(DISTINCT s.kontrola_id) AS failed_controls,
            COUNT(DISTINCT k.kamin) AS affected_kamini
        FROM kvalitet_odgovori_snapshot s
        JOIN kvalitet_kontrola k ON k.id = s.kontrola_id
        {error_where}
        """,
        shared_params,
    ).fetchone()

    top_errors = [
        dict(row) for row in cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(s.podcekor_opis), ''), 'Непозната грешка') AS opis,
                COUNT(*) AS nok_count,
                COUNT(DISTINCT s.kontrola_id) AS controls_count
            FROM kvalitet_odgovori_snapshot s
            JOIN kvalitet_kontrola k ON k.id = s.kontrola_id
            {error_where}
            GROUP BY COALESCE(NULLIF(TRIM(s.podcekor_opis), ''), 'Непозната грешка')
            ORDER BY nok_count DESC, opis ASC
            LIMIT 12
            """,
            shared_params,
        ).fetchall()
    ]

    top_kamini = [
        dict(row) for row in cursor.execute(
            f"""
            SELECT
                k.kamin,
                COUNT(*) AS nok_count,
                COUNT(DISTINCT s.kontrola_id) AS controls_count
            FROM kvalitet_odgovori_snapshot s
            JOIN kvalitet_kontrola k ON k.id = s.kontrola_id
            {error_where}
            GROUP BY k.kamin
            ORDER BY nok_count DESC, k.kamin ASC
            LIMIT 12
            """,
            shared_params,
        ).fetchall()
    ]

    top_cekori = [
        dict(row) for row in cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(s.cekor_naslov), ''), 'Непознат чекор') AS cekor,
                COUNT(*) AS nok_count
            FROM kvalitet_odgovori_snapshot s
            JOIN kvalitet_kontrola k ON k.id = s.kontrola_id
            {error_where}
            GROUP BY COALESCE(NULLIF(TRIM(s.cekor_naslov), ''), 'Непознат чекор')
            ORDER BY nok_count DESC, cekor ASC
            LIMIT 10
            """,
            shared_params,
        ).fetchall()
    ]

    recent_findings = [
        dict(row) for row in cursor.execute(
            f"""
            SELECT
                k.id,
                k.kamin,
                k.vnatresen_broj,
                k.seriski_broj,
                k.datum,
                COALESCE(NULLIF(TRIM(s.cekor_naslov), ''), 'Непознат чекор') AS cekor,
                COALESCE(NULLIF(TRIM(s.podcekor_opis), ''), 'Непознат опис') AS opis,
                COALESCE(s.zabeleska, '') AS zabeleska,
                COALESCE(s.slika, '') AS slika
            FROM kvalitet_odgovori_snapshot s
            JOIN kvalitet_kontrola k ON k.id = s.kontrola_id
            {error_where}
            ORDER BY k.datum DESC, s.id DESC
            LIMIT 24
            """,
            shared_params,
        ).fetchall()
    ]

    total_nok = int(summary["total_nok"] or 0)
    failed_controls = int(summary["failed_controls"] or 0)
    affected_kamini = int(summary["affected_kamini"] or 0)
    failure_rate = round((failed_controls / total_controls) * 100, 1) if total_controls else 0
    avg_nok_per_failed = round((total_nok / failed_controls), 2) if failed_controls else 0

    conn.close()
    return render_template(
        "kvalitet_greski_statistika.html",
        kamini=kamini,
        selected_kamin=selected_kamin,
        date_from=date_from,
        date_to=date_to,
        total_controls=total_controls,
        total_nok=total_nok,
        failed_controls=failed_controls,
        affected_kamini=affected_kamini,
        failure_rate=failure_rate,
        avg_nok_per_failed=avg_nok_per_failed,
        top_errors=top_errors,
        top_kamini=top_kamini,
        top_cekori=top_cekori,
        recent_findings=recent_findings,
    )


@kvalitet_bp.route("/select_kamin")
@login_required
@module_required("kvalitet_nova")
def kvalitet_select_kamin():
    conn   = get_db()
    kamini = [k["ime"] for k in conn.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()]
    conn.close()
    return render_template("kvalitet_select_kamin.html", kamini=kamini)


@kvalitet_bp.route("/arhiva", methods=["GET"])
@login_required
@module_required("kvalitet_arhiva")
def kvalitet_arhiva():
    conn   = get_db()
    cursor = conn.cursor()
    query  = request.args.get("q", "").strip()
    sql    = """
        SELECT id, kamin, seriski_broj, vnatresen_broj, datum, pdf_file, original_pdf_file
        FROM kvalitet_kontrola
    """
    params = []
    if query:
        sql   += " WHERE seriski_broj LIKE ? OR vnatresen_broj LIKE ? OR kamin LIKE ? OR datum LIKE ?"
        like_q = f"%{query}%"
        params = [like_q, like_q, like_q, like_q]
    sql += " ORDER BY id DESC"
    kontroli = [dict(k) for k in cursor.execute(sql, params).fetchall()]
    for k in kontroli:
        verzii = cursor.execute("""
            SELECT pdf_file, verzija, datum FROM kvalitet_pdf_verzii
            WHERE kontrola_id = ? ORDER BY verzija ASC
        """, (k["id"],)).fetchall()
        k["pdf_verzii"] = [dict(v) for v in verzii]
    conn.close()
    return render_template("kvalitet_arhiva.html", kontroli=kontroli, query=query)


@kvalitet_bp.route("/nova", methods=["GET", "POST"])
@login_required
@module_required("kvalitet_nova")
def nova_kontrola():
    UPLOAD_FOLDER = os.path.join(STATIC_FOLDER, "kvalitet_sliki")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn          = get_db()
    cursor        = conn.cursor()
    kamini        = [k["ime"] for k in cursor.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()]
    selected_kamin = request.args.get("kamin") or request.form.get("kamin")
    cekori        = []
    template      = None
    preview_vnatresen_broj = _next_vnatresen_broj_preview(cursor)

    if selected_kamin:
        template = cursor.execute(
            "SELECT * FROM kvalitet_template WHERE kamin = ?", (selected_kamin,)
        ).fetchone()
        if template:
            try:
                cekori_rows = cursor.execute(
                    "SELECT * FROM kvalitet_template_cekori WHERE template_id = ? ORDER BY redosled",
                    (template["id"],)
                ).fetchall()
            except Exception:
                cekori_rows = cursor.execute(
                    "SELECT * FROM kvalitet_template_cekori WHERE template_id = ? ORDER BY id",
                    (template["id"],)
                ).fetchall()
            for c in cekori_rows:
                podcekori = cursor.execute(
                    "SELECT * FROM kvalitet_template_podcekori WHERE cekor_id = ?", (c["id"],)
                ).fetchall()
                cekori.append({
                    "id": c["id"], "naslov": c["naslov"],
                    "podcekori": [dict(p) for p in podcekori]
                })

    if request.method == "POST":
        kamin        = request.form.get("kamin", "").strip()
        seriski_broj = request.form.get("seriski_broj", "").strip()
        vkupno_podcekori = sum(len(c["podcekori"]) for c in cekori)
        pominali_podcekori = 0

        for c in cekori:
            for pod in c["podcekori"]:
                if request.form.get(f"pod_{pod['id']}"):
                    pominali_podcekori += 1

        site_pominale = vkupno_podcekori > 0 and pominali_podcekori == vkupno_podcekori
        if not kamin:
            flash("Мора да изберете камин!", "danger")
            return render_template(
                "nova_kontrola_forma.html",
                kamini=kamini,
                cekori=cekori,
                selected_kamin=selected_kamin,
                preview_vnatresen_broj=preview_vnatresen_broj,
            )
        if site_pominale and not seriski_broj:
            flash("Серискиот број е задолжителен кога сите чекори се означени како добри.", "danger")
            return render_template(
                "nova_kontrola_forma.html",
                kamini=kamini,
                cekori=cekori,
                selected_kamin=selected_kamin,
                preview_vnatresen_broj=preview_vnatresen_broj,
            )
        try:
            naslov = f"Контрола за {kamin} - {seriski_broj or preview_vnatresen_broj}"
            cursor.execute("""
                INSERT INTO kvalitet_kontrola (kamin, seriski_broj, naslov, datum, username, status)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, 'VO_TEK')
            """, (kamin, seriski_broj, naslov, session["user"]))
            kontrola_id    = cursor.lastrowid
            vnatresen_broj = _format_vnatresen_broj(kontrola_id)
            naslov = f"Контрола за {kamin} - {seriski_broj or vnatresen_broj}"
            cursor.execute(
                "UPDATE kvalitet_kontrola SET vnatresen_broj = ?, naslov = ? WHERE id = ?",
                (vnatresen_broj, naslov, kontrola_id),
            )
            ima_nok        = False
            odgovori_za_pdf = []

            if template and cekori:
                for c in cekori:
                    odgovori_za_pdf.append({"naslov": c["naslov"], "status": None, "is_cekor": True})
                    for pod in c["podcekori"]:
                        pod_id     = pod["id"]
                        status_val = 1 if request.form.get(f"pod_{pod_id}") else 0
                        if status_val == 0:
                            ima_nok = True
                        zabeleska       = request.form.get(f"zabeleska_{pod_id}", "").strip()
                        slika_file      = request.files.get(f"slika_{pod_id}")
                        slika_filename  = slika_full_path = None
                        if slika_file and slika_file.filename:
                            fname          = secure_filename(slika_file.filename)
                            ext            = os.path.splitext(fname)[1].lower()
                            slika_filename = f"kval_{kontrola_id}_{pod_id}_{int(time.time())}{ext}"
                            slika_full_path = os.path.join(UPLOAD_FOLDER, slika_filename)
                            slika_file.save(slika_full_path)
                        cursor.execute("""
                            INSERT INTO kvalitet_odgovori (kontrola_id, podcekor_id, status, zabeleska, slika)
                            VALUES (?, ?, ?, ?, ?)
                        """, (kontrola_id, pod_id, status_val, zabeleska, slika_filename))
                        odgovor_id = cursor.lastrowid
                        _insert_kvalitet_snapshot(
                            cursor,
                            kontrola_id=kontrola_id,
                            odgovor_id=odgovor_id,
                            podcekor_id=pod_id,
                            cekor_naslov=c["naslov"],
                            podcekor_opis=str(pod.get("opis") or ""),
                            status=status_val,
                            zabeleska=zabeleska,
                            slika=slika_filename,
                        )
                        pdf_item = {"naslov": str(pod.get("opis") or ""), "status": status_val}
                        if status_val == 0:
                            if zabeleska:
                                pdf_item["zabeleska"] = zabeleska
                            if slika_full_path:
                                pdf_item["slika_path"] = slika_full_path
                        odgovori_za_pdf.append(pdf_item)

            final_status = "NE_POMINAL" if ima_nok else "POMINAL"
            cursor.execute("UPDATE kvalitet_kontrola SET status = ? WHERE id = ?", (final_status, kontrola_id))
            conn.commit()
            pdf_filename = generiraj_kvalitet_pdf_v2({
                "id": kontrola_id, "kamin": kamin, "seriski_broj": seriski_broj,
                "vnatresen_broj": vnatresen_broj,
                "datum": datetime.now().strftime("%d-%m-%Y %H:%M")
            }, odgovori_za_pdf)
            cursor.execute("UPDATE kvalitet_kontrola SET pdf_file = ? WHERE id = ?", (pdf_filename, kontrola_id))
            conn.commit()
            flash("Контролата е успешно зачувана!", "success")
            return redirect(url_for("kvalitet.kvalitet_arhiva"))
        except Exception as e:
            conn.rollback()
            import traceback; traceback.print_exc()
            flash(f"Грешка при зачувување: {str(e)}", "danger")

    return render_template(
        "nova_kontrola_forma.html",
        kamini=kamini,
        cekori=cekori,
        selected_kamin=selected_kamin,
        preview_vnatresen_broj=preview_vnatresen_broj,
    )


@kvalitet_bp.route("/uredi/<int:kontrola_id>", methods=["GET", "POST"])
@login_required
@module_required("kvalitet_nova")
def uredi_kontrola(kontrola_id):
    UPLOAD_FOLDER = os.path.join(STATIC_FOLDER, "kvalitet_sliki")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn      = get_db()
    cursor    = conn.cursor()
    kontrola  = cursor.execute("""
        SELECT id, kamin, seriski_broj, vnatresen_broj, naslov, datum, username, status, pdf_file, original_pdf_file
        FROM kvalitet_kontrola WHERE id = ?
    """, (kontrola_id,)).fetchone()
    if not kontrola:
        flash("Контролата не постои!", "danger")
        conn.close()
        return redirect(url_for("kvalitet.kvalitet_arhiva"))
    kontrola = dict(kontrola)
    odgovori = cursor.execute("""
        SELECT o.id, o.status, o.zabeleska, o.slika, p.opis AS podcekor_opis, c.naslov AS cekor_naslov
        FROM kvalitet_odgovori o
        LEFT JOIN kvalitet_template_podcekori p ON o.podcekor_id = p.id
        LEFT JOIN kvalitet_template_cekori c ON p.cekor_id = c.id
        WHERE o.kontrola_id = ? ORDER BY c.redosled, p.id
    """, (kontrola_id,)).fetchall()
    cekori = {}
    for o in odgovori:
        cekor = o["cekor_naslov"] or "Непознат чекор"
        cekori.setdefault(cekor, []).append(dict(o))

    if request.method == "POST":
        try:
            nov_seriski     = request.form.get("seriski_broj", kontrola["seriski_broj"]).strip()
            ima_nok         = False
            odgovori_za_pdf = []
            svi_odgovori    = cursor.execute("""
                SELECT o.id, o.status, o.zabeleska, o.slika,
                       p.opis AS podcekor_opis, c.naslov AS cekor_naslov
                FROM kvalitet_odgovori o
                LEFT JOIN kvalitet_template_podcekori p ON o.podcekor_id = p.id
                LEFT JOIN kvalitet_template_cekori c ON p.cekor_id = c.id
                WHERE o.kontrola_id = ? ORDER BY c.redosled, p.id
            """, (kontrola_id,)).fetchall()
            vkupno_odgovori = len(svi_odgovori)
            pominali_odgovori = sum(
                1 for o in svi_odgovori if request.form.get(f"status_{o['id']}") == "1"
            )
            site_pominale = vkupno_odgovori > 0 and pominali_odgovori == vkupno_odgovori

            if site_pominale and not nov_seriski:
                kontrola["seriski_broj"] = nov_seriski
                flash("Серискиот број е задолжителен кога сите чекори се означени како добри.", "danger")
                conn.close()
                return render_template("uredi_kontrola.html", kontrola=kontrola, cekori=cekori)

            posleden_cekor = None
            for o in svi_odgovori:
                odgovor_id   = o["id"]
                cekor_naslov = o["cekor_naslov"] or "Непознат чекор"
                if cekor_naslov != posleden_cekor:
                    odgovori_za_pdf.append({"naslov": cekor_naslov, "is_cekor": True, "status": None})
                    posleden_cekor = cekor_naslov
                nov_status    = 1 if request.form.get(f"status_{odgovor_id}") == "1" else 0
                if nov_status == 0:
                    ima_nok = True
                nova_zabeleska  = request.form.get(f"zabeleska_{odgovor_id}", "").strip()
                pod_opis        = o["podcekor_opis"] or "Непознат подчекор"
                slika_file      = request.files.get(f"slika_{odgovor_id}")
                nova_slika      = slika_full_path = None
                if slika_file and slika_file.filename:
                    fname          = secure_filename(slika_file.filename)
                    ext            = os.path.splitext(fname)[1].lower()
                    nova_slika     = f"kval_edit_{kontrola_id}_{odgovor_id}_{int(time.time())}{ext}"
                    slika_full_path = os.path.join(UPLOAD_FOLDER, nova_slika)
                    slika_file.save(slika_full_path)
                cursor.execute("""
                    UPDATE kvalitet_odgovori
                    SET status = ?, zabeleska = ?, slika = COALESCE(?, slika)
                    WHERE id = ? AND kontrola_id = ?
                """, (nov_status, nova_zabeleska, nova_slika, odgovor_id, kontrola_id))
                pdf_item = {"naslov": pod_opis, "status": nov_status,
                            "zabeleska": nova_zabeleska if nova_zabeleska else None, "slika_path": None}
                if slika_full_path:
                    pdf_item["slika_path"] = slika_full_path
                elif o["slika"]:
                    stara = os.path.join(UPLOAD_FOLDER, o["slika"])
                    if os.path.exists(stara):
                        pdf_item["slika_path"] = stara
                odgovori_za_pdf.append(pdf_item)

            final_status = "NE_POMINAL" if ima_nok else "POMINAL"
            naslov = f"Контрола за {kontrola['kamin']} - {nov_seriski or kontrola['vnatresen_broj']}"
            cursor.execute(
                "UPDATE kvalitet_kontrola SET seriski_broj = ?, naslov = ?, status = ? WHERE id = ?",
                (nov_seriski, naslov, final_status, kontrola_id),
            )
            if kontrola["pdf_file"]:
                row = cursor.execute("""
                    SELECT COALESCE(MAX(verzija), 0) + 1 AS next_ver
                    FROM kvalitet_pdf_verzii WHERE kontrola_id = ?
                """, (kontrola_id,)).fetchone()
                cursor.execute("""
                    INSERT INTO kvalitet_pdf_verzii (kontrola_id, pdf_file, verzija, datum)
                    VALUES (?, ?, ?, ?)
                """, (kontrola_id, kontrola["pdf_file"], row["next_ver"],
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            pdf_filename = generiraj_kvalitet_pdf_v2({
                "id": kontrola_id, "kamin": kontrola["kamin"],
                "seriski_broj": nov_seriski,
                "vnatresen_broj": kontrola["vnatresen_broj"],
                "datum": datetime.now().strftime("%d-%m-%Y %H:%M")
            }, odgovori_za_pdf)
            cursor.execute("UPDATE kvalitet_kontrola SET pdf_file = ? WHERE id = ?", (pdf_filename, kontrola_id))
            conn.commit()
            flash("Контролата е успешно ажурирана! Нов PDF е генериран.", "success")
            return redirect(url_for("kvalitet.kvalitet_arhiva"))
        except Exception as e:
            conn.rollback()
            import traceback; traceback.print_exc()
            flash(f"Грешка при ажурирање: {str(e)}", "danger")

    conn.close()
    return render_template("uredi_kontrola.html", kontrola=kontrola, cekori=cekori)


# ─────────────────────────────────────────────────────────────
# TEMPLATE MANAGER
# ─────────────────────────────────────────────────────────────
@kvalitet_bp.route("/arhiva/delete/<int:kontrola_id>", methods=["POST"])
@login_required
@admin_required
def delete_kontrola_arhiva(kontrola_id):
    conn = get_db()
    cursor = conn.cursor()
    return_q = request.form.get("q", "").strip()
    try:
        kontrola = cursor.execute(
            "SELECT id, pdf_file, original_pdf_file FROM kvalitet_kontrola WHERE id = ?",
            (kontrola_id,),
        ).fetchone()
        if not kontrola:
            flash("Контролата не постои!", "warning")
            return redirect(url_for("kvalitet.kvalitet_arhiva", q=return_q))

        pdf_files = set()
        if kontrola["pdf_file"]:
            pdf_files.add(kontrola["pdf_file"])
        if kontrola["original_pdf_file"]:
            pdf_files.add(kontrola["original_pdf_file"])

        version_rows = cursor.execute(
            "SELECT pdf_file FROM kvalitet_pdf_verzii WHERE kontrola_id = ?",
            (kontrola_id,),
        ).fetchall()
        for row in version_rows:
            if row["pdf_file"]:
                pdf_files.add(row["pdf_file"])

        image_files = set()
        image_rows = cursor.execute(
            "SELECT slika FROM kvalitet_odgovori WHERE kontrola_id = ?",
            (kontrola_id,),
        ).fetchall()
        for row in image_rows:
            if row["slika"]:
                image_files.add(row["slika"])

        cursor.execute("DELETE FROM kvalitet_pdf_verzii WHERE kontrola_id = ?", (kontrola_id,))
        cursor.execute("DELETE FROM kvalitet_odgovori_snapshot WHERE kontrola_id = ?", (kontrola_id,))
        cursor.execute("DELETE FROM kvalitet_odgovori WHERE kontrola_id = ?", (kontrola_id,))
        cursor.execute("DELETE FROM kvalitet_kontrola WHERE id = ?", (kontrola_id,))
        conn.commit()

        pdf_dir = os.path.join(STATIC_FOLDER, "kvalitet_pdf")
        for filename in pdf_files:
            try:
                fpath = os.path.join(pdf_dir, filename)
                if os.path.exists(fpath):
                    os.remove(fpath)
            except Exception:
                pass

        images_dir = os.path.join(STATIC_FOLDER, "kvalitet_sliki")
        for filename in image_files:
            try:
                fpath = os.path.join(images_dir, filename)
                if os.path.exists(fpath):
                    os.remove(fpath)
            except Exception:
                pass

        flash("Контролата е успешно избришана.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Грешка при бришење: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for("kvalitet.kvalitet_arhiva", q=return_q))


@kvalitet_bp.route("/template", methods=["GET"])
@login_required
@module_required("kvalitet_template")
def kvalitet_template_manager():
    conn           = get_db()
    cursor         = conn.cursor()
    kamini         = [k["ime"] for k in cursor.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()]
    selected_kamin = request.args.get("kamin")
    template       = None
    cekori         = []
    if selected_kamin:
        template = cursor.execute("SELECT * FROM kvalitet_template WHERE kamin = ?", (selected_kamin,)).fetchone()
        if not template:
            cursor.execute("INSERT INTO kvalitet_template (kamin) VALUES (?)", (selected_kamin,))
            conn.commit()
            template = cursor.execute("SELECT * FROM kvalitet_template WHERE kamin = ?", (selected_kamin,)).fetchone()
        cekori_raw = cursor.execute("""
            SELECT * FROM kvalitet_template_cekori WHERE template_id = ? ORDER BY redosled
        """, (template["id"],)).fetchall()
        for c in cekori_raw:
            podcekori = cursor.execute(
                "SELECT * FROM kvalitet_template_podcekori WHERE cekor_id = ?", (c["id"],)
            ).fetchall()
            cekori.append({"id": c["id"], "naslov": c["naslov"], "podcekori": podcekori})
    conn.close()
    return render_template("kvalitet_template_manager.html",
                           kamini=kamini, selected_kamin=selected_kamin,
                           template=template, cekori=cekori)


@kvalitet_bp.route("/template/add_cekor", methods=["POST"])
@login_required
@module_required("kvalitet_template")
def add_template_cekor():
    conn        = get_db()
    cursor      = conn.cursor()
    template_id = request.form.get("template_id")
    naslov      = request.form.get("naslov")
    if not template_id or not naslov:
        conn.close()
        return "ERROR"
    row = cursor.execute("""
        SELECT COALESCE(MAX(redosled), 0) + 1 AS next_order
        FROM kvalitet_template_cekori WHERE template_id = ?
    """, (template_id,)).fetchone()
    cursor.execute("""
        INSERT INTO kvalitet_template_cekori (template_id, naslov, redosled) VALUES (?, ?, ?)
    """, (template_id, naslov, row["next_order"]))
    conn.commit()
    conn.close()
    return "OK"


@kvalitet_bp.route("/template/add_podcekor", methods=["POST"])
@login_required
@module_required("kvalitet_template")
def add_template_podcekor():
    conn     = get_db()
    cursor   = conn.cursor()
    cekor_id = request.form.get("cekor_id")
    opis     = request.form.get("opis")
    if cekor_id and opis:
        cursor.execute("INSERT INTO kvalitet_template_podcekori (cekor_id, opis) VALUES (?, ?)", (cekor_id, opis))
        conn.commit()
    conn.close()
    return "OK"


@kvalitet_bp.route("/template/delete_cekor/<int:cekor_id>")
@login_required
@module_required("kvalitet_template")
def delete_template_cekor(cekor_id):
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kvalitet_template_podcekori WHERE cekor_id = ?", (cekor_id,))
    cursor.execute("DELETE FROM kvalitet_template_cekori WHERE id = ?", (cekor_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer)


@kvalitet_bp.route("/template/delete_podcekor/<int:pod_id>")
@login_required
@module_required("kvalitet_template")
def delete_template_podcekor(pod_id):
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kvalitet_template_podcekori WHERE id = ?", (pod_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer)


@kvalitet_bp.route("/template/edit_cekor/<int:cekor_id>", methods=["POST"])
@login_required
@module_required("kvalitet_template")
def edit_template_cekor(cekor_id):
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE kvalitet_template_cekori SET naslov = ? WHERE id = ?",
                   (request.form.get("naslov"), cekor_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer)


@kvalitet_bp.route("/template/edit_podcekor/<int:pod_id>", methods=["POST"])
@login_required
@module_required("kvalitet_template")
def edit_template_podcekor(pod_id):
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE kvalitet_template_podcekori SET opis = ? WHERE id = ?",
                   (request.form.get("opis"), pod_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer)


@kvalitet_bp.route("/template/move_cekor/<int:cekor_id>/<direction>")
@login_required
@module_required("kvalitet_template")
def move_template_cekor(cekor_id, direction):
    conn    = get_db()
    cursor  = conn.cursor()
    current = cursor.execute(
        "SELECT id, template_id, redosled FROM kvalitet_template_cekori WHERE id = ?", (cekor_id,)
    ).fetchone()
    if not current:
        conn.close()
        return redirect(request.referrer)
    template_id   = current["template_id"]
    current_order = current["redosled"]
    if direction == "up":
        swap = cursor.execute("""
            SELECT * FROM kvalitet_template_cekori
            WHERE template_id = ? AND redosled < ? ORDER BY redosled DESC LIMIT 1
        """, (template_id, current_order)).fetchone()
    else:
        swap = cursor.execute("""
            SELECT * FROM kvalitet_template_cekori
            WHERE template_id = ? AND redosled > ? ORDER BY redosled ASC LIMIT 1
        """, (template_id, current_order)).fetchone()
    if swap:
        cursor.execute("UPDATE kvalitet_template_cekori SET redosled = ? WHERE id = ?",
                       (swap["redosled"], current["id"]))
        cursor.execute("UPDATE kvalitet_template_cekori SET redosled = ? WHERE id = ?",
                       (current_order, swap["id"]))
        conn.commit()
    conn.close()
    return redirect(request.referrer)


@kvalitet_bp.route("/template/fix_redosled")
@login_required
@module_required("kvalitet_template")
def fix_template_redosled():
    conn      = get_db()
    cursor    = conn.cursor()
    templates = cursor.execute("SELECT DISTINCT template_id FROM kvalitet_template_cekori").fetchall()
    for t in templates:
        template_id = t["template_id"] if isinstance(t, dict) else t[0]
        cekori = cursor.execute(
            "SELECT id FROM kvalitet_template_cekori WHERE template_id = ? ORDER BY id", (template_id,)
        ).fetchall()
        for red, c in enumerate(cekori, start=1):
            cekor_id = c["id"] if isinstance(c, dict) else c[0]
            cursor.execute("UPDATE kvalitet_template_cekori SET redosled = ? WHERE id = ?", (red, cekor_id))
    conn.commit()
    conn.close()
    return "REDOSLED FIXED"
