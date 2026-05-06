import json
import urllib.parse
import urllib.request

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
