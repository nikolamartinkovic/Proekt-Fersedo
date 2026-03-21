# routes/artikli.py
import os
import glob
import time
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session
from werkzeug.utils import secure_filename
from utils.db import get_db
from utils.decorators import login_required, admin_required
import pandas as pd
import sqlite3

artikli_bp = Blueprint('artikli', __name__, url_prefix='/artikli')

# ─────────────────────────────────────────────────────────────
# API за live preview на Part Number
# ─────────────────────────────────────────────────────────────
@artikli_bp.route("/get_artikal/<pn>")
@login_required
def get_artikal(pn):
    conn = get_db()
    cursor = conn.cursor()
    pn_normalized = pn.upper().strip()
    result = cursor.execute("""
        SELECT id, part_number, ime
        FROM parts
        WHERE UPPER(part_number) = ?
        LIMIT 1
    """, (pn_normalized,)).fetchone()
    conn.close()
    if result:
        return jsonify({
            'success': True,
            'id': result['id'],
            'pn': result['part_number'],
            'ime': result['ime'] or 'Без име'
        })
    return jsonify({'success': False, 'message': 'Артиклот не е најден'}), 404


# ─────────────────────────────────────────────────────────────
# ПРЕГЛЕД НА АРТИКЛИ
# ─────────────────────────────────────────────────────────────
@artikli_bp.route("/", methods=["GET", "POST"])
@login_required
def artikli():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST" and session.get("is_admin"):
        if request.form.get("action") == "delete":
            selected_ids = request.form.getlist("selected_ids")
            if selected_ids:
                placeholders = ",".join("?" for _ in selected_ids)
                cursor.execute(f"DELETE FROM parts WHERE id IN ({placeholders})", selected_ids)
                conn.commit()
                flash(f"Избришани {len(selected_ids)} артикли!", "success")
            else:
                flash("Нема избрани артикли", "warning")

    if session.get("is_admin"):
        artikli_list = cursor.execute("""
            SELECT id, part_number, ime, kamin, slika, vid_artikal, odobren
            FROM parts
            ORDER BY part_number
        """).fetchall()
    else:
        artikli_list = cursor.execute("""
            SELECT id, part_number, ime, kamin, slika, vid_artikal, odobren
            FROM parts
            WHERE odobren = 1
            ORDER BY part_number
        """).fetchall()

    conn.close()

    return render_template("artikli.html", artikli=artikli_list, is_admin=session.get("is_admin"))


# ─────────────────────────────────────────────────────────────
# ДОДАДИ НОВ АРТИКЛ
# ─────────────────────────────────────────────────────────────
@artikli_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    conn = get_db()
    cursor = conn.cursor()
    
    # Земи ги камините за drop-down (тука е во ред да се користи conn)
    kamini = cursor.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()
    # НЕ ЗАТВОРАЈ conn овде!

    if request.method == "POST":
        part_number = request.form.get("part_number", "").strip().upper()
        ime = request.form.get("ime", "").strip()
        kamin = request.form.get("kamin")
        vid_artikal = request.form.get("vid_artikal")
        slika = request.files.get("slika")

        if not part_number or not ime or not kamin or not vid_artikal:
            flash("Пополни ги сите задолжителни полиња!", "danger")
        else:
            slika_filename = None
            if slika and slika.filename:
                ext = os.path.splitext(slika.filename)[1].lower() or ".png"
                slika_filename = f"{part_number}{ext}"
                os.makedirs("static/parts", exist_ok=True)
                slika.save(os.path.join("static/parts", slika_filename))

            try:
                cursor.execute("""
                    INSERT INTO parts (part_number, ime, kamin, slika, vid_artikal, odobren)
                    VALUES (?, ?, ?, ?, ?, 0)
                """, (part_number, ime, kamin, slika_filename, vid_artikal))
                conn.commit()
                flash(f"Артиклот {part_number} - {ime} е креиран!", "success")
                return redirect(url_for("artikli.artikli"))
            except sqlite3.IntegrityError:
                flash("Part Number веќе постои!", "danger")
            except Exception as e:
                flash(f"Грешка: {str(e)}", "danger")
            # НЕ ЗАТВОРАЈ conn овде – остави го отворен или користи with (подолу)

    # Ако сакаш да биде почисто, можеш да го затвориш на крајот од функцијата
    # conn.close()   # ← опционално, но подобро е да не го затвораш рачно

    return render_template("artikli_add.html", kamini=kamini)


