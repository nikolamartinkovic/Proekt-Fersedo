import sqlite3
import os
import time
from datetime import datetime, date
from collections import defaultdict
from io import BytesIO
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, send_file, session
from utils.db import get_db
from utils.decorators import login_required, admin_required
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

zalihi_bp = Blueprint('zalihi', __name__, url_prefix='/zalihi')

# Помошна функција за недела
def get_nedela(datum_str):
    try:
        dt = datetime.strptime(str(datum_str)[:10], '%Y-%m-%d')
        week = dt.isocalendar()[1]
        return f"КН{week:02d}"
    except:
        return "КН--"


def _ensure_profakturi_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profakturi (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            broj            TEXT    NOT NULL,
            datum           TEXT    NOT NULL,
            username        TEXT    NOT NULL,
            status          TEXT    DEFAULT 'pending',
            datum_odobrena  TEXT,
            odobrena_od     TEXT,
            napomena        TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profaktura_stavki (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            profaktura_id INTEGER NOT NULL,
            artikl_id     INTEGER NOT NULL,
            pn            TEXT    NOT NULL,
            ime           TEXT,
            kolicina      INTEGER NOT NULL
        )
    """)


# ─────────────────────────────────────────────────────────────
# API за live preview на Part Number
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/get_artikal/<pn>")
@login_required
def get_artikal(pn):
    try:
        print(f"🔍 DEBUG: get_artikal called with pn='{pn}'")
        conn = get_db()
        cursor = conn.cursor()
        pn_normalized = pn.upper().strip()
        print(f"🔍 Normalized PN: '{pn_normalized}'")
        result = cursor.execute("""
            SELECT id, part_number, ime
            FROM parts
            WHERE UPPER(part_number) = ?
            LIMIT 1
        """, (pn_normalized,)).fetchone()
        print(f"🔍 Result: {result}")
        conn.close()
        if result:
            result_dict = dict(result) if hasattr(result, 'keys') else result
            print(f"✅ УСПЕШНО ПРОНАЈДЕНО: {result_dict}")
            return jsonify({
                'success': True,
                'id': result_dict['id'],
                'pn': result_dict['part_number'],
                'ime': result_dict['ime'] if result_dict['ime'] else 'Без назив'
            })
        print(f"⚠️ НЕ ПРОНАЈДЕНО")
        return jsonify({'success': False}), 404
    except Exception as e:
        print(f"❌ ГРЕШКА: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────
# ГЛАВНА СТРАНИЦА – САМО КАРТИЧКИ
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/", methods=["GET"])
@login_required
def zalihi():
    return render_template("zalihi.html")


# ─────────────────────────────────────────────────────────────
# ДОДАДИ ЗАЛИХА
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/dodadi", methods=["GET", "POST"])
@login_required
def dodadi():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST":
        artikl_id = request.form.get("artikl_id")
        try:
            kolicina = int(request.form.get("kolicina", 0))
        except:
            kolicina = 0
        try:
            cena = float(request.form.get("cena", 0))
        except:
            cena = 0.0
        datum = request.form.get("datum") or datetime.now().strftime("%Y-%m-%d")
        plateno_str = request.form.get("plateno", "0")
        plateno = 1 if plateno_str == "1" else 0
        zabeleska = request.form.get("zabeleska", "").strip()

        print(f"🔍 DEBUG: artikl_id={artikl_id}, plateno={plateno}, kolicina={kolicina}")

        if not artikl_id or kolicina <= 0:
            flash("Внеси валиден артикл и количина!", "danger")
        else:
            try:
                cursor.execute("""
                    INSERT INTO zaliha_dodadi (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (artikl_id, kolicina, cena, datum, plateno, session["user"], zabeleska))

                cursor.execute("""
    INSERT INTO zaliha_dodadi_log (datum, username, pn, ime, kolicina, tip, zabeleska)
    SELECT ?, ?, p.part_number, COALESCE(NULLIF(TRIM(p.ime), ''), 'Непознат артикл'), ?, ?, ?
    FROM parts p WHERE p.id = ?
""", (datum, session["user"], kolicina, "Додавање", zabeleska, artikl_id))

                conn.commit()
                flash("Успешно додадено во залиха!", "success")
            except Exception as e:
                print(f"❌ Грешка: {e}")
                flash(f"Грешка при додавање: {str(e)}", "danger")
                conn.rollback()

        conn.close()
        return redirect(url_for("zalihi.izvoz"))

    artikli = cursor.execute("SELECT id, part_number, ime FROM parts ORDER BY part_number").fetchall()
    conn.close()
    return render_template("zalihi_dodadi.html", artikli=artikli, today=date.today().isoformat())


# ─────────────────────────────────────────────────────────────
# ПРЕФРЛАЊЕ НА ЗАЛИХА (платена → неплатена или обратно)
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/premesti", methods=["POST"])
@login_required
def premesti():
    conn = None
    try:
        data = request.get_json()
        print(f"\n🔍 ПРЕМЕСТИ: Приспеал JSON: {data}")

        artikl_id = int(data.get("artikl_id", 0))
        pn = data.get("pn", "").strip().upper()
        kolicina = int(data.get("kolicina", 0))
        od_plateno = int(data.get("od_plateno", 0))
        na_plateno = 1 - od_plateno
        zabeleska = data.get("zabeleska", "Префрлање од корисник").strip()

        if artikl_id <= 0 or kolicina <= 0:
            return jsonify({'success': False, 'message': 'Невалиден ID или количина'}), 400

        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        row = cursor.execute("""
            SELECT COALESCE(SUM(kolicina), 0) AS total
            FROM zaliha_dodadi
            WHERE artikl_id = ? AND plateno = ?
        """, (artikl_id, od_plateno)).fetchone()

        current = row['total'] if row else 0

        if kolicina > current:
            conn.close()
            return jsonify({'success': False, 'message': f'Немате доволно залиха. Расположливо: {current}'}), 400

        remaining = kolicina
        rows = cursor.execute("""
            SELECT id, kolicina FROM zaliha_dodadi
            WHERE artikl_id = ? AND plateno = ? AND kolicina > 0
            ORDER BY datum ASC
        """, (artikl_id, od_plateno)).fetchall()

        for row_data in rows:
            if remaining <= 0:
                break
            row_id = row_data['id']
            row_kolicina = int(row_data['kolicina'])

            if row_kolicina <= remaining:
                cursor.execute("DELETE FROM zaliha_dodadi WHERE id = ?", (row_id,))
                remaining -= row_kolicina
            else:
                cursor.execute("UPDATE zaliha_dodadi SET kolicina = kolicina - ? WHERE id = ?", (remaining, row_id))
                remaining = 0

        cursor.execute("""
            INSERT INTO zaliha_dodadi (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
            VALUES (?, ?, 0, ?, ?, ?, ?)
        """, (artikl_id, kolicina, datetime.now().strftime("%Y-%m-%d"), na_plateno, session["user"], zabeleska))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Префрлено {kolicina} единици од {"платена" if od_plateno else "неплатена"} во {"платена" if na_plateno else "неплатена"}!'
        })

    except Exception as e:
        print(f"❌ КРИТИЧНА ГРЕШКА: {e}")
        import traceback
        traceback.print_exc()
        if conn is not None:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'message': f'Грешка: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────
