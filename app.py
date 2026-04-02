"""
Fersedo Production Management System
=====================================
Flask web application for managing production, procurement, employees, and vacations.
"""
# ─────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory, session, url_for
from pywebpush import webpush

from extensions import db, migrate
from config import Config
from utils.app_updates import announce_android_release_if_needed
from utils.app_bootstrap import register_blueprints, register_fonts
from utils.db import init_db, get_db
from utils.config import FONT_DIR, POZICII_FOLDER, STATIC_FOLDER, TEMPLATE_FOLDER
from utils.decorators import login_required
from utils.nabavki_images import is_allowed_image_extension, validate_uploaded_image
from utils.notifications import fetch_mobile_notifications
from utils.parts import get_part_info
from utils.runtime import configure_logging, register_healthcheck, resolve_bind_host
from utils.scheduler_jobs import init_scheduler




# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────
VAPID_PUBLIC_KEY  = Config.VAPID_PUBLIC_KEY
VAPID_PRIVATE_KEY = Config.VAPID_PRIVATE_KEY
VAPID_SUBJECT     = Config.VAPID_SUBJECT

AUTO_ASSIGN_INTERVAL_SECONDS = Config.AUTO_ASSIGN_INTERVAL_SECONDS
BASE_DIR = Path(__file__).resolve().parent
ANDROID_BUILD_FILE = BASE_DIR / "android" / "app" / "build.gradle.kts"
ANDROID_RELEASE_APK = BASE_DIR / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"

# ─────────────────────────────────────────────────────────────
# APP INIT
# ─────────────────────────────────────────────────────────────
app = Flask(__name__,
    static_folder=STATIC_FOLDER,
    static_url_path="/static",
    template_folder=TEMPLATE_FOLDER,
)

init_db()

# ── Blueprints ──────────────────────────────────────────────
# ── Blueprints ──────────────────────────────────────────────

# Регистрирање на сите blueprints

# ==================== CHAT BLUEPRINT ====================
# Ова мора да биде на крајот и после креирањето на __init__.py

app.config.from_object(Config)
db.init_app(app)
migrate.init_app(app, db)
register_blueprints(app)
configure_logging(app)
register_healthcheck(app)

app.secret_key = app.config["SECRET_KEY"]


@app.before_request
def normalize_session_state():
    allowed_modules = session.get("allowed_modules")
    if allowed_modules is None:
        session["allowed_modules"] = ""
    elif isinstance(allowed_modules, (list, tuple, set)):
        session["allowed_modules"] = ",".join(str(module).strip() for module in allowed_modules if str(module).strip())
    elif not isinstance(allowed_modules, str):
        session["allowed_modules"] = str(allowed_modules)

    user_group = session.get("user_group")
    if user_group is None:
        session["user_group"] = ""
    elif not isinstance(user_group, str):
        session["user_group"] = str(user_group)

# ─────────────────────────────────────────────────────────────
# FONT REGISTRATION
# ─────────────────────────────────────────────────────────────
register_fonts(FONT_DIR)

# ─────────────────────────────────────────────────────────────
# CONTEXT PROCESSORS & TEMPLATE FILTERS
# ─────────────────────────────────────────────────────────────
@app.after_request
def set_no_cache_headers(response):
    if response.mimetype != "text/html":
        return response

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.context_processor
def inject_vapid_key():
    return dict(VAPID_PUBLIC_KEY=VAPID_PUBLIC_KEY)


def get_android_release_metadata():
    version_name = "1.0.0"
    version_code = 1

    if ANDROID_BUILD_FILE.exists():
        build_text = ANDROID_BUILD_FILE.read_text(encoding="utf-8", errors="ignore")
        version_name_match = re.search(r'versionName\s*=\s*"([^"]+)"', build_text)
        version_code_match = re.search(r"versionCode\s*=\s*(\d+)", build_text)
        if version_name_match:
            version_name = version_name_match.group(1).strip()
        if version_code_match:
            version_code = int(version_code_match.group(1))

    apk_exists = ANDROID_RELEASE_APK.exists()
    apk_last_updated = ""
    apk_last_updated_ts = 0
    apk_size = 0
    if apk_exists:
        apk_stat = ANDROID_RELEASE_APK.stat()
        apk_last_updated_ts = int(apk_stat.st_mtime)
        apk_last_updated = datetime.fromtimestamp(apk_last_updated_ts).strftime("%d-%m-%Y %H:%M")
        apk_size = apk_stat.st_size

    return {
        "available": apk_exists,
        "version_name": version_name,
        "version_code": version_code,
        "version_key": f"{version_name}-{version_code}-{apk_last_updated_ts}",
        "last_updated": apk_last_updated,
        "size_bytes": apk_size,
    }


