# routes/ponudi.py
"""
Модул за управување со понуди — целосно независен од набавки.
Полиња: добавувач, цена+валута, рок на испорака, слика/документ, статус, коментари (чат).

Дозволи:
  - Сите најавени корисници: преглед, креирање, коментирање на свои понуди, постави слика на своја понуда
  - Nabavki група + Admin: смена статус, бришење, архивирање, export, коментирање на сите
"""
import os
import time
import json
from datetime import datetime, date
from io import BytesIO

from flask import (
    Blueprint, render_template, request, flash,
    redirect, url_for, jsonify, send_file, session, current_app
)
from PIL import Image as PILImage
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer

from utils.db import get_db
from utils.decorators import login_required, user_has_module

ponudi_bp = Blueprint('ponudi', __name__, url_prefix='/ponudi')


@ponudi_bp.before_request
def ensure_ponudi_access():
    if "user" not in session:
        return None
    endpoint = request.endpoint or ""
    archive_endpoints = {"ponudi.arhiva", "ponudi.export_excel", "ponudi.export_pdf"}
    required_module = "ponudi_arhiva" if endpoint in archive_endpoints else "ponudi"
    if user_has_module(required_module):
        return None
    flash("Немате дозвола за пристап до овој модул.", "danger")
    return redirect(url_for("auth.index"))

_IMG_MAX_SIZE = (1200, 1200)
_IMG_QUALITY  = 72

STATUSI = ["Отворена", "Прифатена", "Одбиена", "Во преговори", "Завршена"]
VALUTI  = ["MKD", "EUR", "USD", "CHF", "GBP"]


# ─────────────────────────────────────────────────────────────
# ПОМОШНИ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────
def _is_manager():
    """Nabavki група + Admin — може да менаџира (статус, бришење, export)."""
    return bool(session.get("is_admin") or session.get("user_group") == "Nabavki")


def _can_comment(ponuda_row):
    """Може да коментира: креаторот, Nabavki група, Admin."""
    return bool(
        session.get("is_admin") or
        session.get("user_group") == "Nabavki" or
        (ponuda_row and ponuda_row["username"] == session.get("user"))
    )


def _save_compressed_image(file_storage, save_dir, filename_base):
    try:
        os.makedirs(save_dir, exist_ok=True)
        final_name = f"{filename_base}.jpg"
        save_path  = os.path.join(save_dir, final_name)
        img = PILImage.open(file_storage)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        img.thumbnail(_IMG_MAX_SIZE, PILImage.Resampling.LANCZOS)
        img.save(save_path, format="JPEG", quality=_IMG_QUALITY, optimize=True)
        return final_name
    except Exception as e:
        print(f"[PONUDI SLIKA] Грешка: {e}")
        return None


