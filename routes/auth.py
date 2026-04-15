# routes/auth.py
import hashlib
from datetime import datetime

from argon2 import exceptions
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import ph
from utils.audit import log_audit_event
from utils.db import get_db
from utils.decorators import admin_required, login_required, worker_required
from utils.emailing import send_password_change_verification_email
from utils.active_users import remove_active_user, touch_active_user

auth_bp = Blueprint("auth", __name__)

PASSWORD_CHANGE_TOKEN_SALT = "fersedo-password-change"
PASSWORD_CHANGE_TOKEN_MAX_AGE = 30 * 60


def _password_change_serializer():
    return URLSafeTimedSerializer(current_app.secret_key)


def _password_change_marker(user):
    hashed_password = (user.get("hashed_password") or "").encode("utf-8")
    return hashlib.sha256(hashed_password).hexdigest()[:20]


def _mask_email(email):
    if not email or "@" not in email:
        return email or "непозната адреса"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[:2] + "*" * max(2, len(local) - 2)
    return f"{masked_local}@{domain}"


def _build_password_change_token(user):
    payload = {
        "username": user["username"],
        "email": (user.get("email") or "").strip().lower(),
        "marker": _password_change_marker(user),
    }
    return _password_change_serializer().dumps(payload, salt=PASSWORD_CHANGE_TOKEN_SALT)


def _load_password_change_user(token):
    try:
        payload = _password_change_serializer().loads(
            token,
            salt=PASSWORD_CHANGE_TOKEN_SALT,
            max_age=PASSWORD_CHANGE_TOKEN_MAX_AGE,
        )
    except SignatureExpired:
        return None, "Линкот за потврда е истечен. Побарајте нов email за промена на лозинка."
    except BadSignature:
        return None, "Линкот за потврда не е валиден."

    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    marker = payload.get("marker") or ""

    if not username or not email or not marker:
        return None, "Линкот за потврда не содржи валидни податоци."

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT username, email, hashed_password, must_change_password FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()

    if not user:
        return None, "Корисникот за овој линк повеќе не постои."

    if (user.get("email") or "").strip().lower() != email:
        return None, "Email адресата на корисникот е променета. Побарајте нов линк."

    if _password_change_marker(user) != marker:
        return None, "Линкот веќе не важи затоа што лозинката е променета. Побарајте нов линк."

    return user, None


def _validate_new_password(new_password, confirm_password, current_hash):
    if not new_password or not confirm_password:
        return "Пополнете ги сите полиња за промена на лозинка."

    if new_password != confirm_password:
        return "Новата лозинка и потврдата не се совпаѓаат."

    if len(new_password) < 8:
        return "Новата лозинка мора да има најмалку 8 карактери."

    try:
        ph.verify(current_hash, new_password)
        return "Новата лозинка мора да биде различна од тековната."
    except exceptions.VerifyMismatchError:
        return None


