from functools import wraps
from flask import flash, redirect, session, url_for


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Морате прво да се најавите!", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Оваа страница е само за администратори!", "error")
            return redirect(url_for("main.select_kamin"))
        return f(*args, **kwargs)
    return decorated


def worker_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("is_admin"):
            flash("Администраторот не може да внесува нови записи!", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated

def module_required(module_name):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("is_admin"):
                return f(*args, **kwargs)
            allowed = [m.strip() for m in session.get("allowed_modules", "").split(",")]
            if module_name not in allowed:
                flash("Немате дозвола за пристап до овој модул!", "danger")
                return redirect(url_for("auth.index"))
            return f(*args, **kwargs)
        return decorated
    return decorator