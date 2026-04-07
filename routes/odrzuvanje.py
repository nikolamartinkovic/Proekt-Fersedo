import io
import os
from datetime import date, datetime, timedelta

import qrcode
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.utils import secure_filename

from utils.db import get_db
from utils.decorators import admin_or_module_required, login_required
from utils.odrzuvanje_notifications import notify_new_order, notify_order_assignment


odrzuvanje_bp = Blueprint("odrzuvanje", __name__, url_prefix="/odrzuvanje")

MASINA_STATUSI = ["работи", "сервис", "стопирана"]
NALOG_TIPOVI = ["превентивно", "дефект", "итно", "подобрување"]
NALOG_PRIORITETI = ["низок", "среден", "висок", "критичен"]
AKTIVNI_STATUSI = ["креиран", "доделен", "во тек", "чека дел"]
ZATVORENI_STATUSI = ["завршен", "потврден", "откажан"]
PLAN_TIPOVI = ["превентивно", "инспекција", "калибрација", "чистење"]
PROCUREMENT_CREATED_STATUS = "\u043a\u0440\u0435\u0438\u0440\u0430\u043d\u043e"

UPLOAD_ROOT = os.path.join("static", "uploads", "odrzuvanje")
MACHINE_IMAGE_FOLDER = os.path.join(UPLOAD_ROOT, "masini")
MANUAL_FOLDER = os.path.join(UPLOAD_ROOT, "manuals")


def _ensure_upload_dirs():
    os.makedirs(MACHINE_IMAGE_FOLDER, exist_ok=True)
    os.makedirs(MANUAL_FOLDER, exist_ok=True)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return date.today().isoformat()


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _save_upload(file_obj, folder):
    if not file_obj or not file_obj.filename:
        return ""
    _ensure_upload_dirs()
    filename = secure_filename(file_obj.filename)
    base, ext = os.path.splitext(filename)
    unique_name = f"{base}_{int(datetime.now().timestamp())}{ext}"
    final_path = os.path.join(folder, unique_name)
    file_obj.save(final_path)
    return unique_name


def _next_sequence(cursor, prefix):
    cursor.execute(
        """
        INSERT INTO odrzuvanje_sequences(name, last_num)
        VALUES (?, 0)
        ON CONFLICT(name) DO NOTHING
        """,
        (prefix,),
    )
    cursor.execute(
        "UPDATE odrzuvanje_sequences SET last_num = last_num + 1 WHERE name = ?",
        (prefix,),
    )
    row = cursor.execute(
        "SELECT last_num FROM odrzuvanje_sequences WHERE name = ?",
        (prefix,),
    ).fetchone()
    return f"{prefix.upper()}-{int(row['last_num']):04d}"


def _append_activity(cursor, nalog_id, poraka, tip="note", created_by=None):
    cursor.execute(
        """
        INSERT INTO odrzuvanje_nalog_aktivnosti (nalog_id, tip, poraka, created_by)
        VALUES (?, ?, ?, ?)
        """,
        (nalog_id, tip, poraka, created_by or session.get("user", "")),
    )


def _fetch_assignable_users(cursor):
    rows = cursor.execute(
        """
        SELECT username, is_admin, COALESCE(user_group, '') AS user_group,
               COALESCE(allowed_modules, '') AS allowed_modules
        FROM users
        ORDER BY username
        """
    ).fetchall()
    result = []
    for row in rows:
        allowed = {item.strip() for item in row["allowed_modules"].split(",") if item.strip()}
        if row["is_admin"] or "odrzuvanje" in allowed or "odrzuvanje_nalozi" in allowed:
            result.append(row["username"])
            continue
        if row["user_group"].strip().lower() in {"odrzuvanje", "maintenance", "servis"}:
            result.append(row["username"])
    return result


def _machine_card(row):
    status = row["status"] or "работи"
    status_class = {
        "работи": "success",
        "сервис": "warning",
        "стопирана": "danger",
    }.get(status, "secondary")
    return {**dict(row), "status_class": status_class}


def _sync_machine_status(cursor, masina_id):
    open_orders = cursor.execute(
        """
        SELECT prioritet, tip
        FROM odrzuvanje_nalozi
        WHERE masina_id = ? AND status IN (?, ?, ?, ?)
        """,
        (masina_id, *AKTIVNI_STATUSI),
    ).fetchall()
    new_status = "работи"
    if open_orders:
        new_status = "сервис"
        if any(row["prioritet"] == "критичен" or row["tip"] == "итно" for row in open_orders):
            new_status = "стопирана"
    cursor.execute(
        "UPDATE odrzuvanje_masini SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, _now(), masina_id),
    )


def _upsert_plan_next_date(cursor, plan_id, plan_row):
    today = date.today()
    base = today
    if plan_row["sledno_izvrsuvanje"]:
        try:
            base = datetime.strptime(plan_row["sledno_izvrsuvanje"], "%Y-%m-%d").date()
        except Exception:
            base = today
    interval_days = _safe_int(plan_row["interval_dena"], 0)
    next_date = base + timedelta(days=interval_days or 30)
    cursor.execute(
        """
        UPDATE odrzuvanje_planovi
        SET posledno_izvrseno = ?, sledno_izvrsuvanje = ?
        WHERE id = ?
        """,
        (today.isoformat(), next_date.isoformat(), plan_id),
    )


def _fmt_date(value):
    if not value:
        return "—"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).strftime("%d-%m-%Y")
        except Exception:
            continue
    return str(value)


def _fmt_datetime(value):
    if not value:
        return "—"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(str(value), fmt)
            if fmt == "%Y-%m-%d":
                return parsed.strftime("%d-%m-%Y")
            return parsed.strftime("%d-%m-%Y %H:%M")
        except Exception:
            continue
    return str(value)


def _pdf_assets():
    root = current_app.root_path
    return {
        "font_regular": os.path.join(root, "static", "fonts", "DejaVuSans.ttf"),
        "font_bold": os.path.join(root, "static", "fonts", "DejaVuSans-Bold.ttf"),
        "logo": os.path.join(root, "static", "logo2.png"),
    }


def _ensure_pdf_fonts():
    assets = _pdf_assets()
    if os.path.exists(assets["font_regular"]) and "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans", assets["font_regular"]))
    if os.path.exists(assets["font_bold"]) and "DejaVuSans-Bold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", assets["font_bold"]))


def _paragraph(text, style):
    return Paragraph((text or "—").replace("\n", "<br/>"), style)


