#!/usr/bin/env python3
from __future__ import annotations
"""
KiBot Sovereign Master Node (Batam)
===================================
The centralized intelligence and control hub for the KiBot Trinity Mesh.
Integrates Sovereign Council deliberation and autonomous system healing.
"""

import os
import sys
import json
import time
import asyncio
import logging
import threading
import subprocess
import platform
import socket
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime
from Core.Support.ki_vault import load_sovereign_env
import httpx
import signal

# Load Sovereign Environment (Decrypted)
load_sovereign_env()

# Core Imports (Unified Structure)
from Core.Support.ki_config import STATE_DIR, LOGS_DIR, PROJECT_ROOT as ROOT_DIR, OLLAMA_TAGS_URL, WIB, KiConfig
from Core.circuit_breaker import CircuitBreaker
from Core.sovereign_council import SovereignCouncil
from Core.sovereign_notifier import SovereignNotifier
from Core.Intelligence.aggregator import CouncilDataAggregator
from Core.sovereign_state import load_strategy, save_strategy
from Core.Intelligence.kibot_whatif_engine import run_simulation
from Core.Support.system_commander import SystemCommander

# Configure Logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / "kibot_sovereign.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("KiBotMaster")
for noisy_logger in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(noisy_logger).setLevel(logging.ERROR)

# Path Setup
sys.path.append(str(ROOT_DIR))

import re
import shlex

SAFE_COMMAND_PATTERNS = [
    r'^systemctl (status|is-active|restart|start|stop) kibot-\w+(\.service)?$',
    r'^systemctl (status|is-active|restart|start|stop) lazarus-ampere(\.service)?$',
    r'^find /home/ubuntu/KiBot/logs/ -name ".*\.log" -mtime \+\d+ -delete$',
    r'^find ' + str(LOGS_DIR) + r'/ -name ".*\.log" -mtime \+\d+ -delete$',
    r'^sudo sync && echo 3 \| sudo tee /proc/sys/vm/drop_caches$',
    r'^df -h .*$',
    r'^free -h$',
    r'^uptime$'
]

NODES = {
    "BATAM": {"ip": "127.0.0.1", "role": "MASTER"},
    "SINGAPORE_SCANNER": {"ip": "100.105.139.21", "role": "SCANNER", "services": ["kibot-scanner"]},
    "SINGAPORE_EXECUTOR": {"ip": "100.122.1.109", "role": "EXECUTOR", "services": ["kibot-executor-engine", "kibot-polymarket"]}
}

