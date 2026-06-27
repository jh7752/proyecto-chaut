import pytest

from chaut_api import htx, kucoin


@pytest.mark.parametrize(
    ("action", "params"),
    [
        ("accounts", {}),
        ("balance", {"account_id": "123"}),
        ("place_market_buy", {"symbol": "xautusdt", "funds": "1.23"}),
        ("place_market_sell", {"symbol": "xautusdt", "amount": "0.0003"}),
        ("order", {"order_id": "456"}),
    ],
)
def test_htx_worker_script_builds_valid_python_for_all_actions(action, params) -> None:
    script = htx._worker_script(
        {
            "action": action,
            "params": params,
            "env": {"HTX_KEY": "fake-key", "HTX_SECRETKEY": "fake-secret"},
        }
    )

    compile(script, "<htx-worker>", "exec")


def test_htx_buy_worker_does_not_include_sell_path() -> None:
    script = htx._worker_script(
        {
            "action": "place_market_buy",
            "params": {"symbol": "xautusdt", "funds": "1.23"},
            "env": {"HTX_KEY": "fake-key", "HTX_SECRETKEY": "fake-secret"},
        }
    )

    assert "buy-market" in script
    assert "sell-market" not in script
    assert "params[\"amount\"]" not in script


def test_htx_sell_worker_does_not_include_buy_path() -> None:
    script = htx._worker_script(
        {
            "action": "place_market_sell",
            "params": {"symbol": "xautusdt", "amount": "0.0003"},
            "env": {"HTX_KEY": "fake-key", "HTX_SECRETKEY": "fake-secret"},
        }
    )

    assert "sell-market" in script
    assert "buy-market" not in script
    assert "params[\"funds\"]" not in script


@pytest.mark.parametrize(
    ("action", "params"),
    [
        ("accounts", {}),
        ("accounts", {"currency": "USDT"}),
        ("inner_transfer", {"currency": "USDT", "amount": "1", "from": "main", "to": "trade"}),
        ("place_market_buy", {"symbol": "XAUT-USDT", "funds": "1.23"}),
    ],
)
def test_kucoin_worker_script_builds_valid_python_for_all_actions(action, params) -> None:
    script = kucoin._worker_script(
        {
            "action": action,
            "params": params,
            "env": {
                "KUCOIN_API_KEY": "fake-key",
                "KUCOIN_API_SECRET": "fake-secret",
                "KUCOIN_API_PASSPHRASE": "fake-passphrase",
                "KUCOIN_API_KEY_VERSION": "2",
            },
        }
    )

    compile(script, "<kucoin-worker>", "exec")
