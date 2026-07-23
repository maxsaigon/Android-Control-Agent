def test_public_health_but_private_dashboard_and_api(raw_client):
    assert raw_client.get("/api/health").status_code == 200
    assert raw_client.get("/api/devices").status_code == 401
    dashboard = raw_client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 303
    assert dashboard.headers["location"].startswith("/login")


def test_login_rejects_bad_password_and_creates_session(raw_client):
    denied = raw_client.post(
        "/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert denied.status_code == 401

    accepted = raw_client.post(
        "/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert accepted.status_code == 200
    assert raw_client.get("/api/auth/me").json() == {"username": "admin"}
    assert raw_client.get("/dashboard").status_code == 200

    assert raw_client.post("/auth/logout").status_code == 200
    assert raw_client.get("/api/devices").status_code == 401
