import logging
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from Core.Support.ki_config import WIB, KiConfig
from Core.Treasury.venue_ledger import VenueLedger
from Core.Treasury.phantom_treasury import PhantomTreasury
from Core.Treasury.allocation_policy import AllocationPolicy

logger = logging.getLogger("CapitalGovernor")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
GOVERNOR_FILE = STATE_DIR / "capital_governor.json"

def _today_wib() -> str:
    """Business day boundary follows WIB."""
    return str(datetime.now(WIB).date())

class CapitalGovernor:
    """
    Sovereign Capital Governor
    =========================
    The central coordinator of KiBot's capital distribution, target allocations,
    and the global 1.5% daily drawdown cap.
    """
    def __init__(self, indodax_gateway=None, phantom_router=None):
        self.indodax = indodax_gateway
        self.phantom_router = phantom_router
        
        # Initialize internal modules
        self.ledger = VenueLedger()
        self.phantom_treasury = PhantomTreasury(phantom_router)
        self.policy = AllocationPolicy()
        
        # Core metrics
        self.start_total_equity_idr = 0.0
        self.max_daily_loss_idr = 0.0
        self.current_total_equity_idr = 0.0
        self.daily_pnl_idr = 0.0
        self.last_reset_date = _today_wib()
        
        self._load_governor_state()

    def _load_governor_state(self):
        if GOVERNOR_FILE.exists():
            try:
                with open(GOVERNOR_FILE, "r") as f:
                    data = json.load(f)
                    today = _today_wib()
                    if data.get("date") == today:
                        self.start_total_equity_idr = float(data.get("start_total_equity_idr", 0.0))
                        self.max_daily_loss_idr = float(data.get("max_daily_loss_idr", 0.0))
                        self.last_reset_date = today
                    else:
                        self.last_reset_date = today
                        self.start_total_equity_idr = 0.0
                        self.max_daily_loss_idr = 0.0
            except Exception as e:
                logger.error(f"❌ Failed to load Capital Governor state: {e}")
        else:
            self.last_reset_date = _today_wib()

    def save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with open(GOVERNOR_FILE, "w") as f:
                json.dump({
                    "date": self.last_reset_date,
                    "start_total_equity_idr": self.start_total_equity_idr,
                    "max_daily_loss_pct": KiConfig.MAX_DAILY_LOSS_PERCENT,
                    "max_daily_loss_idr": self.max_daily_loss_idr,
                    "current_total_equity_idr": self.current_total_equity_idr,
                    "daily_pnl_idr": self.daily_pnl_idr
                }, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save Capital Governor state: {e}")

    async def check_daily_reset(self, total_equity_idr: float):
        """Reset starting total equity anchor if a new WIB day has begun."""
        today = _today_wib()
        if self.last_reset_date != today or self.start_total_equity_idr <= 0.0:
            self.last_reset_date = today
            self.start_total_equity_idr = total_equity_idr
            self.max_daily_loss_idr = total_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            self.save()
            logger.info(f"⚓ Daily Total Equity Anchor Reset: Rp{self.start_total_equity_idr:,.2f} (Cap: Rp{self.max_daily_loss_idr:,.2f})")

    async def reconcile_governor(self) -> Dict[str, Any]:
        """
        Orchestrate wallet balances, update the Venue Ledger,
        apply target allocation policies, and enforce global risk parameters.
        """
        # 1. Reconcile Phantom Web3 balances
        await self.phantom_treasury.reconcile_balances()
        phantom_summary = self.phantom_treasury.get_summary()
        phantom_equity_idr = phantom_summary.get("total_value_idr", 0.0)
        
        # 2. Reconcile Indodax balance
        indodax_real_balance = 0.0
        if self.indodax:
            try:
                # Query real balance with 5 second timeout
                indo_info = await asyncio.wait_for(self.indodax.get_info(), timeout=5)
                if indo_info.get("success") == 1:
                    balances = indo_info.get("return", {}).get("balance", {})
                    indodax_real_balance = float(balances.get("idr", 0.0) or 0.0)
            except Exception as e:
                logger.error(f"❌ Failed to query Indodax balance: {e}")
                
        # If we are in paper mode, default or load paper balance
        indodax_paper_balance = 1000000.0
        paper_ledger = self.ledger.get_venue("indodax_paper")
        if paper_ledger:
            indodax_paper_balance = paper_ledger.get("equity_idr", 1000000.0)

        # 3. Calculate Total Consolidated Equity
        # Real-canary / Real Mode takes actual Indodax, otherwise paper
        primary_indodax_balance = indodax_real_balance if KiConfig.LIVE_TRADING_ENABLED else indodax_paper_balance
        
        # Total Consolidated Equity = Primary Indodax Balance + Phantom Balance
        self.current_total_equity_idr = primary_indodax_balance + phantom_equity_idr
        
        # Check and initialize today's start anchor if needed
        await self.check_daily_reset(self.current_total_equity_idr)
        
        # Compute daily consolidated PnL
        self.daily_pnl_idr = self.current_total_equity_idr - self.start_total_equity_idr
        self.save()
        
        # 4. Compute target allocation split
        targets = self.policy.compute_targets(phantom_equity_idr)
        
        # 5. Sync to Venue Ledger
        self.ledger.update_venue("indodax_real", equity_idr=indodax_real_balance)
        self.ledger.update_venue("indodax_paper", equity_idr=indodax_paper_balance)
        self.ledger.update_venue("phantom", equity_idr=phantom_equity_idr)
        self.ledger.update_venue("cash_wait", equity_idr=self.current_total_equity_idr * targets.get("reserve", 0.20))
        
        payload = {
            "date": self.last_reset_date,
            "start_total_equity_idr": self.start_total_equity_idr,
            "current_total_equity_idr": self.current_total_equity_idr,
            "max_daily_loss_idr": self.max_daily_loss_idr,
            "daily_pnl_idr": self.daily_pnl_idr,
            "targets": targets,
            "phantom_details": phantom_summary
        }
        return payload
