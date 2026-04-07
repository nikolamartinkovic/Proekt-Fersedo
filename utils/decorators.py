from functools import wraps

from flask import flash, redirect, session, url_for


def user_has_module(module_names):
    if session.get("is_admin"):
        return True
    if isinstance(module_names, str):
        module_names = [module_names]
    allowed = {
        module_name.strip()
        for module_name in (session.get("allowed_modules") or "").split(",")
        if module_name.strip()
    }
    return any(module_name in allowed for module_name in module_names)


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
            if not user_has_module(module_name):
                flash("Немате дозвола за пристап до овој модул!", "danger")
                return redirect(url_for("auth.index"))
            return f(*args, **kwargs)

        return decorated

    return decorator


def admin_or_module_required(module_name, redirect_endpoint="auth.index"):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not user_has_module(module_name):
                flash("Немате дозвола за пристап до овој модул!", "danger")
                return redirect(url_for(redirect_endpoint))
            return f(*args, **kwargs)

        return decorated

    return decorator