def _order_pdf_buffer(order, machine, activities, parts, linked_procurements):
    _ensure_pdf_fonts()
    assets = _pdf_assets()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.35 * cm,
        leftMargin=1.35 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "OdrTitle",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "OdrSubtitle",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=10.2,
        leading=14,
        textColor=colors.HexColor("#475569"),
    )
    section_style = ParagraphStyle(
        "OdrSection",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=12,
        leading=14,
        textColor=colors.white,
    )
    body_style = ParagraphStyle(
        "OdrBody",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=9.4,
        leading=12.2,
        textColor=colors.HexColor("#1e293b"),
    )
    body_small = ParagraphStyle(
        "OdrBodySmall",
        parent=body_style,
        fontSize=8.6,
        leading=11,
    )
    label_style = ParagraphStyle(
        "OdrLabel",
        parent=body_style,
        fontName="DejaVuSans-Bold",
        textColor=colors.HexColor("#334155"),
    )

    story = []
    if os.path.exists(assets["logo"]):
        story.append(RLImage(assets["logo"], width=3.2 * cm, height=1.25 * cm))
        story.append(Spacer(1, 0.35 * cm))

    header_table = Table(
        [
            [
                [
                    _paragraph("Работен налог за одржување", title_style),
                    _paragraph(
                        f"Број: <b>{order['broj']}</b><br/>"
                        f"Машина: <b>{machine['naziv']}</b> · {machine['kod'] or '—'}<br/>"
                        f"Тип: <b>{order['tip'] or '—'}</b> · Приоритет: <b>{order['prioritet'] or '—'}</b><br/>"
                        f"Статус: <b>{order['status'] or '—'}</b>",
                        subtitle_style,
                    ),
                ],
                [
                    _paragraph("Основни информации", label_style),
                    _paragraph(
                        f"Пријавил: <b>{order['prijavil'] or order['created_by'] or '—'}</b><br/>"
                        f"Доделено: <b>{order['dodeleno_na'] or 'Нераспределен'}</b><br/>"
                        f"Креирано: <b>{_fmt_datetime(order['created_at'])}</b><br/>"
                        f"Почеток: <b>{_fmt_datetime(order['pocetok_at'])}</b><br/>"
                        f"Крај: <b>{_fmt_datetime(order['kraj_at'])}</b>",
                        body_style,
                    ),
                ],
            ]
        ],
        colWidths=[11.2 * cm, 6.0 * cm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f8fafc")),
                ("BOX", (1, 0), (1, 0), 0.7, colors.HexColor("#cbd5e1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 0.3 * cm))

    summary_rows = [
        [_paragraph("Наслов", label_style), _paragraph(order["naslov"] or "—", body_style)],
        [_paragraph("Опис на дефект", label_style), _paragraph(order["opis_defekt"] or "—", body_style)],
        [_paragraph("Симптом", label_style), _paragraph(order["simptom"] or "—", body_style)],
        [_paragraph("Решение", label_style), _paragraph(order["resenie"] or "—", body_style)],
        [
            _paragraph("Застој / Трошок", label_style),
            _paragraph(f"{order['zastoj_minuti'] or 0} минути · {order['trosok'] or 0} ден.", body_style),
        ],
    ]
    summary_table = Table(summary_rows, colWidths=[4.0 * cm, 13.2 * cm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.35 * cm))

    def section_header(title):
        table = Table([[ _paragraph(title, section_style) ]], colWidths=[17.2 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#172554")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("BOX", (0, 0), (-1, -1), 0, colors.white),
                ]
            )
        )
        return table

    story.append(section_header("Активности на налог"))
    if activities:
        activity_data = [[
            _paragraph("Време", label_style),
            _paragraph("Тип", label_style),
            _paragraph("Корисник", label_style),
            _paragraph("Порака", label_style),
        ]]
        for item in activities:
            activity_data.append(
                [
                    _paragraph(_fmt_datetime(item["created_at"]), body_small),
                    _paragraph(item["tip"] or "—", body_small),
                    _paragraph(item["created_by"] or "—", body_small),
                    _paragraph(item["poraka"] or "—", body_small),
                ]
            )
        activity_table = Table(activity_data, colWidths=[3.0 * cm, 2.5 * cm, 3.0 * cm, 8.7 * cm], repeatRows=1)
        activity_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#cbd5e1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#e2e8f0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(activity_table)
    else:
        story.append(Spacer(1, 0.15 * cm))
        story.append(_paragraph("Нема внесени активности за овој налог.", body_style))
    story.append(Spacer(1, 0.3 * cm))

    story.append(section_header("Делови и материјали"))
    if parts:
        parts_data = [[
            _paragraph("Part number", label_style),
            _paragraph("Опис", label_style),
            _paragraph("Количина", label_style),
            _paragraph("Извор", label_style),
        ]]
        for part in parts:
            parts_data.append(
                [
                    _paragraph(part["part_number"] or "—", body_small),
                    _paragraph(part["opis"] or "—", body_small),
                    _paragraph(str(part["kolicina"] or 0), body_small),
                    _paragraph(part["source_type"] or "—", body_small),
                ]
            )
        parts_table = Table(parts_data, colWidths=[3.0 * cm, 8.4 * cm, 2.1 * cm, 3.7 * cm], repeatRows=1)
        parts_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fff7ed")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#fed7aa")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#fde68a")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(parts_table)
    else:
        story.append(Spacer(1, 0.15 * cm))
        story.append(_paragraph("Нема евидентирани делови за налогот.", body_style))
    story.append(Spacer(1, 0.3 * cm))

    story.append(section_header("Поврзани набавки"))
    if linked_procurements:
        procurement_data = [[
            _paragraph("ID", label_style),
            _paragraph("Наслов", label_style),
            _paragraph("Статус", label_style),
            _paragraph("Количина", label_style),
        ]]
        for req in linked_procurements:
            procurement_data.append(
                [
                    _paragraph(str(req["nabavka_request_id"]), body_small),
                    _paragraph(req["naslov"] or "—", body_small),
                    _paragraph(req["status"] or "—", body_small),
                    _paragraph(str(req["kolicina"] or 0), body_small),
                ]
            )
        procurement_table = Table(procurement_data, colWidths=[2.0 * cm, 9.0 * cm, 3.0 * cm, 3.2 * cm], repeatRows=1)
        procurement_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fef2f2")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#fecaca")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#fee2e2")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(procurement_table)
    else:
        story.append(Spacer(1, 0.15 * cm))
        story.append(_paragraph("Нема поврзани барања кон Набавки.", body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _manual_pdf_buffer():
    _ensure_pdf_fonts()
    assets = _pdf_assets()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.35 * cm,
        leftMargin=1.35 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ManualTitle",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=21,
        leading=26,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ManualSubtitle",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569"),
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "ManualSection",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=12,
        leading=14,
        textColor=colors.white,
    )
    body_style = ParagraphStyle(
        "ManualBody",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=9.3,
        leading=12.3,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=4,
    )
    body_small = ParagraphStyle(
        "ManualBodySmall",
        parent=body_style,
        fontSize=8.6,
        leading=11,
        spaceAfter=0,
    )
    label_style = ParagraphStyle(
        "ManualLabel",
        parent=body_style,
        fontName="DejaVuSans-Bold",
        textColor=colors.HexColor("#334155"),
    )
    bullet_style = ParagraphStyle(
        "ManualBullet",
        parent=body_style,
        leftIndent=12,
        firstLineIndent=0,
        bulletIndent=0,
        spaceAfter=3,
    )

    story = []
    if os.path.exists(assets["logo"]):
        story.append(RLImage(assets["logo"], width=3.3 * cm, height=1.28 * cm))
        story.append(Spacer(1, 0.35 * cm))

    story.append(_paragraph("Прирачник за работа со модулот Одржување", title_style))
    story.append(
        _paragraph(
            "Овој документ е наменет за секој што работи со машини, дефекти, планови и сервисни налози во модулот Одржување. "
            "Прирачникот објаснува како правилно се отвораат записи, како се следи сервисот и како се користи врската со Набавки и Историја.",
            subtitle_style,
        )
    )
    story.append(
        _paragraph(
            f"Верзија на прирачник: {date.today().strftime('%d-%m-%Y')}<br/>"
            "Систем: Fersedo · Одржување на машини во производство",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 0.15 * cm))

    def section_header(title):
        table = Table([[_paragraph(title, section_style)]], colWidths=[17.2 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#172554")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.18 * cm))

    def info_table(rows):
        table = Table(rows, colWidths=[4.2 * cm, 13.0 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.26 * cm))

    def bullet(text):
        story.append(Paragraph(text, bullet_style, bulletText="•"))

    section_header("1. Што е модулот Одржување")
    info_table(
        [
            [_paragraph("Главна намена", label_style), _paragraph("Модулот служи за евиденција, планирање и следење на сервисирање, дефекти, резервни делови и застој на машини во производството.", body_style)],
            [_paragraph("Кој го користи", label_style), _paragraph("Оператори, одржување, одговорни лица, раководители и администрација. Секој гледа делови според своите дозволи.", body_style)],
            [_paragraph("Што се води", label_style), _paragraph("Машини, работни налози, активности, делови, поврзани набавки, планови за сервис и историски интервенции.", body_style)],
        ]
    )

    section_header("2. Главни екрани во модулот")
    screen_rows = [[
        _paragraph("Екран", label_style),
        _paragraph("За што се користи", label_style),
    ]]
    for left, right in [
        ("Почетна Одржување", "Дава преглед на KPI, активни налози, доспеани планови и брз пристап до машините."),
        ("Машини", "Список на сите машини со статус, локација, сервисен интервал, слика и документација."),
        ("Налози", "Сите отворени и затворени работни налози за дефект, превентивно одржување, итни случаи и подобрувања."),
        ("План", "Планирани превентивни сервиси според денови, часови, циклус или рачен датум."),
        ("Историја", "Преглед на завршени интервенции, застој, трошок и PDF документи."),
        ("QR пристап", "Брзо отворање на картон на машина преку QR код залепен на самата машина."),
    ]:
        screen_rows.append([_paragraph(left, body_small), _paragraph(right, body_small)])
    table = Table(screen_rows, colWidths=[4.2 * cm, 13.0 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0f2fe")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.28 * cm))

    section_header("3. Како се креира и одржува картон на машина")
    bullet("Прво отвори Машини и креирај нова машина со код, назив, линија, локација и серија. Кодот треба да биде краток и препознатлив.")
    bullet("Ако машината има прирачник, сервисна книга, гаранција или фотографија, тие се додаваат во картонот за да бидат достапни на едно место.")
    bullet("Во картонот се внесува и сервисен интервал. Тој интервал подоцна се користи во План за автоматско следење на превентивно одржување.")
    bullet("Во секоја машина може да се запише кратка сервисна чек листа: што се проверува, што се чисти, што се затегнува и на што треба да се внимава.")
    bullet("Статусот на машината се менува автоматски според отворените налози: работи, сервис или стопирана.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("4. Како се отвора работен налог")
    info_table(
        [
            [_paragraph("Тип на налог", label_style), _paragraph("Превентивно, дефект, итно или подобрување. Типот кажува зошто е отворен налогот.", body_style)],
            [_paragraph("Приоритет", label_style), _paragraph("Низок, среден, висок или критичен. Критичен или итен налог ја крева машината во повисок ризик и може да ја стави во стоп.", body_style)],
            [_paragraph("Опис", label_style), _paragraph("Во налогот јасно запиши што е проблемот, кој симптом се појавува, кога е забележан и што е очекуваниот исход.", body_style)],
            [_paragraph("Пријавил", label_style), _paragraph("Секогаш се гледа кој го креирал налогот, за да може тимот да знае од кого да добие дополнителни информации.", body_style)],
        ]
    )
    bullet("Кога се отвора нов налог, тој прво е со статус Креиран.")
    bullet("Налогот потоа се доделува на одговорно лице од одржување. По доделување статусот се менува во Доделен.")
    bullet("Кога реално започнува работа, статусот се менува во Во тек, а во активностите треба да се запише што е направено.")
    bullet("Ако интервенцијата не може да продолжи затоа што нема резервен дел, налогот може да оди во Чека дел.")
    bullet("По завршување, налогот се затвора со Завршен или Потврден, а автоматски оди во Историја и влегува во KPI пресметките.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("5. Како се користи страницата за детал на налог")
    bullet("Горе ги гледаш основните информации за машината, типот, приоритетот, статусот и одговорното лице.")
    bullet("Во делот Активности запишуваш секој реален чекор: дијагностика, демонтажа, мерење, замена, тестирање, пуштање во работа.")
    bullet("Во делот Делови и материјали внесуваш што е потрошено: part number, опис, количина и извор.")
    bullet("Ако делот недостасува, од истиот налог се креира барање во Набавки. На тој начин одржување и набавка остануваат поврзани.")
    bullet("Од детал на налог може да се симне PDF работен налог. Тој документ е корисен за сервисна евиденција, потпис и архивирање.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("6. Како функционира врската со Набавки")
    bullet("Ако за сервисот е потребен дел што го нема, во налогот користи Креирај набавка.")
    bullet("Системот автоматски отвора запис во модулот Набавки и го поврзува со конкретниот работен налог.")
    bullet("Во Набавки се следи статусот на нарачката, а во Одржување останува траг дека сервисот чека дел.")
    bullet("Кога делот ќе пристигне, одговорното лице може да го внесе во налогот и да го промени статусот од Чека дел во Во тек.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("7. План за превентивно одржување")
    bullet("Во План се внесуваат рутински сервиси што треба да се повторуваат по денови, часови, циклуси или рачно зададен термин.")
    bullet("Секој план треба да има назив, машина, тип на активност и следно извршување.")
    bullet("Кога планот ќе дојде на ред, се појавува како доспеан. Од таму може да се означи како завршен или да се претвори во сервисен налог.")
    bullet("Со редовно користење на План се намалуваат ненадејни дефекти и застој во производството.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("8. Историја и извештаи")
    bullet("Во Историја се гледаат сите завршени налози. Тука се проверува што било работено на секоја машина и колку често се повторуваат дефекти.")
    bullet("Клучни податоци за историја се: застој во минути, трошок, потрошени делови, датум на интервенција и кој ја завршил.")
    bullet("Историјата е најважна за анализа: ако иста машина често има дефект, треба или нов план, или промена на дел, или дополнителна обука.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("9. Dashboard KPI објаснување")
    kpi_rows = [[_paragraph("Картичка", label_style), _paragraph("Што значи", label_style)]]
    for left, right in [
        ("Критични и итни отворени налози", "Колку налози бараат брза реакција и носат најголем ризик за застој."),
        ("Планови со задоцнување", "Колку превентивни сервиси требало да бидат направени, а уште не се затворени."),
        ("Завршени налози овој месец", "Колку сервиси се затворени во тековниот месец."),
        ("Застој овој месец", "Вкупен застој во минути што го пријавиле и затвориле налозите."),
        ("Трошок овој месец", "Проценет или внесен трошок за делови и сервисни интервенции."),
    ]:
        kpi_rows.append([_paragraph(left, body_small), _paragraph(right, body_small)])
    kpi_table = Table(kpi_rows, colWidths=[5.0 * cm, 12.2 * cm], repeatRows=1)
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dcfce7")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#bbf7d0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1fae5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(kpi_table)
    story.append(Spacer(1, 0.26 * cm))

    section_header("10. QR пристап на машина")
    bullet("За секоја машина системот може да генерира QR код.")
    bullet("QR кодот се печати и се лепи на машината. Со скенирање се отвора картонот на машината или деталниот преглед за сервис.")
    bullet("Ова е корисно кога одржување е на терен во производството и нема време да бара рачно низ модулите.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("11. Препорачана дневна рутина за тимот")
    bullet("На почеток на смена отвори Dashboard и провери критични налози и доспеани планови.")
    bullet("Провери дали има налози со статус Чека дел и дали за нив е отворена набавка.")
    bullet("При секоја реална интервенција внесувај активност, а не само финален резултат. Така историјата е корисна и за други лица.")
    bullet("По завршување на работа, затвори го налогот со точен застој, трошок и финална забелешка.")
    bullet("Барем еднаш неделно провери Историја по машина за повторливи дефекти.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("12. Правила за добро користење")
    bullet("Не оставај налог без одговорно лице ако веќе е започнат.")
    bullet("Не користи општи описи како Поправено. Наместо тоа, запиши што точно е направено.")
    bullet("Ако се смени дел, внеси го делот по можност со part number и количина.")
    bullet("Ако машината работи, а налогот уште стои Во тек, затвори го навреме за KPI бројките да бидат точни.")
    bullet("Кога има повторлив дефект, користи Историја и отвори налог со јасна врска кон претходната интервенција.")
    story.append(Spacer(1, 0.16 * cm))

    section_header("13. Брз workflow од почеток до крај")
    workflow_rows = [[
        _paragraph("Чекор", label_style),
        _paragraph("Што правиш", label_style),
    ]]
    for step, action in [
        ("1", "Провери дали машината веќе постои во Машини. Ако не, прво креирај картон."),
        ("2", "Отвори нов налог со точен тип, приоритет и опис на дефектот."),
        ("3", "Додели одговорно лице и започни работа."),
        ("4", "Внесувај активности додека сервисот е во тек."),
        ("5", "Додај делови и материјали што се потрошени."),
        ("6", "Ако недостига дел, креирај поврзана набавка од налогот."),
        ("7", "По поправка, внеси застој, трошок и финално решение."),
        ("8", "Затвори го налогот и провери дали машината автоматски се вратила во правилен статус."),
        ("9", "По потреба симни PDF и архивирај го документот."),
    ]:
        workflow_rows.append([_paragraph(step, body_small), _paragraph(action, body_small)])
    workflow_table = Table(workflow_rows, colWidths=[1.3 * cm, 15.9 * cm], repeatRows=1)
    workflow_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ede9fe")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d8b4fe")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e9d5ff")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(workflow_table)
    story.append(Spacer(1, 0.22 * cm))
    story.append(
        _paragraph(
            "Совет: користи го модулот како оперативна алатка, а не само како архива. Колку е подобро пополнет еден налог, толку полесно ќе се решава следниот дефект на истата машина.",
            subtitle_style,
        )
    )

    story.append(PageBreak())
    section_header("14. Визуелен преглед на модулот")
    story.append(
        _paragraph(
            "Подолу се вметнати screenshots од главните екрани на модулот Одржување. Овие слики служат како брз визуелен водич за нови корисници и за полесно снаоѓање низ секциите.",
            body_style,
        )
    )
    story.append(Spacer(1, 0.08 * cm))

    screenshot_dir = os.path.join(current_app.root_path, "static", "manual", "odrzuvanje")
    screenshot_items = [
        (
            "dashboard.png",
            "Почетен dashboard со преглед на KPI, број активни и критични налози, како и доспеани планови.",
        ),
        (
            "machines.png",
            "Листа на машини, каде што се внесуваат и се следат основните податоци за код, локација, интервал и сервисна состојба.",
        ),
        (
            "orders.png",
            "Листа на налози, каде што се креираат, доделуваат и следат поединечни сервисни задачи.",
        ),
        (
            "plan.png",
            "План за одржување, наменет за превентивни активности и распоредување задачи по периоди и одговорни лица.",
        ),
        (
            "history.png",
            "Листа на историја, каде што се гледаат завршени интервенции, PDF документи, трошок и застој.",
        ),
    ]
    for filename, caption in screenshot_items:
        screenshot_path = os.path.join(screenshot_dir, filename)
        if not os.path.exists(screenshot_path):
            continue
        img = RLImage(screenshot_path)
        max_width = 16.6 * cm
        max_height = 11.0 * cm
        width_ratio = max_width / float(img.imageWidth)
        height_ratio = max_height / float(img.imageHeight)
        ratio = min(width_ratio, height_ratio)
        img.drawWidth = img.imageWidth * ratio
        img.drawHeight = img.imageHeight * ratio
        story.append(img)
        story.append(Spacer(1, 0.12 * cm))
        story.append(_paragraph(caption, body_small))
        story.append(Spacer(1, 0.28 * cm))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _create_procurement_request(cursor, nalog_row, opis, kolicina):
    cursor.execute(
        """
        INSERT INTO nabavki_requests
        (username, naslov, kolicina, datum_kreiranje, datum_itnost, opis, slika, status, nalog_broj)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, '', 'РєСЂРµРёСЂР°РЅРѕ', ?)
        """,
        (
            session.get("user", ""),
            f"Одржување: {nalog_row['broj']} / {opis}",
            _safe_float(kolicina, 1),
            (date.today() + timedelta(days=7)).isoformat(),
            f"Поврзано со работен налог {nalog_row['broj']} за машина #{nalog_row['masina_id']}",
            nalog_row["broj"],
        ),
    )
    return cursor.lastrowid


def _create_procurement_request(cursor, nalog_row, opis, kolicina):
    cursor.execute(
        """
        INSERT INTO nabavki_requests
        (username, naslov, kolicina, datum_kreiranje, datum_itnost, opis, slika, status, nalog_broj)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, '', ?, ?)
        """,
        (
            session.get("user", ""),
            f"Одржување: {nalog_row['broj']} / {opis}",
            _safe_float(kolicina, 1),
            (date.today() + timedelta(days=7)).isoformat(),
            f"Поврзано со работен налог {nalog_row['broj']} за машина #{nalog_row['masina_id']}",
            PROCUREMENT_CREATED_STATUS,
            nalog_row["broj"],
        ),
    )
    return cursor.lastrowid


@odrzuvanje_bp.route("/")
@login_required
@admin_or_module_required("odrzuvanje")
def dashboard():
    conn = get_db()
    cursor = conn.cursor()
    today = _today()
    month_prefix = date.today().strftime("%Y-%m")
    machines = cursor.execute(
        "SELECT * FROM odrzuvanje_masini ORDER BY naziv, kod"
    ).fetchall()
    active_orders = cursor.execute(
        """
        SELECT n.*, m.naziv AS masina_naziv, m.kod AS masina_kod
        FROM odrzuvanje_nalozi n
        JOIN odrzuvanje_masini m ON m.id = n.masina_id
        WHERE n.status IN (?, ?, ?, ?)
        ORDER BY n.created_at DESC
        LIMIT 8
        """,
        (*AKTIVNI_STATUSI,),
    ).fetchall()
    due_plans = cursor.execute(
        """
        SELECT p.*, m.naziv AS masina_naziv, m.kod AS masina_kod
        FROM odrzuvanje_planovi p
        JOIN odrzuvanje_masini m ON m.id = p.masina_id
        WHERE p.aktivno = 1
          AND p.sledno_izvrsuvanje IS NOT NULL
          AND p.sledno_izvrsuvanje <= ?
        ORDER BY p.sledno_izvrsuvanje ASC
        LIMIT 8
        """,
        (today,),
    ).fetchall()
    overdue_plans = cursor.execute(
        """
        SELECT COUNT(*) AS c
        FROM odrzuvanje_planovi
        WHERE aktivno = 1
          AND sledno_izvrsuvanje IS NOT NULL
          AND sledno_izvrsuvanje < ?
        """,
        (today,),
    ).fetchone()["c"]
    monthly_rollup = cursor.execute(
        """
        SELECT COUNT(*) AS completed_month,
               COALESCE(SUM(COALESCE(trosok, 0)), 0) AS monthly_cost,
               COALESCE(SUM(COALESCE(zastoj_minuti, 0)), 0) AS monthly_downtime
        FROM odrzuvanje_nalozi
        WHERE status IN (?, ?, ?)
          AND substr(COALESCE(kraj_at, updated_at, created_at), 1, 7) = ?
        """,
        (*ZATVORENI_STATUSI, month_prefix),
    ).fetchone()
    critical_open = cursor.execute(
        """
        SELECT COUNT(*) AS c
        FROM odrzuvanje_nalozi
        WHERE status IN (?, ?, ?, ?)
          AND (prioritet = ? OR tip = ?)
        """,
        (*AKTIVNI_STATUSI, "РєСЂРёС‚РёС‡РµРЅ", "РёС‚РЅРѕ"),
    ).fetchone()["c"]
    stats = {
        "machines": len(machines),
        "active_orders": len(active_orders),
        "due_plans": len(due_plans),
        "overdue_plans": overdue_plans,
        "completed_month": monthly_rollup["completed_month"],
        "monthly_cost": round(float(monthly_rollup["monthly_cost"] or 0), 2),
        "monthly_downtime": int(monthly_rollup["monthly_downtime"] or 0),
        "critical_open": critical_open,
        "stopped": sum(1 for row in machines if (row["status"] or "") == "стопирана"),
    }
    conn.close()
    return render_template(
        "odrzuvanje.html",
        stats=stats,
        machines=[_machine_card(row) for row in machines],
        active_orders=active_orders,
        due_plans=due_plans,
    )


@odrzuvanje_bp.route("/priracnik/pdf")
@login_required
@admin_or_module_required("odrzuvanje")
def manual_pdf():
    pdf_buffer = _manual_pdf_buffer()
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="Odrzuvanje_priracnik.pdf",
    )


@odrzuvanje_bp.route("/masini", methods=["GET", "POST"])
@login_required
@admin_or_module_required("odrzuvanje_masini")
def machines():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST":
        kod = request.form.get("kod", "").strip() or _next_sequence(cursor, "MAS")
        naziv = request.form.get("naziv", "").strip()
        if not naziv:
            flash("Името на машината е задолжително.", "danger")
            conn.close()
            return redirect(url_for("odrzuvanje.machines"))

        image_name = _save_upload(request.files.get("slika"), MACHINE_IMAGE_FOLDER)
        manual_name = _save_upload(request.files.get("manual_file"), MANUAL_FOLDER)
        cursor.execute(
            """
            INSERT INTO odrzuvanje_masini
            (kod, naziv, linija, lokacija, seriski_broj, proizvoditel, model,
             datum_pustanje, status, servis_interval_dena, servis_interval_casovi,
             sledna_proverka_na, belezka, slika, manual_file, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kod,
                naziv,
                request.form.get("linija", "").strip(),
                request.form.get("lokacija", "").strip(),
                request.form.get("seriski_broj", "").strip(),
                request.form.get("proizvoditel", "").strip(),
                request.form.get("model", "").strip(),
                request.form.get("datum_pustanje", "").strip() or None,
                request.form.get("status", "работи"),
                _safe_int(request.form.get("servis_interval_dena"), 0),
                _safe_int(request.form.get("servis_interval_casovi"), 0),
                request.form.get("sledna_proverka_na", "").strip() or None,
                request.form.get("belezka", "").strip(),
                image_name,
                manual_name,
                session.get("user", ""),
                _now(),
            ),
        )
        masina_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO odrzuvanje_checklists (masina_id, naziv, opis, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (masina_id, "Основна сервисна листа", "Почетна листа за оваа машина.", session.get("user", "")),
        )
        conn.commit()
        conn.close()
        flash(f"Машината „{naziv}“ е успешно креирана.", "success")
        return redirect(url_for("odrzuvanje.machine_detail", machine_id=masina_id))

    query = (request.args.get("q") or "").strip().lower()
    status = (request.args.get("status") or "").strip()
    rows = cursor.execute(
        "SELECT * FROM odrzuvanje_masini ORDER BY naziv, kod"
    ).fetchall()
    machine_rows = []
    for row in rows:
        haystack = " ".join(
            [row["kod"] or "", row["naziv"] or "", row["linija"] or "", row["lokacija"] or "", row["seriski_broj"] or ""]
        ).lower()
        if query and query not in haystack:
            continue
        if status and (row["status"] or "") != status:
            continue
        machine_rows.append(_machine_card(row))
    conn.close()
    return render_template(
        "odrzuvanje_masini.html",
        machines=machine_rows,
        machine_statuses=MASINA_STATUSI,
        query=query,
        selected_status=status,
    )


@odrzuvanje_bp.route("/masini/<int:machine_id>")
@login_required
@admin_or_module_required("odrzuvanje_masini")
def machine_detail(machine_id):
    conn = get_db()
    cursor = conn.cursor()
    machine = cursor.execute(
        "SELECT * FROM odrzuvanje_masini WHERE id = ?",
        (machine_id,),
    ).fetchone()
    if not machine:
        conn.close()
        abort(404)
    checklists = cursor.execute(
        """
        SELECT c.*, COUNT(i.id) AS item_count
        FROM odrzuvanje_checklists c
        LEFT JOIN odrzuvanje_checklist_items i ON i.checklist_id = c.id
        WHERE c.masina_id = ?
        GROUP BY c.id
        ORDER BY c.created_at DESC
        """,
        (machine_id,),
    ).fetchall()
    checklist_items = cursor.execute(
        """
        SELECT i.*, c.naziv AS checklist_naziv
        FROM odrzuvanje_checklist_items i
        JOIN odrzuvanje_checklists c ON c.id = i.checklist_id
        WHERE c.masina_id = ?
        ORDER BY c.naziv, i.redosled, i.id
        """,
        (machine_id,),
    ).fetchall()
    plans = cursor.execute(
        """
        SELECT p.*, c.naziv AS checklist_naziv
        FROM odrzuvanje_planovi p
        LEFT JOIN odrzuvanje_checklists c ON c.id = p.checklist_id
        WHERE p.masina_id = ?
        ORDER BY p.aktivно DESC, p.sledno_izvrsuvanje ASC, p.id DESC
        """.replace("aktivно", "aktivno"),
        (machine_id,),
    ).fetchall()
    recent_orders = cursor.execute(
        """
        SELECT *
        FROM odrzuvanje_nalozi
        WHERE masina_id = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (machine_id,),
    ).fetchall()
    conn.close()
    return render_template(
        "odrzuvanje_masina_detail.html",
        machine=_machine_card(machine),
        checklists=checklists,
        checklist_items=checklist_items,
        plans=plans,
        recent_orders=recent_orders,
        machine_statuses=MASINA_STATUSI,
        plan_types=PLAN_TIPOVI,
    )


@odrzuvanje_bp.route("/masini/<int:machine_id>/edit", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_masini")
def machine_edit(machine_id):
    conn = get_db()
    cursor = conn.cursor()
    machine = cursor.execute("SELECT * FROM odrzuvanje_masini WHERE id = ?", (machine_id,)).fetchone()
    if not machine:
        conn.close()
        abort(404)
    image_name = machine["slika"]
    manual_name = machine["manual_file"]
    new_image = _save_upload(request.files.get("slika"), MACHINE_IMAGE_FOLDER)
    new_manual = _save_upload(request.files.get("manual_file"), MANUAL_FOLDER)
    if new_image:
        image_name = new_image
    if new_manual:
        manual_name = new_manual
    cursor.execute(
        """
        UPDATE odrzuvanje_masini
        SET kod = ?, naziv = ?, linija = ?, lokacija = ?, seriski_broj = ?, proizvoditel = ?,
            model = ?, datum_pustanje = ?, status = ?, servis_interval_dena = ?, servis_interval_casovi = ?,
            posleden_servis_na = ?, sledna_proverka_na = ?, belezka = ?, slika = ?, manual_file = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            request.form.get("kod", "").strip() or machine["kod"],
            request.form.get("naziv", "").strip() or machine["naziv"],
            request.form.get("linija", "").strip(),
            request.form.get("lokacija", "").strip(),
            request.form.get("seriski_broj", "").strip(),
            request.form.get("proizvoditel", "").strip(),
            request.form.get("model", "").strip(),
            request.form.get("datum_pustanje", "").strip() or None,
            request.form.get("status", "работи"),
            _safe_int(request.form.get("servis_interval_dena"), 0),
            _safe_int(request.form.get("servis_interval_casovi"), 0),
            request.form.get("posleden_servis_na", "").strip() or None,
            request.form.get("sledna_proverka_na", "").strip() or None,
            request.form.get("belezka", "").strip(),
            image_name,
            manual_name,
            _now(),
            machine_id,
        ),
    )
    conn.commit()
    conn.close()
    flash("Податоците за машината се успешно ажурирани.", "success")
    return redirect(url_for("odrzuvanje.machine_detail", machine_id=machine_id))


@odrzuvanje_bp.route("/masini/<int:machine_id>/checklist/add", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_masini")
def checklist_add(machine_id):
    conn = get_db()
    cursor = conn.cursor()
    naslov = request.form.get("naslov", "").strip()
    if not naslov:
        flash("Насловот на ставката е задолжителен.", "danger")
        conn.close()
        return redirect(url_for("odrzuvanje.machine_detail", machine_id=machine_id))
    checklist_id = request.form.get("checklist_id", "").strip()
    if not checklist_id:
        cursor.execute(
            """
            INSERT INTO odrzuvanje_checklists (masina_id, naziv, opis, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (machine_id, request.form.get("checklist_naziv", "").strip() or "Сервисна листа", "", session.get("user", "")),
        )
        checklist_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO odrzuvanje_checklist_items (checklist_id, naslov, opis, redosled)
        VALUES (?, ?, ?, ?)
        """,
        (
            int(checklist_id),
            naslov,
            request.form.get("opis", "").strip(),
            _safe_int(request.form.get("redosled"), 0),
        ),
    )
    conn.commit()
    conn.close()
    flash("Чекорот е додаден.", "success")
    return redirect(url_for("odrzuvanje.machine_detail", machine_id=machine_id))


@odrzuvanje_bp.route("/checklist-item/<int:item_id>/delete", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_masini")
def checklist_item_delete(item_id):
    conn = get_db()
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT i.id, c.masina_id
        FROM odrzuvanje_checklist_items i
        JOIN odrzuvanje_checklists c ON c.id = i.checklist_id
        WHERE i.id = ?
        """,
        (item_id,),
    ).fetchone()
    if not row:
        conn.close()
        abort(404)
    cursor.execute("DELETE FROM odrzuvanje_checklist_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash("Чекорот е избришан.", "success")
    return redirect(url_for("odrzuvanje.machine_detail", machine_id=row["masina_id"]))


@odrzuvanje_bp.route("/nalozi", methods=["GET", "POST"])
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def orders():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST":
        masina_id = _safe_int(request.form.get("masina_id"))
        masina = cursor.execute(
            "SELECT * FROM odrzuvanje_masini WHERE id = ?",
            (masina_id,),
        ).fetchone()
        if not masina:
            flash("Избраната машина не постои.", "danger")
            conn.close()
            return redirect(url_for("odrzuvanje.orders"))
        broj = _next_sequence(cursor, "NAL")
        cursor.execute(
            """
            INSERT INTO odrzuvanje_nalozi
            (broj, masina_id, tip, prioritet, status, naslov, opis_defekt, simptom,
             prijavil, dodeleno_na, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                broj,
                masina_id,
                request.form.get("tip", "дефект"),
                request.form.get("prioritet", "среден"),
                "креиран",
                request.form.get("naslov", "").strip(),
                request.form.get("opis_defekt", "").strip(),
                request.form.get("simptom", "").strip(),
                request.form.get("prijavil", "").strip() or session.get("user", ""),
                request.form.get("dodeleno_na", "").strip(),
                session.get("user", ""),
                _now(),
                _now(),
            ),
        )
        nalog_id = cursor.lastrowid
        _append_activity(cursor, nalog_id, f"Налогот е креиран од {session.get('user', '')}.", "create")
        if request.form.get("dodeleno_na", "").strip():
            _append_activity(
                cursor,
                nalog_id,
                f"Налогот е доделен на {request.form.get('dodeleno_na').strip()}.",
                "assign",
            )
        _sync_machine_status(cursor, masina_id)
        conn.commit()
        conn.close()
        flash(f"Работниот налог {broj} е успешно креиран.", "success")
        try:
            notify_new_order(nalog_id)
        except Exception as exc:
            print(f"[ODRZUVANJE NOTIFY] create #{nalog_id}: {exc}")
        return redirect(url_for("odrzuvanje.order_detail", order_id=nalog_id))

    q = (request.args.get("q") or "").strip().lower()
    status = (request.args.get("status") or "").strip()
    machine_id = request.args.get("machine_id", "").strip()
    order_rows = cursor.execute(
        """
        SELECT n.*, m.naziv AS masina_naziv, m.kod AS masina_kod, m.status AS masina_status
        FROM odrzuvanje_nalozi n
        JOIN odrzuvanje_masini m ON m.id = n.masina_id
        WHERE n.status IN (?, ?, ?, ?)
        ORDER BY
          CASE n.prioritet
            WHEN 'критичен' THEN 1
            WHEN 'висок' THEN 2
            WHEN 'среден' THEN 3
            ELSE 4
          END,
          n.created_at DESC
        """,
        (*AKTIVNI_STATUSI,),
    ).fetchall()
    filtered_orders = []
    for row in order_rows:
        haystack = " ".join(
            [row["broj"] or "", row["naslov"] or "", row["masina_naziv"] or "", row["dodeleno_na"] or ""]
        ).lower()
        if q and q not in haystack:
            continue
        if status and row["status"] != status:
            continue
        if machine_id and str(row["masina_id"]) != machine_id:
            continue
        filtered_orders.append(row)

    machines = cursor.execute(
        "SELECT id, kod, naziv, status FROM odrzuvanje_masini ORDER BY naziv, kod"
    ).fetchall()
    assignable_users = _fetch_assignable_users(cursor)
    conn.close()
    return render_template(
        "odrzuvanje_nalozi.html",
        orders=filtered_orders,
        machines=machines,
        assignable_users=assignable_users,
        order_types=NALOG_TIPOVI,
        priorities=NALOG_PRIORITETI,
        statuses=AKTIVNI_STATUSI + ZATVORENI_STATUSI,
        query=q,
        selected_status=status,
        selected_machine=machine_id,
    )


@odrzuvanje_bp.route("/nalozi/<int:order_id>")
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def order_detail(order_id):
    conn = get_db()
    cursor = conn.cursor()
    order = cursor.execute(
        """
        SELECT n.*, m.naziv AS masina_naziv, m.kod AS masina_kod, m.status AS masina_status
        FROM odrzuvanje_nalozi n
        JOIN odrzuvanje_masini m ON m.id = n.masina_id
        WHERE n.id = ?
        """,
        (order_id,),
    ).fetchone()
    if not order:
        conn.close()
        abort(404)
    activities = cursor.execute(
        """
        SELECT *
        FROM odrzuvanje_nalog_aktivnosti
        WHERE nalog_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (order_id,),
    ).fetchall()
    parts = cursor.execute(
        """
        SELECT *
        FROM odrzuvanje_nalog_delovi
        WHERE nalog_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (order_id,),
    ).fetchall()
    linked_procurements = cursor.execute(
        """
        SELECT l.*, r.naslov, r.status, r.kolicina
        FROM odrzuvanje_nalog_nabavki l
        JOIN nabavki_requests r ON r.id = l.nabavka_request_id
        WHERE l.nalog_id = ?
        ORDER BY l.id DESC
        """,
        (order_id,),
    ).fetchall()
    checklists = cursor.execute(
        """
        SELECT c.*, i.id AS item_id, i.naslov AS item_naslov, i.opis AS item_opis, i.redosled
        FROM odrzuvanje_checklists c
        LEFT JOIN odrzuvanje_checklist_items i ON i.checklist_id = c.id
        WHERE c.masina_id = ?
        ORDER BY c.naziv, i.redosled, i.id
        """,
        (order["masina_id"],),
    ).fetchall()
    assignable_users = _fetch_assignable_users(cursor)
    conn.close()
    return render_template(
        "odrzuvanje_nalog_detail.html",
        order=order,
        activities=activities,
        parts=parts,
        linked_procurements=linked_procurements,
        checklists=checklists,
        statuses=AKTIVNI_STATUSI + ZATVORENI_STATUSI,
        assignable_users=assignable_users,
    )


@odrzuvanje_bp.route("/nalozi/<int:order_id>/pdf")
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def order_pdf(order_id):
    conn = get_db()
    cursor = conn.cursor()
    order = cursor.execute(
        """
        SELECT n.*, m.naziv AS masina_naziv, m.kod AS masina_kod, m.status AS masina_status
        FROM odrzuvanje_nalozi n
        JOIN odrzuvanje_masini m ON m.id = n.masina_id
        WHERE n.id = ?
        """,
        (order_id,),
    ).fetchone()
    if not order:
        conn.close()
        abort(404)
    machine = cursor.execute(
        "SELECT * FROM odrzuvanje_masini WHERE id = ?",
        (order["masina_id"],),
    ).fetchone()
    activities = cursor.execute(
        """
        SELECT *
        FROM odrzuvanje_nalog_aktivnosti
        WHERE nalog_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (order_id,),
    ).fetchall()
    parts = cursor.execute(
        """
        SELECT *
        FROM odrzuvanje_nalog_delovi
        WHERE nalog_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (order_id,),
    ).fetchall()
    linked_procurements = cursor.execute(
        """
        SELECT l.*, r.naslov, r.status, r.kolicina
        FROM odrzuvanje_nalog_nabavki l
        JOIN nabavki_requests r ON r.id = l.nabavka_request_id
        WHERE l.nalog_id = ?
        ORDER BY l.id DESC
        """,
        (order_id,),
    ).fetchall()
    conn.close()

    pdf_buffer = _order_pdf_buffer(order, machine, activities, parts, linked_procurements)
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{order['broj'] or 'nalog'}.pdf",
    )


@odrzuvanje_bp.route("/nalozi/<int:order_id>/assign", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def order_assign(order_id):
    conn = get_db()
    cursor = conn.cursor()
    order = cursor.execute("SELECT * FROM odrzuvanje_nalozi WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        abort(404)
    previous_assignee = (order["dodeleno_na"] or "").strip()
    assignee = request.form.get("dodeleno_na", "").strip()
    status = order["status"]
    if assignee and status == "креиран":
        status = "доделен"
    cursor.execute(
        "UPDATE odrzuvanje_nalozi SET dodeleno_na = ?, status = ?, updated_at = ? WHERE id = ?",
        (assignee, status, _now(), order_id),
    )
    _append_activity(cursor, order_id, f"Налогот е доделен на {assignee or 'без одговорно лице'}.", "assign")
    _sync_machine_status(cursor, order["masina_id"])
    conn.commit()
    conn.close()
    flash("Доделувањето е успешно ажурирано.", "success")
    if assignee and assignee != previous_assignee:
        try:
            notify_order_assignment(order_id, assignee, previous_assignee)
        except Exception as exc:
            print(f"[ODRZUVANJE NOTIFY] assign #{order_id}: {exc}")
    return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))


@odrzuvanje_bp.route("/nalozi/<int:order_id>/status", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def order_status(order_id):
    conn = get_db()
    cursor = conn.cursor()
    order = cursor.execute("SELECT * FROM odrzuvanje_nalozi WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        abort(404)
    new_status = request.form.get("status", "").strip() or order["status"]
    start_at = order["pocetok_at"]
    end_at = order["kraj_at"]
    if new_status == "во тек" and not start_at:
        start_at = _now()
    if new_status in ZATVORENI_STATUSI:
        end_at = _now()
    cursor.execute(
        """
        UPDATE odrzuvanje_nalozi
        SET status = ?, resenie = ?, trosok = ?, zastoj_minuti = ?, potvrdil = ?,
            updated_at = ?, pocetok_at = ?, kraj_at = ?
        WHERE id = ?
        """,
        (
            new_status,
            request.form.get("resenie", "").strip(),
            _safe_float(request.form.get("trosok"), 0),
            _safe_int(request.form.get("zastoj_minuti"), 0),
            request.form.get("potvrdil", "").strip(),
            _now(),
            start_at,
            end_at,
            order_id,
        ),
    )
    _append_activity(cursor, order_id, f"Статусот е сменет во „{new_status}“.", "status")
    _sync_machine_status(cursor, order["masina_id"])
    conn.commit()
    conn.close()
    flash("Статусот е успешно ажуриран.", "success")
    return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))


@odrzuvanje_bp.route("/nalozi/<int:order_id>/activity", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def order_activity(order_id):
    conn = get_db()
    cursor = conn.cursor()
    order = cursor.execute("SELECT id FROM odrzuvanje_nalozi WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        abort(404)
    poraka = request.form.get("poraka", "").strip()
    if not poraka:
        flash("Внеси текст за активноста.", "warning")
        conn.close()
        return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))
    _append_activity(cursor, order_id, poraka, request.form.get("tip", "note"))
    cursor.execute("UPDATE odrzuvanje_nalozi SET updated_at = ? WHERE id = ?", (_now(), order_id))
    conn.commit()
    conn.close()
    flash("Активноста е додадена.", "success")
    return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))


@odrzuvanje_bp.route("/nalozi/<int:order_id>/parts", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def order_parts(order_id):
    conn = get_db()
    cursor = conn.cursor()
    order = cursor.execute("SELECT * FROM odrzuvanje_nalozi WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        abort(404)
    opis = request.form.get("opis", "").strip()
    if not opis:
        flash("Описот на делот е задолжителен.", "danger")
        conn.close()
        return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))
    cursor.execute(
        """
        INSERT INTO odrzuvanje_nalog_delovi
        (nalog_id, part_number, opis, kolicina, source_type, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            request.form.get("part_number", "").strip(),
            opis,
            _safe_float(request.form.get("kolicina"), 1),
            request.form.get("source_type", "рачна ставка").strip() or "рачна ставка",
            session.get("user", ""),
        ),
    )
    _append_activity(cursor, order_id, f"Додаден е дел/материјал: {opis}.", "part")
    conn.commit()
    conn.close()
    flash("Делот е додаден.", "success")
    return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))


@odrzuvanje_bp.route("/nalozi/<int:order_id>/nabavka", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_nalozi")
def order_nabavka(order_id):
    conn = get_db()
    cursor = conn.cursor()
    order = cursor.execute("SELECT * FROM odrzuvanje_nalozi WHERE id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        abort(404)
    opis = request.form.get("opis", "").strip()
    if not opis:
        flash("Внеси опис за набавката.", "danger")
        conn.close()
        return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))
    request_id = _create_procurement_request(cursor, order, opis, request.form.get("kolicina", 1))
    cursor.execute(
        """
        INSERT INTO odrzuvanje_nalog_nabavki (nalog_id, nabavka_request_id)
        VALUES (?, ?)
        """,
        (order_id, request_id),
    )
    cursor.execute(
        """
        INSERT INTO odrzuvanje_nalog_delovi
        (nalog_id, opis, kolicina, source_type, nabavka_request_id, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            opis,
            _safe_float(request.form.get("kolicina"), 1),
            "набавка",
            request_id,
            session.get("user", ""),
        ),
    )
    cursor.execute(
        "UPDATE odrzuvanje_nalozi SET status = ?, updated_at = ? WHERE id = ?",
        ("чека дел", _now(), order_id),
    )
    _append_activity(cursor, order_id, f"Креирано е барање за набавка #{request_id} ({opis}).", "procurement")
    _sync_machine_status(cursor, order["masina_id"])
    conn.commit()
    conn.close()
    flash("Креирано е поврзано барање во Набавки.", "success")
    return redirect(url_for("odrzuvanje.order_detail", order_id=order_id))


@odrzuvanje_bp.route("/plan", methods=["GET", "POST"])
@login_required
@admin_or_module_required("odrzuvanje_plan")
def plan():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST":
        masina_id = _safe_int(request.form.get("masina_id"))
        masina = cursor.execute(
            "SELECT id, naziv FROM odrzuvanje_masini WHERE id = ?",
            (masina_id,),
        ).fetchone()
        if not masina:
            flash("Избраната машина не постои.", "danger")
            conn.close()
            return redirect(url_for("odrzuvanje.plan"))

        naziv = request.form.get("naziv", "").strip()
        if not naziv:
            flash("Називот на планот е задолжителен.", "danger")
            conn.close()
            return redirect(url_for("odrzuvanje.plan"))

        cursor.execute(
            """
            INSERT INTO odrzuvanje_planovi
            (masina_id, naziv, tip, interval_dena, interval_casovi, sledno_izvrsuvanje,
             odgovoren, checklist_id, aktivno, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                masina_id,
                naziv,
                request.form.get("tip", "превентивно").strip() or "превентивно",
                _safe_int(request.form.get("interval_dena"), 0),
                _safe_int(request.form.get("interval_casovi"), 0),
                request.form.get("sledno_izvrsuvanje", "").strip() or None,
                request.form.get("odgovoren", "").strip(),
                _safe_int(request.form.get("checklist_id")) or None,
                1 if request.form.get("aktivno") else 0,
                session.get("user", ""),
            ),
        )
        conn.commit()
        conn.close()
        flash(f"Планот за машината „{masina['naziv']}“ е успешно креиран.", "success")
        return redirect(url_for("odrzuvanje.plan"))

    q = (request.args.get("q") or "").strip().lower()
    machine_filter = (request.args.get("machine_id") or "").strip()

    plans = cursor.execute(
        """
        SELECT p.*, m.naziv AS masina_naziv, m.kod AS masina_kod, c.naziv AS checklist_naziv
        FROM odrzuvanje_planovi p
        JOIN odrzuvanje_masini m ON m.id = p.masina_id
        LEFT JOIN odrzuvanje_checklists c ON c.id = p.checklist_id
        ORDER BY
            CASE
                WHEN p.aktivno = 1 AND p.sledno_izvrsuvanje IS NOT NULL AND p.sledno_izvrsuvanje <= ? THEN 0
                WHEN p.aktivno = 1 THEN 1
                ELSE 2
            END,
            p.sledno_izvrsuvanje ASC,
            p.id DESC
        """,
        (_today(),),
    ).fetchall()

    filtered_plans = []
    due_today = 0
    active_count = 0
    inactive_count = 0
    for row in plans:
        haystack = " ".join(
            [
                row["naziv"] or "",
                row["tip"] or "",
                row["masina_naziv"] or "",
                row["masina_kod"] or "",
                row["odgovoren"] or "",
            ]
        ).lower()
        if q and q not in haystack:
            continue
        if machine_filter and str(row["masina_id"]) != machine_filter:
            continue
        if row["aktivno"]:
            active_count += 1
            if row["sledno_izvrsuvanje"] and row["sledno_izvrsuvanje"] <= _today():
                due_today += 1
        else:
            inactive_count += 1
        filtered_plans.append(row)

    machines = cursor.execute(
        "SELECT id, kod, naziv FROM odrzuvanje_masini ORDER BY naziv, kod"
    ).fetchall()
    checklists = cursor.execute(
        """
        SELECT c.id, c.masina_id, c.naziv, m.naziv AS masina_naziv
        FROM odrzuvanje_checklists c
        JOIN odrzuvanje_masini m ON m.id = c.masina_id
        ORDER BY m.naziv, c.naziv
        """
    ).fetchall()
    assignable_users = _fetch_assignable_users(cursor)
    conn.close()
    return render_template(
        "odrzuvanje_plan.html",
        plans=filtered_plans,
        machines=machines,
        checklists=checklists,
        assignable_users=assignable_users,
        plan_types=PLAN_TIPOVI,
        query=q,
        selected_machine=machine_filter,
        due_today=due_today,
        active_count=active_count,
        inactive_count=inactive_count,
        today=_today(),
    )


@odrzuvanje_bp.route("/plan/<int:plan_id>/complete", methods=["POST"])
@login_required
@admin_or_module_required("odrzuvanje_plan")
def plan_complete(plan_id):
    conn = get_db()
    cursor = conn.cursor()
    plan_row = cursor.execute(
        """
        SELECT p.*, m.naziv AS masina_naziv
        FROM odrzuvanje_planovi p
        JOIN odrzuvanje_masini m ON m.id = p.masina_id
        WHERE p.id = ?
        """,
        (plan_id,),
    ).fetchone()
    if not plan_row:
        conn.close()
        abort(404)

    broj = _next_sequence(cursor, "NAL")
    naslov = request.form.get("naslov", "").strip() or f"Планско одржување: {plan_row['naziv']}"
    opis_defekt = f"Плански сервис според планот „{plan_row['naziv']}“."
    cursor.execute(
        """
        INSERT INTO odrzuvanje_nalozi
        (broj, masina_id, tip, prioritet, status, naslov, opis_defekt, simptom,
         prijavil, dodeleno_na, created_by, created_at, updated_at, pocetok_at, kraj_at, resenie)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            broj,
            plan_row["masina_id"],
            plan_row["tip"] or "превентивно",
            "среден",
            "завршен",
            naslov,
            opis_defekt,
            "Извршен плански сервис",
            session.get("user", ""),
            request.form.get("dodeleno_na", "").strip() or plan_row["odgovoren"],
            session.get("user", ""),
            _now(),
            _now(),
            _now(),
            _now(),
            request.form.get("resenie", "").strip() or "Планот е завршен преку планерот за одржување.",
        ),
    )
    nalog_id = cursor.lastrowid
    _append_activity(cursor, nalog_id, f"Налогот е креиран од планот „{plan_row['naziv']}“.", "plan")
    _upsert_plan_next_date(cursor, plan_id, plan_row)
    cursor.execute(
        """
        UPDATE odrzuvanje_masini
        SET posleden_servis_na = ?, sledna_proverka_na = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            _today(),
            cursor.execute("SELECT sledno_izvrsuvanje FROM odrzuvanje_planovi WHERE id = ?", (plan_id,)).fetchone()["sledno_izvrsuvanje"],
            _now(),
            plan_row["masina_id"],
        ),
    )
    _sync_machine_status(cursor, plan_row["masina_id"])
    conn.commit()
    conn.close()
    flash(f"Планот „{plan_row['naziv']}“ е завршен и е запишан во историја.", "success")
    return redirect(url_for("odrzuvanje.order_detail", order_id=nalog_id))


@odrzuvanje_bp.route("/istorija")
@login_required
@admin_or_module_required("odrzuvanje_istorija")
def history():
    conn = get_db()
    cursor = conn.cursor()
    q = (request.args.get("q") or "").strip().lower()
    status = (request.args.get("status") or "").strip()
    order_type = (request.args.get("tip") or "").strip()

    rows = cursor.execute(
        """
        SELECT n.*, m.naziv AS masina_naziv, m.kod AS masina_kod
        FROM odrzuvanje_nalozi n
        JOIN odrzuvanje_masini m ON m.id = n.masina_id
        WHERE n.status IN (?, ?, ?)
        ORDER BY COALESCE(n.kraj_at, n.updated_at, n.created_at) DESC
        """,
        (*ZATVORENI_STATUSI,),
    ).fetchall()

    history_rows = []
    total_cost = 0.0
    total_downtime = 0
    for row in rows:
        haystack = " ".join(
            [
                row["broj"] or "",
                row["naslov"] or "",
                row["masina_naziv"] or "",
                row["masina_kod"] or "",
                row["dodeleno_na"] or "",
            ]
        ).lower()
        if q and q not in haystack:
            continue
        if status and row["status"] != status:
            continue
        if order_type and row["tip"] != order_type:
            continue
        total_cost += _safe_float(row["trosok"], 0)
        total_downtime += _safe_int(row["zastoj_minuti"], 0)
        history_rows.append(row)

    machines = cursor.execute(
        "SELECT id, kod, naziv, status, posleden_servis_na, sledna_proverka_na FROM odrzuvanje_masini ORDER BY naziv, kod"
    ).fetchall()
    conn.close()
    return render_template(
        "odrzuvanje_istorija.html",
        orders=history_rows,
        machines=machines,
        statuses=ZATVORENI_STATUSI,
        order_types=NALOG_TIPOVI,
        query=q,
        selected_status=status,
        selected_type=order_type,
        total_cost=round(total_cost, 2),
        total_downtime=total_downtime,
    )


@odrzuvanje_bp.route("/masini/<int:machine_id>/qr")
@login_required
@admin_or_module_required("odrzuvanje_masini")
def machine_qr(machine_id):
    conn = get_db()
    cursor = conn.cursor()
    machine = cursor.execute(
        "SELECT id, kod, naziv FROM odrzuvanje_masini WHERE id = ?",
        (machine_id,),
    ).fetchone()
    conn.close()
    if not machine:
        abort(404)

    detail_url = url_for("odrzuvanje.machine_detail", machine_id=machine_id, _external=True)
    qr_image = qrcode.make(detail_url)
    buffer = io.BytesIO()
    qr_image.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"{machine['kod'] or 'masina'}-qr.png",
    )