def _ensure_tables(cursor):
    """Создај ги табелите ако не постојат."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ponudi (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ponuda_broj      TEXT UNIQUE,
            username         TEXT NOT NULL,
            naslov           TEXT NOT NULL,
            dobavuvac        TEXT NOT NULL,
            cena             REAL,
            valuta           TEXT DEFAULT 'EUR',
            rok_isporaka     TEXT,
            opis             TEXT,
            slika            TEXT,
            status           TEXT DEFAULT 'Отворена',
            datum_kreiranje  TEXT DEFAULT CURRENT_TIMESTAMP,
            datum_vaznost    TEXT,
            arhivirano_od    TEXT,
            arhivirano_na    TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ponudi_comments (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ponuda_id INTEGER NOT NULL,
            user      TEXT,
            comment   TEXT,
            slika     TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ponudi_archive (
            id              INTEGER PRIMARY KEY,
            ponuda_broj     TEXT,
            username        TEXT,
            naslov          TEXT,
            dobavuvac       TEXT,
            cena            REAL,
            valuta          TEXT,
            rok_isporaka    TEXT,
            opis            TEXT,
            slika           TEXT,
            status          TEXT,
            datum_kreiranje TEXT,
            datum_vaznost   TEXT,
            arhivirano_od   TEXT,
            arhivirano_na   TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ponudi_archive_comments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_ponuda_id INTEGER NOT NULL,
            user            TEXT,
            comment         TEXT,
            slika           TEXT,
            timestamp       TEXT
        )
    """)
    # Секвенца за Pon001, Pon002...
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pon_sequence (
            id       INTEGER PRIMARY KEY,
            last_num INTEGER DEFAULT 0
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO pon_sequence (id, last_num) VALUES (1, 0)")


def _next_ponuda_broj(cursor):
    cursor.execute("UPDATE pon_sequence SET last_num = last_num + 1 WHERE id = 1")
    row = cursor.execute("SELECT last_num FROM pon_sequence WHERE id = 1").fetchone()
    return f"Pon{row['last_num']:03d}"


# ─────────────────────────────────────────────────────────────
# ГЛАВНА СТРАНИЦА
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/", methods=["GET", "POST"])
@login_required
def ponudi():
    conn   = get_db()
    cursor = conn.cursor()
    _ensure_tables(cursor)
    conn.commit()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "kreiraj":
            naslov       = request.form.get("naslov", "").strip()
            dobavuvac    = request.form.get("dobavuvac", "").strip()
            cena_str     = request.form.get("cena", "").strip()
            valuta       = request.form.get("valuta", "EUR").strip()
            rok_isporaka = request.form.get("rok_isporaka", "").strip()
            datum_vaznost= request.form.get("datum_vaznost", "").strip()
            opis         = request.form.get("opis", "").strip()
            chat_comment = request.form.get("chat_comment", "").strip()

            slika_file      = request.files.get("slika")
            camera_filename = request.form.get("camera_slika_filename", "").strip()

            if not naslov or not dobavuvac:
                flash("Наслов и добавувач се задолжителни!", "error")
                conn.close()
                return redirect(url_for("ponudi.ponudi"))

            cena = None
            if cena_str:
                try:
                    cena = float(cena_str.replace(",", "."))
                except ValueError:
                    flash("Цената мора да биде број!", "error")
                    conn.close()
                    return redirect(url_for("ponudi.ponudi"))

            save_dir       = os.path.join(current_app.config['STATIC_FOLDER'], "ponudi")
            slika_filename = None
            filename_base  = f"pon_{int(time.time())}_{session['user']}"

            if slika_file and slika_file.filename:
                slika_filename = _save_compressed_image(slika_file, save_dir, filename_base)
            elif camera_filename:
                from utils.config import POZICII_FOLDER
                src = os.path.join(POZICII_FOLDER, camera_filename)
                if os.path.exists(src):
                    dst_name = f"{filename_base}_cam.jpg"
                    dst      = os.path.join(save_dir, dst_name)
                    os.makedirs(save_dir, exist_ok=True)
                    try:
                        img = PILImage.open(src)
                        if img.mode in ("RGBA", "P", "LA"):
                            img = img.convert("RGB")
                        img.thumbnail(_IMG_MAX_SIZE, PILImage.Resampling.LANCZOS)
                        img.save(dst, format="JPEG", quality=_IMG_QUALITY, optimize=True)
                        slika_filename = dst_name
                    except Exception as e:
                        print(f"[PONUDI CAM] {e}")

            try:
                cursor.execute("""
                    INSERT INTO ponudi
                        (username, naslov, dobavuvac, cena, valuta, rok_isporaka,
                         datum_vaznost, opis, slika, status, datum_kreiranje)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Отворена', CURRENT_TIMESTAMP)
                """, (session["user"], naslov, dobavuvac, cena, valuta,
                      rok_isporaka, datum_vaznost, opis, slika_filename))
                conn.commit()
                new_id      = cursor.lastrowid
                ponuda_broj = _next_ponuda_broj(cursor)
                cursor.execute("UPDATE ponudi SET ponuda_broj=? WHERE id=?", (ponuda_broj, new_id))
                conn.commit()

                if chat_comment:
                    cursor.execute("""
                        INSERT INTO ponudi_comments (ponuda_id, user, comment)
                        VALUES (?, ?, ?)
                    """, (new_id, session["user"], chat_comment))
                    conn.commit()

                now_local = datetime.now().strftime("%d-%m-%Y %H:%M")
                flash(f"Понудата е креирана со број: <strong>{ponuda_broj}</strong> на {now_local}!", "success")

            except Exception as e:
                flash(f"Грешка при креирање: {str(e)}", "danger")
                conn.rollback()

        conn.close()
        return redirect(url_for("ponudi.ponudi", filter=request.args.get("filter", "all")))

    # GET
    filter_type   = request.args.get("filter", "all")
    status_filter = request.args.get("status", "")

    query  = "SELECT * FROM ponudi WHERE 1=1"
    params = []
    if status_filter:
        query += " AND status=?"
        params.append(status_filter)
    query += " ORDER BY id DESC"

    rows = cursor.execute(query, params).fetchall()

    ponudi_list = []
    for row in rows:
        r = dict(row)
        r["comments"] = cursor.execute("""
            SELECT user, comment, slika, timestamp FROM ponudi_comments
            WHERE ponuda_id=? ORDER BY timestamp ASC
        """, (r["id"],)).fetchall()
        ponudi_list.append(r)

    conn.close()
    return render_template(
        "ponudi.html",
        ponudi=ponudi_list,
        statusi=STATUSI,
        valuti=VALUTI,
        today=date.today().isoformat(),
        filter_type=filter_type,
        status_filter=status_filter,
        is_manager=_is_manager(),
    )


# ─────────────────────────────────────────────────────────────
# СМЕНИ СТАТУС
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/update_status/<int:ponuda_id>/<string:new_status>")
@login_required
def update_status(ponuda_id, new_status):
    if not _is_manager():
        flash("Немате дозвола!", "danger")
        return redirect(url_for("ponudi.ponudi"))

    if new_status not in STATUSI:
        flash("Невалиден статус!", "danger")
        return redirect(url_for("ponudi.ponudi"))

    conn   = get_db()
    cursor = conn.cursor()
    _ensure_tables(cursor)

    ponuda = cursor.execute("SELECT * FROM ponudi WHERE id=?", (ponuda_id,)).fetchone()
    if not ponuda:
        flash("Понудата не постои!", "danger")
        conn.close()
        return redirect(url_for("ponudi.ponudi"))

    try:
        if new_status == "Завршена":
            cursor.execute("""
                INSERT OR REPLACE INTO ponudi_archive
                    (id, ponuda_broj, username, naslov, dobavuvac, cena, valuta,
                     rok_isporaka, opis, slika, status, datum_kreiranje,
                     datum_vaznost, arhivirano_od, arhivirano_na)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """, (ponuda["id"], ponuda["ponuda_broj"], ponuda["username"],
                  ponuda["naslov"], ponuda["dobavuvac"], ponuda["cena"],
                  ponuda["valuta"], ponuda["rok_isporaka"], ponuda["opis"],
                  ponuda["slika"], new_status, ponuda["datum_kreiranje"],
                  ponuda["datum_vaznost"], session["user"]))

            comments = cursor.execute("""
                SELECT user, comment, slika, timestamp FROM ponudi_comments
                WHERE ponuda_id=? ORDER BY timestamp ASC
            """, (ponuda_id,)).fetchall()
            for c in comments:
                cursor.execute("""
                    INSERT INTO ponudi_archive_comments
                        (archive_ponuda_id, user, comment, slika, timestamp)
                    VALUES (?,?,?,?,?)
                """, (ponuda_id, c["user"], c["comment"], c["slika"], c["timestamp"]))

            cursor.execute("DELETE FROM ponudi_comments WHERE ponuda_id=?", (ponuda_id,))
            cursor.execute("DELETE FROM ponudi WHERE id=?", (ponuda_id,))
            flash(f'Понудата {ponuda["ponuda_broj"]} е архивирана!', "success")
        else:
            cursor.execute("UPDATE ponudi SET status=? WHERE id=?", (new_status, ponuda_id))
            flash(f"Статусот е сменет на {new_status}!", "success")

        conn.commit()
    except Exception as e:
        flash(f"Грешка: {str(e)}", "danger")
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for("ponudi.ponudi"))


