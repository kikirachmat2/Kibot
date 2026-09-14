import pytest
from unittest.mock import AsyncMock, patch
from async_helper import run_async

from council.evaluator import CouncilDecision
from main import KiBotV2Pipeline
from config import settings


@run_async
async def test_two_stage_pipeline_blocks_insufficient_depth(tmp_path):
    """
    Test Stage 2 Microstructure Verification:
    - Council approves a BUY signal for an illiquid pair (e.g. THIN/IDR).
    - Indodax depth returns thin book (only 50,000 IDR depth).
    - Stage 2 MUST reject with INSUFFICIENT_DEPTH before opening any position.
    """
    with patch.object(settings, "STATE_DIR", tmp_path):
        app = KiBotV2Pipeline()
        
        thin_orderbook = {
            "buy": [["1000", "50"]],
            "sell": [["1020", "50"]],  # 50 * 1020 = 51,000 IDR depth
        }
        
        # Mock get_orderbook to return thin orderbook
        app.indodax_ws.get_orderbook = AsyncMock(return_value=thin_orderbook)
        app.indodax_ws.subscribe_orderbook = AsyncMock()
        
        decision = CouncilDecision(
            verdict="APPROVED",
            symbol="THIN/IDR",
            action="BUY",
            confidence=0.88,
            score=0.85,
            reason="High EV candidate",
            suggested_size_idr=1_000_000.0,  # Needs 1M, depth is only 51k
            ev_pct=0.45,
            kelly_fraction=0.1,
            rr_ratio=1.5,
            deliberation_duration_ms=0.5,
            enrichment_status="FRESH",
            target_tp_pct=1.8,
            target_sl_pct=2.4,
        )
        
        candidate = {"price": 1000.0, "symbol": "THIN/IDR"}
        
        await app._on_council_decision(decision, candidate)
        
        # Verify VirtualLedger rejected order
        assert "THIN/IDR" not in app.virtual_ledger.open_positions
        assert len(app.virtual_ledger.open_positions) == 0
        # Verify subscribe_orderbook was NOT called because trade failed
        assert app.indodax_ws.subscribe_orderbook.call_count == 0


@run_async
async def test_two_stage_pipeline_fills_at_real_vwap_for_liquid_book(tmp_path):
    """
    Test Stage 2 Microstructure Verification for liquid book:
    - Council approves BUY for BTC/IDR.
    - Indodax depth returns deep book.
    - Trade fills at real VWAP (higher than best ask by depth slippage).
    - Position is created and orderbook WS subscription is initiated.
    """
    with patch.object(settings, "STATE_DIR", tmp_path):
        app = KiBotV2Pipeline()
        
        deep_orderbook = {
            "buy": [["995000000", "10.0"]],
            "sell": [
                ["1000000000", "0.0005"],  # 500,000 IDR @ 1B
                ["1005000000", "0.0010"],  # 1,005,000 IDR @ 1.005B
            ],
        }
        
        app.indodax_ws.get_orderbook = AsyncMock(return_value=deep_orderbook)
        app.indodax_ws.subscribe_orderbook = AsyncMock()
        
        decision = CouncilDecision(
            verdict="APPROVED",
            symbol="BTC/IDR",
            action="BUY",
            confidence=0.92,
            score=0.90,
            reason="High EV candidate",
            suggested_size_idr=1_000_000.0,
            ev_pct=0.55,
            kelly_fraction=0.15,
            rr_ratio=1.6,
            deliberation_duration_ms=0.4,
            enrichment_status="FRESH",
            target_tp_pct=1.8,
            target_sl_pct=2.4,
        )
        
        candidate = {"price": 1_000_000_000.0, "symbol": "BTC/IDR"}
        
        await app._on_council_decision(decision, candidate)
        
        # Verify trade executed in VirtualLedger
        assert "BTC/IDR" in app.virtual_ledger.open_positions
        pos = app.virtual_ledger.open_positions["BTC/IDR"]
        # VWAP must be higher than best ask (1,000,000,000) due to walking top level
        assert pos.entry_price > 1_000_000_000.0
        assert pos.entry_price < 1_005_000_000.0
        # Verify subscribe_orderbook was called for active position tracking
        app.indodax_ws.subscribe_orderbook.assert_called_once_with("BTC/IDR")
