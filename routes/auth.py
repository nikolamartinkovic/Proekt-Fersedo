# routes/auth.py
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from datetime import datetime
from argon2 import exceptions
from utils.decorators import login_required, admin_required, worker_required

from extensions import ph
from utils.db import get_db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user:
            try:
                ph.verify(user["hashed_password"], password)
                session["user"] = username
                session["is_admin"] = bool(user["is_admin"])
                session["user_group"] = user.get("user_group", "")
                session["allowed_modules"] = user.get("allowed_modules", "")
                flash("Успешно најавување!", "success")
                return redirect(url_for("auth.index"))
            except exceptions.VerifyMismatchError:
                pass
        flash("Погрешно корисничко име или лозинка!", "error")
    return render_template(
        'login.html',
        current_year=datetime.now().strftime('%Y')
    )

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Успешно одјавување.", "success")
    return redirect(url_for("auth.login"))

@auth_bp.route("/")
@login_required
def index():
    if session.get("is_admin"):
        return redirect(url_for("admin.dashboard"))

    allowed = [m.strip() for m in session.get("allowed_modules", "").split(",") if m.strip()]
    if not allowed:
        flash("Немате дозволен пристап до ниту еден модул. Контактирајте го администраторот.", "warning")
        return redirect(url_for("auth.login"))

    # Сите одмори модули — ако корисникот има кој било од нив, оди на главна одмори страница
    odmori_modules = {
        "odmori", "baranje_odmor", "odmori_vraboteni",
        "odmori_kalendar", "odmori_pregled_odmori",
        "odmori_sekojdnevni_otsustva", "odmori_manager_emails",
    }
    if any(m in odmori_modules for m in allowed):
        return redirect(url_for("main.odmori"))

    # Точни blueprint endpoints за секој модул
    module_map = {
    "select_kamin":      "main.select_kamin",
    "add_part":          "artikli.add",
    "moj_zapisi":        "main.moj_zapisi",
    "kalkulacija":       "main.kalkulacija",
    "artikli":           "artikli.artikli",
    "nabavki":           "nabavki.nabavki",
    "dashboard":         "admin.dashboard",
    "pregled_greski":    "admin.pregled_greski",
    "admin_users":       "admin.admin_users",
    "plan_proizvodstvo": "main.plan_proizvodstvo",
    "izvestaj":          "main.izvestaj",
    "procesni_cekori":   "admin.procesni_cekori",
    "zalihi":            "zalihi.zalihi",
    "email_recipients":  "admin.email_recipients",
    # ✅ ПОПРАВЕНО: вистински имиња на квалитет модули
    "kvalitet_nova":     "kvalitet.kvalitet",
    "kvalitet_arhiva":   "kvalitet.kvalitet",
    "kvalitet_template": "kvalitet.kvalitet",
}

    for mod in allowed:
        route = module_map.get(mod)
        if route:
            return redirect(url_for(route))

    flash("Немате дозволен пристап до ниту еден активен модул.", "warning")
    return redirect(url_for("auth.login"))