@app.context_processor
def inject_app_install_meta():
    android_release = get_android_release_metadata()
    android_release["download_url"] = url_for("download_latest_android_apk")
    try:
        announce_android_release_if_needed(
            android_release,
            url_for("download_latest_android_apk", _external=True),
        )
    except Exception as exc:
        app.logger.warning("Android release announce failed in context processor: %s", exc)
    return {
        "app_install_meta": {
            "android": android_release,
            "web": {
                "name": "Fersedo Web App",
            },
        }
    }


@app.context_processor
def inject_modules():
    modules = {
        "basic": [
            {"value": "select_kamin",        "label": "Нов запис"},
            {"value": "add_part",            "label": "Отвори нов артикл"},
            {"value": "moj_zapisi",          "label": "Мои записи"},
            {"value": "kalkulacija",         "label": "Калкулација"},
            {"value": "artikli",             "label": "Артикли"},
            {"value": "dashboard",           "label": "Dashboard"},
            {"value": "system_logs",         "label": "Системски логови"},
            {"value": "pregled_greski",      "label": "Грешки"},
            {"value": "admin_users",         "label": "Корисници"},
            {"value": "email_recipients",    "label": "Email примачи"},
            {"value": "plan_proizvodstvo",   "label": "План за производство"},
            {"value": "izvestaj",            "label": "Извештај"},
            {"value": "procesni_cekori",     "label": "Процесни чекори"},
        ],
        "nabavki": [
            {"value": "nabavki",             "label": "Набавки"},
            {"value": "nabavki_arhiva",      "label": "Архива на набавки"},
            {"value": "ponudi",              "label": "Понуди"},
            {"value": "ponudi_arhiva",       "label": "Архива на понуди"},
            {"value": "sostanoci",           "label": "Состаноци"},
            {"value": "chat",                "label": "Чат"},
        ],
        "odmori": [
            {"value": "odmori",                      "label": "Одмори (главна)"},
            {"value": "baranje_odmor",               "label": "Барање за одмор"},
            {"value": "odmori_vraboteni",            "label": "Вработени"},
            {"value": "odmori_kalendar",             "label": "Календар"},
            {"value": "odmori_pregled_odmori",       "label": "Преглед на одмори"},
            {"value": "odmori_sekojdnevni_otsustva", "label": "Секојдневни отсуства"},
            {"value": "odmori_manager_emails",       "label": "📧 Email за менаџери"},
        ],
        "zalihi": [
            {"value": "zalihi",           "label": "Залихи"},
        ],
        "kvalitet": [
            {"value": "kvalitet",         "label": "Квалитет"},
            {"value": "kvalitet_nova",    "label": "Нова контрола"},
            {"value": "kvalitet_arhiva",  "label": "Архива на контроли"},
            {"value": "kvalitet_template","label": "QC Шаблони"},
        ],
    }
    return dict(modules=modules)


@app.template_filter("datetimeformat")
def datetimeformat(value, format_string="%d-%m-%Y %H:%M"):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        dt = value
    dt_local = dt.replace(tzinfo=timezone.utc) + timedelta(hours=1)
    return dt_local.strftime(format_string)

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
@app.route("/api/part_info")
@login_required
def api_part_info():
    part_number = request.args.get("part_number", "").strip()
    if not part_number:
        return jsonify({"success": False, "error": "Нема part number"})
    result = get_part_info(part_number)
    if result and result.get("slika"):
        return jsonify({"success": True, "slika": result["slika"], "ime": result.get("ime", "")})
    return jsonify({"success": False, "error": "Не е пронајден"})


@app.route("/debug_routes")
def debug_routes():
    routes = [(r.endpoint, r.rule) for r in app.url_map.iter_rules()]
    return jsonify(sorted(routes))


