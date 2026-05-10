import json
import urllib.parse
import urllib.request

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


def create_kucoin_client(base_url: str = KUCOIN_BASE_URL, symbol: str = XAUT_SYMBOL) -> KucoinClient:
    return KucoinClient(base_url, symbol)


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