# ИЗВОЗ  →  запишува во pending (НЕ ги брише залихите веднаш)
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/izvoz", methods=["GET", "POST"])
@login_required
def izvoz():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            data = request.get_json()
            artikli = data.get('artikli', [])

            print(f"🔍 DEBUG: Приспеал POST со JSON")
            print(f"🔍 Артикли: {artikli}")

            total_pending = 0
            errors = []

            for art in artikli:
                try:
                    art_id = int(art.get('id', 0))
                    pn = str(art.get('pn', '')).strip()
                    izvoz_platena = int(art.get('platena', 0))
                    izvoz_neplatena = int(art.get('neplatena', 0))

                    if izvoz_platena <= 0 and izvoz_neplatena <= 0:
                        continue

                    part_row = cursor.execute(
                        "SELECT ime FROM parts WHERE id = ?", (art_id,)
                    ).fetchone()
                    ime = part_row['ime'] if part_row and part_row['ime'] else '—'

                    if izvoz_platena > 0:
                        avail = cursor.execute("""
                            SELECT COALESCE(SUM(kolicina), 0) AS total
                            FROM zaliha_dodadi WHERE artikl_id = ? AND plateno = 1
                        """, (art_id,)).fetchone()
                        avail_qty = int(avail['total']) if avail else 0

                        if izvoz_platena > avail_qty:
                            errors.append(
                                f"❌ {pn}: Немате доволно платена залиха! (Расположливо: {avail_qty})"
                            )
                            continue

                        remaining = izvoz_platena
                        rows = cursor.execute("""
                            SELECT id, kolicina FROM zaliha_dodadi
                            WHERE artikl_id = ? AND plateno = 1 AND kolicina > 0
                            ORDER BY datum ASC
                        """, (art_id,)).fetchall()

                        for r in rows:
                            if remaining <= 0:
                                break
                            r_id = r['id']
                            r_qty = int(r['kolicina'])
                            if r_qty <= remaining:
                                cursor.execute("DELETE FROM zaliha_dodadi WHERE id = ?", (r_id,))
                                remaining -= r_qty
                            else:
                                cursor.execute(
                                    "UPDATE zaliha_dodadi SET kolicina = kolicina - ? WHERE id = ?",
                                    (remaining, r_id)
                                )
                                remaining = 0

                        cursor.execute("""
                            INSERT INTO zaliha_izvoz_pending
                                (artikl_id, pn, ime, kolicina, tip, datum_izvoz, username, status)
                            VALUES (?, ?, ?, ?, 'Извоз - Платена', ?, ?, 'pending')
                        """, (art_id, pn, ime, izvoz_platena,
                              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session["user"]))

                        total_pending += izvoz_platena
                        print(f"  ✅ Pending платена: {izvoz_platena} за {pn}")

                    if izvoz_neplatena > 0:
                        avail = cursor.execute("""
                            SELECT COALESCE(SUM(kolicina), 0) AS total
                            FROM zaliha_dodadi WHERE artikl_id = ? AND plateno = 0
                        """, (art_id,)).fetchone()
                        avail_qty = int(avail['total']) if avail else 0

                        if izvoz_neplatena > avail_qty:
                            errors.append(
                                f"❌ {pn}: Немате доволно неплатена залиха! (Расположливо: {avail_qty})"
                            )
                            continue

                        remaining = izvoz_neplatena
                        rows = cursor.execute("""
                            SELECT id, kolicina FROM zaliha_dodadi
                            WHERE artikl_id = ? AND plateno = 0 AND kolicina > 0
                            ORDER BY datum ASC
                        """, (art_id,)).fetchall()

                        for r in rows:
                            if remaining <= 0:
                                break
                            r_id = r['id']
                            r_qty = int(r['kolicina'])
                            if r_qty <= remaining:
                                cursor.execute("DELETE FROM zaliha_dodadi WHERE id = ?", (r_id,))
                                remaining -= r_qty
                            else:
                                cursor.execute(
                                    "UPDATE zaliha_dodadi SET kolicina = kolicina - ? WHERE id = ?",
                                    (remaining, r_id)
                                )
                                remaining = 0

                        cursor.execute("""
                            INSERT INTO zaliha_izvoz_pending
                                (artikl_id, pn, ime, kolicina, tip, datum_izvoz, username, status)
                            VALUES (?, ?, ?, ?, 'Извоз - Неплатена', ?, ?, 'pending')
                        """, (art_id, pn, ime, izvoz_neplatena,
                              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session["user"]))

                        total_pending += izvoz_neplatena
                        print(f"  ✅ Pending неплатена: {izvoz_neplatena} за {pn}")

                except Exception as art_err:
                    print(f"  ❌ Грешка при обработка на артикл: {art_err}")
                    import traceback
                    traceback.print_exc()
                    errors.append(f"Грешка при обработка на {pn}: {str(art_err)}")

            if errors:
                conn.rollback()
                return jsonify({'success': False, 'message': '\n'.join(errors)}), 400
            elif total_pending > 0:
                conn.commit()
                msg = f"✅ Испратено {total_pending} единици на одобрување (Pending извози)!"
                print(f"\n{msg}")
                return jsonify({'success': True, 'message': msg}), 200
            else:
                return jsonify({'success': False, 'message': '⚠️ Не избра количина за извоз!'}), 400

        except Exception as e:
            print(f"\n❌ КРИТИЧНА ГРЕШКА: {e}")
            import traceback
            traceback.print_exc()
            conn.rollback()
            return jsonify({'success': False, 'message': f'Грешка: {str(e)}'}), 500

        finally:
            conn.close()

    # ── GET – артикли со залиха > 0 + профактура резервации ──
    try:
        _ensure_profakturi_tables(cursor)
        conn.commit()

        # Редовна залиха (платена + неплатена)
        artikli_rows = cursor.execute("""
            SELECT a.id, a.part_number, a.ime,
                   COALESCE(SUM(CASE WHEN d.plateno=1 THEN d.kolicina ELSE 0 END), 0) AS kolicina_platena,
                   COALESCE(SUM(CASE WHEN d.plateno=0 THEN d.kolicina ELSE 0 END), 0) AS kolicina_neplatena
            FROM parts a
            LEFT JOIN zaliha_dodadi d ON a.id = d.artikl_id
            GROUP BY a.id
            HAVING (kolicina_platena + kolicina_neplatena) > 0
            ORDER BY a.part_number
        """).fetchall()

        # Резервирана за pending профактури по artikl_id
        profaktura_reserved = cursor.execute("""
            SELECT s.artikl_id, SUM(s.kolicina) AS kolicina_profaktura
            FROM profaktura_stavki s
            JOIN profakturi p ON s.profaktura_id = p.id
            WHERE p.status = 'pending'
            GROUP BY s.artikl_id
        """).fetchall()
        reserved_map = {r['artikl_id']: r['kolicina_profaktura'] for r in profaktura_reserved}

        # Споји ги
        artikli = []
        existing_ids = set()
        for row in artikli_rows:
            r = dict(row)
            r['kolicina_profaktura'] = reserved_map.get(r['id'], 0)
            artikli.append(r)
            existing_ids.add(r['id'])

        # Артикли кои САМО имаат профактура резервација (0 во zaliha_dodadi)
        for art_id, qty in reserved_map.items():
            if art_id not in existing_ids:
                part = cursor.execute(
                    "SELECT id, part_number, ime FROM parts WHERE id = ?", (art_id,)
                ).fetchone()
                if part:
                    artikli.append({
                        'id': part['id'],
                        'part_number': part['part_number'],
                        'ime': part['ime'],
                        'kolicina_platena': 0,
                        'kolicina_neplatena': 0,
                        'kolicina_profaktura': qty,
                    })

        artikli.sort(key=lambda x: x['part_number'])

    except Exception as e:
        print(f"❌ Грешка при читање артикли: {e}")
        import traceback
        traceback.print_exc()
        artikli = []
    finally:
        conn.close()

    return render_template("zalihi_izvoz.html", artikli=artikli, today=date.today().isoformat())


