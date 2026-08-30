def test_signup_creates_customer_account(client):
    resp = client.post("/signup", json={"username": "alice1", "password": "Passw0rd!", "email": "alice1@example.com"})
    assert resp.status_code == 200

    login = client.post("/login", json={"username": "alice1", "password": "Passw0rd!"})
    assert login.status_code == 200
    body = login.json()
    assert body["role"] == "customer"
    assert "access_token" in body


def test_signup_duplicate_username_rejected(client):
    client.post("/signup", json={"username": "bob1", "password": "Passw0rd!"})
    resp = client.post("/signup", json={"username": "bob1", "password": "Different1!"})
    assert resp.status_code == 400


def test_signup_short_password_rejected_by_schema(client):
    resp = client.post("/signup", json={"username": "carol1", "password": "abc"})
    assert resp.status_code == 422


def test_login_wrong_password_rejected(client):
    client.post("/signup", json={"username": "dave1", "password": "Passw0rd!"})
    resp = client.post("/login", json={"username": "dave1", "password": "WrongPass1!"})
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_returns_current_user(client, auth_headers):
    headers = auth_headers(username="erin1")
    resp = client.get("/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "erin1"
