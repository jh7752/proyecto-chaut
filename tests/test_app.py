import concurrent.futures

import pytest
from fastapi.testclient import TestClient

from chaut_api import create_app
from chaut_api.settings import Settings


@pytest.fixture(autouse=True)
def stub_seticap_trm(monkeypatch):
    import chaut_api.app as app_module

    trm = {
        "reference_rate": 3794.91,
        "source": "seticap-test",
        "reference_rate_source": "seticap-test",
        "reference_rate_date": "2026-05-18",
    }
    monkeypatch.setattr(app_module, "get_seticap_trm", lambda: trm)
    monkeypatch.setattr(app_module, "get_cached_seticap_trm", lambda: trm)
    monkeypatch.setattr(app_module, "refresh_seticap_trm_cache", lambda: trm)


def build_settings(tmp_path, **overrides):
    values = {
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "admin_token": None,
        "admin_username": None,
        "admin_password": None,
        "admin_session_secret": None,
    }
    values.update(overrides)
    return Settings(**values)


def make_client(tmp_path):
    return TestClient(create_app(settings=build_settings(tmp_path)))


def test_health(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_documentation_is_disabled(tmp_path) -> None:
    client = make_client(tmp_path)

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_create_order_calculates_fee_and_persists(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000})
    assert response.status_code == 200
    body = response.json()
    assert body["fee_percent"] == 0
    assert body["fee_cop"] == 0
    assert body["amount_cop_net"] == 100000
    assert body["payment_status"] == "draft"
    assert body["conversion_status"] == "not_started"
    assert body["payment_request_id"] is None

    get_response = client.get(f"/orders/{body['external_id']}")
    assert get_response.status_code == 200
    assert get_response.json() == body


def test_create_order_rejects_amount_below_5000_cop(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 4999})
    assert response.status_code == 422


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
    return TestClient(create_app(settings=build_settings(tmp_path), coinsenda_client=coinsenda_client))


def make_client_with_payout(tmp_path, coinsenda_payout_client):
    return TestClient(create_app(settings=build_settings(tmp_path), coinsenda_payout_client=coinsenda_payout_client))


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
    assert "Bre-B" in body["instructions"]["methods"]
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
    assert body["checkout_status"] == "ready"
    assert body["pay_amount_cop_numeric"] == 5000
    assert body["price_slippage_cop"] == 0
    assert body["attempts"] == 1
    assert "Bre-B" in body["instructions"]["methods"]

    events = client.get(f"/orders/{body['external_id']}/events").json()
    assert [event["event_type"] for event in events] == [
        "order.created",
        "payment_request.created",
        "payment_instructions.inspected",
    ]


