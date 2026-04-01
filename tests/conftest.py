import shutil
import sqlite3
from pathlib import Path

import pytest

import utils.db as db_module
from app import app
from extensions import ph


@pytest.fixture()
def test_db_path(tmp_path):
    source = Path(app.config["DATABASE_PATH"])
    target = tmp_path / "test_database.db"
    shutil.copy2(source, target)
    return target


@pytest.fixture()
def client(test_db_path):
    original_path = app.config["DATABASE_PATH"]
    original_testing = app.config.get("TESTING", False)
    original_db_module_path = db_module.DATABASE_PATH

    app.config["TESTING"] = True
    app.config["DATABASE_PATH"] = str(test_db_path)
    db_module.DATABASE_PATH = str(test_db_path)

    with app.app_context():
        conn = sqlite3.connect(test_db_path)
        conn.row_factory = sqlite3.Row
        hashed_password = ph.hash("test-password-123")
        existing = conn.execute(
            "SELECT username FROM users WHERE username = ?",
            ("testuser",),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE users
                SET hashed_password = ?, is_admin = ?, user_group = ?, allowed_modules = ?, email = ?
                WHERE username = ?
                """,
                (hashed_password, 0, "", "nabavki,zalihi", "testuser@example.com", "testuser"),
            )
        else:
            conn.execute(
                """
                INSERT INTO users
                (username, hashed_password, is_admin, user_group, allowed_modules, email)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("testuser", hashed_password, 0, "", "nabavki,zalihi", "testuser@example.com"),
            )
        conn.commit()
        conn.close()

    try:
        with app.test_client() as client:
            yield client
    finally:
        app.config["DATABASE_PATH"] = original_path
        app.config["TESTING"] = original_testing
        db_module.DATABASE_PATH = original_db_module_path


@pytest.fixture()
def logged_in_client(client):
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "test-password-123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    return client