# ─────────────────────────────────────────────────────────────
# ДОДАЈ КОМЕНТАР
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/add_comment/<int:ponuda_id>", methods=["POST"])
@login_required
def add_comment(ponuda_id):
    conn   = get_db()
    cursor = conn.cursor()
    _ensure_tables(cursor)

    comment    = request.form.get("comment", "").strip()
    slika_file = request.files.get("chat_slika")

    ponuda_row = cursor.execute("SELECT username FROM ponudi WHERE id=?", (ponuda_id,)).fetchone()
    if not _can_comment(ponuda_row):
        flash("Немате дозвола да коментирате!", "danger")
        conn.close()
        return redirect(url_for("ponudi.ponudi"))

    if not comment and (not slika_file or not slika_file.filename):
        flash("Коментарот е празен!", "error")
        conn.close()
        return redirect(url_for("ponudi.ponudi"))

    try:
        chat_slika_filename = None
        if slika_file and slika_file.filename:
            save_dir      = os.path.join(current_app.config['STATIC_FOLDER'], "ponudi_chat")
            filename_base = f"chat_{ponuda_id}_{int(time.time())}_{session['user']}"
            chat_slika_filename = _save_compressed_image(slika_file, save_dir, filename_base)

        cursor.execute(
            "INSERT INTO ponudi_comments (ponuda_id, user, comment, slika) VALUES (?,?,?,?)",
            (ponuda_id, session["user"], comment, chat_slika_filename)
        )
        conn.commit()
        flash("Коментарот е успешно додаден!", "success")
    except Exception as e:
        flash(f"Грешка: {str(e)}", "danger")
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for("ponudi.ponudi", filter=request.args.get("filter", "all")))