def test_checkout_rejects_amount_below_5000_cop(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post("/checkout", json={"client_id": "cli-test", "amount_cop": 4999})
    assert response.status_code == 422


class SlippageCoinsendaClient(AcceptedCoinsendaClient):
    def __init__(self) -> None:
        super().__init__()
        self.inspections = 0

    def inspect_payment_request(self, order, click_text: str):
        self.inspections += 1
        amount = "4,964.73" if self.inspections == 1 else "5,000"
        return {
            "mode": "mock",
            "targetUrl": order.payment_url,
            "clickText": click_text,
            "after": {"text": f"Envia {amount} COP a @coinsendaRetry123"},
            "events": [],
        }


def test_checkout_retries_when_price_slippage_exceeds_tolerance(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    prices = iter([3550.61, 3535.69])
    monkeypatch.setattr(app_module, "get_usdt_cop_sell_price", lambda: next(prices))
    client = make_client_with_coinsenda(tmp_path, SlippageCoinsendaClient())

    response = client.post(
        "/checkout",
        json={
            "client_id": "cli-test",
            "amount_cop": 5000,
            "expiration_minutes": 60,
            "max_price_slippage_cop": 1,
            "max_retries": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["checkout_status"] == "ready"
    assert body["attempts"] == 2
    assert body["pay_amount_cop_numeric"] == 5000
    assert body["instructions"]["checkout_attempts"][0]["checkout_status"] == "price_mismatch"
    assert body["instructions"]["checkout_attempts"][1]["checkout_status"] == "ready"

    first_external_id = body["instructions"]["checkout_attempts"][0]["external_id"]
    first_order = client.get(f"/orders/{first_external_id}").json()
    assert first_order["payment_status"] == "voided"
    first_event_types = [event["event_type"] for event in client.get(f"/orders/{first_external_id}/events").json()]
    assert "checkout.price_mismatch" in first_event_types
    assert "checkout.replaced" in first_event_types


class UnverifiedCoinsendaClient(AcceptedCoinsendaClient):
    def inspect_payment_request(self, order, click_text: str):
        return {
            "mode": "mock",
            "targetUrl": order.payment_url,
            "clickText": click_text,
            "after": {"text": "Verificando parámetros de pago..."},
            "events": [],
        }


def test_checkout_voids_unverified_retry_attempt_and_returns_final_unverified(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    prices = iter([3423.99, 3423.98])
    monkeypatch.setattr(app_module, "get_usdt_cop_sell_price", lambda: next(prices))
    client = make_client_with_coinsenda(tmp_path, UnverifiedCoinsendaClient())

    response = client.post(
        "/checkout",
        json={
            "client_id": "telegram:8528719436",
            "amount_cop": 5000,
            "expiration_minutes": 45,
            "max_retries": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["checkout_status"] == "price_unverified"
    assert body["pay_to"] is None
    assert body["pay_amount_cop"] is None
    first_external_id = body["instructions"]["checkout_attempts"][0]["external_id"]
    final_external_id = body["external_id"]
    assert first_external_id != final_external_id
    assert client.get(f"/orders/{first_external_id}").json()["payment_status"] == "voided"
    assert client.get(f"/orders/{final_external_id}").json()["payment_status"] == "pending"
    first_event_types = [event["event_type"] for event in client.get(f"/orders/{first_external_id}/events").json()]
    assert "checkout.replaced" in first_event_types


def test_account_identify_creates_and_updates_customer(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/accounts/identify",
        json={
            "provider": "telegram",
            "provider_user_id": "271173673",
            "chat_id": "271173673",
            "username": "johan",
            "display_name": "Johan",
        },
    )

    assert response.status_code == 200
    account = response.json()
    assert account["customer_id"].startswith("cus-")
    assert account["status"] == "active"
    assert account["display_name"] == "Johan"
    assert account["identities"][0]["provider"] == "telegram"
    assert account["identities"][0]["provider_user_id"] == "271173673"

    second = client.post(
        "/accounts/identify",
        json={
            "provider": "telegram",
            "provider_user_id": "271173673",
            "chat_id": "271173673",
            "username": "johan_updated",
            "display_name": "Johan D",
        },
    ).json()

    assert second["customer_id"] == account["customer_id"]
    assert second["display_name"] == "Johan D"
    assert second["identities"][0]["username"] == "johan_updated"

    lookup = client.get("/accounts/by-identity/telegram/271173673")
    assert lookup.status_code == 200
    assert lookup.json()["customer_id"] == account["customer_id"]


def test_checkout_with_identity_links_order_to_account(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    monkeypatch.setattr(app_module, "get_usdt_cop_sell_price", lambda: 3527.5)
    client = make_client(tmp_path)

    response = client.post(
        "/checkout",
        json={
            "client_id": "telegram:271173673",
            "identity": {
                "provider": "telegram",
                "provider_user_id": "271173673",
                "chat_id": "271173673",
                "display_name": "Johan",
            },
            "amount_cop": 5000,
            "expiration_minutes": 60,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"].startswith("cus-")
    order = client.get(f"/orders/{body['external_id']}").json()
    assert order["customer_id"] == body["customer_id"]
    account = client.get(f"/accounts/{body['customer_id']}").json()
    assert account["identities"][0]["provider_user_id"] == "271173673"


def test_reconcile_payment_confirms_accepted_matching_usdt_payment_request(tmp_path) -> None:
    class AcceptedUsdtCoinsendaClient(AcceptedCoinsendaClient):
        def get_usdt_cop_sell_price(self):
            return 3500.0

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
                        "amount": str(order.payment_amount),
                        "currency": "usdt",
                    },
                },
            )

    client = make_client_with_coinsenda(tmp_path, AcceptedUsdtCoinsendaClient())
    # Recreate equivalent persisted state in this client's isolated store.
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 5000}).json()
    client.post(
        f"/orders/{order['external_id']}/payment-request",
        json={
            "expiration_minutes": 60,
            "currency": "usdt",
            "sell_price_cop_per_usdt": 3527.49,
        },
    )

    response = client.post(f"/orders/{order['external_id']}/reconcile-payment")

    assert response.status_code == 200
    assert response.json()["payment_status"] == "confirmed"
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert events[-1]["event_type"] == "payment.confirmed"
    assert events[-1]["payload"]["validation"]["confirmed_currency"] == "usdt"
    assert events[-1]["payload"]["validation"]["confirmed_amount"] == str(response.json()["payment_amount"])


def test_kucoin_public_endpoints(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubKucoinClient:
        def health(self):
            return {"status": "ok", "source": "kucoin", "symbol": "XAUT-USDT"}

        def get_xaut_ticker(self):
            return {
                "category": "spot",
                "symbol": "XAUT-USDT",
                "price": "4710.47",
                "bestBid": "4710.47",
                "bestAsk": "4710.48",
                "raw": {"code": "200000"},
            }

        def get_xaut_instrument(self):
            return {
                "category": "spot",
                "symbol": "XAUT-USDT",
                "baseCurrency": "XAUT",
                "quoteCurrency": "USDT",
                "baseMinSize": "0.0001",
                "baseIncrement": "0.0001",
                "priceIncrement": "0.01",
                "enableTrading": True,
                "raw": {"symbol": "XAUT-USDT"},
            }

    monkeypatch.setattr(app_module, "create_kucoin_client", lambda *args, **kwargs: StubKucoinClient())
    client = make_client(tmp_path)

    assert client.get("/kucoin/health").json() == {
        "status": "ok",
        "source": "kucoin",
        "symbol": "XAUT-USDT",
    }
    assert client.get("/kucoin/xaut-ticker").json()["bestAsk"] == "4710.48"
    assert client.get("/kucoin/xaut-instrument").json()["baseCurrency"] == "XAUT"


def test_htx_public_endpoints(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxClient:
        def health(self):
            return {"status": "ok", "source": "htx", "symbol": "xautusdt"}

        def get_xaut_ticker(self):
            return {
                "category": "spot",
                "symbol": "xautusdt",
                "price": "4710.47",
                "bestBid": "4710.47",
                "bestAsk": "4710.48",
                "raw": {"status": "ok"},
            }

        def get_xaut_instrument(self):
            return {
                "category": "spot",
                "symbol": "xautusdt",
                "base-currency": "xaut",
                "quote-currency": "usdt",
                "min-order-value": 1,
                "min-order-amt": 0.00001,
                "api-trading": "enabled",
                "raw": {"symbol": "xautusdt"},
            }

    monkeypatch.setattr(app_module, "create_htx_client", lambda *args, **kwargs: StubHtxClient())
    client = make_client(tmp_path)

    assert client.get("/htx/health").json() == {"status": "ok", "source": "htx", "symbol": "xautusdt"}
    assert client.get("/htx/xaut-ticker").json()["bestAsk"] == "4710.48"
    assert client.get("/htx/xaut-instrument").json()["base-currency"] == "xaut"


def test_xaut_quote_requires_confirmed_payment(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubKucoinClient:
        def get_xaut_ticker(self):
            return {
                "category": "spot",
                "symbol": "xautusdt",
                "bestAsk": "4692.8",
                "price": "4692.0",
                "raw": {"status": "ok"},
            }

    monkeypatch.setattr(app_module, "create_htx_client", lambda *args, **kwargs: StubKucoinClient())
    client = make_client_with_coinsenda(tmp_path, AcceptedCoinsendaClient())
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 5000}).json()

    response = client.post(f"/orders/{order['external_id']}/xaut-quote")

    assert response.status_code == 409


def test_xaut_quote_applies_fee_before_user_grams(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class AcceptedUsdtCoinsendaClient(AcceptedCoinsendaClient):
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
                        "amount": str(order.payment_amount),
                        "currency": "usdt",
                    },
                },
            )

    class StubKucoinClient:
        def get_xaut_ticker(self):
            return {
                "category": "spot",
                "symbol": "xautusdt",
                "bestAsk": "4692.8",
                "price": "4692.0",
                "raw": {"status": "ok"},
            }

    monkeypatch.setattr(app_module, "create_htx_client", lambda *args, **kwargs: StubKucoinClient())
    client = make_client_with_coinsenda(tmp_path, AcceptedUsdtCoinsendaClient())
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 5000}).json()
    client.post(
        f"/orders/{order['external_id']}/payment-request",
        json={"currency": "usdt", "sell_price_cop_per_usdt": 3527.49},
    )
    client.post(f"/orders/{order['external_id']}/reconcile-payment")

    response = client.post(f"/orders/{order['external_id']}/xaut-quote")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "quoted"
    assert body["confirmed_usdt"] == 1.417438
    assert body["xaut_ask_price"] == 4692.8
    assert body["fee_percent"] == 0
    assert body["xaut_gross"] == body["xaut_net"]
    assert body["fee_xaut"] == 0
    assert body["gold_grams_gross"] == body["gold_grams_net"]
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert events[-1]["event_type"] == "xaut.quote_created"
    assert events[-1]["payload"]["gold_grams_net"] == body["gold_grams_net"]


def test_execute_xaut_market_buy_is_idempotent(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class AcceptedUsdtCoinsendaClient(AcceptedCoinsendaClient):
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
                        "amount": str(order.payment_amount),
                        "currency": "usdt",
                    },
                },
            )

    class StubHtxClient:
        calls = 0

        def get_xaut_ticker(self):
            return {"category": "spot", "symbol": "xautusdt", "bestAsk": "4700", "price": "4700", "raw": {"status": "ok"}}

        def get_xaut_instrument(self):
            return {"category": "spot", "symbol": "xautusdt", "min-order-value": 1, "raw": {"status": "ok"}}

    class StubHtxPrivateClient:
        def place_market_buy(self, symbol, funds):
            StubHtxClient.calls += 1
            return {"status": "ok", "data": "order-1"}

        def order(self, order_id):
            return {
                "status": "ok",
                "data": {
                    "id": order_id,
                    "state": "filled",
                    "field-amount": "0.0003",
                    "field-cash-amount": "1.4",
                    "field-fees": "0.0000006",
                },
            }

    monkeypatch.setattr(app_module, "create_htx_client", lambda *args, **kwargs: StubHtxClient())
    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client_with_coinsenda(tmp_path, AcceptedUsdtCoinsendaClient())
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 5000}).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"currency": "usdt", "sell_price_cop_per_usdt": 3500})
    client.post(f"/orders/{order['external_id']}/reconcile-payment")

    first = client.post(f"/orders/{order['external_id']}/xaut-execute-market-buy?confirm=EXECUTE_HTX_XAUT_BUY")
    second = client.post(f"/orders/{order['external_id']}/xaut-execute-market-buy?confirm=EXECUTE_HTX_XAUT_BUY")

    assert first.status_code == 200
    assert first.json()["status"] == "settled"
    assert first.json()["user_summary"]["gold_grams_net"] == "0.009312380953"
    assert second.status_code == 200
    assert second.json()["status"] == "already_settled"
    assert second.json()["idempotent"] is True
    assert StubHtxClient.calls == 1