# ─────────────────────────────────────────────────────────────
# ПРЕГЛЕД ПО PN
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/pregled")
@login_required
def pregled():
    conn = get_db()
    cursor = conn.cursor()

    _ensure_profakturi_tables(cursor)
    conn.commit()

    # 1. Платена залиха
    plateni = cursor.execute("""
        SELECT a.id, a.part_number, a.ime,
               SUM(d.kolicina) AS kolicina_platena
        FROM zaliha_dodadi d
        JOIN parts a ON d.artikl_id = a.id
        WHERE d.plateno = 1
        GROUP BY a.id HAVING SUM(d.kolicina) > 0
        ORDER BY a.part_number
    """).fetchall()

    # 2. Неплатена залиха (само расположлива, БЕЗ резервирана)
    neplateni = cursor.execute("""
        SELECT a.id, a.part_number, a.ime,
               SUM(d.kolicina) AS kolicina_neplatena
        FROM zaliha_dodadi d
        JOIN parts a ON d.artikl_id = a.id
        WHERE d.plateno = 0
        GROUP BY a.id HAVING SUM(d.kolicina) > 0
        ORDER BY a.part_number
    """).fetchall()

    # 3. Резервирана за pending профактури
    profaktura_zaliha = cursor.execute("""
        SELECT s.artikl_id, s.pn, s.ime,
               SUM(s.kolicina)            AS kolicina_reserved,
               GROUP_CONCAT(p.broj, ', ') AS profakturi_broevi,
               GROUP_CONCAT(p.username, ', ') AS korisnici_raw
        FROM profaktura_stavki s
        JOIN profakturi p ON s.profaktura_id = p.id
        WHERE p.status = 'pending'
        GROUP BY s.artikl_id
        ORDER BY s.pn
    """).fetchall()

    pz_list = []
    for row in profaktura_zaliha:
        r = dict(row)
        if r.get('korisnici_raw'):
            users = sorted(set(u.strip() for u in r['korisnici_raw'].split(',')))
            r['korisnici'] = ', '.join(users)
        else:
            r['korisnici'] = '—'
        pz_list.append(r)

    conn.close()
    return render_template(
        "zalihi_pregled.html",
        plateni=plateni,
        neplateni=neplateni,
        profaktura_zaliha=pz_list,
    )


# ─────────────────────────────────────────────────────────────
# DEBUG РУТА
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/debug")
@login_required
def debug():
    conn = get_db()
    cursor = conn.cursor()

    site = cursor.execute("""
        SELECT d.id, d.artikl_id, d.kolicina, d.plateno, d.datum, d.username,
               p.part_number, p.ime
        FROM zaliha_dodadi d
        LEFT JOIN parts p ON d.artikl_id = p.id
        ORDER BY d.id DESC
        LIMIT 50
    """).fetchall()

    vkupno = cursor.execute("""
        SELECT p.part_number, p.ime,
               SUM(CASE WHEN d.plateno=1 THEN d.kolicina ELSE 0 END) AS platena,
               SUM(CASE WHEN d.plateno=0 THEN d.kolicina ELSE 0 END) AS neplatena,
               COUNT(*) AS redovi
        FROM zaliha_dodadi d
        LEFT JOIN parts p ON d.artikl_id = p.id
        GROUP BY d.artikl_id
    """).fetchall()

    conn.close()

    html = "<h2>zaliha_dodadi (последни 50)</h2><table border=1 cellpadding=5>"
    html += "<tr><th>ID</th><th>artikl_id</th><th>PN</th><th>Ime</th><th>Kolicina</th><th>Plateno</th><th>Datum</th><th>Username</th></tr>"
    for r in site:
        r = dict(r)
        html += f"<tr><td>{r['id']}</td><td>{r['artikl_id']}</td><td>{r['part_number']}</td><td>{r['ime']}</td><td>{r['kolicina']}</td><td>{r['plateno']}</td><td>{r['datum']}</td><td>{r['username']}</td></tr>"
    html += "</table>"

    html += "<br><h2>Вкупно по артикл</h2><table border=1 cellpadding=5>"
    html += "<tr><th>PN</th><th>Ime</th><th>Platena</th><th>Neplatena</th><th>Redovi</th></tr>"
    for r in vkupno:
        r = dict(r)
        html += f"<tr><td>{r['part_number']}</td><td>{r['ime']}</td><td>{r['platena']}</td><td>{r['neplatena']}</td><td>{r['redovi']}</td></tr>"
    html += "</table>"

    return html


