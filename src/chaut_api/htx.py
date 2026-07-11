import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN, ROUND_UP

import boto3

HTX_BASE_URL = "https://api.huobi.pro"
XAUT_SYMBOL = "xautusdt"
GRAMS_PER_XAUT = Decimal("31.1034768")


class HtxClient:
    def __init__(self, base_url: str = HTX_BASE_URL, symbol: str = XAUT_SYMBOL) -> None:
        self.base_url = base_url.rstrip("/")
        self.symbol = symbol

    def health(self) -> dict:
        ticker = self.get_xaut_ticker()
        return {"status": "ok", "source": "htx", "symbol": ticker["symbol"]}

    def get_xaut_ticker(self) -> dict:
        data = self._get("/market/detail/merged", {"symbol": self.symbol})
        tick = data["tick"]
        bid = tick.get("bid") or [None, None]
        ask = tick.get("ask") or [None, None]
        return {
            "category": "spot",
            "symbol": self.symbol,
            "price": str(tick.get("close")) if tick.get("close") is not None else None,
            "bestBid": str(bid[0]) if bid[0] is not None else None,
            "bestBidSize": str(bid[1]) if bid[1] is not None else None,
            "bestAsk": str(ask[0]) if ask[0] is not None else None,
            "bestAskSize": str(ask[1]) if ask[1] is not None else None,
            "raw": data,
        }

    def get_xaut_instrument(self) -> dict:
        data = self._get("/v1/common/symbols", {})
        for item in data.get("data", []):
            if item.get("symbol") == self.symbol:
                return {"category": "spot", **item, "raw": item}
        raise RuntimeError(f"HTX returned no {self.symbol} symbol data")

    def _get(self, path: str, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ProyectoChaut/0.1"})
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode())
        if payload.get("status") != "ok":
            raise RuntimeError(f"HTX API error: {payload}")
        return payload


