import pytest
from fastapi.testclient import TestClient

from chaut_api import create_app
from chaut_api.settings import Settings


@pytest.fixture(autouse=True)
def stub_seticap_trm(monkeypatch):
    import chaut_api.app as app_module

    monkeypatch.setattr(
        app_module,
        "get_seticap_trm",
        lambda: {
            "reference_rate": 3794.91,
            "source": "seticap-test",
            "reference_rate_source": "seticap-test",
            "reference_rate_date": "2026-05-18",
        },
    )


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
    assert body["fee_percent"] == 0.5
    assert body["xaut_gross"] > body["xaut_net"]
    assert body["fee_xaut"] > 0
    assert body["gold_grams_gross"] > body["gold_grams_net"]
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
    from chaut_api.settings import Settings
    from chaut_api.store import create_store

    class PendingCoinsendaClient(AcceptedCoinsendaClient):
        def check_payment_request(self, order):
            from chaut_api.coinsenda import PaymentRequestStatus

            return PaymentRequestStatus(payment_status="pending", raw={"payment_request": {"id": order.payment_request_id}})

    client = TestClient(create_app(settings=Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"), coinsenda_client=PendingCoinsendaClient()))
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
