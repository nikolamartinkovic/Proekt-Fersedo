import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def register_fonts(font_dir):
    for name, filename in [
        ("DejaVuSans", "DejaVuSans.ttf"),
        ("DejaVuSans-Bold", "DejaVuSans-Bold.ttf"),
    ]:
        path = os.path.join(font_dir, filename)
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception as exc:
                print(f"[FONT] Could not register {name}: {exc}")
        else:
            print(f"[FONT] File not found: {path}")


def register_blueprints(app):
    from routes.admin import admin_bp
    from routes.artikli import artikli_bp
    from routes.auth import auth_bp
    from routes.chat import chat_bp
    from routes.kvalitet import kvalitet_bp
    from routes.main import main_bp
    from routes.nabavki import nabavki_bp
    from routes.odmori import odmori_bp
    from routes.ponudi import ponudi_bp
    from routes.sostanoci import sostanoci_bp
    from routes.zalihi import zalihi_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(artikli_bp)
    app.register_blueprint(zalihi_bp)
    app.register_blueprint(nabavki_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(odmori_bp)
    app.register_blueprint(kvalitet_bp)
    app.register_blueprint(sostanoci_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(ponudi_bp)
