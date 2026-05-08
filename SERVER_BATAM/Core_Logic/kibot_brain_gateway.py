import socket
import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

# Add project root and parent dirs to sys.path for internal imports
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "Intelligence"))
sys.path.append(str(ROOT_DIR / "Core_Logic"))
sys.path.append(str(ROOT_DIR / "AI_Orchestration"))

from ki_brain import BrainManager
from kibot_whatif_engine import simulate_pair

# Configuration
LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 9998
EXECUTOR_IP = "100.122.1.109"  # Singapore Tailscale IP
EXECUTOR_PORT = 9999

logging.basicConfig(level=logging.INFO, format='%(asctime)s - BRAIN_GATEWAY - %(levelname)s - %(message)s')
logger = logging.getLogger("BrainGateway")

class BatamSovereignBrain:
    def __init__(self):
        from sovereign_arbitrator import SovereignArbitrator
        self.brain = BrainManager()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((LISTEN_IP, LISTEN_PORT))
        self.out_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Risk Arbitrator Integration
        self.arbitrator = SovereignArbitrator(ROOT_DIR / "state")

    def check_pnl_safety(self):
        """Returns False if daily loss limit is hit."""
        with self.arbitrator._lock:
            # Refresh state to get latest PnL from state file
            self.arbitrator.load_state()
            total_balance = self.get_total_capital()
            if total_balance == 0: total_balance = 100000000 
            
            pnl_pct = self.arbitrator.daily_pnl_idr / total_balance
            if pnl_pct <= -self.arbitrator.max_daily_loss_pct:
                return False, f"HARD STOP: Daily PnL ({pnl_pct*100:.2f}%) hit limit!"
            return True, "Safe"

    def get_total_capital(self):
        """Fetch total IDR equity from sovereign state."""
        try:
            state_path = ROOT_DIR / "state" / "sovereign_state.json"
            if state_path.exists():
                with open(state_path, "r") as f:
                    data = json.load(f)
                    # Use a generous default or fetch from specific key if available
                    # For now, we use a fallback of 100M if key is missing but file exists
                    return float(data.get("total_equity_idr") or 100_000_000.0)
        except:
            pass
        return 50_000_000.0 # Emergency fallback capital

    def decide_and_execute(self, s):
        symbol = s.get('s') or s.get('base_symbol')
        price = float(s.get('p') or s.get('price_idr') or s.get('price_usdt', 0))
        change = float(s.get('c') or s.get('change_1h', 0))
        
        if not symbol or price <= 0: return

        # --- 0. PnL SAFETY CHECK (The Consciousness Gate) ---
        is_safe, reason = self.check_pnl_safety()
        if not is_safe:
            logger.warning(f"🛑 {reason} - HALTING ALL TRADING.")
            return

        # --- NEW: INDODAX BALANCE GUARD ---
        # "gaboleh beli koin yang harga satuannya diatas total saldo indodax saat ini"
        total_capital = self.get_total_capital()
        if price > total_capital:
            logger.info(f"🛡️ VETOED: {symbol} | Reason: Price (Rp{price:,.0f}) exceeds Total Capital (Rp{total_capital:,.0f})")
            return

        # 1. AI VETO CHECK (ki_brain.py)
        try:
            veto_status, veto_reason = self.brain.veto_signal(
                pair=symbol,
                msg_type="SIGNAL",
                regime=s.get('regime', 'UNKNOWN'),
                obi=float(s.get('obi', 0.0))
            )
        except Exception as e:
            logger.error(f"Veto Error for {symbol}: {e}")
            veto_status, veto_reason = "ERROR", str(e)

        # 2. MATH WHAT-IF CHECK (kibot_whatif_engine.py)
        try:
            sim = simulate_pair(symbol, price)
            ev = sim.get("expectedValue", 0)
            verdict = sim.get("verdict", "SKIP")
        except Exception as e:
            logger.error(f"WhatIf Error for {symbol}: {e}")
            ev, verdict = 0, "ERROR"

        # 3. CONSOLIDATED DECISION
        if veto_status == "APPROVED" and ev > 0.001 and verdict != "SKIP":
            logger.info(f"🚀 GASS! {symbol} | Price: {price} | EV: {ev} | Veto: {veto_reason}")
            
            execution_order = {
                "symbol": symbol,
                "price": price,
                "side": "BUY",
                "brain_reason": f"AI:{veto_reason} | EV:{ev}",
                "kelly_size": sim.get("kellySizeRecommended", 0),
                "timestamp": datetime.now().isoformat()
            }
            try:
                self.out_sock.sendto(json.dumps(execution_order).encode("utf-8"), (EXECUTOR_IP, EXECUTOR_PORT))
            except Exception as e:
                logger.error(f"Failed to send to Executor: {e}")
        else:
            # Log only significant moves to avoid spam
            if abs(change) > 1.5:
                logger.info(f"🛡️ VETOED: {symbol} | Veto: {veto_status} | EV: {ev} | Verdict: {verdict}")

    def feedback_listener(self):
        """Listen for execution reports from Singapore (Port 9997)."""
        report_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        report_sock.bind(("0.0.0.0", 9997))
        logger.info("📡 Batam Feedback Listener: ACTIVE (Port 9997)")
        
        while True:
            try:
                data, addr = report_sock.recvfrom(65535)
                report = json.loads(data.decode("utf-8"))
                
                if report.get("type") == "EXECUTION_REPORT":
                    symbol = report.get("symbol")
                    status = report.get("status")
                    order_id = report.get("order_id")
                    logger.info(f"📬 REPORT FROM SINGAPORE: {symbol} -> {status} | OrderID: {order_id}")
                    
                    # ALERT TELEGRAM
                    try:
                        from telegram_commander import notify_trade
                        import asyncio
                        msg = f"🔔 **TRADE REPORT**\nPair: `{symbol}`\nStatus: {'✅ SUCCESS' if status == 'SUCCESS' else '❌ FAILED'}\nID: `{order_id}`"
                        asyncio.run(notify_trade(msg))
                    except Exception as te:
                        logger.error(f"Telegram Notification Failed: {te}")
                    
                    # Update internal state if success
                    if status == "SUCCESS":
                        pass
                elif report.get("type") == "HEARTBEAT":
                    logger.debug(f"💓 Heartbeat from {report.get('node')}")

            except Exception as e:
                logger.error(f"Feedback Listener Error: {e}")

    def process(self):
        import threading
        logger.info("--- SOVEREIGN BRAIN GATEWAY ACTIVE (THREADED) ---")
        
        # Start Feedback Listener in background
        threading.Thread(target=self.feedback_listener, daemon=True).start()
        
        while True:
            try:
                data, addr = self.sock.recvfrom(65535)
                payload = json.loads(data.decode("utf-8"))
                
                # Handle Heartbeats from nodes
                if payload.get("type") == "HEARTBEAT":
                    logger.info(f"💓 Heartbeat from {payload.get('node')} ({payload.get('status')})")
                    continue

                signals = payload.get("signals", [])
                if not signals and "s" in payload:
                    signals = [payload]

                for s in signals:
                    # Dispatch each signal to a background thread
                    threading.Thread(target=self.decide_and_execute, args=(s,), daemon=True).start()

            except Exception as e:
                logger.error(f"Receiver Loop Error: {e}")

if __name__ == "__main__":
    BatamSovereignBrain().process()
