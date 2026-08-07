import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from Core.Executors.Indodax.indodax_executor import IndodaxExecutor

def test_idempotency_pre_trade_guard_blocks_duplicate():
    async def _test():
        executor = IndodaxExecutor()
        executor.indodax = AsyncMock()
        
        # Mock openOrders returning existing order for pair
        executor.indodax.get_open_orders.return_value = {
            "success": 1,
            "return": {"orders": [{"order_id": "12345", "pair": "btc_idr"}]}
        }
        
        signal = {
            "symbol": "BTC/IDR",
            "side": "BUY",
            "price": 1000000000.0,
            "type": "COUNCIL_MANDATE",
            "confidence": 0.85,
            "change_5m_pct": 1.0,
        }
        
        # Execute entry should abort due to idempotency guard
        await executor.process_signal(signal)
        
        # Verify trade was NOT called
        executor.indodax.trade.assert_not_called()
    asyncio.run(_test())

def test_idempotency_timeout_recovery_success():
    async def _test():
        executor = IndodaxExecutor()
        executor.indodax = AsyncMock()
        
        # Pre-trade openOrders returns no orders
        executor.indodax.get_open_orders.return_value = {"success": 1, "return": {"orders": []}}
        
        # Balance before and balance after (simulating wallet delta after timeout)
        executor.indodax.get_balance.side_effect = [
            100000.0, # IDR balance (get_balance('idr'))
            0.0,      # coin balance before (get_balance('btc'))
            0.001,    # coin balance after timeout (get_balance('btc'))
            0.001,    # coin balance after 1.5s sleep (get_balance('btc'))
        ]
        
        # trade() raises exception (network timeout)
        executor.indodax.trade.side_effect = Exception("Connection Timed Out")
        
        signal = {
            "symbol": "BTC/IDR",
            "side": "BUY",
            "price": 1000.0,
            "type": "COUNCIL_MANDATE",
            "confidence": 0.85,
            "change_5m_pct": 1.0,
        }
        
        from Core.Support.ki_config import KiConfig
        KiConfig.LIVE_TRADING_ENABLED = True

        from unittest.mock import patch
        from Core.Decision.deterministic_decision_gate import DecisionGateResult
        
        executor.risk = MagicMock()
        executor.risk.validate_signal.return_value = (True, "OK")
        executor.sizing = MagicMock()
        executor.sizing.size.return_value = {"approved": True, "size_idr": 20000.0}
        
        executor.indodax.get_pair_info.return_value = {
            "trade_min_base_currency": 10000,
            "trade_min_traded_currency": 0.0001,
            "price_precision": 0,
            "volume_precision": 4
        }
        
        executor.indodax.get_orderbook.return_value = {
            "bids": [[1000.0, 1.0]],
            "asks": [[1001.0, 1.0]]
        }
        
        with patch("Core.Executors.Indodax.indodax_executor.load_live_truth") as mock_truth, \
             patch("Core.Executors.Indodax.indodax_executor.load_strategy") as mock_strat, \
             patch("Core.Executors.Indodax.indodax_executor.evaluate_live_trade") as mock_gate, \
             patch("Core.Intelligence.indodax_microstructure.IndodaxMicrostructureAnalyzer") as mock_micro, \
             patch("Core.Intelligence.pre_trade_simulator.simulate_pre_trade") as mock_sim:
            mock_truth.return_value = {"daily_loss_cap_breached": False, "hard_stop": False, "status": "NORMAL"}
            mock_strat.return_value = {"indodax": {"allowed_pairs": ["*"], "min_confidence": 0.50, "buy_threshold_pct": 0.1}}
            mock_sim.return_value = {"simulation_verdict": "PASS"}
            mock_gate.return_value = DecisionGateResult(approved=True, reason="APPROVED")
            instance = mock_micro.return_value
            instance.analyze_liquidity.return_value = {
                "pass_liquidity": True,
                "spread_pct": 0.1,
                "slippage_pct": 0.1,
                "reason": "OK"
            }
            instance.calculate_net_yield.return_value = 1.0
            await executor.process_signal(signal)
        assert "BTC/IDR" in executor.active_trades
    asyncio.run(_test())
