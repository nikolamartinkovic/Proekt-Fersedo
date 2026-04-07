import os
import time
from datetime import date, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from utils.db import get_db
from utils.decorators import login_required
from utils.nabavki_data import (
    build_api_tbody_html,
    build_excel_output,
    build_export_filename,
    build_pdf_output,
    fetch_comments,
    fetch_export_rows,
    fetch_requests_with_comments,
    get_archived_requests,
    get_user_lists,
)
from utils.nabavki_email import notify_novo_baranje
from utils.nabavki_images import (
    ensure_comment_slika_column,
    save_camera_image,
    save_compressed_image,
)
from utils.nabavki_workflow import (
    add_request_comment,
    take_request,
    transfer_request,
    update_request_status,
    upload_request_image,
)
from utils.notifications import send_push_to_nabavki_group
from utils.route_helpers import flash_service_response

nabavki_bp = Blueprint("nabavki", __name__, url_prefix="/nabavki")


@nabavki_bp.route("/", methods=["GET", "POST"])
@login_required
def nabavki():
    conn = get_db()
    cursor = conn.cursor()
    ensure_comment_slika_column(cursor)
    is_nabavki_user = session.get("is_admin") or session.get("user_group") == "Nabavki"

    if request.method == "POST":
        action = request.form.get("action")
        if action == "kreiraj":
            naslov = request.form.get("naslov", "").strip()
            kolicina_str = request.form.get("kolicina", "0").strip()
            datum_itnost = request.form.get("datum_itnost")
            chat_comment = request.form.get("chat_comment", "").strip()

            slika_file = request.files.get("slika")
            camera_filename = request.form.get("camera_slika_filename", "").strip()

            try:
                kolicina = int(kolicina_str)
                if not naslov or kolicina < 1 or not datum_itnost:
                    flash("Наслов, количина и датум на итност се задолжителни!", "error")
                    return redirect(url_for("nabavki.nabavki"))

                save_dir = os.path.join(current_app.config["STATIC_FOLDER"], "nabavki")
                slika_filename = None
                filename_base = f"req_{int(time.time())}_{session['user']}"

                if slika_file and slika_file.filename:
                    slika_filename = save_compressed_image(slika_file, save_dir, filename_base)
                    if not slika_filename:
                        flash("Грешка при зачувување на сликата!", "warning")
                elif camera_filename:
                    slika_filename = save_camera_image(camera_filename, save_dir, filename_base)
                    if not slika_filename:
                        flash(f"Камера сликата не е пронајдена: {camera_filename}", "warning")

                cursor.execute(
                    """
                    INSERT INTO nabavki_requests
                    (username, naslov, kolicina, datum_kreiranje, datum_itnost, opis, slika, status)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, '', ?, 'креирано')
                    """,
                    (session["user"], naslov, kolicina, datum_itnost, slika_filename),
                )
                conn.commit()
                new_id = cursor.lastrowid

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fer_sequence (
                        id INTEGER PRIMARY KEY, last_num INTEGER DEFAULT 0
                    )
                    """
                )
                cursor.execute("INSERT OR IGNORE INTO fer_sequence (id, last_num) VALUES (1, 0)")
                cursor.execute("UPDATE fer_sequence SET last_num = last_num + 1 WHERE id = 1")
                seq_row = cursor.execute("SELECT last_num FROM fer_sequence WHERE id = 1").fetchone()
                nalog = f"Fer{seq_row['last_num']:03d}"
                cursor.execute("UPDATE nabavki_requests SET nalog_broj=? WHERE id=?", (nalog, new_id))
                conn.commit()

                if chat_comment:
                    cursor.execute(
                        "INSERT INTO nabavki_comments (req_id, user, comment) VALUES (?, ?, ?)",
                        (new_id, session["user"], chat_comment),
                    )
                    conn.commit()

                now_local = datetime.now().strftime("%d-%m-%Y %H:%M")
                flash(
                    f"Барањето е креирано со број: <strong>{nalog}</strong> на {now_local}!",
                    "success",
                )

                send_push_to_nabavki_group(
                    title="Ново барање за набавка!",
                    body=f"{naslov} (број {nalog}) - од {session['user']}",
                    url="/nabavki",
                    exclude_user=session["user"],
                )
                notify_novo_baranje(
                    nalog=nalog,
                    naslov=naslov,
                    kolicina=kolicina,
                    datum_itnost=datum_itnost,
                    kreator=session["user"],
                )
            except ValueError:
                flash("Количина мора да биде број!", "error")
            except Exception as e:
                flash(f"Грешка при креирање: {str(e)}", "danger")
                conn.rollback()

        conn.close()
        return redirect(url_for("nabavki.nabavki", filter=request.args.get("filter", "all")))

    filter_type = request.args.get("filter", "all")
    requests_list, page_title = fetch_requests_with_comments(
        cursor,
        filter_type=filter_type,
        current_user=session["user"],
        is_nabavki_user=is_nabavki_user,
    )
    users, nabavki_users = get_user_lists(cursor)
    conn.close()

    return render_template(
        "nabavki.html",
        requests=requests_list,
        is_admin=session.get("is_admin"),
        is_nabavki_user=is_nabavki_user,
        filter_type=filter_type,
        page_title=page_title,
        today=date.today().isoformat(),
        users=users,
        nabavki_users=nabavki_users,
    )


@nabavki_bp.route("/delete_selected", methods=["POST"])
@login_required
def delete_selected():
    if not (session.get("is_admin") or session.get("user_group") == "Nabavki"):
        flash("Немате дозвола за бришење барања.", "danger")
        return redirect(url_for("nabavki.nabavki"))

    selected_ids = request.form.getlist("selected_ids")
    if not selected_ids:
        flash("Нема избрани барања за бришење!", "warning")
        return redirect(url_for("nabavki.nabavki"))

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in selected_ids)
        linked_orders = cursor.execute(
            f"""
            SELECT l.nalog_id, l.nabavka_request_id,
                   COALESCE(NULLIF(r.nalog_broj, ''), '#' || r.id) AS request_broj
            FROM odrzuvanje_nalog_nabavki l
            JOIN nabavki_requests r ON r.id = l.nabavka_request_id
            WHERE l.nabavka_request_id IN ({placeholders})
            """,
            selected_ids,
        ).fetchall()
        if linked_orders:
            cursor.execute(
                f"DELETE FROM odrzuvanje_nalog_nabavki WHERE nabavka_request_id IN ({placeholders})",
                selected_ids,
            )
            cursor.execute(
                f"""
                UPDATE odrzuvanje_nalog_delovi
                SET nabavka_request_id = NULL,
                    source_type = 'избришана набавка'
                WHERE nabavka_request_id IN ({placeholders})
                """,
                selected_ids,
            )
            for link in linked_orders:
                cursor.execute(
                    """
                    INSERT INTO odrzuvanje_nalog_aktivnosti (nalog_id, tip, poraka, created_by)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        link["nalog_id"],
                        "procurement",
                        f"Поврзаното барање за набавка {link['request_broj']} е избришано од модулот Набавки.",
                        session.get("user", ""),
                    ),
                )
                cursor.execute(
                    "UPDATE odrzuvanje_nalozi SET updated_at = ? WHERE id = ?",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), link["nalog_id"]),
                )
        cursor.execute(f"DELETE FROM nabavki_requests WHERE id IN ({placeholders})", selected_ids)
        count = cursor.rowcount
        conn.commit()
        flash(f"Успешно избришани {count} барања!", "success")
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"Грешка при бришење: {str(e)}", "danger")
    finally:
        if conn:
            conn.close()

    return redirect(url_for("nabavki.nabavki"))