# ─────────────────────────────────────────────────────────────
# ЕДИТ АРТИКЛ
# ─────────────────────────────────────────────────────────────
@artikli_bp.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    conn = get_db()
    cursor = conn.cursor()
    art = cursor.execute("SELECT * FROM parts WHERE id = ?", (id,)).fetchone()
    if not art:
        flash("Артиклот не постои!", "danger")
        conn.close()
        return redirect(url_for("artikli.artikli"))

    kamini = cursor.execute("SELECT ime FROM kamini ORDER BY ime").fetchall()

    if request.method == "POST":
        is_admin = session.get("is_admin")
        if is_admin:
            part_number = request.form.get("part_number", "").strip().upper()
            kamin = request.form.get("kamin")
            vid_artikal = request.form.get("vid_artikal")
        else:
            part_number = art["part_number"]
            kamin = art["kamin"]
            vid_artikal = art["vid_artikal"]

        slika_filename = art["slika"]
        slika = request.files.get("slika")
        if slika and slika.filename:
            ext = os.path.splitext(slika.filename)[1].lower() or ".png"
            timestamp = int(time.time() * 1000)
            slika_filename = f"{part_number}_{timestamp}{ext}"
            parts_dir = os.path.join("static", "parts")
            os.makedirs(parts_dir, exist_ok=True)
            slika.save(os.path.join(parts_dir, slika_filename))

        try:
            cursor.execute("""
                UPDATE parts SET part_number=?, kamin=?, slika=?, vid_artikal=?
                WHERE id=?
            """, (part_number, kamin, slika_filename, vid_artikal, id))
            conn.commit()
            flash("Артиклот е успешно ажуриран!", "success")
        except sqlite3.IntegrityError:
            flash("Part Number веќе постои!", "danger")
        except Exception as e:
            flash(f"Грешка: {str(e)}", "danger")
        finally:
            conn.close()

        return redirect(url_for("artikli.artikli"))

    conn.close()
    return render_template("artikli_edit.html", art=art, kamini=kamini, is_admin=session.get("is_admin"))


# ─────────────────────────────────────────────────────────────
# ОДОБРИ АРТИКЛ
# ─────────────────────────────────────────────────────────────
@artikli_bp.route("/odobri/<int:id>", methods=["POST"])
@login_required
@admin_required
def odobri(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE parts SET odobren = 1 WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Артиклот е одобрен!", "success")
    return redirect(url_for("artikli.artikli"))


# ─────────────────────────────────────────────────────────────
# ИМПОРТ ОД EXCEL + СЛИКИ
# ─────────────────────────────────────────────────────────────
@artikli_bp.route("/import", methods=["GET", "POST"])
@login_required
@admin_required
def import_artikli():
    if request.method == "POST":
        excel_file = request.files.get("excel_file")
        images = request.files.getlist("images")

        if not excel_file or not excel_file.filename.endswith((".xlsx", ".xls")):
            flash("Мора да upload-неш Excel фајл!", "danger")
            return redirect(url_for("artikli.import_artikli"))

        try:
            df = pd.read_excel(excel_file, engine="openpyxl")
            df.columns = df.columns.str.strip().str.lower()
            required = ["part number", "kamin", "slika"]
            if not all(col in df.columns for col in required):
                flash("Excel-от мора да има колони: Part number, Kamin, Slika", "danger")
                return redirect(url_for("artikli.import_artikli"))

            conn = get_db()
            cursor = conn.cursor()
            imported = updated = 0
            for img in images:
                if not img.filename:
                    continue
                ext = os.path.splitext(img.filename)[1].lower() or ".png"
                pn = os.path.splitext(img.filename)[0].strip().upper()
                if not pn:
                    continue
                filename = f"{pn}{ext}"
                img.save(os.path.join("static", "parts", filename))

                row = df[df["part number"].astype(str).str.strip().str.upper() == pn]
                kamin = str(row.iloc[0]["kamin"]).strip() if not row.empty else "default_kamin"

                if cursor.execute("SELECT id FROM parts WHERE part_number=?", (pn,)).fetchone():
                    cursor.execute("UPDATE parts SET kamin=?, slika=? WHERE part_number=?", (kamin, filename, pn))
                    updated += 1
                else:
                    cursor.execute("INSERT INTO parts (part_number, kamin, slika) VALUES (?,?,?)", (pn, kamin, filename))
                    imported += 1

            conn.commit()
            conn.close()
            flash(f"Додадени {imported}, ажурирани {updated} артикли!", "success")
        except Exception as e:
            flash(f"Грешка при импорт: {str(e)}", "danger")

        return redirect(url_for("artikli.artikli"))

    return render_template("artikli_import.html")