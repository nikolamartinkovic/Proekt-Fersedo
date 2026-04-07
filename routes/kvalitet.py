import os
import sqlite3
import time
from datetime import datetime

from flask import (
    Blueprint, flash, redirect, render_template,
    request, session, url_for
)
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
    c.drawString(50, y, f"Сериски број: {kontrola['seriski_broj']}")
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


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@kvalitet_bp.route("/")
@login_required
def kvalitet():
    """Главна страница — прикажува само картички за кои корисникот има дозвола."""
    return render_template("kvalitet.html")


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
    sql    = "SELECT id, kamin, seriski_broj, datum, pdf_file, original_pdf_file FROM kvalitet_kontrola"
    params = []
    if query:
        sql   += " WHERE seriski_broj LIKE ? OR kamin LIKE ? OR datum LIKE ?"
        like_q = f"%{query}%"
        params = [like_q, like_q, like_q]
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
        if not kamin:
            flash("Мора да изберете камин!", "danger")
            return render_template("nova_kontrola_forma.html", kamini=kamini, cekori=cekori, selected_kamin=selected_kamin)
        if not seriski_broj:
            flash("Мора да внесете сериски број!", "danger")
            return render_template("nova_kontrola_forma.html", kamini=kamini, cekori=cekori, selected_kamin=selected_kamin)
        try:
            naslov = f"Контрола за {kamin} - {seriski_broj}"
            cursor.execute("""
                INSERT INTO kvalitet_kontrola (kamin, seriski_broj, naslov, datum, username, status)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, 'VO_TEK')
            """, (kamin, seriski_broj, naslov, session["user"]))
            kontrola_id    = cursor.lastrowid
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
            pdf_filename = generiraj_kvalitet_pdf({
                "id": kontrola_id, "kamin": kamin, "seriski_broj": seriski_broj,
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

    return render_template("nova_kontrola_forma.html", kamini=kamini, cekori=cekori, selected_kamin=selected_kamin)


@kvalitet_bp.route("/uredi/<int:kontrola_id>", methods=["GET", "POST"])
@login_required
@module_required("kvalitet_nova")
def uredi_kontrola(kontrola_id):
    UPLOAD_FOLDER = os.path.join(STATIC_FOLDER, "kvalitet_sliki")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    conn      = get_db()
    cursor    = conn.cursor()
    kontrola  = cursor.execute("""
        SELECT id, kamin, seriski_broj, naslov, datum, username, status, pdf_file, original_pdf_file
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
            cursor.execute("UPDATE kvalitet_kontrola SET seriski_broj = ? WHERE id = ?", (nov_seriski, kontrola_id))
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
            cursor.execute("UPDATE kvalitet_kontrola SET status = ? WHERE id = ?", (final_status, kontrola_id))
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
            pdf_filename = generiraj_kvalitet_pdf({
                "id": kontrola_id, "kamin": kontrola["kamin"],
                "seriski_broj": nov_seriski, "datum": datetime.now().strftime("%d-%m-%Y %H:%M")
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