# ─────────────────────────────────────────────────────────────
# PENDING ИЗВОЗИ
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/pending")
@login_required
def pending():
    try:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zaliha_izvoz_pending (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artikl_id INTEGER NOT NULL,
                pn TEXT NOT NULL,
                ime TEXT NOT NULL,
                kolicina INTEGER NOT NULL,
                tip TEXT NOT NULL,
                datum_izvoz TEXT NOT NULL,
                username TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                datum_odobren TEXT,
                odobren_od TEXT
            )
        """)
        conn.commit()

        pending_items = cursor.execute("""
            SELECT id, artikl_id, pn, ime, kolicina, tip, status, datum_izvoz, username
            FROM zaliha_izvoz_pending
            WHERE status = 'pending'
            ORDER BY datum_izvoz DESC
        """).fetchall()

        conn.close()
        return render_template("zalihi_pending.html", pending_items=pending_items)

    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f"Грешка: {str(e)}", "danger")
        return render_template("zalihi_pending.html", pending_items=[])


# ─────────────────────────────────────────────────────────────
# ОДОБРИ ЕДЕН PENDING ИЗВОЗ
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/pending/odobri", methods=["POST"])
@login_required
def pending_odobri():
    conn = None
    try:
        data = request.get_json()
        pending_id = int(data.get("id", 0))

        if pending_id <= 0:
            return jsonify({'success': False, 'message': 'Невалиден ID'}), 400

        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        item = cursor.execute(
            "SELECT * FROM zaliha_izvoz_pending WHERE id = ? AND status = 'pending'",
            (pending_id,)
        ).fetchone()

        if not item:
            conn.close()
            return jsonify({'success': False, 'message': 'Не е пронајден pending извоз'}), 404

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            UPDATE zaliha_izvoz_pending
            SET status = 'odobren', datum_odobren = ?, odobren_od = ?
            WHERE id = ?
        """, (now, session["user"], pending_id))

        cursor.execute("""
            INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now, session["user"], item['pn'], item['ime'], item['kolicina'], item['tip']))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Одобрен извоз на {item["kolicina"]} единици од {item["pn"]}!'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'message': f'Грешка: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────
# ОДБИЈ ЕДЕН PENDING ИЗВОЗ
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/pending/odbij", methods=["POST"])
@login_required
def pending_odbij():
    conn = None
    try:
        data = request.get_json()
        pending_id = int(data.get("id", 0))

        if pending_id <= 0:
            return jsonify({'success': False, 'message': 'Невалиден ID'}), 400

        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        item = cursor.execute(
            "SELECT * FROM zaliha_izvoz_pending WHERE id = ? AND status = 'pending'",
            (pending_id,)
        ).fetchone()

        if not item:
            conn.close()
            return jsonify({'success': False, 'message': 'Не е пронајден pending извоз'}), 404

        plateno = 1 if 'Платена' in item['tip'] else 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_date = datetime.now().strftime("%Y-%m-%d")

        cursor.execute("""
            INSERT INTO zaliha_dodadi (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
            VALUES (?, ?, 0, ?, ?, ?, ?)
        """, (item['artikl_id'], item['kolicina'], now_date, plateno, session["user"],
              f"Вратено (одбиен извоз #{pending_id})"))

        cursor.execute("""
            UPDATE zaliha_izvoz_pending
            SET status = 'odbijen', datum_odobren = ?, odobren_od = ?
            WHERE id = ?
        """, (now_str, session["user"], pending_id))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Одбиен извоз. Вратени {item["kolicina"]} единици за {item["pn"]} во залиха!'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'message': f'Грешка: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────
# ОДОБРИ СИТЕ PENDING
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/pending/odobri_site", methods=["POST"])
@login_required
def pending_odobri_site():
    conn = None
    try:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        items = cursor.execute(
            "SELECT * FROM zaliha_izvoz_pending WHERE status = 'pending'"
        ).fetchall()

        if not items:
            conn.close()
            return jsonify({'success': False, 'message': 'Нема pending извози за одобрување'}), 400

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = 0

        for item in items:
            cursor.execute("""
                UPDATE zaliha_izvoz_pending
                SET status = 'odobren', datum_odobren = ?, odobren_od = ?
                WHERE id = ?
            """, (now, session["user"], item['id']))

            cursor.execute("""
                INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now, session["user"], item['pn'], item['ime'], item['kolicina'], item['tip']))

            total += item['kolicina']

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Одобрени сите {len(items)} pending извози ({total} единици)!'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'message': f'Грешка: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────────
# ДОДАДЕНИ ПО НЕДЕЛИ + EXPORT
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/dodadeni_po_nedeli")
@login_required
def dodadeni_po_nedeli():
    conn = get_db()
    cursor = conn.cursor()
    raw = cursor.execute("""
        SELECT
            datum,
            pn,
            ime,
            SUM(kolicina) AS vkupna_kolicina,
            GROUP_CONCAT(username, ', ') AS korisnici_raw,
            zabeleska
        FROM zaliha_dodadi_log
        GROUP BY pn, ime, strftime('%Y-%W', datum)
        ORDER BY datum DESC
    """).fetchall()
    conn.close()
    weeks = defaultdict(list)
    week_totals = {}
    for row in raw:
        r = dict(row)
        try:
            dt = datetime.strptime(r['datum'][:10], '%Y-%m-%d')
            week_num = dt.isocalendar()[1]
            nedela_key = f"КН{week_num:02d}"
        except:
            nedela_key = "КН--"
        r['nedela'] = nedela_key
        if r.get('korisnici_raw'):
            users = sorted(set(u.strip() for u in r['korisnici_raw'].split(',')))
            r['korisnici'] = ', '.join(users)
        else:
            r['korisnici'] = '—'
        weeks[nedela_key].append(r)
        if nedela_key not in week_totals:
            week_totals[nedela_key] = 0
        week_totals[nedela_key] += r['vkupna_kolicina']
    sorted_weeks = sorted(weeks.items(), key=lambda x: x[0], reverse=True)
    return render_template('zalihi_dodadeni_po_nedeli.html',
                           sorted_weeks=sorted_weeks,
                           week_totals=week_totals)


