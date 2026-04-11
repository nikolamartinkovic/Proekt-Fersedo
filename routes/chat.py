"""
routes/chat.py — Целосен чат: глобален + DM + нотификации
"""

from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for
from datetime import datetime

from utils.db import get_db
from utils.decorators import login_required, user_has_module

chat_bp = Blueprint("chat", __name__)


@chat_bp.before_request
def ensure_chat_access():
    if "user" not in session:
        return None
    if user_has_module("chat"):
        return None
    flash("Немате дозвола за пристап до модулот Чат.", "danger")
    return redirect(url_for("auth.index"))


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        today = datetime.now().date()
        if dt.date() == today:
            return dt.strftime("%H:%M")
        return dt.strftime("%d-%m-%Y %H:%M")
    except:
        return dt_str


def _get_or_create_global_room(conn):
    room = conn.execute("SELECT id FROM chat_rooms WHERE tip='global'").fetchone()
    if not room:
        conn.execute("INSERT INTO chat_rooms (tip, ime) VALUES ('global', 'Општ чат')")
        conn.commit()
        room = conn.execute("SELECT id FROM chat_rooms WHERE tip='global'").fetchone()
    return room["id"]


def _get_unread(conn, me):
    """Врати dict {room_id: unread_count} за дадениот корисник."""
    rows = conn.execute("""
        SELECT cm.room_id,
               COUNT(*) AS cnt
        FROM chat_messages cm
        LEFT JOIN chat_read cr
            ON cr.room_id = cm.room_id AND cr.username = ?
        WHERE cm.sender != ?
          AND cm.id > COALESCE(cr.last_read_id, 0)
        GROUP BY cm.room_id
    """, (me, me)).fetchall()
    return {r["room_id"]: r["cnt"] for r in rows}


def _mark_read(conn, room_id, me):
    last = conn.execute(
        "SELECT MAX(id) AS mx FROM chat_messages WHERE room_id=?", (room_id,)
    ).fetchone()
    last_id = last["mx"] or 0
    conn.execute("""
        INSERT INTO chat_read (room_id, username, last_read_id)
        VALUES (?,?,?)
        ON CONFLICT(room_id, username) DO UPDATE SET last_read_id=excluded.last_read_id
    """, (room_id, me, last_id))
    conn.commit()


# ─────────────────────────────────────────────────────────────
# FULL-PAGE CHAT  /chat/page
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/page")
@login_required
def chat_page():
    me = session["user"]
    conn = get_db()

    global_room_id = _get_or_create_global_room(conn)

    # DM листа
    dm_rooms = conn.execute("""
        SELECT cr.id,
               CASE WHEN cr.user1=? THEN cr.user2 ELSE cr.user1 END AS other,
               (SELECT text FROM chat_messages
                WHERE room_id=cr.id ORDER BY id DESC LIMIT 1) AS last_msg,
               (SELECT timestamp FROM chat_messages
                WHERE room_id=cr.id ORDER BY id DESC LIMIT 1) AS last_ts
        FROM chat_rooms cr
        WHERE cr.tip='dm' AND (cr.user1=? OR cr.user2=?)
        ORDER BY last_ts DESC NULLS LAST
    """, (me, me, me)).fetchall()

    unread = _get_unread(conn, me)

    dm_list = []
    for dm in dm_rooms:
        dm_list.append({
            "id": dm["id"],
            "other": dm["other"],
            "last_msg": dm["last_msg"] or "",
            "unread": unread.get(dm["id"], 0),
        })

    # Сите корисници (за DM modal)
    users = conn.execute(
        "SELECT username FROM users WHERE username != ? ORDER BY username", (me,)
    ).fetchall()

    # Отвори ја глобалната соба по default
    open_room = global_room_id

    conn.close()

    return render_template(
        "chat_page.html",
        me=me,
        global_room_id=global_room_id,
        dm_list=dm_list,
        users=users,
        open_room=open_room,
        unread=unread,
    )


# ─────────────────────────────────────────────────────────────
# GLOBAL ROOM ID (за chat widget во base.html)
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/global_room")
@login_required
def global_room():
    conn = get_db()
    room_id = _get_or_create_global_room(conn)
    conn.close()
    return jsonify({"room_id": room_id})


# ─────────────────────────────────────────────────────────────
# WIDGET  /chat  (мал прозорец долу-десно)
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat")
@login_required
def chat_window():
    me = session["user"]
    conn = get_db()
    global_room_id = _get_or_create_global_room(conn)
    conn.close()
    return render_template("chat_window.html", me=me, global_room_id=global_room_id)


# ─────────────────────────────────────────────────────────────
# SEND MESSAGE
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/send", methods=["POST"])
@login_required
def send():
    data = request.get_json() or {}
    room_id = data.get("room_id")
    text = (data.get("text") or "").strip()

    if not room_id or not text:
        return jsonify({"error": "Нема текст"}), 400

    me = session["user"]
    conn = get_db()

    # Провери дали room_id постои и дали корисникот има пристап
    room = conn.execute("SELECT * FROM chat_rooms WHERE id=?", (room_id,)).fetchone()
    if not room:
        conn.close()
        return jsonify({"error": "Собата не постои"}), 404
    if room["tip"] == "dm" and me not in (room["user1"], room["user2"]):
        conn.close()
        return jsonify({"error": "Нема пристап"}), 403

    ts = _now_str()
    conn.execute(
        "INSERT INTO chat_messages (room_id, sender, text, timestamp, tip) VALUES (?,?,?,?,?)",
        (room_id, me, text, ts, room["tip"])
    )
    # Означи ја пораката прочитана за испраќачот
    last = conn.execute("SELECT MAX(id) AS mx FROM chat_messages WHERE room_id=?", (room_id,)).fetchone()
    message_id = last["mx"] or 0
    _mark_read(conn, room_id, me)
    conn.commit()
    conn.close()

    return jsonify({"ok": True, "ts": _fmt(ts), "message_id": message_id})


