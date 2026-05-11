import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN

import boto3

KUCOIN_BASE_URL = "https://api.kucoin.com"
XAUT_SYMBOL = "XAUT-USDT"


class KucoinClient:
    def __init__(self, base_url: str = KUCOIN_BASE_URL, symbol: str = XAUT_SYMBOL) -> None:
        self.base_url = base_url.rstrip("/")
        self.symbol = symbol

    def health(self) -> dict:
        ticker = self.get_xaut_ticker()
        return {"status": "ok", "source": "kucoin", "symbol": ticker["symbol"]}

    def get_xaut_ticker(self) -> dict:
        data = self._get("/api/v1/market/orderbook/level1", {"symbol": self.symbol})
        item = data["data"]
        return {"category": "spot", "symbol": self.symbol, **item, "raw": data}

    def get_xaut_instrument(self) -> dict:
        data = self._get("/api/v2/symbols", {})
        for item in data.get("data", []):
            if item.get("symbol") == self.symbol:
                return {"category": "spot", **item, "raw": item}
        raise RuntimeError(f"KuCoin returned no {self.symbol} symbol data")

    def _get(self, path: str, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "ProyectoChaut/0.1"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode())
        if payload.get("code") != "200000":
            raise RuntimeError(f"KuCoin API error: {payload}")
        return payload


