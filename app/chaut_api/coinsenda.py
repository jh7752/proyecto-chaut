import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import OrderResponse


@dataclass(frozen=True)
class PaymentRequestResult:
    payment_request_id: str
    payment_url: str
    status: str
    raw: dict


@dataclass(frozen=True)
class PaymentRequestStatus:
    payment_status: str
    raw: dict


class CoinsendaClient:
    def create_payment_request(self, order: OrderResponse, expiration_minutes: int) -> PaymentRequestResult:
        raise NotImplementedError

    def check_payment_request(self, order: OrderResponse) -> PaymentRequestStatus:
        raise NotImplementedError


class CoinsendaNotConfiguredError(RuntimeError):
    pass


class DisabledCoinsendaClient(CoinsendaClient):
    def create_payment_request(self, order: OrderResponse, expiration_minutes: int) -> PaymentRequestResult:
        raise CoinsendaNotConfiguredError("Coinsenda integration is not configured")

    def check_payment_request(self, order: OrderResponse) -> PaymentRequestStatus:
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

    def check_payment_request(self, order: OrderResponse) -> PaymentRequestStatus:
        return PaymentRequestStatus(
            payment_status=order.payment_status,
            raw={"mode": "mock", "external_id": order.external_id},
        )


class ScriptCoinsendaClient(CoinsendaClient):
    def __init__(self, runtime_dir: str) -> None:
        self._runtime_dir = Path(runtime_dir)

    def create_payment_request(self, order: OrderResponse, expiration_minutes: int) -> PaymentRequestResult:
        record = self._run_json(
            "create-payment-request.js",
            "--amount",
            str(order.amount_cop_gross),
            "--currency",
            "cop",
            "--external-id",
            order.external_id,
            "--expiration",
            str(expiration_minutes),
            "--client-id",
            order.client_id,
        )
        payment_request_id = str(record["payment_request_id"])
        return PaymentRequestResult(
            payment_request_id=payment_request_id,
            payment_url=str(record.get("url") or record.get("pay_url")),
            status=str(record.get("status") or "created"),
            raw=record,
        )

    def check_payment_request(self, order: OrderResponse) -> PaymentRequestStatus:
        if not order.payment_request_id:
            raise ValueError("Order does not have a payment_request_id")
        record = self._run_json("check-payment-request.js", "--id", order.payment_request_id)
        return PaymentRequestStatus(
            payment_status=str(record.get("event_type") or "payment_pending_or_ambiguous"),
            raw=record,
        )

    def _run_json(self, script_name: str, *args: str) -> dict:
        script = self._runtime_dir / "scripts" / script_name
        proc = subprocess.run(
            ["node", str(script), *args],
            cwd=self._runtime_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode not in (0, 2):
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "Coinsenda script failed")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Coinsenda script returned invalid JSON: {proc.stdout}") from exc


def create_coinsenda_client(mode: str, app_origin: str, runtime_dir: str) -> CoinsendaClient:
    if mode == "mock":
        return MockCoinsendaClient(app_origin=app_origin)
    if mode == "script":
        return ScriptCoinsendaClient(runtime_dir=runtime_dir)
    return DisabledCoinsendaClient()