def test_settle_xaut_reconciles_then_executes(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class AcceptedUsdtCoinsendaClient(AcceptedCoinsendaClient):
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
                        "amount": str(order.payment_amount),
                        "currency": "usdt",
                    },
                },
            )

    class StubHtxClient:
        def get_xaut_ticker(self):
            return {"category": "spot", "symbol": "xautusdt", "bestAsk": "4700", "price": "4700", "raw": {"status": "ok"}}

        def get_xaut_instrument(self):
            return {"category": "spot", "symbol": "xautusdt", "min-order-value": 1, "raw": {"status": "ok"}}

    class StubHtxPrivateClient:
        def place_market_buy(self, symbol, funds):
            return {"status": "ok", "data": "order-1"}

        def order(self, order_id):
            return {"status": "ok", "data": {"id": order_id, "state": "filled", "field-amount": "0.0003", "field-cash-amount": "1.4", "field-fees": "0.0000006"}}

    monkeypatch.setattr(app_module, "create_htx_client", lambda *args, **kwargs: StubHtxClient())
    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client_with_coinsenda(tmp_path, AcceptedUsdtCoinsendaClient())
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 5000}).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"currency": "usdt", "sell_price_cop_per_usdt": 3500})

    response = client.post(f"/orders/{order['external_id']}/settle-xaut?confirm=EXECUTE_HTX_XAUT_BUY")

    assert response.status_code == 200
    assert response.json()["payment_status"] == "confirmed"
    assert response.json()["status"] == "settled"
    assert response.json()["user_summary"]["message"].startswith("Compra completada")