@zalihi_bp.route("/dodadeni_po_nedeli/export")
@login_required
def dodadeni_po_nedeli_export():
    conn = get_db()
    cursor = conn.cursor()
    data = cursor.execute("""
        SELECT
            datum,
            pn,
            ime,
            SUM(kolicina) AS vkupna_kolicina,
            GROUP_CONCAT(username, ', ') AS korisnici_raw,
            zabeleska
        FROM zaliha_dodadi_log
        GROUP BY pn, ime
        ORDER BY datum DESC
    """).fetchall()
    conn.close()
    cleaned_data = []
    for row in data:
        r = dict(row)
        try:
            dt = datetime.strptime(r['datum'][:10], '%Y-%m-%d')
            week_num = dt.isocalendar()[1]
            r['nedela'] = f"КН{week_num:02d}"
        except:
            r['nedela'] = "КН--"
        if r.get('korisnici_raw'):
            users = sorted(set(u.strip() for u in r['korisnici_raw'].split(',')))
            r['korisnici'] = ', '.join(users)
        else:
            r['korisnici'] = '—'
        cleaned_data.append(r)
    wb = Workbook()
    ws = wb.active
    ws.title = "Zaliha Po Nedeli"
    ws.append(["Датум", "Недела", "PN", "Ime на артикл", "Вкупна количина", "Корисници", "Забелешка"])
    for row in cleaned_data:
        ws.append([
            row['datum'][:16],
            row['nedela'],
            row['pn'],
            row['ime'],
            row['vkupna_kolicina'],
            row['korisnici'],
            row['zabeleska'] or '—'
        ])
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[column].width = max_length + 5
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"zaliha_po_nedeli_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    )


# ─────────────────────────────────────────────────────────────
# ИСТОРИЈА НА ИЗВОЗИ
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/istorija")
@login_required
def istorija():
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT datum, username, pn, ime, kolicina, tip
        FROM zaliha_izvoz_log
        ORDER BY datum DESC
        LIMIT 200
    """).fetchall()
    conn.close()
    logovi = []
    for row in rows:
        d = dict(row) if hasattr(row, 'keys') else {
            'datum': row[0], 'username': row[1], 'pn': row[2],
            'ime': row[3], 'kolicina': row[4], 'tip': row[5]
        }
        d['nedela'] = get_nedela(d['datum'])
        logovi.append(d)
    return render_template('zalihi_istorija.html', logovi=logovi)


# ─────────────────────────────────────────────────────────────
# ИЗВОЗИ ПО НЕДЕЛИ
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/izvozi_po_nedeli")
@login_required
def izvozi_po_nedeli():
    conn = get_db()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT datum, username, pn, ime, kolicina, tip
        FROM zaliha_izvoz_log
        ORDER BY datum ASC
    """).fetchall()
    conn.close()

    week_data = defaultdict(lambda: defaultdict(lambda: {
        'ime': '—', 'kolicina_platena': 0, 'kolicina_neplatena': 0, 'korisnici': set()
    }))

    for row in rows:
        r = dict(row) if hasattr(row, 'keys') else {
            'datum': row[0], 'username': row[1], 'pn': row[2],
            'ime': row[3], 'kolicina': row[4], 'tip': row[5]
        }
        try:
            dt = datetime.strptime(str(r['datum'])[:10], '%Y-%m-%d')
            week_num = dt.isocalendar()[1]
            year = dt.isocalendar()[0]
            nedela_key = f"{year}-КН{week_num:02d}"
        except:
            nedela_key = "----КН--"

        pn = r['pn']
        entry = week_data[nedela_key][pn]
        entry['ime'] = r['ime'] or '—'
        entry['korisnici'].add(r['username'])

        if 'Платена' in (r['tip'] or ''):
            entry['kolicina_platena'] += int(r['kolicina'])
        else:
            entry['kolicina_neplatena'] += int(r['kolicina'])

    week_totals = {}
    week_platena = {}
    week_neplatena = {}
    sorted_weeks = []

    for nedela_key in sorted(week_data.keys(), reverse=True):
        pn_dict = week_data[nedela_key]
        artikli = []
        total = tot_pl = tot_npl = 0
        for pn, entry in sorted(pn_dict.items()):
            vkupno = entry['kolicina_platena'] + entry['kolicina_neplatena']
            artikli.append({
                'pn': pn,
                'ime': entry['ime'],
                'kolicina_platena': entry['kolicina_platena'],
                'kolicina_neplatena': entry['kolicina_neplatena'],
                'vkupno': vkupno,
                'korisnici': ', '.join(sorted(entry['korisnici']))
            })
            total += vkupno
            tot_pl += entry['kolicina_platena']
            tot_npl += entry['kolicina_neplatena']

        display_key = nedela_key.split('-', 1)[1] if '-' in nedela_key else nedela_key
        sorted_weeks.append((display_key, artikli))
        week_totals[display_key] = total
        week_platena[display_key] = tot_pl
        week_neplatena[display_key] = tot_npl

    return render_template(
        'zalihi_izvozi_po_nedeli.html',
        sorted_weeks=sorted_weeks,
        week_totals=week_totals,
        week_platena=week_platena,
        week_neplatena=week_neplatena
    )


