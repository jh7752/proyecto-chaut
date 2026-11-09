import io
import json
import urllib.request

import pytest

from chaut_api import coinsenda


def test_get_usdt_cop_pair_uses_clean_post_payload(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {
                            "primary_currency": "usdt",
                            "secondary_currency": "cop",
                            "sell_price": "3116.32",
                            "enabled": True,
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        captured["content_type"] = request.headers["Content-type"]
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    pair = coinsenda.get_usdt_cop_pair()

    assert captured == {
        "method": "POST",
        "body": {"data": {}},
        "timeout": 20,
        "content_type": "application/json",
    }
    assert pair["sell_price"] == "3116.32"


def test_get_usdt_cop_pair_rejects_invalid_shape(monkeypatch) -> None:
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(json.dumps({"data": {"error": "invalid"}}).encode()),
    )

    with pytest.raises(RuntimeError, match="response is not an array"):
        coinsenda.get_usdt_cop_pair()