@nabavki_bp.route("/add_comment/<int:req_id>", methods=["POST"])
@login_required
def add_comment(req_id):
    response = add_request_comment(
        req_id=req_id,
        current_user=session["user"],
        is_admin=session.get("is_admin"),
        user_group=session.get("user_group"),
        comment=request.form.get("comment", "").strip(),
        slika_file=request.files.get("chat_slika"),
        static_folder=current_app.config["STATIC_FOLDER"],
    )
    flash_service_response(response)
    return redirect(url_for("nabavki.nabavki", filter=request.args.get("filter", "all")))


@nabavki_bp.route("/prevzemi/<int:req_id>", methods=["POST"])
@login_required
def prevzemi(req_id):
    response = take_request(
        req_id=req_id,
        current_user=session["user"],
        user_group=session.get("user_group"),
        is_admin=session.get("is_admin"),
    )
    flash_service_response(response)
    return redirect(url_for("nabavki.nabavki"))


@nabavki_bp.route("/transfer/<int:req_id>", methods=["POST"])
@login_required
def transfer(req_id):
    response = transfer_request(
        req_id=req_id,
        current_user=session["user"],
        user_group=session.get("user_group"),
        is_admin=session.get("is_admin"),
        new_user=request.form.get("novi_korisnik", "").strip(),
    )
    flash_service_response(response)
    return redirect(url_for("nabavki.nabavki", filter=request.args.get("filter", "all")))