@zalihi_bp.route("/izvozi_po_nedeli/export")
@login_required
def izvozi_po_nedeli_export():
    conn = get_db()
    cursor = conn.cursor()

    rows = cursor.execute("""
        SELECT datum, username, pn, ime, kolicina, tip
        FROM zaliha_izvoz_log
        ORDER BY datum ASC
    """).fetchall()
    conn.close()

    week_data = defaultdict(lambda: defaultdict(lambda: {
        'ime': '—', 'kolicina_platena': 0, 'kolicina_neplatena': 0, 'korisnici': set()
    }))

    for row in rows:
        r = dict(row) if hasattr(row, 'keys') else {
            'datum': row[0], 'username': row[1], 'pn': row[2],
            'ime': row[3], 'kolicina': row[4], 'tip': row[5]
        }
        try:
            dt = datetime.strptime(str(r['datum'])[:10], '%Y-%m-%d')
            week_num = dt.isocalendar()[1]
            year = dt.isocalendar()[0]
            nedela_key = f"{year}-КН{week_num:02d}"
        except:
            nedela_key = "----КН--"

        pn = r['pn']
        entry = week_data[nedela_key][pn]
        entry['ime'] = r['ime'] or '—'
        entry['korisnici'].add(r['username'])
        if 'Платена' in (r['tip'] or ''):
            entry['kolicina_platena'] += int(r['kolicina'])
        else:
            entry['kolicina_neplatena'] += int(r['kolicina'])

    wb = Workbook()
    ws = wb.active
    ws.title = "Izvozi Po Nedeli"

    header_fill = PatternFill("solid", fgColor="1e40af")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    total_fill = PatternFill("solid", fgColor="bbf7d0")
    total_font = Font(bold=True)

    headers = ["Недела", "PN", "Ime на артикл", "Платена", "Неплатена", "Вкупно", "Корисници"]
    ws.append(headers)
    for col_idx, _ in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    row_num = 2
    for nedela_key in sorted(week_data.keys(), reverse=True):
        display_key = nedela_key.split('-', 1)[1] if '-' in nedela_key else nedela_key
        pn_dict = week_data[nedela_key]
        total = tot_pl = tot_npl = 0

        for pn, entry in sorted(pn_dict.items()):
            vkupno = entry['kolicina_platena'] + entry['kolicina_neplatena']
            ws.append([
                display_key, pn, entry['ime'],
                entry['kolicina_platena'], entry['kolicina_neplatena'], vkupno,
                ', '.join(sorted(entry['korisnici']))
            ])
            total += vkupno
            tot_pl += entry['kolicina_platena']
            tot_npl += entry['kolicina_neplatena']
            row_num += 1

        ws.append([f"ВКУПНО {display_key}", '', '', tot_pl, tot_npl, total, ''])
        for col_idx in range(1, 8):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.fill = total_fill
            cell.font = total_font
        row_num += 2
        ws.append([])

    for col in ws.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if cell.value and len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[col_letter].width = max_length + 4

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"izvozi_po_nedeli_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    )