# ─────────────────────────────────────────────────────────────
# GET COMMENTS (AJAX)
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/comments/<int:ponuda_id>")
@login_required
def get_comments(ponuda_id):
    conn     = get_db()
    cursor   = conn.cursor()
    _ensure_tables(cursor)
    comments = cursor.execute("""
        SELECT user, comment, slika, timestamp FROM ponudi_comments
        WHERE ponuda_id=? ORDER BY timestamp ASC
    """, (ponuda_id,)).fetchall()
    conn.close()
    return jsonify([dict(c) for c in comments])


# ─────────────────────────────────────────────────────────────
# АРХИВА  ← ПОПРАВЕНО: main.dashboard → admin.dashboard
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/arhiva")
@login_required
def arhiva():
    if not _is_manager():
        flash("Немате дозвола!", "danger")
        return redirect(url_for("admin.dashboard"))

    conn   = get_db()
    cursor = conn.cursor()
    _ensure_tables(cursor)
    conn.commit()  # ← ДОДАЈ ОВА — треба commit после _ensure_tables

    archived_raw = cursor.execute(
        "SELECT * FROM ponudi_archive ORDER BY arhivirano_na DESC"
    ).fetchall()

    archived = []
    for row in archived_raw:
        r = dict(row)
        r["comments"] = cursor.execute("""
            SELECT user, comment, slika, timestamp FROM ponudi_archive_comments
            WHERE archive_ponuda_id=? ORDER BY timestamp ASC
        """, (r["id"],)).fetchall()
        archived.append(r)

    conn.close()
    return render_template("ponudi_arhiva.html", archived=archived)