# ─────────────────────────────────────────────────────────────
# HISTORY (прв вчит на соба)
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/history")
@login_required
def history():
    room_id = request.args.get("room_id", type=int)
    me = session["user"]

    if not room_id:
        return jsonify({"messages": []})

    conn = get_db()

    # Пристап
    room = conn.execute("SELECT * FROM chat_rooms WHERE id=?", (room_id,)).fetchone()
    if not room:
        conn.close()
        return jsonify({"messages": []})
    if room["tip"] == "dm" and me not in (room["user1"], room["user2"]):
        conn.close()
        return jsonify({"messages": [], "error": "no access"})

    msgs = conn.execute("""
        SELECT id, sender, text, timestamp
        FROM chat_messages
        WHERE room_id=?
        ORDER BY id ASC
        LIMIT 100
    """, (room_id,)).fetchall()

    _mark_read(conn, room_id, me)
    conn.commit()
    conn.close()

    messages = [{
        "id": m["id"],
        "sender": m["sender"],
        "text": m["text"],
        "ts": _fmt(m["timestamp"]),
        "mine": m["sender"] == me
    } for m in msgs]

    return jsonify({"messages": messages})


# ─────────────────────────────────────────────────────────────
# POLL (нови пораки + unread)
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/messages")
@login_required
def get_messages():
    room_id = request.args.get("room_id", type=int)
    after = request.args.get("after", 0, type=int)
    me = session["user"]

    if not room_id:
        return jsonify({"messages": [], "unread": {}, "total_unread": 0})

    conn = get_db()

    msgs = conn.execute("""
        SELECT id, sender, text, timestamp
        FROM chat_messages
        WHERE room_id=? AND id>?
        ORDER BY id ASC LIMIT 50
    """, (room_id, after)).fetchall()

    if msgs:
        _mark_read(conn, room_id, me)

    unread = _get_unread(conn, me)
    total = sum(unread.values())
    conn.commit()
    conn.close()

    messages = [{
        "id": m["id"],
        "sender": m["sender"],
        "text": m["text"],
        "ts": _fmt(m["timestamp"]),
        "mine": m["sender"] == me
    } for m in msgs]

    return jsonify({
        "messages": messages,
        "unread": {str(k): v for k, v in unread.items()},
        "total_unread": total
    })


# ─────────────────────────────────────────────────────────────
# UNREAD (само badge brojki)
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/unread")
@login_required
def unread_counts():
    me = session["user"]
    conn = get_db()
    unread = _get_unread(conn, me)
    conn.close()
    total = sum(unread.values())
    return jsonify({
        "per_room": {str(k): v for k, v in unread.items()},
        "total": total
    })


# ─────────────────────────────────────────────────────────────
# ОТВОРИ / КРЕИРАЈ DM СОБА
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/dm/open", methods=["POST"])
@login_required
def open_dm():
    data = request.get_json() or {}
    other = (data.get("username") or "").strip()
    me = session["user"]

    if not other or other == me:
        return jsonify({"error": "Невалиден корисник"}), 400

    conn = get_db()

    # Провери дали корисникот постои
    u = conn.execute("SELECT username FROM users WHERE username=?", (other,)).fetchone()
    if not u:
        conn.close()
        return jsonify({"error": "Корисникот не постои"}), 404

    # Барај постоечка DM соба
    room = conn.execute("""
        SELECT id FROM chat_rooms
        WHERE tip='dm'
          AND ((user1=? AND user2=?) OR (user1=? AND user2=?))
    """, (me, other, other, me)).fetchone()

    if room:
        room_id = room["id"]
    else:
        conn.execute(
            "INSERT INTO chat_rooms (tip, user1, user2) VALUES ('dm',?,?)",
            (me, other)
        )
        conn.commit()
        room_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    conn.close()
    return jsonify({"ok": True, "room_id": room_id, "other": other})


# ─────────────────────────────────────────────────────────────
# INFO ЗА DM СОБА (за auto-add во sidebar)
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/dm/info")
@login_required
def dm_info():
    room_id = request.args.get("room_id", type=int)
    me = session["user"]
    if not room_id:
        return jsonify({"error": "no room_id"}), 400
    conn = get_db()
    room = conn.execute(
        "SELECT * FROM chat_rooms WHERE id=? AND tip='dm'", (room_id,)
    ).fetchone()
    conn.close()
    if not room or me not in (room["user1"], room["user2"]):
        return jsonify({"error": "not found"}), 404
    other = room["user2"] if room["user1"] == me else room["user1"]
    return jsonify({"room_id": room_id, "other": other})


# ─────────────────────────────────────────────────────────────
# ЛИСТА НА КОРИСНИЦИ (за DM modal)
# ─────────────────────────────────────────────────────────────
@chat_bp.route("/chat/users")
@login_required
def user_list():
    me = session["user"]
    conn = get_db()
    users = conn.execute(
        "SELECT username FROM users WHERE username != ? ORDER BY username", (me,)
    ).fetchall()
    conn.close()
    return jsonify({"users": [u["username"] for u in users]})