def test_portfolio_tracks_user_ledger_after_settlement(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class AcceptedUsdtCoinsendaClient(AcceptedCoinsendaClient):
        def get_usdt_cop_sell_price(self):
            return 3500.0

        def inspect_payment_request(self, order, method):
            return {"addresses": [{"address": "@coinsendaTEST"}], "amount_cop_text": "5000"}

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
                        "amount": str(order.payment_amount),
                        "currency": "usdt",
                    },
                },
            )

    class StubHtxClient:
        def get_xaut_ticker(self):
            return {"category": "spot", "symbol": "xautusdt", "bestAsk": "4700", "price": "4700", "raw": {"status": "ok"}}

        def get_xaut_instrument(self):
            return {"category": "spot", "symbol": "xautusdt", "min-order-value": 1, "raw": {"status": "ok"}}

    class StubHtxPrivateClient:
        def place_market_buy(self, symbol, funds):
            return {"status": "ok", "data": "order-1"}

        def order(self, order_id):
            return {"status": "ok", "data": {"id": order_id, "state": "filled", "field-amount": "0.0003", "field-cash-amount": "1.4", "field-fees": "0.0000006"}}

    monkeypatch.setattr(app_module, "create_htx_client", lambda *args, **kwargs: StubHtxClient())
    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client_with_coinsenda(tmp_path, AcceptedUsdtCoinsendaClient())
    checkout = client.post(
        "/checkout",
        json={
            "client_id": "telegram-42",
            "identity": {"provider": "telegram", "provider_user_id": "42", "chat_id": "42", "display_name": "Tester"},
            "amount_cop": 5000,
        },
    ).json()

    settlement = client.post(f"/orders/{checkout['external_id']}/settle-xaut?confirm=EXECUTE_HTX_XAUT_BUY").json()
    portfolio = client.get("/accounts/by-identity/telegram/42/portfolio").json()

    assert settlement["ledger_entry"]["customer_id"] == checkout["customer_id"]
    assert portfolio["customer_id"] == checkout["customer_id"]
    assert portfolio["entries_count"] == 1
    assert portfolio["xaut_net"] == 0.000281768398798842
    assert portfolio["gold_grams_net"] == 0.008763976854
    allocation = portfolio["entries"][0]["payload"]["allocation"]
    assert allocation["chaut_spread_xaut"] == 1.7631601201158e-05
    assert allocation["spread_profit_cop_estimated"] > 0
    assert portfolio["cop_invested"] == 5000.0
    assert portfolio["entries"][0]["external_id"] == checkout["external_id"]


def test_portfolio_value_uses_coinsenda_sell_price_plus_configured_markup(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxClient:
        def get_xaut_ticker(self):
            return {"category": "spot", "symbol": "xautusdt", "price": "4500", "raw": {"status": "ok"}}

    class StubCoinsendaClient:
        def get_usdt_cop_sell_price(self):
            return 3392.52

    monkeypatch.setattr(app_module, "create_htx_client", lambda *args, **kwargs: StubHtxClient())
    settings = build_settings(
        tmp_path,
        portfolio_valuation_markup_percent=2,
    )
    client = TestClient(create_app(settings=settings, coinsenda_client=StubCoinsendaClient()))
    account = client.post(
        "/accounts/identify",
        json={"provider": "telegram", "provider_user_id": "value-1", "display_name": "Value Uno"},
    ).json()
    order = client.post(
        "/orders",
        json={"client_id": "telegram:value-1", "customer_id": account["customer_id"], "amount_cop_gross": 5000},
    ).json()

    from chaut_api.store import create_store

    store = create_store(settings.database_url)
    store.create_ledger_entry(
        store.get_order(order["external_id"]),
        {"xaut_net": 0.001, "gold_grams_net": 0.0311034768, "field_cash_amount": "4.5", "order_id": "htx-1"},
        {"prepared": {"ask_price": 4400}},
    )

    portfolio = client.get("/accounts/by-identity/telegram/value-1/portfolio").json()

    assert portfolio["valuation_price_xaut_usdt"] == 4500.0
    assert portfolio["valuation_rate_cop_per_usdt"] == 3460.37
    assert portfolio["estimated_value_cop"] == 15571.66

    liquidation_portfolio = client.get("/accounts/by-identity/telegram/value-1/portfolio?include_markup=false").json()
    assert liquidation_portfolio["valuation_rate_cop_per_usdt"] == 3392.52
    assert liquidation_portfolio["estimated_value_cop"] == 15266.34



def test_admin_order_detail_shows_exchange_rates(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    monkeypatch.setattr(app_module, "get_usdt_cop_sell_price", lambda: 3423.91)
    client = make_client_with_coinsenda(tmp_path, SlippageCoinsendaClient())

    checkout = client.post(
        "/checkout",
        json={
            "client_id": "cli-rates",
            "amount_cop": 5000,
            "expiration_minutes": 45,
            "max_retries": 0,
        },
    ).json()

    response = client.get(f"/admin/orders/{checkout['external_id']}")

    assert response.status_code == 200
    assert "Tasas aplicadas" in response.text
    assert "Coinsenda venta" in response.text
    assert "3,423.91 COP/USDT" in response.text
    assert "Referencia" in response.text
    assert "seticap-test" in response.text
    assert "Spread estimado" in response.text


def test_admin_order_detail_shows_htx_execution_price(tmp_path) -> None:
    import chaut_api.app as app_module

    client = make_client(tmp_path)
    account = client.post(
        "/accounts/identify",
        json={"provider": "telegram", "provider_user_id": "admin-price", "display_name": "Precio HTX"},
    ).json()
    order = client.post(
        "/orders",
        json={
            "client_id": "telegram:admin-price",
            "customer_id": account["customer_id"],
            "amount_cop_gross": 5000,
        },
    ).json()
    store = app_module.create_store(build_settings(tmp_path).database_url)
    stored_order = store.get_order(order["external_id"])
    store.create_ledger_entry(
        stored_order,
        {
            "order_id": "htx-execution-1",
            "state": "filled",
            "field_amount": "0.001",
            "field_cash_amount": "4.5",
            "field_fees": "0.00001",
            "xaut_net": "0.00099",
            "gold_grams_net": "0.030792442032",
        },
        {"prepared": {"ask_price": "4400"}},
    )
    store.add_event(
        order["external_id"],
        "xaut.order_filled",
        {
            "prepared": {"ask_price": "4400"},
            "order": {
                "order_id": "htx-execution-1",
                "state": "filled",
                "field_amount": "0.001",
                "field_cash_amount": "4.5",
                "field_fees": "0.00001",
                "xaut_net": "0.00099",
            },
        },
    )

    response = client.get(f"/admin/orders/{order['external_id']}")

    assert response.status_code == 200
    assert "Tasas aplicadas" in response.text
    assert "Compra XAUT HTX" in response.text
    assert "4,500.0000 USDT/XAUT" in response.text
    assert "Ejecucion HTX" not in response.text
    assert "USDT ejecutado" not in response.text


def test_admin_orders_table_shows_exchange_rate_columns(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    monkeypatch.setattr(app_module, "get_usdt_cop_sell_price", lambda: 3527.5)
    client = make_client_with_coinsenda(tmp_path, SlippageCoinsendaClient())
    client.post(
        "/checkout",
        json={
            "client_id": "cli-rate-list",
            "amount_cop": 5000,
            "expiration_minutes": 45,
            "max_retries": 0,
        },
    )

    response = client.get("/admin/orders")

    assert response.status_code == 200
    assert "Coinsenda" in response.text
    assert "Referencia" in response.text
    assert "3,527.50 COP/USDT" in response.text

def test_admin_orders_shows_attention_queue(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})
    client.post(f"/orders/{order['external_id']}/payment-request/check")

    response = client.get("/admin/orders")

    assert response.status_code == 200
    assert "Pagadas" in response.text
    assert "No pagadas" in response.text
    assert "day-title" in response.text
    assert "timeline" in response.text
    assert "Preparar XAUT" not in response.text
    assert "Marcar atencion" not in response.text
    assert order["external_id"] in response.text


def test_admin_dashboard_splits_latest_orders_by_payment_state(tmp_path) -> None:
    client = make_client(tmp_path)
    unpaid = client.post("/orders", json={"client_id": "cli-unpaid", "amount_cop_gross": 50000}).json()
    paid = client.post("/orders", json={"client_id": "cli-paid", "amount_cop_gross": 100000}).json()
    client.post(f"/orders/{paid['external_id']}/payment-request", json={"expiration_minutes": 60})
    client.post(f"/orders/{paid['external_id']}/payment-request/check")

    response = client.get("/admin")

    assert response.status_code == 200
    assert "Ultimas ordenes" in response.text
    assert "Pagadas" in response.text
    assert "No pagadas" in response.text
    assert paid["external_id"] in response.text
    assert unpaid["external_id"] in response.text


def test_admin_dashboard_shows_coinsenda_available_balances(tmp_path) -> None:
    client = make_client(tmp_path)

    response = client.get("/admin")

    assert response.status_code == 200
    assert "Saldos disponibles en Coinsenda" in response.text
    assert "125.000000 USDT" in response.text
    assert "250,000.00 COP" in response.text


def test_admin_mark_attention_records_event(tmp_path) -> None:
    client = make_client(tmp_path)
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()

    response = client.post(f"/admin/orders/{order['external_id']}/mark-attention", follow_redirects=False)

    assert response.status_code == 303
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert events[-1]["event_type"] == "admin.attention_marked"


def test_admin_expired_orders_show_expiration_time_not_mark_time(tmp_path) -> None:
    from chaut_api.admin import order_date_context
    from chaut_api.app import create_app
    from chaut_api.store import create_store

    class PendingCoinsendaClient(AcceptedCoinsendaClient):
        def check_payment_request(self, order):
            from chaut_api.coinsenda import PaymentRequestStatus

            return PaymentRequestStatus(payment_status="pending", raw={"payment_request": {"id": order.payment_request_id}})

    client = TestClient(create_app(settings=build_settings(tmp_path), coinsenda_client=PendingCoinsendaClient()))
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 100000}).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})
    store = create_store(f"sqlite:///{tmp_path / 'test.db'}")
    stale = store.get_order(order["external_id"])
    store.add_event(
        order["external_id"],
        "payment.expired",
        {
            "expired_at": stale.created_at,
            "marked_at": stale.updated_at,
            "expiration_minutes": 60,
        },
    )
    store.update_payment_status(order["external_id"], "expired")
    expired_order = store.get_order(order["external_id"])
    events = store.list_events(order["external_id"])

    date_label, main_date, secondary_label, secondary_date = order_date_context(expired_order, events)

    assert date_label == "Expira"
    assert main_date.startswith("2026-")
    assert secondary_label == "Marcada"
    assert secondary_date == expired_order.updated_at


