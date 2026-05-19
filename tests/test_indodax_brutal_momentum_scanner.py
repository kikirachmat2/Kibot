import asyncio

from Core.Scanner.indodax_market_scanner import IndodaxMarketScanner


def test_indodax_scanner_market_wide_fields():
    state = asyncio.run(IndodaxMarketScanner().scan())
    assert state["scan_mode"] == "REAL_EXCHANGE_MARKET_WIDE"
    assert "candidates" in state
