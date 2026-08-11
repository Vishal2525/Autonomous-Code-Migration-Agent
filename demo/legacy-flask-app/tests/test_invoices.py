from tests.helpers import body


def _create(client, customer="Acme Corp", amount=120.5, description="consulting"):
    return client.post(
        "/api/invoices",
        json={"customer": customer, "amount": amount, "description": description},
    )


def test_list_invoices_initially_empty(client):
    resp = client.get("/api/invoices")
    assert resp.status_code == 200
    data = body(resp)
    assert data["invoices"] == []
    assert data["count"] == 0


def test_create_invoice(client):
    resp = _create(client)
    assert resp.status_code == 201
    data = body(resp)
    assert data["id"] == 1
    assert data["customer"] == "Acme Corp"
    assert data["amount"] == 120.5
    assert data["status"] == "draft"


def test_create_invoice_requires_fields(client):
    resp = client.post("/api/invoices", json={"customer": "Acme Corp"})
    assert resp.status_code == 400
    assert "amount" in body(resp)["error"]


def test_create_invoice_rejects_negative_amount(client):
    resp = _create(client, amount=-5)
    assert resp.status_code == 400
    assert "amount" in body(resp)["error"]


def test_get_invoice(client):
    _create(client)
    resp = client.get("/api/invoices/1")
    assert resp.status_code == 200
    assert body(resp)["customer"] == "Acme Corp"


def test_get_missing_invoice_returns_404(client):
    resp = client.get("/api/invoices/999")
    assert resp.status_code == 404
    assert "error" in body(resp)


def test_update_invoice(client):
    _create(client)
    resp = client.put("/api/invoices/1", json={"amount": 200, "customer": "Beta LLC"})
    assert resp.status_code == 200
    data = body(resp)
    assert data["amount"] == 200.0
    assert data["customer"] == "Beta LLC"


def test_update_invoice_validates_amount(client):
    _create(client)
    resp = client.put("/api/invoices/1", json={"amount": "not-a-number"})
    assert resp.status_code == 400


def test_delete_invoice(client):
    _create(client)
    resp = client.delete("/api/invoices/1")
    assert resp.status_code == 200
    assert body(resp)["deleted"] == 1
    assert client.get("/api/invoices/1").status_code == 404


def test_pay_invoice(client):
    _create(client)
    resp = client.post("/api/invoices/1/pay")
    assert resp.status_code == 200
    assert body(resp)["status"] == "paid"


def test_pay_invoice_twice_fails(client):
    _create(client)
    client.post("/api/invoices/1/pay")
    resp = client.post("/api/invoices/1/pay")
    assert resp.status_code == 400
    assert "already paid" in body(resp)["error"]


def test_filter_invoices_by_status(client):
    _create(client)
    _create(client, customer="Beta LLC", amount=50)
    client.post("/api/invoices/1/pay")
    resp = client.get("/api/invoices?status=paid")
    data = body(resp)
    assert data["count"] == 1
    assert data["invoices"][0]["id"] == 1
