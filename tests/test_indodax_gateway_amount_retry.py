import pytest

from Core.Exchange.indodax import IndodaxGateway


@pytest.mark.anyio
async def test_trade_retries_integer_amount_when_exchange_rejects_decimal(monkeypatch):
    gateway = IndodaxGateway(api_key="key", api_secret="secret")
    calls = []

    async def fake_pair_info(pair):
        return {}

    async def fake_post(method, params):
        calls.append(dict(params))
        if len(calls) == 1:
            return {"success": 0, "error": "amount can't be in decimal."}
        return {"success": 1, "return": {"order_id": "ok"}}

    monkeypatch.setattr(gateway, "get_pair_info", fake_pair_info)
    monkeypatch.setattr(gateway, "_post_private", fake_post)

    result = await gateway.trade("pond_idr", "sell", 112.5, amount_coin=556.1234)

    assert result["success"] == 1
    assert calls[0]["pond"] == 556.1234
    assert calls[1]["pond"] == 556
