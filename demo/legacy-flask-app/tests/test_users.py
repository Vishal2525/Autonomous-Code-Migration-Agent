from tests.helpers import body


def test_list_users_initially_empty(client):
    resp = client.get("/api/users")
    assert resp.status_code == 200
    assert body(resp)["count"] == 0


def test_create_user(client):
    resp = client.post("/api/users", json={"name": "Dana", "email": "Dana@Example.com"})
    assert resp.status_code == 201
    data = body(resp)
    assert data["id"] == 1
    assert data["name"] == "Dana"
    assert data["email"] == "dana@example.com"


def test_create_user_requires_valid_email(client):
    resp = client.post("/api/users", json={"name": "Dana", "email": "nope"})
    assert resp.status_code == 400


def test_get_user(client):
    client.post("/api/users", json={"name": "Dana", "email": "dana@example.com"})
    resp = client.get("/api/users/1")
    assert resp.status_code == 200
    assert body(resp)["name"] == "Dana"


def test_get_missing_user_returns_404(client):
    resp = client.get("/api/users/42")
    assert resp.status_code == 404
