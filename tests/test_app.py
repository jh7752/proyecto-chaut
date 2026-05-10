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
    assert body["checkout_status"] == "ready"
    assert body["pay_amount_cop_numeric"] == 5000
    assert body["price_slippage_cop"] == 0
    assert body["attempts"] == 1
    assert "DCOP" in body["instructions"]["methods"]

    events = client.get(f"/orders/{body['external_id']}/events").json()
    assert [event["event_type"] for event in events] == [
        "order.created",
        "payment_request.created",
        "payment_instructions.inspected",
    ]


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
    first_events = client.get(f"/orders/{first_external_id}/events").json()
    assert first_events[-1]["event_type"] == "checkout.price_mismatch"


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


def test_bybit_public_endpoints(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubBybitClient:
        def health(self):
            return {"status": "ok", "source": "bybit", "symbol": "XAUTUSDT"}

        def get_xaut_ticker(self):
            return {
                "category": "spot",
                "symbol": "XAUTUSDT",
                "lastPrice": "3300.12",
                "bid1Price": "3299.10",
                "ask1Price": "3301.20",
                "raw": {"retCode": 0},
            }

        def get_xaut_instrument(self):
            return {
                "category": "spot",
                "symbol": "XAUTUSDT",
                "baseCoin": "XAUT",
                "quoteCoin": "USDT",
                "status": "Trading",
                "lotSizeFilter": {"minOrderQty": "0.00001"},
                "priceFilter": {"tickSize": "0.01"},
                "raw": {"retCode": 0},
            }

    monkeypatch.setattr(app_module, "create_bybit_client", lambda *args, **kwargs: StubBybitClient())
    client = make_client(tmp_path)

    assert client.get("/bybit/health").json() == {
        "status": "ok",
        "source": "bybit",
        "symbol": "XAUTUSDT",
    }
    assert client.get("/bybit/xaut-ticker").json()["lastPrice"] == "3300.12"
    assert client.get("/bybit/xaut-instrument").json()["baseCoin"] == "XAUT"


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


def test_xaut_quote_requires_confirmed_payment(monkeypatch, tmp_path) -> None:
    import chaut_api.app as app_module

    class StubKucoinClient:
        def get_xaut_ticker(self):
            return {
                "category": "spot",
                "symbol": "XAUT-USDT",
                "bestAsk": "4692.8",
                "price": "4692.0",
                "raw": {"code": "200000"},
            }

    monkeypatch.setattr(app_module, "create_kucoin_client", lambda *args, **kwargs: StubKucoinClient())
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
                "symbol": "XAUT-USDT",
                "bestAsk": "4692.8",
                "price": "4692.0",
                "raw": {"code": "200000"},
            }

    monkeypatch.setattr(app_module, "create_kucoin_client", lambda *args, **kwargs: StubKucoinClient())
    client = make_client_with_coinsenda(tmp_path, AcceptedUsdtCoinsendaClient())
    order = client.post("/orders", json={"client_id": "cli-test", "amount_cop_gross": 2000}).json()
    client.post(
        f"/orders/{order['external_id']}/payment-request",
        json={"currency": "usdt", "sell_price_cop_per_usdt": 3527.49},
    )
    client.post(f"/orders/{order['external_id']}/reconcile-payment")

    response = client.post(f"/orders/{order['external_id']}/xaut-quote")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "quoted"
    assert body["confirmed_usdt"] == 0.566975
    assert body["xaut_ask_price"] == 4692.8
    assert body["fee_percent"] == 0.5
    assert body["xaut_gross"] > body["xaut_net"]
    assert body["fee_xaut"] > 0
    assert body["gold_grams_gross"] > body["gold_grams_net"]
    events = client.get(f"/orders/{order['external_id']}/events").json()
    assert events[-1]["event_type"] == "xaut.quote_created"
    assert events[-1]["payload"]["gold_grams_net"] == body["gold_grams_net"]