def test_account_credit_profile_scores_customer_and_suggests_credit_limit(tmp_path) -> None:
    client = make_client_with_coinsenda(tmp_path, AcceptedCoinsendaClient())
    account = client.post(
        "/accounts/identify",
        json={"provider": "telegram", "provider_user_id": "credit-1", "display_name": "Credito Uno"},
    ).json()
    order = client.post(
        "/orders",
        json={"client_id": "telegram:credit-1", "customer_id": account["customer_id"], "amount_cop_gross": 120000},
    ).json()
    client.post(f"/orders/{order['external_id']}/payment-request", json={"expiration_minutes": 60})
    client.post(f"/orders/{order['external_id']}/reconcile-payment")

    profile = client.get(f"/accounts/{account['customer_id']}/credit-profile").json()

    assert profile["customer_id"] == account["customer_id"]
    assert profile["paid_orders"] == 1
    assert profile["rating"] in {"C", "B", "A"}
    assert profile["score"] >= 40
    assert profile["suggested_credit_limit_cop"] > 0
    assert profile["max_ltv_percent"] > 0



def test_admin_uses_net_cop_after_completed_withdrawal(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            return {"status": "ok", "data": "sell-admin-net"}

        def order(self, order_id):
            return {
                "status": "ok",
                "data": {
                    "id": order_id,
                    "state": "filled",
                    "field-amount": "0.0003",
                    "field-cash-amount": "1.4",
                    "field-fees": "0",
                },
            }

    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client(tmp_path)
    account = _seed_withdrawable_account(client, tmp_path, "admin-net")
    withdrawal = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={
            "customer_id": account["customer_id"],
            "provider": "telegram",
            "provider_user_id": "admin-net",
            "breb_key": "@breb",
            "portfolio_snapshot": {"xaut_net": 0.0003},
        },
    ).json()
    client.post(
        f"/withdrawals/{withdrawal['withdrawal_id']}/confirm-payment",
        json={"cop_paid": 5000, "cop_tx_ref": "breb-ref-admin"},
    )

    portfolio = client.get(f"/accounts/{account['customer_id']}/portfolio").json()
    assert portfolio["cop_invested"] == 5000.0
    assert portfolio["cop_withdrawn"] == 4900.0
    assert portfolio["cop_net_contributed"] == 100.0

    dashboard = client.get("/admin").text
    accounts = client.get("/admin/accounts").text
    detail = client.get(f"/admin/accounts/{account['customer_id']}").text

    assert "100 COP netos" in dashboard
    assert "COP neto" in accounts
    assert "COP neto" in detail
    assert "COP retirado" in detail


