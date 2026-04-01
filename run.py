import os

from waitress import serve
from werkzeug.serving import run_simple

from app import app
from utils.runtime import resolve_bind_host


configured_host = os.getenv("APP_HOST", "0.0.0.0")
host = resolve_bind_host(configured_host)
port = int(os.getenv("APP_PORT", "8080"))
url_scheme = os.getenv("APP_URL_SCHEME", "http").lower()
cert_path = os.getenv("HTTPS_CERT_PATH", os.path.join(os.path.dirname(__file__), "192.168.0.20.pem"))
key_path = os.getenv("HTTPS_KEY_PATH", os.path.join(os.path.dirname(__file__), "192.168.0.20-key.pem"))

if host != configured_host:
    print(f"[SERVER] APP_HOST={configured_host} не е достапен локално. Се користи {host}.")

if url_scheme == "https":
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        raise FileNotFoundError(
            f"HTTPS е вклучен, но сертификатите недостигаат: cert={cert_path}, key={key_path}"
        )

    run_simple(
        hostname=host,
        port=port,
        application=app,
        ssl_context=(cert_path, key_path),
        use_reloader=False,
        threaded=True,
    )
else:
    serve(
        app,
        host=host,
        port=port,
        url_scheme=url_scheme,
        threads=int(os.getenv("WAITRESS_THREADS", "8")),
        channel_timeout=60,
    )