@zalihi_bp.route("/istorija/export")
@login_required
def istorija_export():
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT datum, username, pn, ime, kolicina, tip
        FROM zaliha_izvoz_log
        ORDER BY datum DESC
    """).fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Istorija Izvozi"
    ws.append(["Датум", "Корисник", "PN", "Ime на артикл", "Количина", "Тип"])

    for row in rows:
        r = dict(row) if hasattr(row, 'keys') else {
            'datum': row[0], 'username': row[1], 'pn': row[2],
            'ime': row[3], 'kolicina': row[4], 'tip': row[5]
        }
        ws.append([
            r['datum'][:16],
            r['username'],
            r['pn'],
            r['ime'],
            r['kolicina'],
            r['tip']
        ])

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[column].width = max_length + 5

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"istorija_izvozi_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    )


# ─────────────────────────────────────────────────────────────
# НОВА ПРОФАКТУРА
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/profakturi/nova", methods=["GET", "POST"])
@login_required
def profakturi_nova():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    _ensure_profakturi_tables(cursor)
    conn.commit()

    if request.method == "POST":
        try:
            data = request.get_json()
            artikli  = data.get("artikli", [])
            napomena = data.get("napomena", "").strip()

            if not artikli:
                return jsonify({"success": False, "message": "Не избра ниеден артикл!"}), 400

            last = cursor.execute(
                "SELECT COUNT(*) AS cnt FROM profakturi WHERE datum LIKE ?",
                (datetime.now().strftime("%Y-%m-%d") + "%",)
            ).fetchone()
            seq  = (last["cnt"] if last else 0) + 1
            broj = f"PF-{datetime.now().strftime('%Y%m%d')}-{seq:03d}"

            errors = []
            valid  = []

            for art in artikli:
                art_id   = int(art.get("id", 0))
                pn       = str(art.get("pn", "")).strip()
                kolicina = int(art.get("kolicina", 0))

                if kolicina <= 0:
                    continue

                avail = cursor.execute("""
                    SELECT COALESCE(SUM(kolicina), 0) AS total
                    FROM zaliha_dodadi
                    WHERE artikl_id = ? AND plateno = 0
                """, (art_id,)).fetchone()
                avail_qty = int(avail["total"]) if avail else 0

                if kolicina > avail_qty:
                    errors.append(
                        f"❌ {pn}: Немате доволно неплатена залиха! (Расположливо: {avail_qty})"
                    )
                    continue

                valid.append({"id": art_id, "pn": pn, "kolicina": kolicina})

            if errors:
                conn.rollback()
                conn.close()
                return jsonify({"success": False, "message": "\n".join(errors)}), 400

            if not valid:
                conn.close()
                return jsonify({"success": False, "message": "Не избра количина за ниеден артикл!"}), 400

            now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            now_date = datetime.now().strftime("%Y-%m-%d")

            cursor.execute("""
                INSERT INTO profakturi (broj, datum, username, status, napomena)
                VALUES (?, ?, ?, 'pending', ?)
            """, (broj, now_str, session["user"], napomena))
            profaktura_id = cursor.lastrowid

            for art in valid:
                art_id   = art["id"]
                pn       = art["pn"]
                kolicina = art["kolicina"]

                part_row = cursor.execute(
                    "SELECT ime FROM parts WHERE id = ?", (art_id,)
                ).fetchone()
                ime = part_row["ime"] if part_row and part_row["ime"] else "—"

                remaining = kolicina
                rows = cursor.execute("""
                    SELECT id, kolicina FROM zaliha_dodadi
                    WHERE artikl_id = ? AND plateno = 0 AND kolicina > 0
                    ORDER BY datum ASC
                """, (art_id,)).fetchall()

                for r in rows:
                    if remaining <= 0:
                        break
                    r_id  = r["id"]
                    r_qty = int(r["kolicina"])
                    if r_qty <= remaining:
                        cursor.execute("DELETE FROM zaliha_dodadi WHERE id = ?", (r_id,))
                        remaining -= r_qty
                    else:
                        cursor.execute(
                            "UPDATE zaliha_dodadi SET kolicina = kolicina - ? WHERE id = ?",
                            (remaining, r_id)
                        )
                        remaining = 0

                cursor.execute("""
                    INSERT INTO profaktura_stavki (profaktura_id, artikl_id, pn, ime, kolicina)
                    VALUES (?, ?, ?, ?, ?)
                """, (profaktura_id, art_id, pn, ime, kolicina))

            conn.commit()
            conn.close()
            return jsonify({
                "success": True,
                "message": f"✅ Профактурата {broj} е креирана и чека одобрување!"
            })

        except Exception as e:
            import traceback; traceback.print_exc()
            conn.rollback(); conn.close()
            return jsonify({"success": False, "message": f"Грешка: {str(e)}"}), 500

    # GET
    try:
        artikli = cursor.execute("""
            SELECT a.id, a.part_number, a.ime,
                   COALESCE(SUM(d.kolicina), 0) AS kolicina_neplatena
            FROM parts a
            LEFT JOIN zaliha_dodadi d ON a.id = d.artikl_id AND d.plateno = 0
            GROUP BY a.id
            HAVING kolicina_neplatena > 0
            ORDER BY a.part_number
        """).fetchall()
    except Exception as e:
        print(f"❌ Грешка: {e}"); artikli = []
    finally:
        conn.close()

    return render_template("profakturi_nova.html",
                           artikli=artikli,
                           today=date.today().isoformat())


# ─────────────────────────────────────────────────────────────
# ПРОФАКТУРИ НА ЧЕКАЊЕ
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/profakturi/pending")
@login_required
def profakturi_pending():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    _ensure_profakturi_tables(cursor)
    conn.commit()

    profakturi = cursor.execute("""
        SELECT p.id, p.broj, p.datum, p.username, p.napomena,
               SUM(s.kolicina) AS vkupno_kolicina,
               COUNT(s.id)     AS broj_stavki
        FROM profakturi p
        LEFT JOIN profaktura_stavki s ON p.id = s.profaktura_id
        WHERE p.status = 'pending'
        GROUP BY p.id
        ORDER BY p.datum DESC
    """).fetchall()

    profakturi_so_stavki = []
    for pf in profakturi:
        stavki = cursor.execute("""
            SELECT pn, ime, kolicina FROM profaktura_stavki
            WHERE profaktura_id = ?
        """, (pf["id"],)).fetchall()
        profakturi_so_stavki.append({
            "id":              pf["id"],
            "broj":            pf["broj"],
            "datum":           pf["datum"][:16],
            "username":        pf["username"],
            "napomena":        pf["napomena"] or "—",
            "vkupno_kolicina": pf["vkupno_kolicina"] or 0,
            "broj_stavki":     pf["broj_stavki"] or 0,
            "stavki":          [dict(s) for s in stavki],
        })

    conn.close()
    return render_template("profakturi_pending.html",
                           profakturi=profakturi_so_stavki)


# ─────────────────────────────────────────────────────────────
# ОДОБРИ ПРОФАКТУРА  →  ставките одат во ПЛАТЕНА залиха
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/profakturi/odobri", methods=["POST"])
@login_required
def profakturi_odobri():
    conn = None
    try:
        data          = request.get_json()
        profaktura_id = int(data.get("id", 0))
        if profaktura_id <= 0:
            return jsonify({"success": False, "message": "Невалиден ID"}), 400

        conn = get_db(); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        _ensure_profakturi_tables(cursor)

        pf = cursor.execute(
            "SELECT * FROM profakturi WHERE id = ? AND status = 'pending'",
            (profaktura_id,)
        ).fetchone()
        if not pf:
            conn.close()
            return jsonify({"success": False, "message": "Профактурата не е пронајдена"}), 404

        stavki = cursor.execute(
            "SELECT * FROM profaktura_stavki WHERE profaktura_id = ?",
            (profaktura_id,)
        ).fetchall()

        now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_date = datetime.now().strftime("%Y-%m-%d")

        for s in stavki:
            cursor.execute("""
                INSERT INTO zaliha_dodadi
                    (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
                VALUES (?, ?, 0, ?, 1, ?, ?)
            """, (s["artikl_id"], s["kolicina"], now_date,
                  session["user"],
                  f"Одобрена профактура {pf['broj']}"))

            cursor.execute("""
                INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now_str, session["user"], s["pn"], s["ime"],
                  s["kolicina"], f"Профактура {pf['broj']} – Платена"))

        cursor.execute("""
            UPDATE profakturi
            SET status = 'odobrena', datum_odobrena = ?, odobrena_od = ?
            WHERE id = ?
        """, (now_str, session["user"], profaktura_id))

        conn.commit(); conn.close()
        return jsonify({
            "success": True,
            "message": f"✅ Профактурата {pf['broj']} е одобрена! Залихата е префрлена во Платена."
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        if conn:
            try: conn.rollback(); conn.close()
            except: pass
        return jsonify({"success": False, "message": f"Грешка: {str(e)}"}), 500


# ─────────────────────────────────────────────────────────────
# ОДБИЈ ПРОФАКТУРА  →  ставките се враќаат во НЕПЛАТЕНА
# ─────────────────────────────────────────────────────────────
@zalihi_bp.route("/profakturi/odbij", methods=["POST"])
@login_required
def profakturi_odbij():
    conn = None
    try:
        data          = request.get_json()
        profaktura_id = int(data.get("id", 0))
        if profaktura_id <= 0:
            return jsonify({"success": False, "message": "Невалиден ID"}), 400

        conn = get_db(); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        _ensure_profakturi_tables(cursor)

        pf = cursor.execute(
            "SELECT * FROM profakturi WHERE id = ? AND status = 'pending'",
            (profaktura_id,)
        ).fetchone()
        if not pf:
            conn.close()
            return jsonify({"success": False, "message": "Профактурата не е пронајдена"}), 404

        stavki = cursor.execute(
            "SELECT * FROM profaktura_stavki WHERE profaktura_id = ?",
            (profaktura_id,)
        ).fetchall()

        now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_date = datetime.now().strftime("%Y-%m-%d")

        for s in stavki:
            cursor.execute("""
                INSERT INTO zaliha_dodadi
                    (artikl_id, kolicina, cena, datum, plateno, username, zabeleska)
                VALUES (?, ?, 0, ?, 0, ?, ?)
            """, (s["artikl_id"], s["kolicina"], now_date,
                  session["user"],
                  f"Вратено (одбиена профактура {pf['broj']})"))

        cursor.execute("""
            UPDATE profakturi
            SET status = 'odbiena', datum_odobrena = ?, odobrena_od = ?
            WHERE id = ?
        """, (now_str, session["user"], profaktura_id))

        conn.commit(); conn.close()
        return jsonify({
            "success": True,
            "message": f"↩️ Профактурата {pf['broj']} е одбиена. Залихата е вратена во Неплатена."
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        if conn:
            try: conn.rollback(); conn.close()
            except: pass
        return jsonify({"success": False, "message": f"Грешка: {str(e)}"}), 500
    
    # ─────────────────────────────────────────────────────────────
# СТОРНО НА ЗАЛИХА
# ─────────────────────────────────────────────────────────────

@zalihi_bp.route("/storno/zaliha/<int:artikl_id>")
@login_required
def storno_zaliha(artikl_id):
    """Враќа JSON со тековни залихи (платена / неплатена) за дадениот артикл."""
    try:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        row = cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN plateno=1 THEN kolicina ELSE 0 END), 0) AS platena,
                COALESCE(SUM(CASE WHEN plateno=0 THEN kolicina ELSE 0 END), 0) AS neplatena
            FROM zaliha_dodadi
            WHERE artikl_id = ?
        """, (artikl_id,)).fetchone()

        conn.close()
        return jsonify({
            'platena':   int(row['platena'])   if row else 0,
            'neplatena': int(row['neplatena']) if row else 0,
        })
    except Exception as e:
        return jsonify({'platena': 0, 'neplatena': 0, 'error': str(e)}), 500


@zalihi_bp.route("/storno", methods=["GET", "POST"])
@login_required
def storno():
    # ── POST – изврши сторно ───────────────────────────────
    if request.method == "POST":
        conn = None
        try:
            data      = request.get_json()
            artikl_id = int(data.get("artikl_id", 0))
            pn        = str(data.get("pn", "")).strip().upper()
            kolicina  = int(data.get("kolicina", 0))
            plateno   = int(data.get("plateno", 0))   # 1 = платена, 0 = неплатена
            zabeleska = str(data.get("zabeleska", "")).strip()

            # Валидација
            if artikl_id <= 0 or kolicina <= 0:
                return jsonify({'success': False, 'message': 'Невалиден артикл или количина!'}), 400
            if not zabeleska:
                return jsonify({'success': False, 'message': 'Забелешката е задолжителна!'}), 400

            conn = get_db()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Провери дали има доволно залиха
            avail = cursor.execute("""
                SELECT COALESCE(SUM(kolicina), 0) AS total
                FROM zaliha_dodadi
                WHERE artikl_id = ? AND plateno = ?
            """, (artikl_id, plateno)).fetchone()
            avail_qty = int(avail['total']) if avail else 0

            if kolicina > avail_qty:
                conn.close()
                tip_str = "платена" if plateno else "неплатена"
                return jsonify({
                    'success': False,
                    'message': f'Немате доволно {tip_str} залиха! Расположливо: {avail_qty}'
                }), 400

            # Одземање по FIFO
            remaining = kolicina
            rows = cursor.execute("""
                SELECT id, kolicina FROM zaliha_dodadi
                WHERE artikl_id = ? AND plateno = ? AND kolicina > 0
                ORDER BY datum ASC
            """, (artikl_id, plateno)).fetchall()

            for r in rows:
                if remaining <= 0:
                    break
                r_id  = r['id']
                r_qty = int(r['kolicina'])
                if r_qty <= remaining:
                    cursor.execute("DELETE FROM zaliha_dodadi WHERE id = ?", (r_id,))
                    remaining -= r_qty
                else:
                    cursor.execute(
                        "UPDATE zaliha_dodadi SET kolicina = kolicina - ? WHERE id = ?",
                        (remaining, r_id)
                    )
                    remaining = 0

            # Земи го името на артиклот
            part = cursor.execute(
                "SELECT ime FROM parts WHERE id = ?", (artikl_id,)
            ).fetchone()
            ime = part['ime'] if part and part['ime'] else '—'

            now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tip_log  = f"Сторно - {'Платена' if plateno else 'Неплатена'}"

            # Запис во лог на извози (со негативен предзнак во tip)
            cursor.execute("""
                INSERT INTO zaliha_izvoz_log (datum, username, pn, ime, kolicina, tip)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now_str, session["user"], pn, ime, kolicina, tip_log))

            # Запис во посебна табела за сторна (се креира ако нема)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS zaliha_storno_log (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    datum     TEXT    NOT NULL,
                    username  TEXT    NOT NULL,
                    artikl_id INTEGER NOT NULL,
                    pn        TEXT    NOT NULL,
                    ime       TEXT,
                    kolicina  INTEGER NOT NULL,
                    plateno   INTEGER NOT NULL,
                    tip       TEXT    NOT NULL,
                    zabeleska TEXT    NOT NULL
                )
            """)
            cursor.execute("""
                INSERT INTO zaliha_storno_log
                    (datum, username, artikl_id, pn, ime, kolicina, plateno, tip, zabeleska)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (now_str, session["user"], artikl_id, pn, ime, kolicina, plateno, tip_log, zabeleska))

            conn.commit()
            conn.close()

            tip_str = "платена" if plateno else "неплатена"
            return jsonify({
                'success': True,
                'message': f'✅ Сторно успешен! Одземени {kolicina} ед. ({tip_str}) од {pn}.'
            })

        except Exception as e:
            import traceback; traceback.print_exc()
            if conn:
                try: conn.rollback(); conn.close()
                except: pass
            return jsonify({'success': False, 'message': f'Грешка: {str(e)}'}), 500

    # ── GET – страница со форма + историја ────────────────
    try:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Осигури ја табелата
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zaliha_storno_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                datum     TEXT    NOT NULL,
                username  TEXT    NOT NULL,
                artikl_id INTEGER NOT NULL,
                pn        TEXT    NOT NULL,
                ime       TEXT,
                kolicina  INTEGER NOT NULL,
                plateno   INTEGER NOT NULL,
                tip       TEXT    NOT NULL,
                zabeleska TEXT    NOT NULL
            )
        """)
        conn.commit()

        storna = cursor.execute("""
            SELECT datum, username, pn, ime, kolicina, plateno, tip, zabeleska
            FROM zaliha_storno_log
            ORDER BY datum DESC
            LIMIT 50
        """).fetchall()

        conn.close()
        storna_list = [dict(s) for s in storna]

    except Exception as e:
        print(f"❌ Грешка при читање сторна: {e}")
        storna_list = []

    return render_template("zalihi_storno.html", storna=storna_list)