class KiBotMaster:
    def __init__(self):
        from Core.ki_brain import BrainManager
        self.brain = BrainManager()
        self.council = SovereignCouncil()
        self.council.brain = self.brain # Inject brain
        self.aggregator = CouncilDataAggregator(self)
        self.system_commander = SystemCommander(str(ROOT_DIR))
        from Core.Treasury.capital_commander import CapitalCommander
        from Core.Exchange.phantom_router import PhantomRouter
        self.phantom_router = PhantomRouter()
        self.capital_commander = None # Will be initialized after IndodaxGateway
        self.is_running = True
        self.last_state = {"portfolio": {"equity_idr": 0, "daily_pnl": "0.0%", "active_positions": []}}
        self.market_mood = "NEUTRAL"
        self.breakers = {
            "SCANNER": CircuitBreaker("SCANNER", max_failures=3, reset_after_sec=600),
            "EXECUTOR": CircuitBreaker("EXECUTOR", max_failures=3, reset_after_sec=600),
            "ollama": CircuitBreaker("ollama", max_failures=5, reset_after_sec=120)
        }
        self._emergency_cooldown = {}
        self.notifier = SovereignNotifier()
        self.procs: Dict[str, asyncio.subprocess.Process] = {}
        self.use_systemd_services = os.getenv("KIBOT_USE_SYSTEMD_SERVICES", "1") == "1"
        self._pnl_session_start_balance: Optional[float] = None
        self._pnl_last_milestone: Dict[str, float] = {}
        self._whatif_last_refresh = 0.0
        
        # [OPTIMIZATION] Reuse Gateway instances
        from Core.Exchange.indodax import IndodaxGateway
        self.indodax = IndodaxGateway()
        self.capital_commander = CapitalCommander(self.indodax, self.phantom_router)
        
        # Self-Healing: Keep AI provider cooldowns persistent by default.
        # Reset only when explicitly requested so 401/429 providers stay muted
        # across restarts instead of being hammered again on every boot.
        provider_cache = STATE_DIR / "ai_coordinator_providers.json"
        if os.getenv("KIBOT_RESET_AI_COOLDOWNS_ON_BOOT", "0") == "1" and provider_cache.exists():
            try:
                provider_cache.unlink()
                logger.info("🔥 AI Provider Cooldowns Reset Successfully.")
            except Exception as e:
                logger.error(f"❌ Failed to reset AI cooldowns: {e}")
        elif provider_cache.exists():
            logger.info("🧠 AI Provider cooldowns preserved across boot.")
        
        logger.info("Initializing KiBot Sovereign Master...")

    async def ensure_ollama_models(self):
        required_models = [
            "qwen2.5:0.5b",
            "qwen2.5:1.5b",
            "qwen2.5:3b",
            "llama3.2:3b",
        ]
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(OLLAMA_TAGS_URL)
                if resp.status_code != 200:
                    logger.warning(f"Ollama health check failed: {resp.status_code}")
                    return
                installed = {m.get("name", "") for m in resp.json().get("models", [])}
                missing = [m for m in required_models if not any(m in name for name in installed)]
                if missing:
                    logger.warning(f"Missing Ollama models: {missing}")
        except Exception as e:
            logger.warning(f"Ollama health check error: {e}")

    async def pnl_watchdog_loop(self):
        logger.info("💰 PnL Watchdog aktif - monitoring setiap 5 menit.")
        while self.is_running:
            try:
                portfolio_snapshot = await self.aggregator._get_portfolio_snapshot()
                current_idr = float(portfolio_snapshot.get("idr_cash", 0.0) or 0.0)
                poly_state = portfolio_snapshot.get("polymarket", {}) if isinstance(portfolio_snapshot.get("polymarket"), dict) else {}
                usdc_balance = float(poly_state.get("usdc_balance", 0) or 0)
                combined_equity_idr = float(portfolio_snapshot.get("combined_equity_idr", 0.0) or 0.0)
                pnl_idr = float(portfolio_snapshot.get("daily_pnl_idr", 0.0) or 0.0)
                pnl_pct = float(portfolio_snapshot.get("daily_pnl_pct", 0.0) or 0.0)
                daily_state = dict(portfolio_snapshot.get("daily_state", {}) or {})
                green_color = str(daily_state.get("color") or ("GREEN" if pnl_idr > 0 else "RECOVERY" if pnl_idr < 0 else "FLAT")).upper()

                if self._pnl_session_start_balance is None:
                    self._pnl_session_start_balance = max(combined_equity_idr - pnl_idr, 1.0)
                    logger.info(
                        f"💼 Session baseline set to Rp{self._pnl_session_start_balance:,.0f} "
                        f"(IDR Rp{current_idr:,.0f} + USDC ${usdc_balance:.2f})"
                    )

                daily_state = {
                    "color": green_color,
                    "hold_winners": green_color == "GREEN",
                    "take_profit_multiplier": 1.75 if green_color == "GREEN" else 1.0,
                    "reason": daily_state.get("reason") or "mark_to_market_pnl",
                }
                logger.info(
                    f"💰 [PNL-5M] IDR Rp{current_idr:,.0f} | USDC ${usdc_balance:.2f} | "
                    f"Combined Rp{combined_equity_idr:,.0f} | PnL Rp{pnl_idr:+,.0f} ({pnl_pct:+.2f}%) | "
                    f"State {green_color}"
                )
                try:
                    from Core.Intelligence.daily_context import update_daily_state

                    update_daily_state(
                        realized_pnl_idr=float(portfolio_snapshot.get("realized_pnl_idr", 0.0) or 0.0),
                        unrealized_pnl_idr=float(portfolio_snapshot.get("unrealized_pnl_idr", 0.0) or 0.0),
                        combined_equity_idr=combined_equity_idr,
                        available_cash_idr=current_idr,
                        current_positions=list(portfolio_snapshot.get("active_positions") or []),
                    )
                except Exception as daily_ctx_err:
                    logger.debug(f"Daily context persist skipped: {daily_ctx_err}")

                if green_color == "GREEN":
                    key = "green_state"
                    if key not in self._pnl_last_milestone:
                        self._pnl_last_milestone[key] = time.time()
                        logger.info("🟢 Daily state GREEN reached. Preserve winners; exit only on weaker edge.")
                if pnl_pct <= -1.2:
                    key = "loss_warning"
                    if key not in self._pnl_last_milestone:
                        self._pnl_last_milestone[key] = time.time()
                        logger.warning("⚠️ Approaching loss limit.")
                if isinstance(self.last_state, dict):
                    portfolio_state = dict(self.last_state.get("portfolio", {}) or {})
                    portfolio_state["daily_state"] = {
                        **daily_state,
                        "pnl_idr": round(pnl_idr, 2),
                        "pnl_pct": round(pnl_pct, 4),
                        "equity_idr": round(combined_equity_idr, 2),
                    }
                    self.last_state["portfolio"] = portfolio_state

                strategy = load_strategy()
                strategy_daily_state = strategy.get("daily_state") if isinstance(strategy.get("daily_state"), dict) else {}
                if strategy_daily_state != daily_state:
                    strategy["daily_state"] = daily_state
                    strategy.setdefault("indodax", {})
                    strategy["indodax"]["green_hold_tp_multiplier"] = daily_state["take_profit_multiplier"]
                    save_strategy(strategy)
            except Exception as e:
                logger.error(f"PnL Watchdog error: {e}")

            # ── §16.2 Stale Order Scan (every 5-min cycle) ──────────────────
            try:
                from Core.Intelligence.order_tracker import get_tracker as _get_ot
                _ot = _get_ot()
                _stale = _ot.scan_stale()
                _ot_summary = _ot.get_today_summary()
                if _stale:
                    _stale_pairs = ", ".join(
                        str(o.get("pair") or o.get("symbol") or o.get("id") or "?").upper()
                        for o in _stale[:5]
                    )
                    logger.warning(f"⏰ [OrderTracker] {len(_stale)} stale order(s): {_stale_pairs}")
                    await self.notifier.send_urgent_alert(
                        f"⏰ OrderTracker: {len(_stale)} STALE order(s) detected — {_stale_pairs}. "
                        f"Manual review or auto-cancel required.",
                        "STALE_ORDER"
                    )
                else:
                    logger.debug(f"[OrderTracker] no stale orders. today={_ot_summary}")

                # Inject into telemetry so dashboard picks it up
                if isinstance(self.last_state, dict):
                    self.last_state["order_tracker"] = {
                        "today_summary": _ot_summary,
                        "open_orders":   _ot.get_open_orders()[:5],
                    }
            except Exception as _ot_err:
                logger.debug(f"[MasterNode] OrderTracker scan skipped: {_ot_err}")

            await asyncio.sleep(300)

    async def capital_rotation_watchdog_loop(self):
        """
        Autonomous Capital Rotation Engine.
        Evaluates DeFi APYs vs Indodax market mood, and automatically bridges funds to/from Phantom.
        """
        interval_sec = int(os.getenv("KIBOT_CAPITAL_ROTATION_SEC", "600"))
        # Leave a safety buffer of 500,000 IDR
        MIN_IDR_IDLE = float(os.getenv("KIBOT_MIN_IDR_IDLE", "500000"))
        logger.info(f"🔄 Autonomous Capital Rotation Engine active ({interval_sec}s). Min Idle: Rp {MIN_IDR_IDLE:,.0f}")
        
        while self.is_running:
            try:
                # 1. Fetch World Model and Possibility Matrix
                world_model = self.brain._load_external_world_model() if hasattr(self.brain, "_load_external_world_model") else {}
                possibility_matrix = world_model.get("possibility_matrix", [])
                
                # 2. Get current equity and balances
                portfolio_snapshot = await self.aggregator._get_portfolio_snapshot()
                idle_idr = float(portfolio_snapshot.get("idr_cash", 0.0) or 0.0)
                
                # 3. Check if PHANTOM_DEFI is the top recommended regime
                if possibility_matrix:
                    top_possibility = possibility_matrix[0]
                    platforms = top_possibility.get("platforms", [])
                    probability = top_possibility.get("probability", 0)
                    
                    if "PHANTOM_DEFI" in platforms and probability > 0.75:
                        logger.info(f"🚀 AI Recommends PHANTOM_DEFI with {probability*100:.1f}% confidence.")
                        
                        amount_to_bridge = idle_idr - MIN_IDR_IDLE
                        if amount_to_bridge > 100000: # Min 100k IDR to bridge
                            logger.info(f"🌉 Preparing to bridge Rp {amount_to_bridge:,.0f} to Phantom...")
                            if self.capital_commander:
                                await self.capital_commander.bridge_indodax_to_phantom(
                                    amount_idr_equiv=amount_to_bridge,
                                    target_network="all",
                                    target_apy=20.0 # Assumed target APY for profitability check
                                )
                        else:
                            logger.debug(f"💤 Idle IDR (Rp {idle_idr:,.0f}) is below bridging threshold.")
            except Exception as e:
                logger.error(f"Capital Rotation Engine error: {e}")
                
            await asyncio.sleep(interval_sec)

    async def whatif_refresh_loop(self):
        """Refresh what-if simulation so council always has a live scenario view."""
        interval_sec = int(os.getenv("KIBOT_WHATIF_REFRESH_SEC", "900"))
        logger.info(f"🧪 What-if refresh loop active ({interval_sec}s).")
        while self.is_running:
            try:
                strategy = load_strategy()
                allowed = strategy.get("indodax", {}).get("allowed_pairs", ["*"])
                pair_list = []
                if "*" in allowed:
                    try:
                        candidates_path = ROOT_DIR / "state" / "scanner_candidates.json"
                        if candidates_path.exists():
                            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
                            for sig in list(candidates.get("top") or [])[:8]:
                                if not isinstance(sig, dict):
                                    continue
                                pair = str(sig.get("pair") or sig.get("symbol") or "").lower().replace("/", "_")
                                if pair and pair.endswith("_idr"):
                                    pair_list.append(pair)
                    except Exception:
                        pair_list = []
                    if not pair_list:
                        pair_list = ["btc_idr", "eth_idr", "sol_idr", "xrp_idr"]
                else:
                    for pair in allowed:
                        pair = str(pair).strip().lower()
                        if pair:
                            pair_list.append(pair if pair.endswith("_idr") else f"{pair}_idr")

                prices = {}
                for pair in pair_list:
                    try:
                        ticker = await self.indodax.get_ticker(pair)
                        price = float(ticker.get("last", 0) or 0)
                        if price > 0:
                            prices[pair] = price
                    except Exception:
                        continue

                if not prices:
                    prices = {
                        "btc_idr": float(os.getenv("KIBOT_WHATIF_BTC_PRICE", "1500000000")),
                        "eth_idr": float(os.getenv("KIBOT_WHATIF_ETH_PRICE", "50000000")),
                    }

                output = run_simulation(prices)
                logger.info(f"🧪 What-if refreshed: {output.get('pairsSimulated', 0)} pairs simulated.")
                self._whatif_last_refresh = time.time()
            except Exception as e:
                logger.error(f"What-if refresh error: {e}")
            await asyncio.sleep(interval_sec)

    def is_command_safe(self, cmd: str) -> bool:
        """Verify if a command is allowed to be executed by the AI."""
        if cmd == 'sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches':
            return True
        for pattern in SAFE_COMMAND_PATTERNS:
            if re.match(pattern, cmd):
                return True
        return False

    def tail_logs(self, name, path):
        """Monitor logs for critical errors in the background."""
        logger.info(f'🛡️ Governor: Watching {name} at {path}')
        if not os.path.exists(path):
            logger.warning(f"Log path not found: {path}")
            return
            
        try:
            # Using tail -F to handle log rotation
            proc = subprocess.Popen(['tail', '-n', '0', '-F', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            while self.is_running:
                line = proc.stdout.readline().decode('utf-8')
                if not line: break
                if any(x in line for x in ['ERROR', 'CRITICAL', 'Exception', 'Traceback']):
                    logger.warning(f"🔍 [LOG ALERT ({name})] {line.strip()}")
                    # Decision to alert human or self-heal can be made here
        except Exception as e:
            logger.error(f"Log Watcher Error ({name}): {e}")

    # --- Signal & Command Plane ---
    async def signal_listener_loop(self):
        """Listens for HMAC-signed high-priority signals from all scanner sources."""
        from Core.Support.ki_utils import verify_signature, sign_payload
        secret = os.environ.get("KIBOT_SECRET")
        if not secret:
            logger.error("❌ CRITICAL: KIBOT_SECRET missing. Council listener will reject all signals.")
            return

        logger.info("📡 Council Signal Listener active on UDP:9991")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_host = os.getenv("KIBOT_COUNCIL_BIND_HOST", "127.0.0.1")
        sock.bind((bind_host, 9991))
        sock.setblocking(False)
        
        loop = asyncio.get_event_loop()
        while self.is_running:
            try:
                data, addr = await loop.sock_recvfrom(sock, 8192)
                envelope = json.loads(data.decode())
                payload = envelope.get("data", {})
                signature = envelope.get("signature", "")
                
                if verify_signature(payload, signature, secret):
                    if payload.get("type") == "COUNCIL_SIGNAL_DATA":
                        signals = payload.get("signals", [])
                        
                        # [G-001] Sovereign Execution Block
                        sys_state = self.system_commander.get_system_state({})
                        if sys_state.get("system_state") in ["UNSAFE", "BLIND"]:
                            logger.error(f"🚨 [COMMANDER BLOCK] System is {sys_state['system_state']}. Rejecting incoming signals.")
                            await self.notifier.send_urgent_alert(f"🚨 **COMMANDER BLOCK**\nSystem is `{sys_state['system_state']}`. Signals rejected to protect capital.", "SYSTEM_BLOCK")
                            continue
                            
                        logger.info(f"🏛️ Received {len(signals)} signed signals from {addr}. Deliberating...")
                        
                        async def deliberate_and_dispatch(sigs):
                            now = datetime.now(WIB)
                            is_midnight = (now.hour == 23 and now.minute >= 45)
                            minutes_to_midnight = self.council._minutes_to_midnight_wib()
                            portfolio_state = dict(self.last_state.get("portfolio", {}) or {})
                            polymarket_state = dict(self.last_state.get("polymarket", {}) or {})
                            decision = await self.council.deliberate_trading({
                                "signals": sigs, 
                                "source": addr[0],
                                "is_midnight_approaching": is_midnight,
                                "minutes_to_midnight": minutes_to_midnight,
                                "portfolio_state": portfolio_state,
                                "polymarket_state": polymarket_state,
                                "current_strategy": load_strategy(),
                            })
                            
                            if not decision or not isinstance(decision, dict):
                                logger.warning("⚠️ Council returned invalid or empty decision.")
                                return

                            if decision.get("status") == "EXECUTING":
                                action = decision.get("action", "UNKNOWN")
                                ticker = decision.get("ticker", "UNKNOWN")
                                logger.info(f"🚀 [MANDATE] Council approved {action} {ticker}.")
                                
                                source_signal = decision.get("source_signal", {})
                                if not isinstance(source_signal, dict):
                                    source_signal = {}

                                # Prepare mandate for the right executor. Start with the
                                # source signal so pump-stage, quality, spread, and
                                # Polymarket metadata survive the Council hop.
                                mandate_data = dict(source_signal)
                                mandate_data.update({
                                    "type": "COUNCIL_MANDATE",
                                    "symbol": decision.get("ticker") or source_signal.get("symbol"),
                                    "side": decision["action"],
                                    "price": source_signal.get("price", decision.get("price", 0)),
                                    "confidence": decision.get("confidence", 0),
                                    "reason": decision.get("logic", "Council Mandate")[:100],
                                    "learning_probe": bool(decision.get("learning_probe", False)),
                                    "probe_confidence_floor": float(decision.get("probe_confidence_floor", 0.0) or 0.0),
                                    "trade_profile": decision.get("trade_profile", "STANDARD"),
                                    "daily_state": dict(self.last_state.get("portfolio", {}).get("daily_state", {}) or {}),
                                    "daily_context": decision.get("daily_context", {}),
                                    "deadline_mode": decision.get("deadline_mode"),
                                    "capital_state": decision.get("capital_state"),
                                    "budget_fraction": decision.get("budget_fraction"),
                                    "trade_grade": decision.get("trade_grade") or source_signal.get("trade_grade"),
                                    "lifecycle": source_signal.get("lifecycle") or source_signal.get("pump_stage"),
                                    "exit_plan": decision.get("exit_plan", {}),
                                    "green_probability": decision.get("green_probability", {}),
                                    "confidence_breakdown": decision.get("confidence_breakdown") or source_signal.get("confidence_breakdown", {}),
                                    "fallback_category": decision.get("fallback_category") or source_signal.get("fallback_category"),
                                    "category_policy": decision.get("category_policy") or source_signal.get("category_policy", {}),
                                    "unit_price_rule": decision.get("unit_price_rule") or {
                                        "must_be_below_total_equity": True,
                                        "basis": "total_equity_idr",
                                    },
                                    "role_votes": decision.get("role_votes", []),
                                    "two_phase_council": decision.get("two_phase_council", {}),
                                    "council_score": decision.get("decision_score"),
                                    "council_wait_reason": decision.get("wait_reason", ""),
                                })

                                exchange = str(source_signal.get("exchange") or "").upper()
                                mandate_symbol = str(mandate_data.get("symbol") or "").upper()
                                if exchange == "POLYMARKET":
                                    target_port = KiConfig.POLY_SIGNAL_PORT
                                elif exchange == "INDODAX" or mandate_symbol.endswith("/IDR") or mandate_symbol.endswith("_IDR"):
                                    target_port = KiConfig.INDO_SIGNAL_PORT
                                else:
                                    logger.warning(
                                        f"⚠️ Council mandate has unsupported route: exchange={exchange}, ticker={mandate_symbol}"
                                    )
                                    return
                                
                                # Send HMAC-signed mandate to the selected executor.
                                envelope_out = {
                                    "data": mandate_data,
                                    "signature": sign_payload(mandate_data, secret)
                                }
                                sock_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                sock_out.sendto(json.dumps(envelope_out).encode(), ("127.0.0.1", target_port))
                                
                        asyncio.create_task(deliberate_and_dispatch(signals))
                else:
                    logger.warning(f"🛡️ REJECTED: Invalid HMAC signature from {addr}")
                    
            except Exception as e:
                if self.is_running:
                    logger.error(f"Signal Listener Error: {e}")
                await asyncio.sleep(0.1)

    # --- Mesh Monitoring ---
    async def mesh_monitor_loop(self):
        """High-integrity Monitoring: Combines Watchman, CircuitBreaker, and Oracle Scouting."""
        logger.info("🛰️ High-Integrity Mesh Monitor started.")
        
        # Start Signal Listener in background
        asyncio.create_task(self.signal_listener_loop())
        asyncio.create_task(self.pnl_watchdog_loop())
        asyncio.create_task(self.whatif_refresh_loop())
        
        # Immediate Oracle Scout on startup
        logger.info("Oracle Mode (Startup): Performing initial market scouting...")
        await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": await self.get_telemetry()}, alert=False)
        
        iteration = 0
        last_dashboard_time = 0
        dashboard_interval = 60
        while self.is_running:
            iteration += 1
            
            # 3. Telemetry Update & Snapshot
            try:
                telemetry = await self.get_telemetry()
                snapshot_path = ROOT_DIR / "state" / "telemetry_snapshot.json"
                with open(snapshot_path, "w") as f:
                    json.dump(telemetry, f, indent=2)
                logger.debug("Telemetry snapshot updated.")
            except Exception as e:
                logger.error(f"Telemetry snapshot failed: {e}")

            # 4. Dashboard (Telegram) - DISABLED (MasterNode no longer spams)
            # if self.is_running and (time.time() - last_dashboard_time > dashboard_interval):
            #     await self.send_dashboard(telemetry)
            #     last_dashboard_time = time.time()
            
            # 1. CIRCUIT BREAKER CHECK (Physical Node Health)
            # Since everything is local, we just check if local services are responsive
            pass

            # 2. WATCHMAN CHECK (Service Health)
            critical_services = [
                telemetry["redis"] == "OFFLINE",
                # Add more local service checks here if needed
            ]
            
            if any(critical_services):
                logger.warning("Watchman: CRITICAL infrastructure anomaly detected!")
                await self.notifier.send_urgent_alert(
                    "CRITICAL infrastructure anomaly detected! Redis is OFFLINE.",
                    "INFRASTRUCTURE_FAILURE"
                )
                await self.deliberate_issue("EMERGENCY", {"type": "SYSTEM_ANOMALY", "snapshot": telemetry}, alert=False)
            # 3. PERSISTENCE & REPORTING
            try:
                now = datetime.now(WIB)
                # A. Midnight Report (00:00 WIB)
                if now.hour == 0 and now.minute <= 4:
                    midnight_key = now.date().isoformat()
                    if not hasattr(self, '_midnight_sent') or self._midnight_sent != midnight_key:
                        logger.info("Midnight reached. Sending Sovereign Daily Report...")
                        if hasattr(self.notifier, "send_daily_report"):
                            await self.notifier.send_daily_report(telemetry, force=True)
                        else:
                            await self.notifier.send_status_reply(telemetry)
                        self._midnight_sent = midnight_key
                
                # B. Periodic Council Deliberation (Scouting) - SILENT (No Telegram)
                if iteration % 60 == 0:
                    logger.info("Oracle Mode: Periodic scouting (Silent)...")
                    await self.deliberate_issue("SCOUTING", {"type": "PROACTIVE_ORACLE", "snapshot": telemetry}, alert=False)
                    
            except Exception as e:
                logger.error(f"Failed to process telemetry: {e}")

            # Guaranteed sleep
            await asyncio.sleep(60)

    async def deliberate_issue(self, target: str, context: Dict, alert: bool = True):
        """Trigger Council deliberation and execute the resulting strategy."""
        decision = await self.council.deliberate(context)
        if not decision or not isinstance(decision, dict):
             logger.warning(f"⚠️ Council returned invalid decision for {target}")
             return
        
        # Only execute if confidence is high and action is valid
        if decision.get("action") and decision.get("confidence", 0) >= 0.8:
            if alert:
                msg = (
                    f"🚨 **Urgent Trouble Detected**\n"
                    f"Node: {target}\n"
                    f"Action: `{decision['action']}`\n"
                    f"Reasoning: {decision['reasoning']}"
                )
                await self.notifier.send_urgent_alert(msg, f"COUNCIL_ACTION_{target}")
            
            logger.info(f"Council approved action: {decision['action']}. Executing...")
            await self.execute_action(decision["action"], target, notify=alert)
        else:
            logger.info(f"Council decision: {decision.get('action', 'NONE')} (Confidence: {decision.get('confidence', 0)*100:.1f}%). No action taken.")

    async def invoke_council(self, target: str, issue_type: str):
        """Invoke the Sovereign Council for complex decision making."""
        context = {
            "type": issue_type,
            "target": target,
            "snapshot": {
                "node": target,
                "timestamp": time.time(),
                "failures": self.breakers.get(target.split("_")[-1], {}).get_status() if self.breakers.get(target.split("_")[-1]) else {}
            }
        }
        
        decision = await self.council.deliberate(context)
        if not decision or not isinstance(decision, dict):
            logger.warning(f"⚠️ Council failed to return a valid decision for {target}")
            return
        
        # Execute Decision
        msg = (
            f"🧠 **Council Decision: {target}**\n"
            f"Action: `{decision.get('action', 'NONE')}`\n"
            f"Confidence: `{decision.get('confidence', 0)*100:.1f}%`\n"
            f"Risk: `{decision.get('risk', 'UNKNOWN')}`\n"
            f"Reasoning: {decision.get('reasoning', 'No reasoning provided.')}"
        )
        await self.notifier.send_urgent_alert(msg, f"COUNCIL_DECISION_{target}")
        
        if decision.get('auto_execute'):
            await self.execute_action(decision['action'], target)

    async def execute_action(self, action: str, target: str, notify: bool = True):
        """Executes a recovery action (restart service, reboot, etc) with safety check."""
        logger.info(f"Executing recovery action: {action} on {target}")
        
        # Mapping actions to shell commands
        commands = {
            "RESTART_SERVICE": "systemctl restart kibot-high-command",
            "CLEAN_CACHE": "rm -rf /tmp/kibot_cache/*",
            "REBOOT_NODE": "sudo reboot",
            "OLLAMA_PULL": "ollama pull qwen2.5:1.5b",
            "LOG_ROTATE": "logrotate -f /etc/logrotate.d/kibot"
        }
        
        cmd = commands.get(action)
        if cmd:
            if not self.is_command_safe(cmd):
                logger.error(f"🛡️ [SECURITY BLOCK] Attempted unsafe command: {cmd}")
                if notify:
                    await self.notifier.send_urgent_alert(f"🛡️ **Security Block**: Blocked unsafe command `{cmd}` on `{target}`", "SECURITY_BLOCK")
                return

            try:
                proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await proc.communicate()
                
                if proc.returncode == 0:
                    logger.info(f"Successfully executed {action}")
                    if notify:
                        await self.notifier.send_urgent_alert(f"✅ **Urgent Fix Applied**: `{action}` on `{target}`", f"FIX_APPLIED_{action}")
                else:
                    logger.error(f"Failed to execute {action}: {stderr.decode()}")
                    if notify:
                        await self.notifier.send_urgent_alert(f"❌ **Urgent Fix Failed**: `{action}` on `{target}`\nError: `{stderr.decode()[:100]}`", f"FIX_FAILED_{action}")
            except Exception as e:
                logger.error(f"Error during action execution: {e}")
        else:
            logger.warning(f"Action {action} not recognized by Master.")

    async def _fetch_json(self, url: str) -> Optional[Dict]:
        """Fetch JSON data from a URL."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return None

    def _check_local_port(self, port: int) -> bool:
        """Check if a local port is listening."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(('127.0.0.1', port)) == 0
        except:
            return False

    async def get_telemetry(self) -> Dict:
        """Gather real-time telemetry from Batam and remote Singapore nodes."""
        import shutil
        import psutil
        
        # 1. Base Infrastructure Stats
        local_stats = {
            "cpu": psutil.cpu_percent(interval=0.2),
            "ram": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent
        }
        
        telemetry = {
            "timestamp": time.time(),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "os_load": os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0),
            "redis": "ONLINE" if self._check_local_port(6379) else "OFFLINE",
            "tailscale": "ONLINE" if self._check_local_port(41641) or os.path.exists("/dev/net/tun") else "OFFLINE",
            "mesh_nodes": {
                "BATAM_MASTER": "ONLINE",
                "SINGAPORE_SCANNER": "UNKNOWN",
                "SINGAPORE_EXECUTOR": "UNKNOWN"
            },
            "system_stats": {
                "BATAM_MASTER": local_stats,
                "SINGAPORE_SCANNER": {"cpu": 0, "ram": 0, "disk": 0},
                "SINGAPORE_EXECUTOR": {"cpu": 0, "ram": 0, "disk": 0}
            },
            "status_text": {
                "activity": "Monitoring Trinity Mesh",
                "difficulty": "No active issues"
            },
            "heartbeat": "ACTIVE"
        }

        # 2. Add Indodax Portfolio Context
        try:
            info = await self.indodax.get_info()
            if info.get("success") == 1:
                balances = info["return"]["balance"]
                # Filter non-zero balances
                active_pos = [{"coin": k, "amount": v} for k, v in balances.items() if float(v) > 0.000001]
                
                # Get IDR Equity (Total)
                equity_idr = float(balances.get("idr", 0))
                
                # Update last state with more details
                self.last_state["portfolio"] = {
                    "equity_idr": equity_idr,
                    "pnl_idr": 0, # Placeholder until historical tracking is implemented
                    "return_pct": 0.0,
                    "wl_ratio": "0W / 0L",
                    "active_positions": active_pos[:5]
                }
        except Exception as e:
            logger.error(f"Failed to fetch Indodax balance: {e}")

        # 3. Add Polymarket State
        try:
            poly_url = f"http://{NODES['SINGAPORE_EXECUTOR']['ip']}:11600/api/state"
            poly_state = await self._fetch_json(poly_url)
            if poly_state:
                telemetry["polymarket"] = {
                    "status": "ONLINE" if poly_state.get("ready") else "DEGRADED",
                    "equity_idr": 0, # Still placeholder
                    "pnl_idr": 0,
                    "return_pct": 0.0,
                    "wl_ratio": "0W / 0L",
                    "pnl_today": "+0.00%",
                    "pnl_7d": "+0.00%",
                    "pnl_30d": "+0.00%",
                    "active_positions": []
                }
        except: pass

        # 4. Add Council & Market Context
        try:
            context = await self.aggregator.get_debate_context()
            portfolio_state = context.get("portfolio_state", {})
            existing_portfolio_state = dict(self.last_state.get("portfolio", {}) or {})
            if "daily_state" not in portfolio_state and existing_portfolio_state.get("daily_state"):
                portfolio_state["daily_state"] = existing_portfolio_state.get("daily_state")
            telemetry["portfolio"] = portfolio_state
            telemetry["market"] = context.get("market_context", {})
            telemetry["stats"] = context.get("audit_data", {}).get("rejection_analysis", {})
            telemetry["council"] = context.get("philosophy", {})
            telemetry["polymarket"] = portfolio_state.get("polymarket", telemetry.get("polymarket", {}))
            self.last_state["portfolio"] = portfolio_state
            self.last_state["polymarket"] = portfolio_state.get("polymarket", {})
        except Exception as e:
            logger.error(f"Failed to aggregate council data: {e}")
        
        # Telemetry is now purely local for the Sovereign Node
        telemetry["mesh_nodes"]["BATAM_MASTER"] = "ONLINE"

        # Check Local Redis via redis-cli as final authority
        redis_path = shutil.which("redis-cli")
        if redis_path:
            try:
                proc = await asyncio.create_subprocess_shell(
                    f"{redis_path} ping", 
                    stdout=asyncio.subprocess.PIPE, 
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                if b"PONG" in stdout: 
                    telemetry["redis"] = "ONLINE"
                else:
                    telemetry["redis"] = "OFFLINE"
            except: 
                # Fallback to port check if redis-cli fails
                telemetry["redis"] = "ONLINE" if self._check_local_port(6379) else "OFFLINE"
        else:
            # Fallback to port check if redis-cli missing
            telemetry["redis"] = "ONLINE" if self._check_local_port(6379) else "OFFLINE"

        # 3. Intelligent Status Text (For Sovereign Dashboard)
        activity = "Monitoring Sovereign Batam Node."
        difficulty = "None"
        problems = []
        if telemetry["redis"] == "OFFLINE":
            problems.append("Local Redis Offline")
        if telemetry["system_stats"]["BATAM_MASTER"]["ram"] > 90:
            problems.append("High Memory Pressure")
        
        if problems:
            difficulty = ", ".join(problems)
        
        telemetry["status_text"] = {
            "activity": activity,
            "difficulty": difficulty
        }
        telemetry["ai_online"] = True # Assuming Ollama is reachable
        telemetry["commander"] = self.system_commander.get_system_state(telemetry)
        
        return telemetry


    async def process_manager_loop(self):
        """Service monitor. In systemd mode, only checks health to avoid double-starting services."""
        if not self.use_systemd_services:
            logger.info("Service spawning mode disabled by default. Set KIBOT_USE_SYSTEMD_SERVICES=0 to manage subprocesses locally.")
            return

        monitored = [
            "kibot-scanner",
            "kibot-executor",
            "kibot-executor-polymarket",
            "kibot-ai-scout",
            "kibot-janitor",
            "ollama",
            "redis-server",
        ]
        logger.info("🛡️ Service monitor active (systemd mode).")
        while self.is_running:
            for svc in monitored:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "systemctl", "is-active", svc,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    stdout, _ = await proc.communicate()
                    status = stdout.decode().strip()
                    if status != "active":
                        logger.warning(f"⚠️ Service {svc} status={status}.")
                except Exception as e:
                    logger.error(f"Service monitor error for {svc}: {e}")
            await asyncio.sleep(60)

    async def _log_pipe(self, name: str, proc: asyncio.subprocess.Process):
        """Pipes child process output to main log."""
        if not proc.stdout: return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line: break
                decoded = line.decode().strip()
                if decoded:
                    # Avoid recursive logging if possible, but for child procs it's fine
                    logger.info(f"[{name.upper()}] {decoded}")
        except Exception:
            pass


    def handle_sigterm(self, signum, frame):
        """Graceful shutdown for Master Node."""
        logger.info(f"👋 Received signal {signum}. Shutting down Sovereign Master...")
        self.is_running = False
        # Kill all child processes
        for name, proc in self.procs.items():
            try:
                logger.info(f"🛑 Terminating child: {name}")
                proc.terminate()
            except: pass
        sys.exit(0)

    def start(self):
        # Start core loops
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Register signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                # Fallback for Windows or environments where add_signal_handler fails
                signal.signal(sig, self.handle_sigterm)

        # Add tasks
        loop.create_task(self.mesh_monitor_loop())
        loop.create_task(self.process_manager_loop())
        loop.create_task(self.ensure_ollama_models())
        loop.create_task(self.pnl_watchdog_loop())
        loop.create_task(self.capital_rotation_watchdog_loop())
        loop.create_task(self.whatif_refresh_loop())

        
        logger.info("🎖️ KiBot Sovereign Master is fully OPERATIONAL.")
        try:
            loop.run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            loop.close()
            logger.info("Sovereign Node offline.")

    async def shutdown(self):
        """Async shutdown handler."""
        logger.info("👋 Initiating graceful shutdown...")
        self.is_running = False
        
        # Kill child processes
        for name, proc in self.procs.items():
            if proc.returncode is None:
                logger.info(f"Stopping service {name}...")
                try:
                    proc.terminate()
                except: pass
        
        # Wait for them to finish (briefly)
        if self.procs:
            await asyncio.gather(*[proc.wait() for proc in self.procs.values()], return_exceptions=True)

        # Cancel all running tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.get_event_loop().stop()

if __name__ == "__main__":
    master = KiBotMaster()
    master.start()