class KucoinPrivateClient:
    def __init__(self, base_url: str = KUCOIN_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get("KUCOIN_API_KEY", "")
        self.api_secret = os.environ.get("KUCOIN_API_SECRET", "")
        self.api_passphrase = os.environ.get("KUCOIN_API_PASSPHRASE", "")
        self.api_key_version = os.environ.get("KUCOIN_API_KEY_VERSION", "2") or "2"

    def accounts(self, currency: str | None = None) -> dict:
        path = "/api/v1/accounts"
        if currency:
            path = f"{path}?{urllib.parse.urlencode({'currency': currency})}"
        return self._request("GET", path)

    def inner_transfer(self, currency: str, amount: str, from_type: str = "main", to_type: str = "trade") -> dict:
        body = json.dumps(
            {
                "clientOid": f"chaut-{int(time.time() * 1000)}",
                "currency": currency,
                "amount": amount,
                "from": from_type,
                "to": to_type,
            },
            separators=(",", ":"),
        )
        return self._request("POST", "/api/v2/accounts/inner-transfer", body)

    def place_market_buy(self, symbol: str, funds: str) -> dict:
        body = json.dumps(
            {
                "clientOid": f"chaut-{int(time.time() * 1000)}",
                "side": "buy",
                "symbol": symbol,
                "type": "market",
                "funds": funds,
            },
            separators=(",", ":"),
        )
        return self._request("POST", "/api/v1/orders", body)

    def _request(self, method: str, path: str, body: str = "") -> dict:
        if not self.api_key or not self.api_secret or not self.api_passphrase:
            raise RuntimeError("KuCoin private credentials are not configured")
        timestamp = str(int(time.time() * 1000))
        prehash = f"{timestamp}{method.upper()}{path}{body}"
        sign = base64.b64encode(hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        passphrase = self.api_passphrase
        if self.api_key_version != "1":
            passphrase = base64.b64encode(
                hmac.new(self.api_secret.encode(), self.api_passphrase.encode(), hashlib.sha256).digest()
            ).decode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body.encode() if body else None,
            method=method.upper(),
            headers={
                "KC-API-KEY": self.api_key,
                "KC-API-SIGN": sign,
                "KC-API-TIMESTAMP": timestamp,
                "KC-API-PASSPHRASE": passphrase,
                "KC-API-KEY-VERSION": self.api_key_version,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode())
        if payload.get("code") != "200000":
            raise RuntimeError(f"KuCoin private API error: {payload}")
        return payload


class SsmKucoinPrivateClient:
    def __init__(self, instance_id: str, region: str = "ap-south-1") -> None:
        self.instance_id = instance_id
        self.ssm = boto3.client("ssm", region_name=region)

    def accounts(self, currency: str | None = None) -> dict:
        return self._run_worker("accounts", {"currency": currency})

    def inner_transfer(self, currency: str, amount: str, from_type: str = "main", to_type: str = "trade") -> dict:
        return self._run_worker("inner_transfer", {"currency": currency, "amount": amount, "from": from_type, "to": to_type})

    def place_market_buy(self, symbol: str, funds: str) -> dict:
        return self._run_worker("place_market_buy", {"symbol": symbol, "funds": funds})

    def _run_worker(self, action: str, params: dict) -> dict:
        worker_payload = {
            "action": action,
            "params": params,
            "env": {
                "KUCOIN_API_KEY": os.environ.get("KUCOIN_API_KEY", ""),
                "KUCOIN_API_SECRET": os.environ.get("KUCOIN_API_SECRET", ""),
                "KUCOIN_API_PASSPHRASE": os.environ.get("KUCOIN_API_PASSPHRASE", ""),
                "KUCOIN_API_KEY_VERSION": os.environ.get("KUCOIN_API_KEY_VERSION", "2"),
            },
        }
        script = _worker_script(worker_payload)
        response = self.ssm.send_command(
            InstanceIds=[self.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [f"python3 - <<'PY'\n{script}\nPY"]},
            TimeoutSeconds=90,
        )
        command_id = response["Command"]["CommandId"]
        invocation = None
        for _ in range(45):
            time.sleep(2)
            invocation = self.ssm.get_command_invocation(CommandId=command_id, InstanceId=self.instance_id)
            if invocation["Status"] in {"Success", "Failed", "TimedOut", "Cancelled"}:
                break
        if invocation is None or invocation["Status"] != "Success":
            raise RuntimeError(f"KuCoin worker SSM command failed: {invocation}")
        stdout = invocation.get("StandardOutputContent", "").strip()
        if not stdout:
            raise RuntimeError("KuCoin worker returned empty output")
        result = json.loads(stdout)
        if not result.get("ok"):
            raise RuntimeError(f"KuCoin worker error: {result}")
        return result["payload"]


def _worker_script(payload: dict) -> str:
    payload_json = json.dumps(payload)
    return f'''
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
request = json.loads({payload_json!r})
for key, value in request.get("env", {{}}).items():
    os.environ[key] = value
base = "https://api.kucoin.com"
api_key = os.environ["KUCOIN_API_KEY"]
api_secret = os.environ["KUCOIN_API_SECRET"]
api_passphrase = os.environ["KUCOIN_API_PASSPHRASE"]
api_version = os.environ.get("KUCOIN_API_KEY_VERSION", "2") or "2"
def call(method, path, body=""):
    timestamp = str(int(time.time() * 1000))
    prehash = timestamp + method.upper() + path + body
    sign = base64.b64encode(hmac.new(api_secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
    passphrase = api_passphrase
    if api_version != "1":
        passphrase = base64.b64encode(hmac.new(api_secret.encode(), api_passphrase.encode(), hashlib.sha256).digest()).decode()
    req = urllib.request.Request(
        base + path,
        data=body.encode() if body else None,
        method=method.upper(),
        headers={{
            "KC-API-KEY": api_key,
            "KC-API-SIGN": sign,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-PASSPHRASE": passphrase,
            "KC-API-KEY-VERSION": api_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode())
    if payload.get("code") != "200000":
        raise RuntimeError(str(payload))
    return payload
action = request["action"]
params = request.get("params", {{}})
if action == "accounts":
    currency = params.get("currency")
    path = "/api/v1/accounts"
    if currency:
        path = path + "?" + urllib.parse.urlencode({{"currency": currency}})
    payload = call("GET", path)
elif action == "inner_transfer":
    body = json.dumps({{"clientOid": "chaut-" + str(int(time.time() * 1000)), "currency": params["currency"], "amount": params["amount"], "from": params.get("from", "main"), "to": params.get("to", "trade")}}, separators=(",", ":"))
    payload = call("POST", "/api/v2/accounts/inner-transfer", body)
elif action == "place_market_buy":
    body = json.dumps({{"clientOid": "chaut-" + str(int(time.time() * 1000)), "side": "buy", "symbol": params["symbol"], "type": "market", "funds": params["funds"]}}, separators=(",", ":"))
    payload = call("POST", "/api/v1/orders", body)
else:
    raise RuntimeError("unknown action " + action)
print(json.dumps({{"ok": True, "payload": payload}}))
'''


def create_kucoin_client(base_url: str = KUCOIN_BASE_URL, symbol: str = XAUT_SYMBOL) -> KucoinClient:
    return KucoinClient(base_url, symbol)


def create_kucoin_private_client(worker_instance_id: str | None = None, worker_region: str = "ap-south-1"):
    if worker_instance_id:
        return SsmKucoinPrivateClient(worker_instance_id, worker_region)
    return KucoinPrivateClient()


def summarize_accounts(payload: dict) -> list[dict]:
    return [{k: account.get(k) for k in ("currency", "type", "balance", "available", "holds")} for account in payload.get("data", [])]


def prepare_xaut_market_buy(
    confirmed_usdt: float,
    ask_price: float,
    fee_percent: float,
    base_increment: str,
    min_funds: str,
    symbol: str = XAUT_SYMBOL,
) -> dict:
    funds = Decimal(str(confirmed_usdt))
    ask = Decimal(str(ask_price))
    increment = Decimal(str(base_increment))
    min_funds_decimal = Decimal(str(min_funds))
    if funds < min_funds_decimal:
        raise ValueError("confirmed USDT is below KuCoin minFunds")
    gross = (funds / ask).quantize(increment, rounding=ROUND_DOWN)
    fee = (gross * Decimal(str(fee_percent)) / Decimal("100")).quantize(Decimal("0.000000000001"), rounding=ROUND_DOWN)
    net = gross - fee
    return {
        "symbol": symbol,
        "order_type": "market",
        "side": "buy",
        "funds": str(funds),
        "estimated_xaut_gross": str(gross),
        "fee_xaut": str(fee),
        "estimated_xaut_net": str(net),
        "estimated_gold_grams_net": str((net * Decimal("31.1034768")).quantize(Decimal("0.000000000001"))),
        "ask_price": str(ask),
        "base_increment": str(increment),
        "min_funds": str(min_funds_decimal),
        "status": "prepared",
    }


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
