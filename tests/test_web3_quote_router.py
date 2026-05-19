import pytest
from Core.Web3.web3_quote_router import Web3QuoteRouter

@pytest.mark.anyio
async def test_web3_quote_router_rejects_zero_amount():
    router = Web3QuoteRouter()
    res = await router.quote('solana', 'SOL', 'USDC', 0)
    assert not res['quote_ok']
    assert 'invalid amount' in res['reason']