@app.route("/upload_temp_image", methods=["POST"])
@login_required
def upload_temp_image():
    if "slika" not in request.files:
        return jsonify({"success": False, "error": "Нема датотека"}), 400
    file = request.files["slika"]
    if not file.filename:
        return jsonify({"success": False, "error": "Празно ime"}), 400
    if not is_allowed_image_extension(file.filename):
        return jsonify({"success": False, "error": "Дозволени се само JPG, PNG и WEBP слики"}), 400
    try:
        validate_uploaded_image(file)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    filename = f"camera_{int(time.time() * 1000)}{ext}"
    os.makedirs(POZICII_FOLDER, exist_ok=True)
    file.save(os.path.join(POZICII_FOLDER, filename))
    return jsonify({"success": True, "filename": filename})


@app.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    subscription = request.json
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM push_subscriptions WHERE user=?", (session["user"],))
    cursor.execute("INSERT INTO push_subscriptions (user, subscription) VALUES (?,?)",
                   (session["user"], json.dumps(subscription)))
    conn.commit(); conn.close()
    return jsonify({"success": True})


@app.route("/test_push")
@login_required
def test_push():
    conn = get_db()
    sub_row = conn.execute(
        "SELECT subscription FROM push_subscriptions WHERE user=?", (session["user"],)
    ).fetchone()
    conn.close()
    if sub_row:
        try:
            webpush(
                subscription_info=json.loads(sub_row["subscription"]),
                data=json.dumps({"title": "Тест известување", "body": "Тест push од Fersedo!", "url": "/nabavki"}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
            return "Push испратен!"
        except Exception as e:
            return f"Грешка: {e}"
    return "Нема subscription"

@app.route("/api/mobile_notifications/poll")
@login_required
def mobile_notifications_poll():
    try:
        since_id = int(request.args.get("since_id", "0"))
    except ValueError:
        since_id = 0

    rows = fetch_mobile_notifications(session["user"], since_id=since_id, limit=20)
    last_id = since_id
    items = []
    for row in rows:
        last_id = max(last_id, row["id"])
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "body": row["body"],
                "url": row.get("url") or "/welcome",
                "category": row.get("category") or "general",
                "created_at": row.get("created_at", ""),
            }
        )

    return jsonify({"success": True, "last_id": last_id, "items": items})


@app.route('/manifest.json')
def manifest():
    return send_from_directory(app.static_folder, 'manifest.json')

@app.route('/sw.js')
def sw():
    return send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')


@app.route("/android/latest-apk")
def download_latest_android_apk():
    if not ANDROID_RELEASE_APK.exists():
        return jsonify({
            "success": False,
            "error": "Android APK не е достапен во моментов.",
        }), 404

    metadata = get_android_release_metadata()
    download_name = f"Fersedo-v{metadata['version_name']}.apk"
    return send_file(
        ANDROID_RELEASE_APK,
        mimetype="application/vnd.android.package-archive",
        as_attachment=True,
        download_name=download_name,
        max_age=0,
    )


@app.route("/android/release-meta")
def android_release_meta():
    metadata = get_android_release_metadata()
    metadata["download_url"] = url_for("download_latest_android_apk", _external=True)
    try:
        announce_android_release_if_needed(metadata, metadata["download_url"])
    except Exception as exc:
        app.logger.warning("Android release announce failed in release-meta: %s", exc)
    return jsonify({
        "success": True,
        "android": metadata,
    })

# ─────────────────────────────────────────────────────────────
# AUTO-ASSIGN  (логика останува овде, scheduler исто)
# ─────────────────────────────────────────────────────────────
# SCHEDULER
scheduler = init_scheduler(app, AUTO_ASSIGN_INTERVAL_SECONDS)

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ?????????????????????????????????????????????????????????????
if __name__ == "__main__":
    configured_host = os.getenv("APP_HOST", "0.0.0.0")
    bind_host = resolve_bind_host(configured_host)
    if bind_host != configured_host:
        print(f"[SERVER] APP_HOST={configured_host} не е достапен локално. Се користи {bind_host}.")

    ssl_context = None
    if os.getenv("APP_URL_SCHEME", "http").lower() == "https":
        cert_path = os.getenv("HTTPS_CERT_PATH", os.path.join(os.path.dirname(__file__), "192.168.0.20.pem"))
        key_path = os.getenv("HTTPS_KEY_PATH", os.path.join(os.path.dirname(__file__), "192.168.0.20-key.pem"))
        if os.path.exists(cert_path) and os.path.exists(key_path):
            ssl_context = (cert_path, key_path)

    app.run(
        host=bind_host,
        port=int(os.getenv("APP_PORT", "8080")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        use_reloader=False,
        threaded=True,
        ssl_context=ssl_context,
    )
