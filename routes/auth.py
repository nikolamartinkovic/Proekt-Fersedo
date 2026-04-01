# routes/auth.py
from datetime import datetime

from argon2 import exceptions
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from extensions import ph
from utils.audit import log_audit_event
from utils.db import get_db
from utils.decorators import admin_required, login_required, worker_required

auth_bp = Blueprint("auth", __name__)


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
                session["user_group"] = user.get("user_group") or ""
                session["allowed_modules"] = user.get("allowed_modules") or ""
                log_audit_event(
                    "auth",
                    "login",
                    status="success",
                    details=f"Успешна најава за {username}",
                    username=username,
                )
                flash("Успешно најавување!", "success")
                return redirect(url_for("auth.index"))
            except exceptions.VerifyMismatchError:
                pass

        log_audit_event(
            "auth",
            "login",
            status="warning",
            details=f"Неуспешна најава за {username or 'непознат корисник'}",
            username=username or "",
        )
        flash("Погрешно корисничко име или лозинка!", "error")

    return render_template("login.html", current_year=datetime.now().strftime("%Y"))


@auth_bp.route("/logout")
def logout():
    username = session.get("user", "")
    if username:
        log_audit_event(
            "auth",
            "logout",
            status="info",
            details=f"Одјава за {username}",
            username=username,
        )
    session.clear()
    flash("Успешно одјавување.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/")
@login_required
def index():
    if session.get("is_admin"):
        return redirect(url_for("main.welcome"))

    allowed = [m.strip() for m in (session.get("allowed_modules") or "").split(",") if m.strip()]
    if not allowed:
        flash("Немате дозволен пристап до ниту еден модул. Контактирајте го администраторот.", "warning")
        return redirect(url_for("auth.login"))

    return redirect(url_for("main.welcome"))
