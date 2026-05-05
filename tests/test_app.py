from fastapi.testclient import TestClient

from chaut_api import create_app
from chaut_api.settings import Settings


def make_client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(create_app(settings=settings))


def test_health(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_order_calculates_fee_and_persists(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000})
    assert response.status_code == 200
    body = response.json()
    assert body["fee_percent"] == 0.5
    assert body["fee_cop"] == 500
    assert body["amount_cop_net"] == 99500
    assert body["payment_status"] == "draft"

    get_response = client.get(f"/orders/{body['external_id']}")
    assert get_response.status_code == 200
    assert get_response.json() == body


def test_get_order_returns_404_for_missing_order(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.get("/orders/chaut-missing")
    assert response.status_code == 404
