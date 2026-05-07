import json
import time
import urllib.parse
import urllib.request

import boto3

BYBIT_BASE_URL = "https://api.bybit.com"


class BybitClient:
    def __init__(self, base_url: str = BYBIT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        ticker = self.get_xaut_ticker()
        return {"status": "ok", "source": "bybit", "symbol": ticker.get("symbol", "XAUTUSDT")}

    def get_xaut_ticker(self) -> dict:
        data = self._get("/v5/market/tickers", {"category": "spot", "symbol": "XAUTUSDT"})
        item = _first_result(data)
        return {"category": "spot", **item, "raw": data}

    def get_xaut_instrument(self) -> dict:
        data = self._get(
            "/v5/market/instruments-info",
            {"category": "spot", "symbol": "XAUTUSDT"},
        )
        item = _first_result(data)
        return {"category": "spot", **item, "raw": data}

    def _get(self, path: str, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{self.base_url}{path}?{query}",
            headers={"Accept": "application/json", "User-Agent": "ProyectoChaut/0.1"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode())
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit API error: {payload}")
        return payload


def _first_result(payload: dict) -> dict:
    items = payload.get("result", {}).get("list", [])
    if not items:
        raise RuntimeError("Bybit returned no XAUTUSDT data")
    return items[0]


class SsmBybitClient:
    def __init__(self, instance_id: str, region: str = "ap-south-1") -> None:
        self.instance_id = instance_id
        self.region = region
        self.ssm = boto3.client("ssm", region_name=region)

    def health(self) -> dict:
        ticker = self.get_xaut_ticker()
        return {"status": "ok", "source": "bybit-worker-ssm", "symbol": ticker.get("symbol", "XAUTUSDT")}

    def get_xaut_ticker(self) -> dict:
        data = self._run_bybit_json(
            "curl -sS 'https://api.bybit.com/v5/market/tickers?category=spot&symbol=XAUTUSDT'"
        )
        item = _first_result(data)
        return {"category": "spot", **item, "raw": data}

    def get_xaut_instrument(self) -> dict:
        data = self._run_bybit_json(
            "curl -sS 'https://api.bybit.com/v5/market/instruments-info?category=spot&symbol=XAUTUSDT'"
        )
        item = _first_result(data)
        return {"category": "spot", **item, "raw": data}

    def _run_bybit_json(self, command: str) -> dict:
        response = self.ssm.send_command(
            InstanceIds=[self.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command]},
            TimeoutSeconds=60,
        )
        command_id = response["Command"]["CommandId"]
        invocation = None
        for _ in range(18):
            time.sleep(2)
            invocation = self.ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=self.instance_id,
            )
            if invocation["Status"] in {"Success", "Failed", "TimedOut", "Cancelled"}:
                break
        if invocation is None or invocation["Status"] != "Success":
            raise RuntimeError(f"Bybit worker SSM command failed: {invocation}")
        stdout = invocation.get("StandardOutputContent", "").strip()
        if not stdout:
            raise RuntimeError("Bybit worker returned empty output")
        payload = json.loads(stdout)
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit worker API error: {payload}")
        return payload


def create_bybit_client(worker_instance_id: str | None = None, worker_region: str = "ap-south-1"):
    if worker_instance_id:
        return SsmBybitClient(worker_instance_id, worker_region)
    return BybitClient()


def quote_xaut_from_usdt(confirmed_usdt: float, ask_price: float, fee_percent: float) -> dict:
    xaut_gross = confirmed_usdt / ask_price
    fee_xaut = xaut_gross * (fee_percent / 100)
    xaut_net = xaut_gross - fee_xaut
    grams_per_xaut = 31.1034768
    return {
        "confirmed_usdt": round(confirmed_usdt, 8),
        "xaut_ask_price": ask_price,
        "fee_percent": fee_percent,
        "fee_xaut": round(fee_xaut, 12),
        "xaut_gross": round(xaut_gross, 12),
        "xaut_net": round(xaut_net, 12),
        "gold_grams_gross": round(xaut_gross * grams_per_xaut, 12),
        "gold_grams_net": round(xaut_net * grams_per_xaut, 12),
        "status": "quoted",
    }