@nabavki_bp.route("/update_status/<int:req_id>/<string:new_status>")
@login_required
def update_status(req_id, new_status):
    response = update_request_status(
        req_id=req_id,
        new_status=new_status,
        current_user=session["user"],
        is_admin=session.get("is_admin"),
        user_group=session.get("user_group"),
    )
    flash_service_response(response)
    return redirect(url_for("nabavki.nabavki"))


@nabavki_bp.route("/arhiva")
@login_required
def arhiva():
    conn = get_db()
    cursor = conn.cursor()
    archived = get_archived_requests(cursor)
    conn.close()
    return render_template("nabavki_arhiva.html", archived_requests=archived)


@nabavki_bp.route("/export/excel")
@login_required
def export_excel():
    conn = get_db()
    cursor = conn.cursor()
    rows = fetch_export_rows(
        cursor,
        status_filter=request.args.get("status_filter"),
        datum_od=request.args.get("datum_od"),
        datum_do=request.args.get("datum_do"),
        user_filter=request.args.get("user_filter") if session.get("is_admin") else session["user"],
    )
    conn.close()

    return send_file(
        build_excel_output(rows),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=build_export_filename("nabavki", "xlsx"),
    )


@nabavki_bp.route("/export/pdf")
@login_required
def export_pdf():
    conn = get_db()
    cursor = conn.cursor()
    rows = fetch_export_rows(
        cursor,
        status_filter=request.args.get("status_filter"),
        datum_od=request.args.get("datum_od"),
        datum_do=request.args.get("datum_do"),
        user_filter=request.args.get("user_filter") if session.get("is_admin") else session["user"],
    )
    conn.close()

    return send_file(
        build_pdf_output(rows),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=build_export_filename("nabavki", "pdf"),
    )


@nabavki_bp.route("/comments/<int:req_id>")
@login_required
def get_comments_route(req_id):
    conn = get_db()
    cursor = conn.cursor()
    comments = fetch_comments(cursor, req_id)
    conn.close()
    return jsonify([dict(c) for c in comments])


@nabavki_bp.route("/api")
@login_required
def api():
    conn = get_db()
    cursor = conn.cursor()
    filter_type = request.args.get("filter", "all")
    is_nabavki_user = session.get("is_admin") or session.get("user_group") == "Nabavki"
    requests_list, page_title = fetch_requests_with_comments(
        cursor,
        filter_type=filter_type,
        current_user=session["user"],
        is_nabavki_user=is_nabavki_user,
    )
    conn.close()

    return jsonify(
        {
            "tbody_html": build_api_tbody_html(
                requests_list,
                can_manage=session.get("is_admin") or session.get("user_group") == "Nabavki",
            ),
            "page_title": page_title,
            "count": len(requests_list),
        }
    )


@nabavki_bp.route("/upload_slika/<int:req_id>", methods=["POST"])
@login_required
def upload_slika(req_id):
    response = upload_request_image(
        req_id=req_id,
        current_user=session["user"],
        is_admin=session.get("is_admin"),
        user_group=session.get("user_group"),
        slika_file=request.files.get("nova_slika"),
        static_folder=current_app.config["STATIC_FOLDER"],
    )
    flash_service_response(response)
    return redirect(url_for("nabavki.nabavki", filter=request.args.get("filter", "all")))
