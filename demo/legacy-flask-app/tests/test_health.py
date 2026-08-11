from tests.helpers import body


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = body(resp)
    assert data["status"] == "ok"
    assert data["service"] == "mini-ledger"
