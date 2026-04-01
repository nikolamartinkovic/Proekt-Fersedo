import logging
import os
import re
import socket
from logging.handlers import RotatingFileHandler

from flask import jsonify


def configure_logging(app):
    log_dir = app.config.get("APP_LOG_DIR")
    log_level_name = app.config.get("APP_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    if not log_dir:
        return

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app.log")

    if any(
        isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", "") == os.path.abspath(log_path)
        for handler in app.logger.handlers
    ):
        return

    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s"))

    app.logger.setLevel(log_level)
    app.logger.addHandler(handler)
    app.logger.propagate = False
    app.logger.info("File logging enabled: %s", log_path)


def register_healthcheck(app):
    @app.route("/health")
    def health():
        return jsonify({"status": "ok"}), 200


def resolve_bind_host(configured_host):
    host = (configured_host or "0.0.0.0").strip()
    if host in {"", "0.0.0.0", "::", "127.0.0.1", "localhost"}:
        return "0.0.0.0" if host in {"", "0.0.0.0"} else host

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, 0))
        return host
    except OSError:
        return "0.0.0.0"
    finally:
        probe.close()


def read_app_log_entries(app, limit=80):
    log_dir = app.config.get("APP_LOG_DIR")
    if not log_dir:
        return []

    log_path = os.path.join(log_dir, "app.log")
    if not os.path.exists(log_path):
        return []

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as file_obj:
            raw_lines = file_obj.readlines()
    except OSError:
        return []

    pattern = re.compile(
        r"^\[(?P<timestamp>[^\]]+)\]\s+(?P<level>[A-Z]+)\s+in\s+(?P<module>[^:]+):\s+(?P<message>.*)$"
    )
    parsed = []
    for raw_line in reversed(raw_lines):
        line = raw_line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            parsed.append(
                {
                    "timestamp": match.group("timestamp"),
                    "level": match.group("level"),
                    "module": match.group("module"),
                    "message": match.group("message"),
                    "raw": line,
                }
            )
        else:
            parsed.append(
                {
                    "timestamp": "",
                    "level": "INFO",
                    "module": "runtime",
                    "message": line,
                    "raw": line,
                }
            )
        if len(parsed) >= limit:
            break

    return parsed