# ─────────────────────────────────────────────────────────────
# ИЗБРИШИ ИЗБРАНИ
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/delete_selected", methods=["POST"])
@login_required
def delete_selected():
    if not _is_manager():
        flash("Немате дозвола!", "danger")
        return redirect(url_for("ponudi.ponudi"))

    selected_ids = request.form.getlist("selected_ids")
    if not selected_ids:
        flash("Нема избрани понуди за бришење!", "warning")
        return redirect(url_for("ponudi.ponudi"))

    try:
        conn         = get_db()
        cursor       = conn.cursor()
        _ensure_tables(cursor)
        placeholders = ",".join("?" for _ in selected_ids)
        cursor.execute(f"DELETE FROM ponudi_comments WHERE ponuda_id IN ({placeholders})", selected_ids)
        cursor.execute(f"DELETE FROM ponudi WHERE id IN ({placeholders})", selected_ids)
        count = cursor.rowcount
        conn.commit()
        flash(f"Успешно избришани {count} понуди!", "success")
    except Exception as e:
        flash(f"Грешка при бришење: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for("ponudi.ponudi"))


# ─────────────────────────────────────────────────────────────
# ПОСТАВИ СЛИКА НА ПОСТОЕЧКА ПОНУДА
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/upload_slika/<int:ponuda_id>", methods=["POST"])
@login_required
def upload_slika(ponuda_id):
    conn   = get_db()
    cursor = conn.cursor()
    _ensure_tables(cursor)

    ponuda = cursor.execute("SELECT * FROM ponudi WHERE id=?", (ponuda_id,)).fetchone()
    if not ponuda:
        flash("Понудата не постои!", "danger")
        conn.close()
        return redirect(url_for("ponudi.ponudi"))

    if not (_is_manager() or ponuda["username"] == session.get("user")):
        flash("Немате дозвола!", "danger")
        conn.close()
        return redirect(url_for("ponudi.ponudi"))

    if ponuda["slika"]:
        flash("Оваа понуда веќе има прикачена слика!", "warning")
        conn.close()
        return redirect(url_for("ponudi.ponudi"))

    slika_file = request.files.get("nova_slika")
    if not slika_file or not slika_file.filename:
        flash("Нема избрана слика!", "warning")
        conn.close()
        return redirect(url_for("ponudi.ponudi"))

    try:
        save_dir      = os.path.join(current_app.config['STATIC_FOLDER'], "ponudi")
        filename_base = f"pon_{ponuda_id}_{int(time.time())}_{session['user']}"
        slika_filename = _save_compressed_image(slika_file, save_dir, filename_base)

        if not slika_filename:
            flash("Грешка при зачувување на сликата!", "danger")
            conn.close()
            return redirect(url_for("ponudi.ponudi"))

        cursor.execute("UPDATE ponudi SET slika=? WHERE id=?", (slika_filename, ponuda_id))
        conn.commit()
        flash(f"Сликата е успешно прикачена на понуда {ponuda['ponuda_broj']}!", "success")
    except Exception as e:
        flash(f"Грешка: {str(e)}", "danger")
        conn.rollback()
    finally:
        conn.close()

    return redirect(url_for("ponudi.ponudi", filter=request.args.get("filter", "all")))


# ─────────────────────────────────────────────────────────────
# EXPORT EXCEL
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/export/excel")
@login_required
def export_excel():
    if not _is_manager():
        flash("Немате дозвола!", "danger")
        return redirect(url_for("ponudi.ponudi"))

    conn   = get_db()
    cursor = conn.cursor()
    _ensure_tables(cursor)
    rows = cursor.execute("SELECT * FROM ponudi ORDER BY id DESC").fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Понуди"
    ws.append(["Број", "Корисник", "Наслов", "Добавувач", "Цена", "Валута",
               "Рок испорака", "Статус", "Датум на креирање", "Важи до"])
    for r in rows:
        ws.append([r["ponuda_broj"], r["username"], r["naslov"], r["dobavuvac"],
                   r["cena"], r["valuta"], r["rok_isporaka"], r["status"],
                   r["datum_kreiranje"], r["datum_vaznost"]])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"ponudi_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    )


# ─────────────────────────────────────────────────────────────
# EXPORT PDF
# ─────────────────────────────────────────────────────────────
@ponudi_bp.route("/export/pdf")
@login_required
def export_pdf():
    if not _is_manager():
        flash("Немате дозвола!", "danger")
        return redirect(url_for("ponudi.ponudi"))

    conn   = get_db()
    cursor = conn.cursor()
    _ensure_tables(cursor)
    rows = cursor.execute("SELECT * FROM ponudi ORDER BY id DESC").fetchall()
    conn.close()

    buffer = BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    data   = [["Број", "Наслов", "Добавувач", "Цена", "Валута", "Статус"]]
    for r in rows:
        cena_str = f"{r['cena']:,.2f}" if r["cena"] is not None else "—"
        data.append([r["ponuda_broj"], r["naslov"], r["dobavuvac"],
                     cena_str, r["valuta"], r["status"]])

    table = Table(data, colWidths=[40, 80, 70, 50, 30, 60])
    table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.lightgrey),
    ]))
    doc.build([
        Paragraph("Листа на понуди", styles["Heading1"]),
        Spacer(1, 12),
        table
    ])
    buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=f"ponudi_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