class HtxPrivateClient:
    def __init__(self, base_url: str = HTX_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.host = urllib.parse.urlparse(self.base_url).netloc
        self.api_key = os.environ.get("HTX_KEY", "")
        self.api_secret = os.environ.get("HTX_SECRETKEY", "")

    def accounts(self) -> dict:
        return self._request("GET", "/v1/account/accounts")

    def balance(self, account_id: str) -> dict:
        return self._request("GET", f"/v1/account/accounts/{account_id}/balance")

    def place_market_buy(self, symbol: str, funds: str) -> dict:
        account_id = self.spot_account_id()
        body = json.dumps(
            {
                "account-id": account_id,
                "symbol": symbol,
                "type": "buy-market",
                "amount": funds,
                "client-order-id": f"chaut-htx-{int(time.time() * 1000)}",
                "source": "spot-api",
            },
            separators=(",", ":"),
        )
        return self._request("POST", "/v1/order/orders/place", body=body)

    def place_market_sell(self, symbol: str, amount: str) -> dict:
        account_id = self.spot_account_id()
        amount = str(_quantize_down(Decimal(str(amount)), 6))
        body = json.dumps(
            {
                "account-id": account_id,
                "symbol": symbol,
                "type": "sell-market",
                "amount": amount,
                "client-order-id": f"chaut-wd-{int(time.time() * 1000)}",
                "source": "spot-api",
            },
            separators=(",", ":"),
        )
        return self._request("POST", "/v1/order/orders/place", body=body)

    def order(self, order_id: str) -> dict:
        return self._request("GET", f"/v1/order/orders/{order_id}")

    def spot_account_id(self) -> str:
        payload = self.accounts()
        for account in payload.get("data", []):
            if account.get("type") == "spot" and account.get("state") == "working":
                return str(account["id"])
        raise RuntimeError("HTX spot account not found")

    def _request(self, method: str, path: str, params: dict[str, str] | None = None, body: str = "") -> dict:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("HTX private credentials are not configured")
        signed_params = dict(params or {})
        signed_params.update(
            {
                "AccessKeyId": self.api_key,
                "SignatureMethod": "HmacSHA256",
                "SignatureVersion": "2",
                "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            }
        )
        encoded = urllib.parse.urlencode(sorted(signed_params.items()), quote_via=urllib.parse.quote)
        payload = "\n".join([method.upper(), self.host, path, encoded])
        signature = base64.b64encode(hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).digest()).decode()
        query = f"{encoded}&Signature={urllib.parse.quote(signature, safe='')}"
        req = urllib.request.Request(
            f"{self.base_url}{path}?{query}",
            data=body.encode() if body else None,
            method=method.upper(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as response:
            response_payload = json.loads(response.read().decode())
        if response_payload.get("status") != "ok":
            raise RuntimeError(f"HTX private API error: {response_payload}")
        return response_payload


class SsmHtxPrivateClient:
    def __init__(self, instance_id: str, region: str = "ap-south-1") -> None:
        self.instance_id = instance_id
        self.ssm = boto3.client("ssm", region_name=region)

    def accounts(self) -> dict:
        return self._run_worker("accounts", {})

    def balance(self, account_id: str) -> dict:
        return self._run_worker("balance", {"account_id": account_id})

    def place_market_buy(self, symbol: str, funds: str) -> dict:
        return self._run_worker("place_market_buy", {"symbol": symbol, "funds": funds})

    def place_market_sell(self, symbol: str, amount: str) -> dict:
        amount = str(_quantize_down(Decimal(str(amount)), 6))
        return self._run_worker("place_market_sell", {"symbol": symbol, "amount": amount})

    def order(self, order_id: str) -> dict:
        return self._run_worker("order", {"order_id": order_id})

    def _run_worker(self, action: str, params: dict) -> dict:
        worker_payload = {
            "action": action,
            "params": params,
            "env": {
                "HTX_KEY": os.environ.get("HTX_KEY", ""),
                "HTX_SECRETKEY": os.environ.get("HTX_SECRETKEY", ""),
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
            raise RuntimeError(f"HTX worker SSM command failed: {invocation}")
        stdout = invocation.get("StandardOutputContent", "").strip()
        if not stdout:
            raise RuntimeError("HTX worker returned empty output")
        result = json.loads(stdout)
        if not result.get("ok"):
            raise RuntimeError(f"HTX worker error: {result}")
        return result["payload"]


def _worker_script(payload: dict) -> str:
    action = payload.get("action")
    if action in {"accounts", "balance"}:
        return _accounts_worker_script(payload)
    if action == "place_market_buy":
        return _buy_worker_script(payload)
    if action == "place_market_sell":
        return _sell_worker_script(payload)
    if action == "order":
        return _order_worker_script(payload)
    raise RuntimeError(f"unknown HTX worker action {action}")


def _worker_prelude(payload: dict) -> str:
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
base = "https://api.huobi.pro"
host = "api.huobi.pro"
api_key = os.environ["HTX_KEY"]
api_secret = os.environ["HTX_SECRETKEY"]
def call(method, path, body=""):
    params = {{
        "AccessKeyId": api_key,
        "SignatureMethod": "HmacSHA256",
        "SignatureVersion": "2",
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }}
    encoded = urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)
    payload = "\\n".join([method.upper(), host, path, encoded])
    signature = base64.b64encode(hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).digest()).decode()
    query = encoded + "&Signature=" + urllib.parse.quote(signature, safe="")
    req = urllib.request.Request(
        base + path + "?" + query,
        data=body.encode() if body else None,
        method=method.upper(),
        headers={{"Content-Type": "application/json", "Accept": "application/json"}},
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.loads(response.read().decode())
    if payload.get("status") != "ok":
        raise RuntimeError(str(payload))
    return payload
def spot_account_id():
    payload = call("GET", "/v1/account/accounts")
    for account in payload.get("data", []):
        if account.get("type") == "spot" and account.get("state") == "working":
            return str(account["id"])
    raise RuntimeError("HTX spot account not found")
params = request.get("params", {{}})
'''


def _accounts_worker_script(payload: dict) -> str:
    return _worker_prelude(payload) + '''
action = request["action"]
if action == "accounts":
    payload = call("GET", "/v1/account/accounts")
elif action == "balance":
    payload = call("GET", "/v1/account/accounts/" + str(params["account_id"]) + "/balance")
else:
    raise RuntimeError("unknown accounts action " + action)
print(json.dumps({"ok": True, "payload": payload}))
'''


def _buy_worker_script(payload: dict) -> str:
    return _worker_prelude(payload) + '''
body = json.dumps({"account-id": spot_account_id(), "symbol": params["symbol"], "type": "buy-market", "amount": params["funds"], "client-order-id": "chaut-htx-" + str(int(time.time() * 1000)), "source": "spot-api"}, separators=(",", ":"))
payload = call("POST", "/v1/order/orders/place", body)
print(json.dumps({"ok": True, "payload": payload}))
'''


def _sell_worker_script(payload: dict) -> str:
    return _worker_prelude(payload) + '''
body = json.dumps({"account-id": spot_account_id(), "symbol": params["symbol"], "type": "sell-market", "amount": params["amount"], "client-order-id": "chaut-wd-" + str(int(time.time() * 1000)), "source": "spot-api"}, separators=(",", ":"))
payload = call("POST", "/v1/order/orders/place", body)
print(json.dumps({"ok": True, "payload": payload}))
'''


def _order_worker_script(payload: dict) -> str:
    return _worker_prelude(payload) + '''
payload = call("GET", "/v1/order/orders/" + str(params["order_id"]))
print(json.dumps({"ok": True, "payload": payload}))
'''


def create_htx_client(base_url: str = HTX_BASE_URL, symbol: str = XAUT_SYMBOL) -> HtxClient:
    return HtxClient(base_url, symbol)


def create_htx_private_client(worker_instance_id: str | None = None, worker_region: str = "ap-south-1"):
    if worker_instance_id:
        return SsmHtxPrivateClient(worker_instance_id, worker_region)
    return HtxPrivateClient()


def summarize_accounts(payload: dict) -> list[dict]:
    return [{k: account.get(k) for k in ("id", "type", "subtype", "state")} for account in payload.get("data", [])]


def prepare_xaut_market_buy(
    confirmed_usdt: float,
    ask_price: float,
    fee_percent: float,
    instrument: dict,
    symbol: str = XAUT_SYMBOL,
) -> dict:
    funds = Decimal(str(confirmed_usdt))
    ask = Decimal(str(ask_price))
    min_order_value = Decimal(str(instrument.get("min-order-value", "1")))
    if funds < min_order_value:
        raise ValueError("confirmed USDT is below HTX min-order-value")
    estimated_gross = _quantize_down(funds / ask, 12)
    estimated_fee = _quantize_down(estimated_gross * Decimal(str(fee_percent)) / Decimal("100"), 12)
    estimated_net = estimated_gross - estimated_fee
    return {
        "venue": "htx",
        "symbol": symbol,
        "order_type": "buy-market",
        "side": "buy",
        "funds": str(funds),
        "confirmed_usdt": str(funds),
        "estimated_xaut_gross": str(estimated_gross),
        "estimated_exchange_fee_xaut": str(estimated_fee),
        "estimated_xaut_net": str(estimated_net),
        "estimated_gold_grams_net": str(_quantize_down(estimated_net * GRAMS_PER_XAUT, 12)),
        "ask_price": str(ask),
        "min_order_value": str(min_order_value),
        "status": "prepared",
    }


def summarize_sold_order(order_payload: dict) -> dict:
    data = order_payload.get("data", {})
    return {
        "order_id": str(data.get("id")) if data.get("id") is not None else None,
        "state": data.get("state"),
        "field_amount": str(data.get("field-amount") or "0"),
        "field_cash_amount": str(data.get("field-cash-amount") or "0"),
        "field_fees": str(data.get("field-fees") or "0"),
        "raw": data,
    }


def summarize_filled_order(order_payload: dict) -> dict:
    data = order_payload.get("data", {})
    field_amount = Decimal(str(data.get("field-amount") or "0"))
    field_fees = Decimal(str(data.get("field-fees") or "0"))
    xaut_net = field_amount - field_fees
    return {
        "order_id": str(data.get("id")) if data.get("id") is not None else None,
        "state": data.get("state"),
        "field_amount": str(field_amount),
        "field_cash_amount": str(data.get("field-cash-amount") or "0"),
        "field_fees": str(field_fees),
        "xaut_net": str(xaut_net),
        "gold_grams_net": str(_quantize_down(xaut_net * GRAMS_PER_XAUT, 12)),
        "raw": data,
    }


def quote_xaut_from_usdt(confirmed_usdt: float, ask_price: float, fee_percent: float) -> dict:
    xaut_gross = Decimal(str(confirmed_usdt)) / Decimal(str(ask_price))
    fee_xaut = xaut_gross * Decimal(str(fee_percent)) / Decimal("100")
    xaut_net = xaut_gross - fee_xaut
    return {
        "confirmed_usdt": round(float(confirmed_usdt), 8),
        "xaut_ask_price": float(ask_price),
        "fee_percent": fee_percent,
        "fee_xaut": round(float(fee_xaut), 12),
        "xaut_gross": round(float(xaut_gross), 12),
        "xaut_net": round(float(xaut_net), 12),
        "gold_grams_gross": round(float(xaut_gross * GRAMS_PER_XAUT), 12),
        "gold_grams_net": round(float(xaut_net * GRAMS_PER_XAUT), 12),
        "status": "quoted",
    }


def _quantize_down(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def _quantize_up(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_UP)