def _save_new_password(username, new_password):
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE users
            SET hashed_password = ?, must_change_password = 0
            WHERE username = ?
            """,
            (ph.hash(new_password), username),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        if session.get("must_change_password"):
            return redirect(url_for("auth.change_password"))
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
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
                session["must_change_password"] = bool(user.get("must_change_password"))
                touch_active_user(
                    username=username,
                    endpoint="auth.login",
                    path=request.path,
                    ip_address=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
                    user_agent=request.user_agent.string if request.user_agent else "",
                )
                log_audit_event(
                    "auth",
                    "login",
                    status="success",
                    details=f"Успешна најава за {username}",
                    username=username,
                )
                if session["must_change_password"]:
                    flash("Мора да ја промените привремената лозинка пред да продолжите.", "warning")
                    return redirect(url_for("auth.change_password"))
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
        remove_active_user(username)
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


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    force_change = bool(session.get("must_change_password"))
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT username, email, hashed_password, must_change_password FROM users WHERE username = ?",
            (session["user"],),
        ).fetchone()
    finally:
        conn.close()

    if not user:
        session.clear()
        flash("Корисникот не е пронајден. Најавете се повторно.", "danger")
        return redirect(url_for("auth.login"))

    email = (user.get("email") or "").strip()

    if force_change:
        if request.method == "POST":
            new_password = request.form.get("new_password") or ""
            confirm_password = request.form.get("confirm_password") or ""
            validation_error = _validate_new_password(new_password, confirm_password, user["hashed_password"])

            if validation_error:
                flash(validation_error, "danger")
                return render_template(
                    "change_password.html",
                    force_change=True,
                    direct_change=True,
                    verified=False,
                    verified_user=user["username"],
                )

            try:
                _save_new_password(user["username"], new_password)
            except Exception as exc:
                flash(f"Грешка при промена на лозинка: {exc}", "danger")
                return render_template(
                    "change_password.html",
                    force_change=True,
                    direct_change=True,
                    verified=False,
                    verified_user=user["username"],
                )

            session["must_change_password"] = False
            log_audit_event(
                "auth",
                "change_password",
                status="success",
                details=f"Променета привремена лозинка при прво најавување за {user['username']}",
                username=user["username"],
            )
            flash("Лозинката е успешно поставена. Можете да продолжите во системот.", "success")
            return redirect(url_for("main.welcome"))

        return render_template(
            "change_password.html",
            force_change=True,
            direct_change=True,
            verified=False,
            verified_user=user["username"],
        )

    if request.method == "POST":
        if not email:
            flash("Овој корисник нема внесена email адреса. Контактирајте администратор за да се додаде email.", "danger")
            return render_template(
                "change_password.html",
                force_change=force_change,
                direct_change=False,
                verified=False,
                has_email=False,
                masked_email="",
            )

        try:
            token = _build_password_change_token(user)
            verification_url = url_for("auth.change_password_verify", token=token, _external=True)
            send_password_change_verification_email(email, user["username"], verification_url)
            log_audit_event(
                "auth",
                "change_password_request",
                status="success",
                details=f"Испратен email за промена на лозинка за {user['username']}",
                username=user["username"],
            )
            flash(f"Испративме email за потврда на {email}. Отворете го линкот во пораката за да поставите нова лозинка.", "success")
            return redirect(url_for("auth.change_password"))
        except Exception as exc:
            log_audit_event(
                "auth",
                "change_password_request",
                status="error",
                details=f"Неуспешно праќање email за промена на лозинка: {exc}",
                username=user["username"],
            )
            flash(f"Грешка при праќање на email за потврда: {exc}", "danger")

    return render_template(
        "change_password.html",
        force_change=force_change,
        direct_change=False,
        verified=False,
        has_email=bool(email),
        masked_email=_mask_email(email),
    )


@auth_bp.route("/change-password/verify", methods=["GET", "POST"])
def change_password_verify():
    token = (request.values.get("token") or "").strip()
    if not token:
        flash("Недостасува линк за потврда на промена на лозинка.", "danger")
        if session.get("user"):
            return redirect(url_for("auth.change_password"))
        return redirect(url_for("auth.login"))

    user, error = _load_password_change_user(token)
    if error:
        flash(error, "danger")
        if session.get("user"):
            return redirect(url_for("auth.change_password"))
        return redirect(url_for("auth.login"))

    if session.get("user") and session["user"] != user["username"]:
        flash("Овој линк е наменет за друг корисник. Одјавете се и обидете се повторно.", "danger")
        return redirect(url_for("auth.change_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        validation_error = _validate_new_password(new_password, confirm_password, user["hashed_password"])
        if validation_error:
            flash(validation_error, "danger")
            return render_template(
                "change_password.html",
                force_change=bool(session.get("must_change_password") and session.get("user") == user["username"]),
                direct_change=False,
                verified=True,
                token=token,
                verified_user=user["username"],
            )

        try:
            _save_new_password(user["username"], new_password)
        except Exception as exc:
            flash(f"Грешка при промена на лозинка: {exc}", "danger")
            return render_template(
                "change_password.html",
                force_change=bool(session.get("must_change_password") and session.get("user") == user["username"]),
                direct_change=False,
                verified=True,
                token=token,
                verified_user=user["username"],
            )

        if session.get("user") == user["username"]:
            session["must_change_password"] = False
            destination = url_for("main.welcome")
        else:
            destination = url_for("auth.login")

        log_audit_event(
            "auth",
            "change_password",
            status="success",
            details=f"Променета лозинка за {user['username']} по email потврда",
            username=user["username"],
        )
        flash("Лозинката е успешно променета.", "success")
        return redirect(destination)

    return render_template(
        "change_password.html",
        force_change=bool(session.get("must_change_password") and session.get("user") == user["username"]),
        direct_change=False,
        verified=True,
        token=token,
        verified_user=user["username"],
    )


@auth_bp.route("/")
@login_required
def index():
    if session.get("must_change_password"):
        return redirect(url_for("auth.change_password"))

    if session.get("is_admin"):
        return redirect(url_for("main.welcome"))

    allowed = [m.strip() for m in (session.get("allowed_modules") or "").split(",") if m.strip()]
    if not allowed:
        flash("Немате дозволен пристап до ниту еден модул. Контактирајте го администраторот.", "warning")
        return redirect(url_for("auth.login"))

    return redirect(url_for("main.welcome"))
