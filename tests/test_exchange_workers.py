import pytest

from chaut_api import htx


def test_ssm_htx_sell_client_truncates_amount_to_exchange_precision(monkeypatch) -> None:
    captured = {}

    class FakeSsm:
        def send_command(self, **kwargs):
            captured["script"] = kwargs["Parameters"]["commands"][0]
            return {"Command": {"CommandId": "cmd-1"}}

        def get_command_invocation(self, **kwargs):
            return {
                "Status": "Success",
                "StandardOutputContent": '{"ok": true, "payload": {"status": "ok", "data": "sell-1"}}',
            }

    monkeypatch.setattr(htx.boto3, "client", lambda *args, **kwargs: FakeSsm())

    client = htx.SsmHtxPrivateClient("i-worker")
    client.place_market_sell("xautusdt", "0.001313766022980094")

    assert "0.001313" in captured["script"]
    assert "0.001313766022980094" not in captured["script"]


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
