from dataclasses import dataclass

from .models import OrderResponse


@dataclass(frozen=True)
class PaymentRequestResult:
    payment_request_id: str
    payment_url: str
    status: str
    raw: dict


class CoinsendaClient:
    def create_payment_request(self, order: OrderResponse, expiration_minutes: int) -> PaymentRequestResult:
        raise NotImplementedError


class CoinsendaNotConfiguredError(RuntimeError):
    pass


class DisabledCoinsendaClient(CoinsendaClient):
    def create_payment_request(self, order: OrderResponse, expiration_minutes: int) -> PaymentRequestResult:
        raise CoinsendaNotConfiguredError("Coinsenda integration is not configured")


class MockCoinsendaClient(CoinsendaClient):
    def __init__(self, app_origin: str = "https://app.coinsenda.com") -> None:
        self._app_origin = app_origin.rstrip("/")

    def create_payment_request(self, order: OrderResponse, expiration_minutes: int) -> PaymentRequestResult:
        payment_request_id = f"mock-pr-{order.external_id}"
        return PaymentRequestResult(
            payment_request_id=payment_request_id,
            payment_url=f"{self._app_origin}/paymentRequest/{payment_request_id}",
            status="created",
            raw={
                "mode": "mock",
                "external_id": order.external_id,
                "amount": str(order.amount_cop_gross),
                "currency": "cop",
                "expiration_minutes": expiration_minutes,
            },
        )


def create_coinsenda_client(mode: str, app_origin: str) -> CoinsendaClient:
    if mode == "mock":
        return MockCoinsendaClient(app_origin=app_origin)
    return DisabledCoinsendaClient()
