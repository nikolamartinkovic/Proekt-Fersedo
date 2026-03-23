from waitress import serve
from app import app
import ssl

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain("192.168.0.20.pem", "192.168.0.20-key.pem")

serve(
    app,
    host="0.0.0.0",
    port=443,
    url_scheme="https",
    threads=8,          # 8 паралелни корисници
    channel_timeout=60,
)