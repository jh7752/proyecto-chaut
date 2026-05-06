import json
import subprocess
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
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
    def create_payment_request(
        self, order: OrderResponse, expiration_minutes: int, currency: str, payment_amount: float
    ) -> PaymentRequestResult:
        raise NotImplementedError

    def check_payment_request(self, order: OrderResponse) -> PaymentRequestStatus:
        raise NotImplementedError

    def inspect_payment_request(self, order: OrderResponse, click_text: str) -> dict:
        raise NotImplementedError


class CoinsendaNotConfiguredError(RuntimeError):
    pass


class DisabledCoinsendaClient(CoinsendaClient):
    def create_payment_request(
        self, order: OrderResponse, expiration_minutes: int, currency: str, payment_amount: float
    ) -> PaymentRequestResult:
        raise CoinsendaNotConfiguredError("Coinsenda integration is not configured")

    def check_payment_request(self, order: OrderResponse) -> PaymentRequestStatus:
        raise CoinsendaNotConfiguredError("Coinsenda integration is not configured")

    def inspect_payment_request(self, order: OrderResponse, click_text: str) -> dict:
        raise CoinsendaNotConfiguredError("Coinsenda integration is not configured")


class MockCoinsendaClient(CoinsendaClient):
    def __init__(self, app_origin: str = "https://app.coinsenda.com") -> None:
        self._app_origin = app_origin.rstrip("/")

    def create_payment_request(
        self, order: OrderResponse, expiration_minutes: int, currency: str, payment_amount: float
    ) -> PaymentRequestResult:
        payment_request_id = f"mock-pr-{order.external_id}"
        return PaymentRequestResult(
            payment_request_id=payment_request_id,
            payment_url=f"{self._app_origin}/paymentRequest/{payment_request_id}",
            status="created",
            raw={
                "mode": "mock",
                "external_id": order.external_id,
                "amount": str(payment_amount),
                "currency": currency,
                "expiration_minutes": expiration_minutes,
            },
        )

    def check_payment_request(self, order: OrderResponse) -> PaymentRequestStatus:
        return PaymentRequestStatus(
            payment_status=order.payment_status,
            raw={"mode": "mock", "external_id": order.external_id},
        )

    def inspect_payment_request(self, order: OrderResponse, click_text: str) -> dict:
        amount_cop = order.amount_cop_gross
        return {
            "mode": "mock",
            "targetUrl": order.payment_url,
            "clickText": click_text,
            "before": "DCOP PSE",
            "after": {"text": f"DCOP PSE Envia {amount_cop:,} COP a @coinsendaMock123"},
            "events": [],
        }


class ScriptCoinsendaClient(CoinsendaClient):
    def __init__(self, runtime_dir: str) -> None:
        self._runtime_dir = Path(runtime_dir)

    def create_payment_request(
        self, order: OrderResponse, expiration_minutes: int, currency: str, payment_amount: float
    ) -> PaymentRequestResult:
        record = self._run_json(
            "create-payment-request.js",
            "--amount",
            _format_amount(payment_amount, currency),
            "--currency",
            currency,
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


    def inspect_payment_request(self, order: OrderResponse, click_text: str) -> dict:
        if not order.payment_url:
            raise ValueError("Order does not have a payment_url")
        if not click_text:
            return self._run_json("inspect-payment-request-front.js", order.payment_url, allowed_return_codes=(0,))
        try:
            return self._run_json(
                "inspect-payment-request-click.js",
                order.payment_url,
                click_text,
                allowed_return_codes=(0,),
            )
        except RuntimeError as exc:
            front = self._run_json("inspect-payment-request-front.js", order.payment_url, allowed_return_codes=(0,))
            front["clickError"] = str(exc)
            front["clickText"] = click_text
            return front

    def get_usdt_cop_pair(self) -> dict:
        return self._run_json("get-usdt-cop-pair.js", allowed_return_codes=(0,))

    def get_usdt_cop_sell_price(self) -> float:
        return float(self.get_usdt_cop_pair()["sell_price"])

    def _run_json(self, script_name: str, *args: str, allowed_return_codes: tuple[int, ...] = (0, 2)) -> dict:
        script = self._runtime_dir / "scripts" / script_name
        proc = subprocess.run(
            ["node", str(script), *args],
            cwd=self._runtime_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode not in allowed_return_codes:
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


def calculate_usdt_from_cop(target_cop: int | float, sell_price_cop_per_usdt: float) -> float:
    value = (Decimal(str(target_cop)) / Decimal(str(sell_price_cop_per_usdt))).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )
    return float(value)


def _format_amount(payment_amount: float, currency: str) -> str:
    if currency == "usdt":
        return f"{payment_amount:.6f}"
    return str(int(payment_amount)) if float(payment_amount).is_integer() else str(payment_amount)


def get_usdt_cop_pair() -> dict:
    script = Path(__file__).resolve().parents[2] / "vendor" / "coinsenda" / "scripts" / "get-usdt-cop-pair.js"
    if script.exists():
        proc = subprocess.run(
            ["node", str(script)],
            cwd=script.parents[1],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return json.loads(proc.stdout)

    req = urllib.request.Request(
        "https://swap.coinsenda.com/api/pairs/get-all-pairs-for-public",
        headers={
            "Accept": "application/json",
            "Origin": "https://app.coinsenda.com",
            "Referer": "https://app.coinsenda.com/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode())
    pairs = payload.get("data", payload)
    for pair in pairs:
        if pair.get("primary_currency") == "usdt" and pair.get("secondary_currency") == "cop":
            return pair
    raise RuntimeError("USDT/COP pair not found in Coinsenda public pairs")


def get_usdt_cop_sell_price() -> float:
    return float(get_usdt_cop_pair()["sell_price"])
