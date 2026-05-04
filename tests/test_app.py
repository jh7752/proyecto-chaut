from fastapi.testclient import TestClient

from chaut_api import create_app


def test_health() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_order_calculates_fee() -> None:
    client = TestClient(create_app())
    response = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000})
    assert response.status_code == 200
    body = response.json()
    assert body["fee_percent"] == 0.5
    assert body["fee_cop"] == 500
    assert body["amount_cop_net"] == 99500
    assert body["payment_status"] == "draft"
