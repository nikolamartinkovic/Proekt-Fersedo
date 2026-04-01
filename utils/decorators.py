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
            flash("РњРѕСЂР°С‚Рµ РїСЂРІРѕ РґР° СЃРµ РЅР°СР°РІРёС‚Рµ!", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("РћРІР°Р° СЃС‚СЂР°РЅРёС†Р° Рµ СЃР°РјРѕ Р·Р° Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРё!", "error")
            return redirect(url_for("main.select_kamin"))
        return f(*args, **kwargs)

    return decorated


def worker_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("is_admin"):
            flash("РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРѕС‚ РЅРµ РјРѕР¶Рµ РґР° РІРЅРµСЃСѓРІР° РЅРѕРІРё Р·Р°РїРёСЃРё!", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)

    return decorated


def module_required(module_name):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not user_has_module(module_name):
                flash("РќРµРјР°С‚Рµ РґРѕР·РІРѕР»Р° Р·Р° РїСЂРёСЃС‚Р°Рї РґРѕ РѕРІРѕС РјРѕРґСѓР»!", "danger")
                return redirect(url_for("auth.index"))
            return f(*args, **kwargs)

        return decorated

    return decorator


def admin_or_module_required(module_name, redirect_endpoint="auth.index"):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not user_has_module(module_name):
                flash("РќРµРјР°С‚Рµ РґРѕР·РІРѕР»Р° Р·Р° РїСЂРёСЃС‚Р°Рї РґРѕ РѕРІРѕС РјРѕРґСѓР»!", "danger")
                return redirect(url_for(redirect_endpoint))
            return f(*args, **kwargs)

        return decorated

    return decorator