def test_portfolio_net_cop_uses_ledger_withdrawal_when_payout_is_not_completed(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            return {"status": "ok", "data": "sell-ledger-only"}

        def order(self, order_id):
            return {
                "status": "ok",
                "data": {
                    "id": order_id,
                    "state": "filled",
                    "field-amount": "0.00015",
                    "field-cash-amount": "0.7",
                    "field-fees": "0",
                },
            }

    class FailingPayoutClient:
        def self_transfer_usdt(self, amount):
            raise RuntimeError("transfer failed after ledger debit")

    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client_with_payout(tmp_path, FailingPayoutClient())
    account = _seed_withdrawable_account(client, tmp_path, "ledger-only")

    withdrawal = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={
            "customer_id": account["customer_id"],
            "provider": "telegram",
            "provider_user_id": "ledger-only",
            "breb_key": "@breb",
            "amount_mode": "partial",
            "portfolio_snapshot": {"xaut_net": 0.00015, "gold_grams_net": 0.00466552152},
        },
    ).json()

    assert withdrawal["status"] == "failed"
    assert withdrawal["ledger_entry_id"].startswith("led-")
    portfolio = client.get(f"/accounts/{account['customer_id']}/portfolio").json()
    assert portfolio["cop_invested"] == 5000.0
    assert portfolio["cop_withdrawn"] == 2500.0
    assert portfolio["cop_net_contributed"] == 2500.0

def test_admin_account_detail_shows_credit_profile(tmp_path) -> None:
    client = make_client(tmp_path)
    account = client.post(
        "/accounts/identify",
        json={"provider": "telegram", "provider_user_id": "credit-admin", "display_name": "Credito Admin"},
    ).json()

    response = client.get(f"/admin/accounts/{account['customer_id']}")

    assert response.status_code == 200
    assert "Perfil crediticio interno" in response.text
    assert "Cupo sugerido" in response.text
    assert "score-ring" in response.text
    assert "Ledger" in response.text


def test_admin_login_protects_dashboard(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        admin_username="admin",
        admin_password="secret-pass",
        admin_session_secret="session-secret",
    )
    client = TestClient(
        create_app(settings=settings), base_url="https://testserver", follow_redirects=False
    )

    blocked = client.get("/admin")
    assert blocked.status_code == 401

    login = client.post("/login", data={"username": "admin", "password": "secret-pass"})
    assert login.status_code == 303
    assert login.headers["location"] == "/admin"
    cookie = login.cookies.get("chaut_admin_session")
    assert cookie
    assert cookie != "session-secret"
    set_cookie = login.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=strict" in set_cookie

    allowed = client.get("/admin")
    assert allowed.status_code == 200
    assert "Chaut Admin" in allowed.text


def test_admin_rejects_missing_csrf_token(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        admin_username="admin",
        admin_password="secret-pass",
        admin_session_secret="session-secret",
    )
    client = TestClient(
        create_app(settings=settings), base_url="https://testserver", follow_redirects=False
    )
    client.post("/login", data={"username": "admin", "password": "secret-pass"})
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 5000}).json()

    response = client.post(f"/admin/orders/{order['external_id']}/mark-attention")

    assert response.status_code == 403


