import os
import time
from datetime import datetime

from utils.db import get_db
from utils.nabavki_email import notify_nov_komentar, notify_promena_status
from utils.nabavki_images import (
    ensure_archive_comments_table,
    ensure_comment_slika_column,
    save_compressed_image,
)
from utils.notifications import send_push_to_nabavki_group, send_push_to_user


def add_request_comment(req_id, current_user, is_admin, user_group, comment, slika_file, static_folder):
    conn = get_db()
    cursor = conn.cursor()
    ensure_comment_slika_column(cursor)

    if not comment and (not slika_file or not slika_file.filename):
        conn.close()
        return {"success": False, "message": "Коментарот е празен!"}

    req_row = cursor.execute(
        "SELECT username, nalog_broj, naslov, prevzemeno_od FROM nabavki_requests WHERE id=?",
        (req_id,),
    ).fetchone()
    creator = req_row["username"] if req_row else None
    nalog = req_row["nalog_broj"] if req_row else "?"
    naslov = req_row["naslov"] if req_row else "?"
    prevzemeno = req_row["prevzemeno_od"] if req_row else None

    if not (is_admin or current_user == creator or user_group == "Nabavki"):
        conn.close()
        return {"success": False, "message": "Немате дозвола да коментирате!"}

    try:
        chat_slika_filename = None
        if slika_file and slika_file.filename:
            save_dir = os.path.join(static_folder, "nabavki_chat")
            filename_base = f"chat_{req_id}_{int(time.time())}_{current_user}"
            chat_slika_filename = save_compressed_image(slika_file, save_dir, filename_base)

        cursor.execute(
            "INSERT INTO nabavki_comments (req_id, user, comment, slika) VALUES (?,?,?,?)",
            (req_id, current_user, comment, chat_slika_filename),
        )
        conn.commit()

        if current_user == creator:
            if prevzemeno and prevzemeno != current_user:
                send_push_to_user(
                    prevzemeno,
                    title=f"Нов коментар на барање {nalog}",
                    body=f"{current_user}: {comment[:80] if comment else '[Слика]'}",
                    url="/nabavki",
                )
                notify_nov_komentar(nalog, naslov, comment or "[Слика]", current_user, prevzemeno)
            else:
                send_push_to_nabavki_group(
                    title=f"Нов коментар на барање {nalog}",
                    body=f"{current_user}: {comment[:80] if comment else '[Слика]'}",
                    url="/nabavki",
                    exclude_user=current_user,
                )
        else:
            if creator and creator != current_user:
                send_push_to_user(
                    creator,
                    title=f"Нов коментар на барање {nalog}",
                    body=f"{current_user}: {comment[:80] if comment else '[Слика]'}",
                    url="/nabavki",
                )
                notify_nov_komentar(nalog, naslov, comment or "[Слика]", current_user, creator)

        return {"success": True, "message": "Коментарот е успешно додаден!"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {str(e)}"}
    finally:
        conn.close()


def take_request(req_id, current_user, user_group, is_admin):
    if not (user_group == "Nabavki" or is_admin):
        return {"success": False, "message": "Немате дозвола да превземате барања!"}

    conn = get_db()
    cursor = conn.cursor()
    existing = cursor.execute(
        "SELECT prevzemeno_od, nalog_broj, username, naslov FROM nabavki_requests WHERE id=?",
        (req_id,),
    ).fetchone()

    if existing and existing["prevzemeno_od"]:
        conn.close()
        return {
            "success": False,
            "message": f'Ова барање веќе е превземено од {existing["prevzemeno_od"]}',
            "level": "warning",
        }

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            UPDATE nabavki_requests
            SET prevzemeno_od=?, datum_prevzemanje=?, status='Videno'
            WHERE id=?
            """,
            (current_user, now, req_id),
        )
        conn.commit()

        creator = existing["username"] if existing else None
        nalog = existing["nalog_broj"] if existing else "?"
        naslov = existing["naslov"] if existing else "?"

        if creator and creator != current_user:
            send_push_to_user(
                creator,
                title="Вашето барање е превземено",
                body=f"Барање {nalog} го превзеде {current_user}",
                url="/nabavki",
            )
        notify_promena_status(
            nalog=nalog,
            naslov=naslov,
            star_status="креирано",
            nov_status="Videno",
            kreator=creator,
            promeneto_od=current_user,
        )
        return {"success": True, "message": f"Барањето е превземено од {current_user}!", "level": "success"}
    except Exception as e:
        return {"success": False, "message": f"Грешка: {str(e)}"}
    finally:
        conn.close()


def transfer_request(req_id, current_user, user_group, is_admin, new_user):
    if not (user_group == "Nabavki" or is_admin):
        return {"success": False, "message": "Немате дозвола да префрлате барања!"}
    if not new_user:
        return {"success": False, "message": "Изберете корисник за префрлање!", "level": "warning"}

    conn = get_db()
    cursor = conn.cursor()

    valid_user = cursor.execute(
        """
        SELECT username FROM users
        WHERE username = ? AND (user_group = 'Nabavki' OR is_admin = 1)
        """,
        (new_user,),
    ).fetchone()
    if not valid_user:
        conn.close()
        return {
            "success": False,
            "message": "Корисникот не постои или не е во групата Набавки!",
        }

    existing = cursor.execute(
        "SELECT prevzemeno_od, nalog_broj, username, naslov FROM nabavki_requests WHERE id=?",
        (req_id,),
    ).fetchone()
    if not existing:
        conn.close()
        return {"success": False, "message": "Барањето не постои!"}

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stari_korisnik = existing["prevzemeno_od"] or "—"
        nalog = existing["nalog_broj"]
        creator = existing["username"]
        naslov = existing["naslov"]

        cursor.execute(
            "UPDATE nabavki_requests SET prevzemeno_od = ?, datum_prevzemanje = ? WHERE id = ?",
            (new_user, now, req_id),
        )
        komentar = f"Барањето е префрлено од {stari_korisnik} → {new_user} (од {current_user})"
        cursor.execute(
            "INSERT INTO nabavki_comments (req_id, user, comment) VALUES (?, ?, ?)",
            (req_id, current_user, komentar),
        )
        conn.commit()

        send_push_to_user(
            new_user,
            title="Ново префрлено барање!",
            body=f"Барање {nalog} ти е префрлено од {current_user}",
            url="/nabavki",
        )
        if stari_korisnik != "—" and stari_korisnik != new_user:
            send_push_to_user(
                stari_korisnik,
                title="Барањето ти е префрлено",
                body=f"Барање {nalog} е префрлено на {new_user} од {current_user}",
                url="/nabavki",
            )
        notify_nov_komentar(nalog, naslov, komentar, current_user, new_user)

        return {"success": True, "message": f"Барањето {nalog} е префрлено на {new_user}!", "level": "success"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Грешка при префрлање: {str(e)}"}
    finally:
        conn.close()


def update_request_status(req_id, new_status, current_user, is_admin=False, user_group=""):
    valid_statuses = {"Videno", "Naracano", "Dostaveno", "Zavrseno", "Prevzemeno", "Otkazano"}
    if new_status not in valid_statuses:
        return {"success": False, "message": "Невалиден статус!"}
    if not (is_admin or user_group == "Nabavki"):
        return {"success": False, "message": "Немате дозвола да менувате статус на барања!"}

    conn = get_db()
    cursor = conn.cursor()
    try:
        archive_notification = None
        request_data = cursor.execute("SELECT * FROM nabavki_requests WHERE id=?", (req_id,)).fetchone()
        if not request_data:
            return {"success": False, "message": "Барањето не постои!"}

        old_status = request_data["status"]
        nalog = request_data["nalog_broj"]
        naslov = request_data["naslov"]
        creator = request_data["username"]
        prevzemeno_od = request_data["prevzemeno_od"]

        cursor.execute("UPDATE nabavki_requests SET status=? WHERE id=?", (new_status, req_id))

        success_message = f"Статусот е сменет на {new_status}!"
        if new_status in {"Zavrseno", "Otkazano"}:
            max_row = cursor.execute(
                """
                SELECT MAX(CAST(SUBSTR(arhiva_broj, 4) AS INTEGER)) AS max_num
                FROM nabavki_archive WHERE arhiva_broj LIKE 'Arh%'
                """
            ).fetchone()
            next_num = (max_row["max_num"] or 0) + 1
            arhiva_broj = f"Arh{next_num:03d}"

            cursor.execute(
                """
                INSERT OR REPLACE INTO nabavki_archive
                (id, username, naslov, kolicina, opis, slika, datum_kreiranje, status,
                 datum_naracka, datum_priem, admin_naracal, datum_itnost, nalog_broj,
                 prevzemeno_od, datum_prevzemanje, arhivirano_od, arhiva_broj)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    request_data["id"],
                    request_data["username"],
                    request_data["naslov"],
                    request_data["kolicina"],
                    request_data["opis"],
                    request_data["slika"],
                    request_data["datum_kreiranje"],
                    new_status,
                    request_data["datum_naracka"],
                    request_data["datum_priem"],
                    request_data["admin_naracal"],
                    request_data["datum_itnost"],
                    request_data["nalog_broj"],
                    request_data["prevzemeno_od"],
                    request_data["datum_prevzemanje"],
                    current_user,
                    arhiva_broj,
                ),
            )

            ensure_comment_slika_column(cursor)
            ensure_archive_comments_table(cursor)
            comments = cursor.execute(
                """
                SELECT user, comment, timestamp, slika FROM nabavki_comments
                WHERE req_id=? ORDER BY timestamp ASC
                """,
                (req_id,),
            ).fetchall()
            for comment in comments:
                cursor.execute(
                    """
                    INSERT INTO nabavki_archive_comments
                        (archive_req_id, user, comment, slika, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (req_id, comment["user"], comment["comment"], comment["slika"], comment["timestamp"]),
                )

            cursor.execute("DELETE FROM nabavki_comments WHERE req_id=?", (req_id,))
            cursor.execute("DELETE FROM nabavki_requests WHERE id=?", (req_id,))
            archive_action = "завршено" if new_status == "Zavrseno" else "откажано"
            archive_notification = {
                "title": "Барање архивирано",
                "body": f"Барање {nalog} е завршено и архивирано.",
                "url": "/nabavki/arhiva",
            }
            success_message = f"Барањето {nalog} е архивирано како {arhiva_broj}!"

        conn.commit()

        for recipient in {creator, prevzemeno_od} - {None, current_user}:
            send_push_to_user(
                recipient,
                title=f"Ажурирање на барање {nalog}",
                body=f"Статусот е сменет од {old_status} → {new_status}",
                url="/nabavki",
            )

        notify_promena_status(
            nalog=nalog,
            naslov=naslov,
            star_status=old_status,
            nov_status=new_status,
            kreator=creator,
            promeneto_od=current_user,
        )
        return {"success": True, "message": success_message, "level": "success"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {str(e)}"}
    finally:
        conn.close()


def upload_request_image(req_id, current_user, is_admin, user_group, slika_file, static_folder):
    conn = get_db()
    cursor = conn.cursor()
    req_row = cursor.execute(
        "SELECT username, slika, nalog_broj FROM nabavki_requests WHERE id=?",
        (req_id,),
    ).fetchone()

    if not req_row:
        conn.close()
        return {"success": False, "message": "Барањето не постои!"}

    if not (is_admin or current_user == req_row["username"] or user_group == "Nabavki"):
        conn.close()
        return {"success": False, "message": "Немате дозвола!"}

    if req_row["slika"]:
        conn.close()
        return {"success": False, "message": "Ова барање веќе има прикачена слика!", "level": "warning"}

    if not slika_file or not slika_file.filename:
        conn.close()
        return {"success": False, "message": "Нема избрана слика!", "level": "warning"}

    try:
        save_dir = os.path.join(static_folder, "nabavki")
        filename_base = f"req_{req_id}_{int(time.time())}_{current_user}"
        slika_filename = save_compressed_image(slika_file, save_dir, filename_base)
        if not slika_filename:
            return {"success": False, "message": "Грешка при зачувување на сликата!"}

        cursor.execute(
            "UPDATE nabavki_requests SET slika=? WHERE id=?",
            (slika_filename, req_id),
        )
        conn.commit()
        return {
            "success": True,
            "message": f"Сликата е успешно прикачена на барање {req_row['nalog_broj']}!",
            "level": "success",
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Грешка: {str(e)}"}
    finally:
        conn.close()
