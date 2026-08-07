import pytest
import shutil
import tempfile
import asyncio
from pathlib import Path
from Core.Intelligence.paper_trade_tracker import PaperTradeTracker, get_paper_trade_tracker
from Core.Intelligence.strategy_stats import StrategyStatsAggregator
from Core.Intelligence.autonomous_director import AutonomousDirector, ScorecardVerdict

def test_multi_variant_paper_trading_isolation():
    async def _test():
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            state_dir = tmp_dir / "state"
            history_dir = state_dir / "trade_history"
            
            cons_tracker = PaperTradeTracker("CONSERVATIVE", open_dir=state_dir/"paper_trades"/"conservative"/"open", history_dir=history_dir)
            aggr_tracker = PaperTradeTracker("AGGRESSIVE", open_dir=state_dir/"paper_trades"/"aggressive"/"open", history_dir=history_dir)
            
            # Candidate 1: STRONG grade, high volume ratio (qualifies for BOTH CONSERVATIVE and AGGRESSIVE)
            cand1 = {
                "symbol": "BTC/IDR",
                "price_idr": 1000000000.0,
                "scorecard_verdict": ScorecardVerdict.PAPER_ONLY.value,
                "signal_quality": {"grade": "STRONG"},
                "volume_ratio": 5.0,
            }
            
            # Candidate 2: ACCEPTABLE grade, low volume ratio (qualifies ONLY for AGGRESSIVE)
            cand2 = {
                "symbol": "ETH/IDR",
                "price_idr": 50000000.0,
                "scorecard_verdict": ScorecardVerdict.PAPER_ONLY.value,
                "signal_quality": {"grade": "ACCEPTABLE"},
                "volume_ratio": 1.0,
            }
            
            # Open trades for Candidate 1 in Conservative
            tr_cons_1 = cons_tracker.open_paper_trade(cand1, take_profit_pct=0.026, stop_loss_pct=0.0045)
            assert tr_cons_1 is not None
            assert tr_cons_1["variant_id"] == "CONSERVATIVE"
            
            # Open trades for Candidate 1 in Aggressive
            tr_aggr_1 = aggr_tracker.open_paper_trade(cand1, take_profit_pct=0.050, stop_loss_pct=0.015)
            assert tr_aggr_1 is not None
            assert tr_aggr_1["variant_id"] == "AGGRESSIVE"
            
            # Open trades for Candidate 2 in Conservative (should fail/return None if filter enforced)
            # In direct tracker call, it opens, but let's verify file paths isolation
            open_cons = cons_tracker.get_open_paper_trades()
            open_aggr = aggr_tracker.get_open_paper_trades()
            
            assert len(open_cons) == 1
            assert len(open_aggr) == 1
            assert open_cons[0]["variant_id"] == "CONSERVATIVE"
            assert open_aggr[0]["variant_id"] == "AGGRESSIVE"
            assert open_cons[0]["trade_id"] != open_aggr[0]["trade_id"]
            
            # Simulate closing trades with different prices to verify stats isolation
            closed_cons = cons_tracker.close_paper_trade(tr_cons_1, exit_price=1026000000.0, exit_reason="TAKE_PROFIT_TARGET_HIT")
            closed_aggr = aggr_tracker.close_paper_trade(tr_aggr_1, exit_price=985000000.0, exit_reason="STOP_LOSS_BREACHED")
            
            assert closed_cons["variant_id"] == "CONSERVATIVE"
            assert closed_aggr["variant_id"] == "AGGRESSIVE"
            assert closed_cons["realized_pnl_idr"] > 0
            assert closed_aggr["realized_pnl_idr"] < 0
            
            # Verify file paths created
            cons_file = history_dir / f"paper_conservative_{closed_cons['date_wib']}.jsonl"
            aggr_file = history_dir / f"paper_aggressive_{closed_aggr['date_wib']}.jsonl"
            assert cons_file.exists()
            assert aggr_file.exists()
            
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            
    asyncio.run(_test())
