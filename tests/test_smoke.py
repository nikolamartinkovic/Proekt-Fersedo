import sqlite3

from app import app


def test_login_smoke(client):
    response = client.post(
        "/login",
        data={"username": "testuser", "password": "test-password-123"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    assert response.headers["Location"].endswith("/")


def test_nabavki_page_requires_login(client):
    response = client.get("/nabavki/", follow_redirects=False)

    assert response.status_code in (302, 303)
    assert "/login" in response.headers["Location"]


def test_nabavki_create_request_smoke(logged_in_client):
    response = logged_in_client.post(
        "/nabavki/",
        data={
            "action": "kreiraj",
            "naslov": "Smoke test artikl",
            "kolicina": "2",
            "datum_itnost": "2030-01-01",
            "chat_comment": "Smoke comment",
        },
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)

    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT naslov, kolicina, username, nalog_broj FROM nabavki_requests WHERE naslov = ?",
        ("Smoke test artikl",),
    ).fetchone()
    comment = conn.execute(
        """
        SELECT comment FROM nabavki_comments
        WHERE req_id = (SELECT id FROM nabavki_requests WHERE naslov = ?)
        """,
        ("Smoke test artikl",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["kolicina"] == 2
    assert row["username"] == "testuser"
    assert row["nalog_broj"].startswith("Fer")
    assert comment is not None
    assert comment["comment"] == "Smoke comment"


def test_zalihi_home_loads_for_logged_user(logged_in_client):
    response = logged_in_client.get("/zalihi/", follow_redirects=False)

    assert response.status_code == 200


def test_health_endpoint_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_nabavki_status_change_requires_privileged_user(logged_in_client):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        INSERT INTO nabavki_requests
        (username, naslov, kolicina, datum_kreiranje, datum_itnost, opis, slika, status)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, '', ?, 'kreirano')
        """,
        ("testuser", "Permission smoke", 1, "2030-01-02", None),
    )
    req_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.commit()
    conn.close()

    response = logged_in_client.get(f"/nabavki/update_status/{req_id}/Naracano", follow_redirects=False)

    assert response.status_code in (302, 303)

    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM nabavki_requests WHERE id = ?", (req_id,)).fetchone()
    conn.close()

    assert row["status"] == "kreirano"
