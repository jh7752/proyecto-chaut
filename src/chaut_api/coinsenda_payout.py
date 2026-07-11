import json
import os
import subprocess
from pathlib import Path
from typing import Protocol


class CoinsendaPayoutClient(Protocol):
    def get_usdt_cop_sell_price(self) -> float: ...
    def self_transfer_usdt(self, amount: float) -> dict: ...
    def swap_usdt_to_cop(self, amount: float) -> dict: ...
    def send_cop_via_breb(self, breb_key: str, amount: float) -> dict: ...
    def check_withdraw_status(self, withdraw_id: str) -> dict: ...


class CoinsendaPayoutNotConfiguredError(RuntimeError):
    pass


class DisabledCoinsendaPayoutClient:
    def get_usdt_cop_sell_price(self) -> float:
        raise CoinsendaPayoutNotConfiguredError("Coinsenda payout integration is not configured")

    def self_transfer_usdt(self, amount: float) -> dict:
        raise CoinsendaPayoutNotConfiguredError("Coinsenda payout integration is not configured")

    def swap_usdt_to_cop(self, amount: float) -> dict:
        raise CoinsendaPayoutNotConfiguredError("Coinsenda payout integration is not configured")

    def send_cop_via_breb(self, breb_key: str, amount: float) -> dict:
        raise CoinsendaPayoutNotConfiguredError("Coinsenda payout integration is not configured")

    def check_withdraw_status(self, withdraw_id: str) -> dict:
        raise CoinsendaPayoutNotConfiguredError("Coinsenda payout integration is not configured")


class MockCoinsendaPayoutClient:
    def get_usdt_cop_sell_price(self) -> float:
        return 3500.0

    def self_transfer_usdt(self, amount: float) -> dict:
        return {"id": "mock-self-transfer", "amount": amount, "currency": "usdt", "status": "accepted"}

    def swap_usdt_to_cop(self, amount: float) -> dict:
        sell_price = self.get_usdt_cop_sell_price()
        cop_received = round(float(amount) * sell_price, 2)
        return {
            "id": "mock-swap",
            "amount": amount,
            "cop_received": cop_received,
            "sell_price": sell_price,
            "status": "accepted",
        }

    def send_cop_via_breb(self, breb_key: str, amount: float) -> dict:
        return {
            "id": "mock-breb-withdraw",
            "breb_key": breb_key,
            "amount": round(float(amount), 2),
            "currency": "cop",
            "status": "accepted",
        }

    def check_withdraw_status(self, withdraw_id: str) -> dict:
        return {"id": withdraw_id, "status": "accepted"}


class ScriptCoinsendaPayoutClient:
    def __init__(
        self,
        runtime_dir: str,
        usdt_payment_account_id: str,
        usdt_trade_account_id: str,
        cop_trade_account_id: str,
    ) -> None:
        self._runtime_dir = Path(runtime_dir)
        self._usdt_payment_account_id = usdt_payment_account_id
        self._usdt_trade_account_id = usdt_trade_account_id
        self._cop_trade_account_id = cop_trade_account_id

    def get_usdt_cop_sell_price(self) -> float:
        return float(self._run_json("pair")["sell_price"])

    def self_transfer_usdt(self, amount: float) -> dict:
        return self._run_json(
            "self-transfer",
            "--amount",
            _format_usdt(amount),
            "--from-account-id",
            self._usdt_payment_account_id,
            "--to-account-id",
            self._usdt_trade_account_id,
        )

    def swap_usdt_to_cop(self, amount: float) -> dict:
        return self._run_json(
            "swap",
            "--amount",
            _format_usdt(amount),
            "--from-account-id",
            self._usdt_trade_account_id,
            "--to-account-id",
            self._cop_trade_account_id,
        )

    def send_cop_via_breb(self, breb_key: str, amount: float) -> dict:
        return self._run_json(
            "breb-withdraw",
            "--amount",
            _format_cop(amount),
            "--breb-key",
            breb_key,
            "--from-account-id",
            self._cop_trade_account_id,
        )

    def check_withdraw_status(self, withdraw_id: str) -> dict:
        return self._run_json("withdraw-status", "--withdraw-id", withdraw_id)

    def _run_json(self, action: str, *args: str) -> dict:
        script = self._runtime_dir / "scripts" / "coinsenda-payout.js"
        if not script.exists():
            raise CoinsendaPayoutNotConfiguredError(f"Coinsenda payout script not found: {script}")
        env = os.environ.copy()
        proc = subprocess.run(
            ["node", str(script), action, *args],
            cwd=self._runtime_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "Coinsenda payout script failed")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Coinsenda payout script returned invalid JSON: {proc.stdout}") from exc


def create_coinsenda_payout_client(
    mode: str,
    runtime_dir: str,
    usdt_payment_account_id: str,
    usdt_trade_account_id: str,
    cop_trade_account_id: str,
) -> CoinsendaPayoutClient:
    if mode == "mock":
        return MockCoinsendaPayoutClient()
    if mode == "script":
        return ScriptCoinsendaPayoutClient(
            runtime_dir,
            usdt_payment_account_id,
            usdt_trade_account_id,
            cop_trade_account_id,
        )
    return DisabledCoinsendaPayoutClient()


def _format_usdt(amount: float) -> str:
    return f"{float(amount):.6f}"


def _format_cop(amount: float) -> str:
    return str(round(float(amount), 2))