def test_create_withdrawal_request_executes_full_payout_flow(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxPrivateClient:
        calls = 0

        def place_market_sell(self, symbol, amount):
            StubHtxPrivateClient.calls += 1
            assert symbol == "xautusdt"
            assert float(amount) > 0
            return {"status": "ok", "data": "sell-1"}

        def order(self, order_id):
            return {
                "status": "ok",
                "data": {
                    "id": order_id,
                    "state": "filled",
                    "field-amount": "0.000281768398798842",
                    "field-cash-amount": "1.33",
                    "field-fees": "0",
                },
            }

    class StubPayoutClient:
        def __init__(self):
            self.calls = []

        def get_usdt_cop_sell_price(self):
            self.calls.append(("price", None))
            return 3100.0

        def self_transfer_usdt(self, amount):
            self.calls.append(("self_transfer", amount))
            return {"id": "self-1", "status": "accepted"}

        def swap_usdt_to_cop(self, amount):
            self.calls.append(("swap", amount))
            return {"id": "swap-1", "cop_received": 4123.0, "sell_price": 3100.0, "status": "accepted"}

        def send_cop_via_breb(self, breb_key, amount):
            self.calls.append(("breb", breb_key, amount))
            return {"id": "breb-1", "status": "accepted"}

        def check_withdraw_status(self, withdraw_id):
            return {"id": withdraw_id, "status": "accepted"}

    payout_client = StubPayoutClient()
    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client_with_payout(tmp_path, payout_client)
    account = client.post(
        "/accounts/identify",
        json={"provider": "telegram", "provider_user_id": "withdraw-1", "chat_id": "withdraw-1", "display_name": "Retiro Uno"},
    ).json()
    order = client.post(
        "/orders",
        json={"client_id": "telegram:withdraw-1", "customer_id": account["customer_id"], "amount_cop_gross": 5000},
    ).json()
    store = app_module.create_store(build_settings(tmp_path).database_url)
    store.create_ledger_entry(
        app_module.OrderResponse(**{**order, "payment_amount": 1.4, "sell_price_cop_per_usdt": 3500}),
        {"order_id": "buy-1", "xaut_net": "0.0003", "gold_grams_net": "0.009331043040", "field_cash_amount": "1.4"},
        {"prepared": {"ask_price": "4700"}},
    )

    response = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={
            "customer_id": account["customer_id"],
            "provider": "telegram",
            "provider_user_id": "withdraw-1",
            "chat_id": "withdraw-1",
            "breb_key": "@brebTest",
            "portfolio_snapshot": {"xaut_net": 0.0003},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["htx_order_id"] == "sell-1"
    assert body["usdt_received"] == 1.33
    assert body["coinsenda_self_transfer_id"] == "self-1"
    assert body["coinsenda_swap_id"] == "swap-1"
    assert body["cop_received"] == 4123.0
    assert body["coinsenda_sell_price"] == 3100.0
    assert body["coinsenda_withdraw_id"] == "breb-1"
    assert body["cop_paid"] == 4123.0
    assert body["ledger_entry_id"].startswith("led-")
    assert payout_client.calls == [("self_transfer", 1.33), ("price", None), ("swap", 1.33), ("breb", "@brebTest", 4123.0)]
    assert StubHtxPrivateClient.calls == 1
    portfolio = client.get(f"/accounts/{account['customer_id']}/portfolio").json()
    assert portfolio["entries_count"] == 2
    withdrawal_entry = [entry for entry in portfolio["entries"] if entry["entry_type"] == "xaut_withdrawal"][0]
    assert withdrawal_entry["amount"] < 0
    assert withdrawal_entry["gold_grams"] < 0
    events = client.get(f"/withdrawals/{body['withdrawal_id']}").json()
    assert events["status"] == "completed"


def test_create_withdrawal_request_rejects_mismatched_identity(tmp_path) -> None:
    client = make_client(tmp_path)
    account = client.post(
        "/accounts/identify",
        json={"provider": "telegram", "provider_user_id": "owner", "display_name": "Owner"},
    ).json()

    response = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={
            "customer_id": account["customer_id"],
            "provider": "telegram",
            "provider_user_id": "other",
            "breb_key": "3001234567",
            "amount_mode": "all",
        },
    )

    assert response.status_code == 409



def _seed_withdrawable_account(client, tmp_path, user_id="withdraw-x"):
    import chaut_api.app as app_module

    account = client.post(
        "/accounts/identify",
        json={"provider": "telegram", "provider_user_id": user_id, "display_name": "Withdraw User"},
    ).json()
    order = client.post(
        "/orders",
        json={"client_id": f"telegram:{user_id}", "customer_id": account["customer_id"], "amount_cop_gross": 5000},
    ).json()
    store = app_module.create_store(build_settings(tmp_path).database_url)
    store.create_ledger_entry(
        app_module.OrderResponse(**{**order, "payment_amount": 1.4, "sell_price_cop_per_usdt": 3500}),
        {"order_id": "buy-1", "xaut_net": "0.0003", "gold_grams_net": "0.009331043040", "field_cash_amount": "1.4"},
        {"prepared": {"ask_price": "4700"}},
    )
    return account


def test_confirm_payment_updates_withdrawal_to_completed(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            return {"status": "ok", "data": "sell-2"}

        def order(self, order_id):
            return {"status": "ok", "data": {"id": order_id, "state": "filled", "field-amount": "0.0003", "field-cash-amount": "1.4", "field-fees": "0"}}

    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client(tmp_path)
    account = _seed_withdrawable_account(client, tmp_path, "withdraw-confirm")
    withdrawal = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={"customer_id": account["customer_id"], "provider": "telegram", "provider_user_id": "withdraw-confirm", "breb_key": "@breb", "portfolio_snapshot": {"xaut_net": 0.0003}},
    ).json()

    response = client.post(
        f"/withdrawals/{withdrawal['withdrawal_id']}/confirm-payment",
        json={"cop_paid": 5000, "cop_tx_ref": "breb-ref-1", "admin_note": "pagado"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["cop_paid"] == 4900.0
    assert body["coinsenda_withdraw_id"] == "mock-breb-withdraw"
    assert body["completed_at"] is not None


def test_withdrawal_rejects_more_than_available_snapshot(tmp_path) -> None:
    client = make_client(tmp_path)
    account = _seed_withdrawable_account(client, tmp_path, "withdraw-too-much")

    response = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={"customer_id": account["customer_id"], "provider": "telegram", "provider_user_id": "withdraw-too-much", "breb_key": "@breb", "portfolio_snapshot": {"xaut_net": 2}},
    )

    assert response.status_code == 409
    assert "Cannot withdraw more than available" in response.json()["detail"]


def test_mark_withdrawal_failed(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class FailingHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            raise RuntimeError("exchange unavailable")

    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: FailingHtxPrivateClient())
    client = make_client(tmp_path)
    account = _seed_withdrawable_account(client, tmp_path, "withdraw-failed")
    withdrawal = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={"customer_id": account["customer_id"], "provider": "telegram", "provider_user_id": "withdraw-failed", "breb_key": "@breb", "portfolio_snapshot": {"xaut_net": 0.0003}},
    ).json()
    assert withdrawal["status"] == "sell_review"

    response = client.post(
        f"/withdrawals/{withdrawal['withdrawal_id']}/mark-failed",
        json={"reason": "manual failure", "admin_note": "reviewed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["failure_reason"] == "manual failure"


def test_mark_withdrawal_failed_rejects_after_xaut_sale(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            return {"status": "ok", "data": "sell-post-sale"}

        def order(self, order_id):
            return {
                "status": "ok",
                "data": {
                    "id": order_id,
                    "state": "filled",
                    "field-amount": "0.0003",
                    "field-cash-amount": "1.4",
                    "field-fees": "0",
                },
            }

    class FailingPayoutClient:
        def self_transfer_usdt(self, amount):
            raise RuntimeError("coinsenda unavailable")

    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client_with_payout(tmp_path, FailingPayoutClient())
    account = _seed_withdrawable_account(client, tmp_path, "withdraw-post-sale")
    withdrawal = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={
            "customer_id": account["customer_id"],
            "provider": "telegram",
            "provider_user_id": "withdraw-post-sale",
            "breb_key": "@breb",
            "portfolio_snapshot": {"xaut_net": 0.0003},
        },
    ).json()
    assert withdrawal["status"] == "failed"
    assert withdrawal["htx_order_id"] == "sell-post-sale"
    assert withdrawal["ledger_entry_id"].startswith("led-")

    response = client.post(
        f"/withdrawals/{withdrawal['withdrawal_id']}/mark-failed",
        json={"reason": "release reserve", "admin_note": "should not release"},
    )

    assert response.status_code == 409
    assert "external XAUT movement" in response.json()["detail"]


def test_trm_prefers_seticap_close_over_stale_cache(monkeypatch, tmp_path) -> None:
    import chaut_api.trm as trm_module

    cache_path = tmp_path / "trm-cache.json"
    cache_path.write_text(
        '{"reference_rate":3448.35,"source":"seticap-cache-stale","fetched_at_epoch":1}'
    )
    monkeypatch.setattr(trm_module, "CACHE_PATH", cache_path)
    monkeypatch.setattr(
        trm_module,
        "_fetch_seticap_trm",
        lambda: {
            "reference_rate": 3678.15,
            "reference_rate_source": "seticap-close",
            "reference_rate_date": "1/6/2026",
            "source": "seticap",
        },
    )

    trm = trm_module.get_seticap_trm(ttl_seconds=0)

    assert trm["reference_rate"] == 3678.15
    assert trm["source"] == "seticap"
    assert trm["reference_rate_source"] == "seticap-close"


def test_trm_uses_stale_seticap_cache_when_fetch_fails(monkeypatch, tmp_path) -> None:
    import chaut_api.trm as trm_module

    cache_path = tmp_path / "trm-cache.json"
    cache_path.write_text(
        '{"reference_rate":3448.35,"source":"seticap","reference_rate_source":"seticap-close","fetched_at_epoch":1}'
    )
    monkeypatch.setattr(trm_module, "CACHE_PATH", cache_path)
    monkeypatch.setattr(
        trm_module,
        "_fetch_seticap_trm",
        lambda: (_ for _ in ()).throw(RuntimeError("seticap unavailable")),
    )

    trm = trm_module.get_seticap_trm(ttl_seconds=0)

    assert trm["reference_rate"] == 3448.35
    assert trm["source"] == "seticap-cache-stale"
    assert trm["reference_rate_source"] == "seticap-close"


def test_withdrawal_blocks_double_spend_when_first_is_pending(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            return {"status": "ok", "data": "sell-ds-1"}

        def order(self, order_id):
            return {"status": "ok", "data": {"id": order_id, "state": "filled", "field-amount": "0.0003", "field-cash-amount": "1.4", "field-fees": "0"}}

    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client(tmp_path)
    account = _seed_withdrawable_account(client, tmp_path, "double-spend")

    # First withdrawal succeeds and debits the ledger
    first = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={"customer_id": account["customer_id"], "provider": "telegram", "provider_user_id": "double-spend", "breb_key": "@breb1", "portfolio_snapshot": {"xaut_net": 0.0003}},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "completed"

    # Second withdrawal should be blocked: available balance is 0 after ledger debit
    second = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={"customer_id": account["customer_id"], "provider": "telegram", "provider_user_id": "double-spend", "breb_key": "@breb2", "portfolio_snapshot": {"xaut_net": 0.0003}},
    )
    assert second.status_code == 409
    assert "pending withdrawal" in second.json()["detail"] or "No gold available" in second.json()["detail"]


def test_withdrawal_balance_reservation_is_atomic(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class FailingHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            raise RuntimeError("keep reservation pending")

    monkeypatch.setattr(
        app_module,
        "create_htx_private_client",
        lambda *args, **kwargs: FailingHtxPrivateClient(),
    )
    client = make_client(tmp_path)
    account = _seed_withdrawable_account(client, tmp_path, "atomic-reserve")
    payload = {
        "customer_id": account["customer_id"],
        "provider": "telegram",
        "provider_user_id": "atomic-reserve",
        "breb_key": "@breb",
        "portfolio_snapshot": {"xaut_net": 0.0003},
    }

    def request_withdrawal():
        with TestClient(create_app(settings=build_settings(tmp_path))) as thread_client:
            return thread_client.post(
                "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL", json=payload
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: request_withdrawal(), range(2)))

    assert sorted(response.status_code for response in responses) == [200, 409]
    successful = next(response.json() for response in responses if response.status_code == 200)
    assert successful["status"] == "sell_review"
    store = app_module.create_store(build_settings(tmp_path).database_url)
    withdrawals = [
        withdrawal
        for withdrawal in store.list_withdrawals(limit=10)
        if withdrawal.customer_id == account["customer_id"]
    ]
    assert len(withdrawals) == 1
    assert withdrawals[0].xaut_amount == pytest.approx(0.0003)


def test_partial_withdrawal_extracts_only_requested_xaut(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    sold_amounts = []

    class StubHtxPrivateClient:
        def place_market_sell(self, symbol, amount):
            sold_amounts.append(float(amount))
            return {"status": "ok", "data": "sell-partial-1"}

        def order(self, order_id):
            amt = str(sold_amounts[0]) if sold_amounts else "0"
            cash = str(sold_amounts[0] * 4666.67) if sold_amounts else "0"
            return {"status": "ok", "data": {"id": order_id, "state": "filled", "field-amount": amt, "field-cash-amount": cash, "field-fees": "0"}}

    monkeypatch.setattr(app_module, "create_htx_private_client", lambda *args, **kwargs: StubHtxPrivateClient())
    client = make_client(tmp_path)
    account = _seed_withdrawable_account(client, tmp_path, "partial-user")

    # Partial withdrawal: request only half the XAUT
    response = client.post(
        "/withdrawals?confirm=EXECUTE_WITHDRAWAL_XAUT_SELL",
        json={
            "customer_id": account["customer_id"],
            "provider": "telegram",
            "provider_user_id": "partial-user",
            "breb_key": "@brebPartial",
            "amount_mode": "partial",
            "portfolio_snapshot": {"xaut_net": 0.00015, "gold_grams_net": 0.004665521520},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["amount_mode"] == "partial"
    assert body["xaut_amount"] == pytest.approx(0.00015)
    assert len(sold_amounts) == 1
    assert sold_amounts[0] == pytest.approx(0.00015)

    # Portfolio should still have remaining balance
    portfolio = client.get(f"/accounts/{account['customer_id']}/portfolio").json()
    assert portfolio["xaut_net"] > 0
