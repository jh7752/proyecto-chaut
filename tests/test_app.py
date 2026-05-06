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
    assert body["fee_cop"] == 0
    assert body["amount_cop_net"] == 100000
    assert body["payment_status"] == "draft"
    assert body["conversion_status"] == "not_started"
    assert body["payment_request_id"] is None

    get_response = client.get(f"/orders/{body['external_id']}")
    assert get_response.status_code == 200
    assert get_response.json() == body


def test_create_order_calculates_usdt_estimate(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/orders",
        json={
            "client_id": "cli-test",
            "amount_cop_gross": 100000,
            "estimated_rate_cop_per_usdt": 4000,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["amount_cop_net"] == 100000
    assert body["estimated_usdt"] == 25


def test_order_events_include_order_created(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()

    response = client.get(f"/orders/{order['external_id']}/events")

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "order.created"
    assert events[0]["entity_id"] == order["external_id"]
    assert events[0]["payload"]["external_id"] == order["external_id"]


def test_get_order_returns_404_for_missing_order(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.get("/orders/chaut-missing")
    assert response.status_code == 404


def test_create_payment_request_updates_order_and_adds_event(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()

    response = client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})

    assert response.status_code == 200
    updated = response.json()
    assert updated["payment_request_id"] == f"mock-pr-{order['external_id']}"
    assert updated["payment_url"].endswith(f"/paymentRequest/mock-pr-{order['external_id']}")
    assert updated["payment_status"] == "created"

    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert [event["event_type"] for event in events] == ["order.created", "payment_request.created"]
    assert events[1]["payload"]["payment_request_id"] == updated["payment_request_id"]


def test_create_payment_request_is_idempotent_guarded(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()
    first = client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})
    second = client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})

    assert first.status_code == 200
    assert second.status_code == 409


def test_check_payment_request_records_status_event(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()
    created = client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60}).json()

    response = client.post(f"/orders/{order['external_id']}/payment-request/check")

    assert response.status_code == 200
    assert response.json()["payment_status"] == created["payment_status"]
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert [event["event_type"] for event in events] == [
        "order.created",
        "payment_request.created",
        created["payment_status"],
    ]


class AcceptedCoinsendaClient:
    def __init__(self, payment_request_id: str | None = None) -> None:
        self.payment_request_id = payment_request_id

    def create_payment_request(self, order, expiration_minutes: int, currency: str = "cop", payment_amount: float | None = None):
        from chaut_api.coinsenda import PaymentRequestResult

        payment_request_id = self.payment_request_id or f"pr-{order.external_id}"
        payment_amount = payment_amount or order.amount_cop_gross
        return PaymentRequestResult(
            payment_request_id=payment_request_id,
            payment_url=f"https://app.coinsenda.com/paymentRequest?paymentRequestId={payment_request_id}",
            status="pending",
            raw={"payment_request_id": payment_request_id, "currency": currency, "amount": payment_amount},
        )

    def check_payment_request(self, order):
        from chaut_api.coinsenda import PaymentRequestStatus

        return PaymentRequestStatus(
            payment_status="payment_confirmed",
            raw={
                "event_type": "payment_confirmed",
                "payment_request": {
                    "id": order.payment_request_id,
                    "state": "accepted",
                    "external_id": order.external_id,
                    "amount": order.amount_cop_gross,
                    "currency": "cop",
                },
            },
        )


class MismatchedCoinsendaClient(AcceptedCoinsendaClient):
    def check_payment_request(self, order):
        from chaut_api.coinsenda import PaymentRequestStatus

        return PaymentRequestStatus(
            payment_status="payment_confirmed",
            raw={
                "event_type": "payment_confirmed",
                "payment_request": {
                    "id": order.payment_request_id,
                    "state": "accepted",
                    "external_id": order.external_id,
                    "amount": order.amount_cop_gross + 1,
                    "currency": "cop",
                },
            },
        )


def make_client_with_coinsenda(tmp_path, coinsenda_client):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    return TestClient(create_app(settings=settings, coinsenda_client=coinsenda_client))


def test_reconcile_payment_confirms_accepted_matching_payment_request(tmp_path) -> None:
    client = make_client_with_coinsenda(tmp_path, AcceptedCoinsendaClient())
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})

    response = client.post(f"/orders/{order['external_id']}/reconcile-payment")

    assert response.status_code == 200
    assert response.json()["payment_status"] == "confirmed"
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert events[-1]["event_type"] == "payment.confirmed"
    assert events[-1]["payload"]["validation"]["ok"] is True


def test_reconcile_payment_marks_mismatch_as_ambiguous(tmp_path) -> None:
    client = make_client_with_coinsenda(tmp_path, MismatchedCoinsendaClient())
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})

    response = client.post(f"/orders/{order['external_id']}/reconcile-payment")

    assert response.status_code == 200
    assert response.json()["payment_status"] == "ambiguous"
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert events[-1]["event_type"] == "payment.reconciliation_ambiguous"
    assert events[-1]["payload"]["validation"]["reason"] == "amount mismatch"


def test_payment_instructions_inspects_front_and_records_event(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})

    response = client.post(f"/orders/{order['external_id']}/payment-instructions", json={"click_text": "DCOP"})

    assert response.status_code == 200
    body = response.json()
    assert body["external_id"] == order["external_id"]
    assert "DCOP" in body["instructions"]["methods"]
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert events[-1]["event_type"] == "payment_instructions.inspected"


def test_create_usdt_payment_request_uses_sell_price(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 5000}).json()

    response = client.post(
        f"/orders/{order['external_id']}/payment-request",
        json={
            "expiration_minutes": 60,
            "currency": "usdt",
            "sell_price_cop_per_usdt": 3527.5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payment_currency"] == "usdt"
    assert body["payment_amount"] == 1.417434
    assert body["sell_price_cop_per_usdt"] == 3527.5
    assert body["fee_asset"] == "xaut"
    assert body["fee_cop"] == 0


def test_checkout_orchestrates_order_payment_request_and_instructions(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    monkeypatch.setattr(app_module, "get_usdt_cop_sell_price", lambda: 3527.5)
    client = make_client(tmp_path)

    response = client.post(
        "/checkout",
        json={"client_id": "cli-test", "amount_cop": 5000, "expiration_minutes": 60},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["amount_cop"] == 5000
    assert body["payment_currency"] == "usdt"
    assert body["payment_amount"] == 1.417434
    assert body["sell_price_cop_per_usdt"] == 3527.5
    assert body["method"] == "Bre-B"
    assert body["payment_request_id"] == f"mock-pr-{body['external_id']}"
    assert "DCOP" in body["instructions"]["methods"]

    events = client.get(f"/orders/{body['external_id']}/events").json()
    assert [event["event_type"] for event in events] == [
        "order.created",
        "payment_request.created",
        "payment_instructions.inspected",
    ]
