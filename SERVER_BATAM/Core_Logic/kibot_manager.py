#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import signal
import socket
import sys
import threading
import time
import ast
import redis
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor

# Modular Path Injection
_root = Path(__file__).resolve().parent.parent
for d in ["Intelligence", "Indicators_Math", "Security", "Communication", "AI_Orchestration", "Support"]:
    sys.path.append(str(_root / d))
sys.path.append(str(_root / "Support/Web"))
sys.path.append(str(_root / "Support/Audit_Testing"))

from ki_config import *
from ki_utils import telegram_send, load_json, save_json, get_wib_now, bounded_append, safe_float
import dynamic_config
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import asyncio
import requests
import urllib.request
from multi_scanner_engine import MultiScannerEngine
import kibot_engine_v2 as engine
import sovereign_arbitrator
from dashboard_template import DASHBOARD_HTML
from ki_brain import BrainManager
from ki_stats import calculate_z_score, detect_regime, calculate_obi

try:
    from kibot_ai_search import AISearchService
    import kibot_ai_scout
except ImportError:
    pass
try:
    from kibot_learning_engine import get_engine, get_regime_detector
except ImportError:
    def get_engine(): return None
    def get_regime_detector(): return None
try:
    from kibot_ai_coordinator import query_ai
except Exception as _coordinator_error:
    def query_ai(*args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]:
        return None
    print(f"[KIBOT][AI][WARN] coordinator unavailable: {_coordinator_error}", flush=True)

_WHATIF_AVAILABLE = True
try:
    from kibot_whatif_engine import run_simulation, simulate_pair
except Exception as _whatif_error:
    _WHATIF_AVAILABLE = False
    def run_simulation(market_prices: dict) -> dict: return {}
    def simulate_pair(pair: str, current_price: float) -> dict: return {"verdict": "SKIP"}
    print(f"[KIBOT][WHATIF][WARN] simulation engine unavailable: {_whatif_error}", flush=True)

import kibot_engine_v2
from coin_universe_overlay import auto_discover_new_coins
from kibot_engine_v2 import (
    trade_logger, cascade_state, position_manager,
    screen_bucket_b, dual_scanner_agree, fetch_kicom,
    compute_conviction, evaluate_exit, run_math_review,
    simulate_what_if, update_btc, btc_change_1h,
    size_bucket_a, size_bucket_b, is_btc_ok,
    LEAD_LAG_PAIRS, INDODAX_ONLY_PAIRS, ROUND_TRIP_LIMIT,
    _shutting_down, SCREEN_INTERVAL_S, BTC_UPDATE_S, REVIEW_INTERVAL_S
)

TRADING_CAPITAL_PCT = 0.50
MIN_POSITION_IDR = 50_000
MAX_POSITION_IDR = 1_000_000

# Use defusedxml to prevent XXE attacks
try:
    import defusedxml.ElementTree as ET
except ImportError:
    from xml.etree import ElementTree as ET
    print("[KIBOT][WARN] defusedxml not installed, using stdlib xml (XXE risk)", flush=True)

# Global lock for thread-safe access to shared state
_state_lock = threading.RLock()
_shutdown_event = threading.Event()

@dataclass
class HardStopState:
    initial_capital: float = 0.0
    daily_pnl: float = 0.0

    def check_position_timeout(self, pos: dict) -> bool:
        entry_time = float(pos.get("entry_time", 0))
        if entry_time > 0 and (time.time() - entry_time) > 12 * 3600:
            return True
        return False

_hard_stop = HardStopState()

_main_socket: Optional[socket.socket] = None
_http_server: Optional[ThreadingHTTPServer] = None
_bot_start_time = time.time()
_supabase_auth_state: Dict[str, Any] = {
    "access_token": "",
    "expires_at": 0.0,
    "last_error": "",
    "last_ok_at": "",
}
_last_daily_guard_check_at = 0.0
_metrics: Dict[str, Union[float, int]] = {
    "market_orders_today": 0,
    "limit_orders_today": 0,
    "entries_blocked_hard_stop": 0,
    "entries_blocked_learn_gate": 0,
    "entries_blocked_whatif": 0,
    "entries_blocked_brain": 0,
    "entries_brain_reduced": 0,
    "fee_bleed_est_idr": 0.0,
    "whatif_skips_today": 0,
    "whatif_enters_today": 0,
    "risk_mode": "GROWTH", # GROWTH, CAUTION, DEFENSIVE, RESTRICTED, HARD_STOP
}
_one_shot_used_today = False
_full_stop_active = False
_one_shot_result: Optional[str] = None
_last_math_review_at = 0.0
_math_review_last_action = "INIT"
_math_review_last_reason = ""
_math_review_trade_journal: List[Dict[str, Any]] = []
_price_history: Dict[str, List[float]] = {}  # pair_id -> [price1, price2, ...]
_last_screener_run_at = 0.0
_active_trails: Dict[str, Dict[str, Any]] = {}  # pair_id -> {entry_price, max_price, trailing_pct, ...}
_global_whiteboard: Dict[str, Dict[str, Any]] = {}  # symbol -> {binance: price, cryptocom: price, ts: time}
_market_regime: str = "SIDEWAYS" # Updated by KiBot Radar
LOCAL_SIGNAL_PORT = KIBOT_UDP_PORT
_signal_engine_proc: Optional[threading.Thread] = None

# === v7 Global Engines ===
_arbitrator    = sovereign_arbitrator.get_arbitrator()
_brain         = BrainManager()
_msc_engine    = MultiScannerEngine()
_learning_engine = get_engine()
_regime_detector = get_regime_detector()
_learning_enabled = _learning_engine is not None

# --- v9.0 SOVEREIGN MESH REGISTRY ---
class ScannerRegistry:
    """Tracks health and integrity of all 20+1 global scanner nodes."""
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {} # host_ip -> metadata
        self._lock = threading.Lock()
        self.persistence_path = _root / "state" / "scanner_registry.json"
        self.load_from_disk()

    def save_to_disk(self):
        """Persist node health data to disk."""
        try:
            with self._lock:
                data = {"timestamp": time.time(), "nodes": self.nodes}
            save_json(self.persistence_path, data)
        except Exception as e:
            print(f"[REGISTRY][ERROR] Save failed: {e}", flush=True)

    def load_from_disk(self):
        """Load node health data from disk."""
        try:
            if self.persistence_path.exists():
                data = load_json(self.persistence_path)
                if data and "nodes" in data:
                    self.nodes = data["nodes"]
                    print(f"[REGISTRY] Loaded {len(self.nodes)} nodes from persistence", flush=True)
        except Exception as e:
            print(f"[REGISTRY][ERROR] Load failed: {e}", flush=True)

    def get_latency_multiplier_by_exchange(self, exchange: str) -> float:
        """Find the best node for this exchange and return its health multiplier."""
        best_mult = 0.0
        with self._lock:
            for node_key, node in self.nodes.items():
                if node.get("exchange") == exchange:
                    mult = self.get_latency_multiplier_node(node_key)
                    if mult > best_mult:
                        best_mult = mult
        return best_mult if best_mult > 0 else 0.5 # Default 0.5 if unknown

    def get_latency_multiplier_node(self, node_key: str) -> float:
        """Return a multiplier based on node health (0.0 to 1.0)."""
        node = self.nodes.get(node_key)
        if not node: return 0.0
        
        # Penalize if latency > 500ms
        lat = node.get("latency_ms", 0)
        if lat > 2000: return 0.1 # Severe lag
        if lat > 1000: return 0.5 # Moderate lag
        if lat > 500: return 0.8  # Slight lag
        return 1.0

    def update(self, host: str, msg: dict):
        with self._lock:
            exchange = msg.get("exchange", "UNKNOWN")
            node_key = f"{host}:{exchange}"
            
            now = time.time()
            seq = msg.get("sequence_num", 0)
            
            if node_key not in self.nodes:
                self.nodes[node_key] = {
                    "exchange": exchange,
                    "ip": host,
                    "last_seen": now,
                    "last_seq": seq,
                    "packets_received": 1,
                    "packets_lost": 0,
                    "latency_ms": 0.0
                }
                print(f"[REGISTRY][NEW_NODE] Detected {node_key}", flush=True)
                return

            node = self.nodes[node_key]
            node["last_seen"] = now
            node["packets_received"] += 1
            
            # Detect packet loss via sequence gap
            if seq > 0 and node["last_seq"] > 0:
                gap = seq - node["last_seq"] - 1
                if gap > 0:
                    node["packets_lost"] += gap
                    print(f"[REGISTRY][LOSS] {node_key} lost {gap} packets (seq {node['last_seq']} -> {seq})", flush=True)
            
            node["last_seq"] = seq
            
            # Calculate latency if possible
            sent_at = msg.get("sentAtEpochMs", 0)
            if sent_at > 0:
                node["latency_ms"] = (now * 1000) - sent_at

    def get_summary(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self.nodes.values()]

    async def monitor_health(self):
        """Background task to alert if scanners go silent."""
        while not _shutdown_event.is_set():
            now = time.time()
            with self._lock:
                for key, node in self.nodes.items():
                    silence = now - node["last_seen"]
                    if silence > 120: # 2m timeout for critical alert
                        if not node.get("alerted", False):
                            msg = f"⚠️ [KIBOT][MESH] Node {key} ({node['exchange']}) SILENT for {silence:.0f}s!"
                            telegram_send(msg)
                            node["alerted"] = True
                            print(f"[REGISTRY][CRITICAL] Alert sent for {key}", flush=True)
                    elif silence < 30:
                        node["alerted"] = False # Reset if back online
                self.save_to_disk() # Persist health stats every cycle
            await asyncio.sleep(60)

_scanner_registry = ScannerRegistry()
_msc_engine.registry = _scanner_registry

class AsyncUDPProtocol(asyncio.DatagramProtocol):
    """Sub-millisecond signal ingestion with HMAC validation."""
    def connection_made(self, transport):
        self.transport = transport
        print(f"[UDP_SERVER] Listening on {LOCAL_SIGNAL_PORT}", flush=True)

    def datagram_received(self, data, addr):
        try:
            host = addr[0]
            
            # 0. IP Allowlist (Trinity Gate v9.1)
            if KIBOT_ALLOWED_SCANNER_IPS and host not in KIBOT_ALLOWED_SCANNER_IPS:
                # Silently drop unauthorized packets to prevent port scanning noise
                return

            payload_str = data.decode('utf-8')
            msg = json.loads(payload_str)
            
            # 1. HMAC Integrity Verification (v9.1: Constant-time comparison)
            signature = msg.get("signature")
            if not signature:
                return # Drop silent unsigned packets
            
            # Reconstruct canonical payload for verification
            msg_copy = dict(msg)
            if "signature" in msg_copy:
                del msg_copy["signature"]
            canonical = json.dumps(msg_copy, separators=(',', ':'), sort_keys=True)
            
            import hmac, hashlib, base64
            key = KIBOT_SIGNAL_KEY.encode()
            expected = base64.b64encode(
                hmac.new(key, canonical.encode(), hashlib.sha256).digest()
            ).decode()
            
            if not hmac.compare_digest(signature, expected):
                print(f"[UDP_SERVER][AUTH_FAIL] Invalid signature from {host}", flush=True)
                return

            # 2. Update Registry
            _scanner_registry.update(host, msg)

            # 3. Process Signal
            if msg.get("type") == "MULTI_SCANNER_SIGNAL":
                # Route through MSC engine for consensus/voting
                _msc_engine.process_and_relay(msg, _process_signal)
            else:
                # Direct processing for other types (Heartbeats, etc)
                _process_signal(msg)

        except Exception as e:
            pass # Suppress noise for invalid packets

 
# --- AI VETO CACHE (Non-Blocking) ---
_ai_veto_cache: Dict[str, Dict[str, Any]] = {} # pair -> {verdict: "APPROVED", ts: time}
_ai_veto_queue: List[Tuple[str, str]] = [] # [(pair, type)]
_ai_veto_lock = threading.Lock()

def _get_ai_veto_state(pair: str) -> str:
    with _ai_veto_lock:
        data = _ai_veto_cache.get(pair)
        if data and (time.time() - data['ts']) < 3600: # 1 hour TTL
            v = data['verdict']
            r = data.get('reasoning', '')
            if v == "REJECTED" and r:
                return f"REJECTED: {r}"
            return v
    return ""

def _request_ai_veto(pair: str, msg_type: str):
    with _ai_veto_lock:
        if pair not in [x[0] for x in _ai_veto_queue]:
            _ai_veto_queue.append((pair, msg_type))

def _ai_veto_worker():
    """Background thread to process AI Vetoes non-blockingly."""
    while not _shutdown_event.is_set():
        item = None
        with _ai_veto_lock:
            if _ai_veto_queue:
                item = _ai_veto_queue.pop(0)
        
        if item:
            pair, msg_type = item
            try:
                # [v7.5] Enhanced Veto Context: Regime & OBI
                regime = _market_regime
                obi = 0.0
                depth = engine.fetch_depth(pair)
                if depth:
                    bids = [(float(s[0]), float(s[1])) for s in depth.get("buy", [])]
                    asks = [(float(s[0]), float(s[1])) for s in depth.get("sell", [])]
                    obi = calculate_obi(bids, asks)
                
                # [v7.1] Sovereign Shift: Use brain's dedicated veto logic
                verdict, reasoning = _brain.veto_signal(pair, msg_type, regime=regime, obi=obi)
                
                with _ai_veto_lock:
                    _ai_veto_cache[pair] = {
                        "verdict": verdict.upper(), 
                        "reasoning": reasoning,
                        "ts": time.time()
                    }
                    print(f"[v7][AI_VETO_WORKER] {pair}: {verdict} [Regime:{regime} OBI:{obi:.2f}] ({reasoning[:50]}...)", flush=True)
            except Exception as e:
                print(f"[v7][AI_VETO_WORKER][ERROR] {pair}: {e}", flush=True)
        
        time.sleep(0.5)

# Start the worker
threading.Thread(target=_ai_veto_worker, daemon=True).start()

# --- TRINITY CRITICAL FIX STATE ---
KiBot_UDP_HOST = "100.122.1.109"
KiBot_UDP_PORT = 9999
import pytz
WIB = pytz.timezone('Asia/Jakarta')

_last_entry: Dict[str, float] = {}   # {pair: timestamp}
_entry_loss_count: Dict[str, int] = {}  # {pair: count}
_signal_seen: Dict[str, float] = {}  # {key: timestamp}
_ai_healthy: bool = True
_ai_last_success: float = time.time()
_ai_failure_streak: int = 0

_last_KiBot_heartbeat_at: float = 0.0

# Redis State Store (Local to Batam)
try:
    _redis = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    _redis.ping()
    print("[KIBOT] Redis connected successfully.")
except Exception as e:
    print(f"[KIBOT][WARNING] Redis connection failed: {e}")
    _redis = None
_initial_capital_idr: float = 0.0
_last_dashboard_export = 0.0
DASHBOARD_EXPORT_INTERVAL = 5.0 # 5 seconds

# === Rotation & Learning State ===
from kibot_rotation_engine import RotationEngine
_rotation_engine = RotationEngine()
_last_rotation_check = 0.0

def export_full_state():
    """Export absolutely everything for the high-end dashboard."""
    try:
        # Use absolute path for reliability
        target = Path("/home/ubuntu/KiBot/state/full_system_state.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Resolve engine variables safely
        btc_price = float(getattr(kibot_engine_v2, "_btc_now", 0.0))
        btc_change = float(btc_change_1h())
        
        state = {
            "timestamp": time.time(),
            "metrics": _metrics,
            "risk_mode": _metrics.get("risk_mode", "UNKNOWN"),
            "market_regime": globals().get("_market_regime", "SIDEWAYS"),
            "btc": {
                "price": btc_price,
                "change_1h": btc_change,
                "is_ok": is_btc_ok("B")[0]
            },
            "portfolio": {
                "active_positions": list(position_manager.positions.keys()) if hasattr(position_manager, "positions") else [],
                "capital_allocation": 0
            },
            "ai_status": {
                "healthy": globals().get("_ai_healthy", False),
                "last_success": globals().get("_ai_last_success", 0),
                "failure_streak": globals().get("_ai_failure_streak", 0)
            },
            "recent_actions": globals().get("_math_review_trade_journal", [])[-10:],
            "active_trails": {k: v for k, v in globals().get("_active_trails", {}).items()},
            "scanners": {
                "top_signals": _msc_engine.get_active_signals()
            }
        }
        
        # Use atomic-like write to avoid partial reads by proxy
        temp_target = target.with_suffix(".tmp")
        print(f"DEBUG: Writing telemetry to {temp_target}", flush=True)
        with open(str(temp_target), "w") as f:
            json.dump(state, f, indent=2)
        print(f"DEBUG: Renaming {temp_target} to {target}", flush=True)
        temp_target.replace(target)
        print(f"DEBUG: Telemetry export successful: {target}", flush=True)
        
    except Exception as e:
        print(f"[KIBOT][DASHBOARD][ERROR] Export failed: {e}", flush=True)
def _relay_to_KiBot(msg: dict):
    """
    SATU-SATUNYA fungsi yang relay ke KiBot/KiBot.
    BUY signal HARUS lewat _can_enter dulu (Trinity Gate 0).
    SELL signal tidak perlu (exit harus selalu bisa berjalan).
    """
    global _main_socket
    msg_type = str(msg.get("type") or msg.get("msgType") or "").upper()
    pair     = str(msg.get("pair") or msg.get("pairId") or "").lower()

    # Guard 0.1: Stale Signal Check
    if _is_signal_stale(msg):
        return

    # Guard 0.2: Duplicate Signal Check
    if _is_duplicate_signal(msg):
        return

    # Semua tipe BUY/ENTRY harus cek gate
    entries = ("SIGNAL", "DETECTOR_HIT", "SMART_ENTRY", "ANOMALY", "PUMP", "VETO_APPROVED")
    if any(k in msg_type for k in entries):
        # Kecuali kalau sinyal tersebut mengandung 'REJECTED' atau 'VETO_REJECTED'
        if "REJECTED" not in msg_type:
            score = float(msg.get("score") or msg.get("pump_score") or 0.8)
            if score > 1.0: score /= 100.0 # Normalize 0-1
            ev = float(msg.get("ev") or 0.15)
            
            can_enter, reason, allocated_size = _can_enter(pair, msg_type, score, ev)
            if not can_enter:
                print(f"[v7][ENTRY_BLOCKED] {pair} ({msg_type}): {reason}", flush=True)
                return  # STOP — tidak relay ke KiBot
            
            # Attach sovereign sizing decision
            msg["sovereign_size_idr"] = allocated_size

            # Catat entry untuk quarantine dan repeat blocker
            if pair:
                _last_entry[pair] = time.time()
                print(f"[v7][ENTRY_APPROVED] {pair}: gate passed, size=Rp{allocated_size:,.0f} relaying to egress", flush=True)

                # Mark as seen ONLY after all gates passed
                _mark_signal_seen(msg)

    # Actual Transmission (Fixed Redundancy)
    transient_socket = None
    try:
        payload = json.dumps(msg, ensure_ascii=True, separators=(',', ':')).encode("utf-8")
        udp_socket = _main_socket
        if udp_socket is None:
            transient_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket = transient_socket

        # Multi-Path Relay (Failover Redundancy)
        for host_str in KIBOT_EGRESS_HOSTS:
            try:
                target_host = host_str
                target_port = KIBOT_UDP_PORT
                if ':' in host_str:
                    target_host, port_part = host_str.split(':')
                    target_port = int(port_part)
                
                udp_socket.sendto(payload, (target_host, target_port))
            except Exception as e:
                print(f"[v7][ERROR] Egress failed to {host_str}: {e}", flush=True)
            
        if "POSITION" not in msg_type and "HEARTBEAT" not in msg_type:
            print(f"[v7][EGRESS] {msg_type} {pair or ''}", flush=True)
    except Exception as e:
        print(f"[v7][EGRESS_ERR] {pair}: {e}", flush=True)
    finally:
        if transient_socket is not None:
            try:
                transient_socket.close()
            except Exception:
                pass

def _can_enter(pair: str, msg_type: str, score: float = 0.8, ev: float = 0.1) -> Tuple[bool, str, float]:
    """
    Trinity Gate 0: Sovereign Arbitrator gate.
    """
    global _ai_healthy, _entry_loss_count, _last_entry

    # 1. Sovereign Allocation Guard
    # Fetch current market data for Sentinel
    price = engine.get_price(pair) if hasattr(engine, 'get_price') else 0.0
    mid_price = engine.get_mid_price(pair) if hasattr(engine, 'get_mid_price') else price

    req = sovereign_arbitrator.AllocationRequest(
        source="INDODAX",
        asset=pair,
        signal_score=score,
        ev_estimate=ev,
        metadata={
            "price": price,
            "market_mid_price": mid_price,
            "side": "BUY" if "SIGNAL" in msg_type or "ENTRY" in msg_type else "NEUTRAL"
        }
    )
    ok, size, reason = _arbitrator.request_allocation(req)
    if not ok:
        if "DAILY LOSS LIMIT" in reason:
            print(f"[v7][SOVEREIGN_VETO] {pair}: {reason} — SAFETY GATE TRIGGERED", flush=True)
        else:
            print(f"[v7][SOVEREIGN_SKIP] {pair}: {reason}", flush=True)
        return False, reason, 0.0

    # 2. Risk Mode Guard
    mode = _get_effective_mode()
    if mode == "FULL_FREEZE":
        return False, "MODE: FULL_FREEZE (Level 3 + AI Offline)"
    if mode == "EXIT_ONLY":
        return False, "MODE: EXIT_ONLY (Level 3)"

    # 3. AI Health Guard
    if not _ai_healthy:
        return False, "AI_HEALTH: Sources offline"

    # 3. KiBot Health Guard (Unified Singapore/Batam Check)
    if not _KiBot_healthy:
        if mode == "NORMAL":
            print(f"[v7][FAIL_SOFT] KiBot offline but mode is NORMAL, allowing egress for {pair}", flush=True)
            # Proceeding anyway
        else:
            return False, "KiBot_OFFLINE: No heartbeat from executor (Singapore)"

    # 4. Quarantine Guard
    if pair:
        # 4.1 Cooldown (45m)
        last_t = _last_entry.get(pair, 0.0)
        cooldown_s = int(os.environ.get("KIBOT_QUARANTINE_SECONDS", "2700"))
        if (time.time() - last_t) < cooldown_s:
            return False, f"QUARANTINE: {pair} cooldown"

        # 4.2 Blacklist (Max 2 losses)
        if _entry_loss_count.get(pair, 0) >= int(os.environ.get("KIBOT_MAX_PAIR_LOSS", "2")):
            return False, f"BLACKLIST: {pair} too many losses"

    # 5. Statistical sanity check.
    # Brain/AI research stays advisory-only in background loops so the live
    # entry path never blocks on internet calls.
    if pair:
        prices = _price_history.get(pair, [])
        if prices and len(prices) >= 20:
            z_val = calculate_z_score(prices)
            z_thresh = dynamic_config.get_param("KIBOT_Z_SCORE_THRESHOLD", 2.2)
            if abs(z_val) > z_thresh:
                return False, f"STATS_REJECT: Z-Score {z_val:.2f} too extreme (> {z_thresh})"

    # 6. What-If Simulation Gate (New v7.4)
    if _WHATIF_AVAILABLE and pair:
        sim = simulate_pair(pair, _get_last_price(pair))
        if sim.get("verdict") == "SKIP":
            _metric_inc("entries_blocked_whatif")
            return False, f"WHATIF_REJECT: EV={sim.get('expectedValue')} (SKIP)"
        if sim.get("verdict") == "MARGINAL":
            print(f"[v7][WHATIF][WARN] {pair} is MARGINAL (EV={sim.get('expectedValue')}), proceeding with caution", flush=True)

    # 7. AI Brain Validation (Non-Blocking Satpam)
    if AI_ROUTER_ENABLED and pair and msg_type in ("SIGNAL", "ANOMALY", "PUMP"):
        # Check global veto state (updated by background thread)
        veto_state = _get_ai_veto_state(pair)
        if "REJECTED" in veto_state:
            _metric_inc("entries_blocked_ai_veto")
            return False, f"AI_VETO: {veto_state}"
        
        # If no verdict yet, we push to queue but allow if math gates are ok (Fail-Fast)
        if not veto_state:
             _request_ai_veto(pair, msg_type)

    return True, "ok"

def _send_critical_alert(event: str, data: dict = None):
    """Alert kritis ke Telegram owner."""
    d = data or {}
    ts = datetime.now(WIB).strftime('%H:%M:%S WIB')
    templates = {
        "HARD_STOP": f"🛑 HARD STOP [{ts}]\nLoss: {d.get('loss_pct',0):.2f}%\nModal: Rp{d.get('current',0):,.0f}\nENTRY DIBLOKIR harian",
        "AI_OFFLINE": f"🔴 AI OFFLINE [{ts}]\nSemua provider gagal. Entry baru DITANGGUHKAN.",
        "AVERAGING_DOWN_BLOCKED": f"⚠️ ANTI AVERAGING-DOWN [{ts}]\nPair: {d.get('pair','?')}\nSudah loss {d.get('count',0)}x hari ini. Diblokir.",
        "LEVEL_3_FREEZE": f"🔒 LEVEL 3 FREEZE [{ts}]\nLoss: {d.get('loss_pct',0):.2f}%\nAI: {'Ok' if d.get('ai_ok') else 'OFFLINE'}\nStop entry total.",
    }
    msg = templates.get(event, f"⚠️ {event} [{ts}]: {d}")
    print(f"[v7][ALERT] {msg}", flush=True)
    _telegram_send(msg)

def _on_position_closed_with_loss(pair: str, loss_idr: float):
    """Callback for loss tracking (Fix #6)."""
    _entry_loss_count[pair] = _entry_loss_count.get(pair, 0) + 1
    print(f"[v7][LOSS_RECORDED] {pair}: loss_count={_entry_loss_count[pair]} loss=Rp{loss_idr:.0f}", flush=True)

def _get_effective_mode() -> str:
    """Consolidates Risk Level and AI Health into a final operation mode."""
    level = _gate_state.get("mode") # LEVEL_1, LEVEL_2, LEVEL_3
    ai_ok = _ai_healthy
    
    if level == "LEVEL_3" and not ai_ok:
        return "FULL_FREEZE"
    if level == "LEVEL_3":
        return "EXIT_ONLY"

    # 4. Polymarket Sentiment Check (New v7.4)
    poly_sentiment = _get_polymarket_sentiment()
    if poly_sentiment == "DEFENSIVE":
        return "DEFENSIVE"
    
    return "NORMAL"

def _get_polymarket_sentiment() -> str:
    """Fetch global sentiment from local Polymarket service."""
    try:
        # Query local polymarket state file or service
        path = Path("state/polymarket_state.json")
        if path.exists():
            state = json.loads(path.read_text())
            # If any 'recession' or 'crash' market has > 60% probability
            for m in state.get("markets", []):
                q = m.get("question", "").lower()
                prob = m.get("implied_prob_yes", 0.0)
                if ("recession" in q or "crash" in q or "emergency" in q) and prob > 0.60:
                    print(f"[v7][POLYMARKET] Emergency sentiment detected: {q} ({prob:.2f})", flush=True)
                    return "DEFENSIVE"
    except Exception as e:
        print(f"[v7][POLYMARKET][ERROR] Sentiment check failed: {e}", flush=True)
    return "NORMAL"

def _get_last_price(pair: str) -> float:
    """Helper to get last price from history or whiteboard."""
    hist = _price_history.get(pair, [])
    if hist: return hist[-1]
    return _global_whiteboard.get(pair, {}).get("binance", 0.0)

def _is_signal_stale(signal: dict) -> bool:
    """Drops signals older than STALE_SIGNAL_ABORT_MS (Fix #1)."""
    ts = signal.get("timestamp_ms") or signal.get("ts") or (signal.get("last_update", 0) * 1000)
    if ts == 0: return False
    age_ms = (time.time() * 1000) - ts
    stale_limit = dynamic_config.get_param("KIBOT_STALE_SIGNAL_MS", STALE_SIGNAL_ABORT_MS)
    if age_ms > stale_limit:
        print(f"[v7][STALE_DROP] {signal.get('pair','?')} age={age_ms:.0f}ms > {stale_limit}ms", flush=True)
        return True
    return False


def _is_duplicate_signal(msg: dict) -> bool:
    """
    Sliding window signal deduplication (Bug #5).
    """
    pair = str(msg.get("pair") or msg.get("pair_indodax") or msg.get("pairId") or "").lower()
    mtype = str(msg.get("type") or msg.get("msgType") or "").upper()
    source = str(msg.get("exchange") or msg.get("source") or "unknown").upper()
    if not pair or not mtype: return False

    key = f"{source}:{mtype}:{pair}"
    now = time.time()
    last = _signal_seen.get(key, 0.0)
    dedup_s = int(os.environ.get("KIBOT_SIGNAL_DEDUP_S", "90"))

    if (now - last) < dedup_s:
        # print(f"[v7][DEDUP_SKIP] {key} received {now-last:.1f}s ago", flush=True)
        return True

    # Marker removed from here - now only written AFTER all health/consensus gates pass
    # in _mark_signal_seen() to allow retries on transient blocks.
    return False

def _mark_signal_seen(msg: dict):
    """Updates the deduplication marker for a signal that has passed all gates."""
    pair = str(msg.get("pair") or msg.get("pair_indodax") or msg.get("pairId") or "").lower()
    mtype = str(msg.get("type") or msg.get("msgType") or "").upper()
    source = str(msg.get("exchange") or msg.get("source") or "unknown").upper()
    if not pair or not mtype: return
    key = f"{source}:{mtype}:{pair}"
    _signal_seen[key] = time.time()

def _on_position_update_v7(pos: dict):
    """Check exit conditions setiap update posisi dari KiBot."""
    profit_pct = pos.get("profitPct", 0.0)
    price      = pos.get("currentPrice", 0.0)
    pair       = pos.get("pairId", "?")

    # 1. Hard stop check
    if _hard_stop.check_position_timeout(pos):
        _relay_to_KiBot({"type": "FORCE_EXIT", "pair": pair, "reason": "12h_timeout"})
        print(f"[v7][HARD_STOP] {pair}: 12h timeout → force exit", flush=True)
        return

    # 2. Partial TP check
    tp_action = _partial_tp.check(pos, profit_pct)
    if tp_action:
        _relay_to_KiBot({**tp_action, "type": "PARTIAL_SELL"})
        print(f"[v7][PARTIAL_TP] {pair}: {tp_action['reason']}", flush=True)
        return

    # 3. Trailing stop check
    prices = _price_history.get(pair, [])
    regime = detect_regime(prices) if prices else "UNKNOWN"
    if _trailing_stop.should_stop(pos, price, regime=regime):
        _relay_to_KiBot({"type": "FORCE_EXIT", "pair": pair, "reason": "trailing_stop"})
        print(f"[v7][TRAILING_STOP] {pair}: price={price} hit stop (regime={regime})", flush=True)

def _on_fill_v7(fill: dict):
    """Setelah order fill, update semua tracker."""
    net_profit = fill.get("netProfitIdr", 0.0)
    
    # [SOVEREIGN] Handle Polymarket USDC PnL
    if "netProfitUsdc" in fill:
        net_profit = fill["netProfitUsdc"] * _arbitrator.usd_idr_rate
        
    bucket     = fill.get("bucketType", "LOCAL_PUMP")
    pair       = fill.get("pairId", "?").lower()
    entry_idr  = fill.get("entryBudgetIdr", 0.0)

    # 1. Quarantine & Loss Tracking (Bug #3)
    if net_profit < 0:
        _entry_loss_count[pair] = _entry_loss_count.get(pair, 0) + 1
        print(f"[v7][LOSS_TRACKER] {pair} loss count: {_entry_loss_count[pair]}", flush=True)
    else:
        # Reset loss count on win? USER said "loss 2x hari ini — blacklist"
        # Usually it's better to keep it for the day or reset on win.
        # Screenshot shows repeat fails, so I'll keep it as "loss today".
        pass

    # 2. Profit lock
    lock_result = _profit_lock.lock(net_profit, bucket)
    print(f"[v7][PROFIT_LOCK] {pair}: net=Rp{net_profit:.0f} "
          f"locked=Rp{lock_result['locked']:.0f} "
          f"redeploy=Rp{lock_result['redeployable']:.0f}", flush=True)

    # 3. Release capital (hanya yang redeployable)
    # [SOVEREIGN] Capital release handled internally by Arbitrator tracking
    pass

    # 4. Record to Learning Engine (New v7.4)
    if _learning_enabled and _learning_engine:
        _learning_engine.record_trade(pair, net_profit / max(1.0, entry_idr))
        print(f"[v7][LEARN] Trade recorded for {pair}", flush=True)

    # [SOVEREIGN] Arbitrator tracks performance via Balance Sync
    _arbitrator.report_pnl(net_profit)

    # 5. Persist State (Bug #6)
    _save_daily_state()

# Dotenv already loaded early.

try:
    from kibot_learning_engine import get_engine as _get_learning_engine, get_regime_detector as _get_regime_detector

    _learning_engine = _get_learning_engine()
    _regime_detector = _get_regime_detector()
    _learning_enabled = True
    print("[KIBOT][LEARN] mathematical learning engine loaded", flush=True)
except Exception as _learning_error:
    _learning_enabled = False
    _learning_engine = None
    _regime_detector = None
    print(f"[KIBOT][LEARN][WARN] learning engine unavailable: {_learning_error}", flush=True)

def _load_json_file(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _metric_inc(name: str, amount: int = 1) -> None:
    current = _metrics.get(name, 0)
    if isinstance(current, (int, float)):
        _metrics[name] = current + amount


def _metric_add(name: str, amount: float) -> None:
    current = _metrics.get(name, 0.0)
    if isinstance(current, (int, float)):
        _metrics[name] = float(current) + float(amount)


def _wib_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7")))


def _wib_today_str() -> str:
    return _wib_now().date().isoformat()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_wib_date_string(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return ""
    return (parsed + timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7")))).date().isoformat()


def _parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9,.-]", "", raw)
    if cleaned.count(",") > 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "." in cleaned and "," not in cleaned:
        whole, fractional = cleaned.rsplit(".", 1)
        if fractional.isdigit() and len(fractional) == 3 and whole.replace("-", "").isdigit():
            cleaned = cleaned.replace(".", "")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except Exception:
        return None


def _telegram_send(message: str, *, category: str = "general", force: bool = False) -> None:
    # --- REDIRECTED TO COMM-HUB (v9.1.1) ---
    # Internal messages now logged only to avoid duplication in Telegram.
    with open("/home/ubuntu/KiBot/Infrastructure/logs/brain_internal.log", "a") as f:
        f.write(f"[{time.ctime()}] {message}\n")
    return


import math, statistics
from pathlib import Path
from datetime import datetime, timedelta, date

# =============================================
# TRADE LOGGER — Memory Sistem
# Simpan ke local file DAN Supabase
# =============================================

_EARLY_RUNTIME_ROOT = Path(
    os.getenv(
        "KIBOT_RUNTIME_ROOT",
        str(Path(__file__).resolve().parent.parent),
    )
)
_EARLY_STATE_ROOT = Path(
    os.getenv(
        "KIBOT_MANAGER_STATE_DIR",
        str(_EARLY_RUNTIME_ROOT / "state"),
    )
)
TRADE_LOG_FILE = Path(
    os.getenv(
        "KIBOT_MANAGER_TRADE_LOG_FILE",
        str(_EARLY_STATE_ROOT / "trade_log.jsonl"),
    )
)
DAILY_SUMMARY_FILE = Path(
    os.getenv(
        "KIBOT_MANAGER_DAILY_SUMMARY_FILE",
        str(_EARLY_STATE_ROOT / "daily_summary.json"),
    )
)

# [KIBOT][MODULAR] TradeLogger class removed. Consolidated into kibot_learning_engine.py

# Singleton
# trade_logger now points to the centralized learning engine
trade_logger = _learning_engine

# =============================================
# TRINITY HELPERS — Networking & State
# =============================================

# Consolidated UDP Broadcast
def _broadcast_udp(msg: dict):
    """Egress to Trinity Gate (v7)."""
    _relay_to_KiBot(msg)


def _load_indodax_ticker_snapshot() -> dict:
    """Shorthand untuk ambil ticker snapshot."""
    global _indodax_ticker_snapshot
    return _indodax_ticker_snapshot

def _is_hard_stop_active() -> bool:
    """Check both manager and daily guard hard stops via Arbitrator."""
    return not _arbitrator.is_trading_allowed()

def _maybe_run_30min_math_review():
    """Trigger review setiap 30 menit (math-based)."""
    global _last_30min_review
    now = time.time()
    if (now - _last_30min_review) >= 1800:
        _last_30min_review = now
        run_30min_math_review()





# ═══════════════════════════════════════════════════════════
# KIBOT TRINITY v6.0 — PAIR UNIVERSE & PORTFOLIO MANAGER
# ═══════════════════════════════════════════════════════════

# === PAIR CATEGORY SYSTEM ===

# Kategori A: Lead-Lag (ada di Binance Spot)
LEAD_LAG_PAIRS: dict[str, str] = {
    # TIER 1 — Volume > $500K/hari di Indodax
    "btc_idr":     "BTCUSDT",   "eth_idr":    "ETHUSDT",
    "xrp_idr":     "XRPUSDT",   "sol_idr":    "SOLUSDT",
    "doge_idr":    "DOGEUSDT",  "bnb_idr":    "BNBUSDT",
    "pepe_idr":    "PEPEUSDT",  "ada_idr":    "ADAUSDT",
    "shib_idr":    "SHIBUSDT",  "xlm_idr":    "XLMUSDT",
    "trx_idr":     "TRXUSDT",   "hbar_idr":   "HBARUSDT",
    "sui_idr":     "SUIUSDT",   "dot_idr":    "DOTUSDT",
    "pol_idr":     "POLUSDT",   "bonk_idr":   "BONKUSDT",
    "pengu_idr":   "PENGUUSDT",

    # TIER 2 — Volume $100K-$500K
    "fet_idr":     "FETUSDT",   "render_idr": "RENDERUSDT",
    "anime_idr":   "ANIMEUSDT", "trump_idr":  "TRUMPUSDT",
    "zen_idr":     "ZENUSDT",   "iotx_idr":   "IOTXUSDT",
    "moodeng_idr": "MOODENGUSDT","mon_idr":   "MONUSDT",
    "vanry_idr":   "VANRYUSDT", "mog_idr":    "MOGUSDT",
    "spx_idr":     "SPXUSDT",   "link_idr":   "LINKUSDT",
    "avax_idr":    "AVAXUSDT",  "near_idr":   "NEARUSDT",
    "apt_idr":     "APTUSDT",   "arb_idr":    "ARBUSDT",
    "op_idr":      "OPUSDT",    "atom_idr":   "ATOMUSDT",
    "ltc_idr":     "LTCUSDT",   "uni_idr":    "UNIUSDT",
    "floki_idr":   "FLOKIUSDT", "enj_idr":    "ENJUSDT",
    "fun_idr":     "FUNUSDT",   "dusk_idr":   "DUSKUSDT",
    "matic_idr":   "MATICUSDT", "paxg_idr":   "PAXGUSDT",

    # TIER 3 — Volume < $100K (masuk kalau ada signal kuat)
    "bch_idr":     "BCHUSDT",   "etc_idr":    "ETCUSDT",
    "pixel_idr":   "PIXELUSDT", "zerebro_idr":"ZEREBRUSDT",
    "islm_idr":    "ISLAMUSDT",  # Islamic Coin — cek apakah ada di Binance
}

# Kategori B: Binance Futures only (pakai futures price sebagai proxy)
FUTURES_PROXY_PAIRS: dict[str, str] = {
    "fartcoin_idr": "FARTCOINUSDT",  # Binance Futures only, tidak ada Spot
    # "jellyjelly_idr": delisted dari Binance Futures
}

# Kategori C: Indodax-Only (pure technical, no lead-lag)
INDODAX_ONLY_PAIRS: list[str] = [
    "pippin_idr",      # Volume #2 Indodax ($7.56M) — PRIORITAS
    "myx_idr",         # MYX Finance
    "jellyjelly_idr",  # JellyJelly
    "aster_idr",       # Aster
    "hype_idr",        # Hyperliquid — tidak ada di Binance sama sekali
    "gravity_idr",
    "trollsol_idr",
    "whitewhale_idr",
    "wealth_idr",
    "mubarak_idr",
    "xpl_idr",         # Plasma
    "fanc_idr",
    "nova_idr",
    "mrs_idr",         # Metars Genesis
    "zerebro_idr",     # Zerebro — jika tidak ada di Binance spot
]

# Sektor per pair (untuk diversifikasi)
PAIR_SECTORS: dict[str, str] = {
    "btc_idr": "layer1", "eth_idr": "layer1",
    "sol_idr": "layer1", "ada_idr": "layer1",
    "bnb_idr": "exchange", "trx_idr": "layer1",
    "doge_idr": "meme",  "shib_idr": "meme",
    "pepe_idr": "meme",  "bonk_idr": "meme",
    "floki_idr": "meme", "pippin_idr": "meme",
    "fartcoin_idr": "meme", "moodeng_idr": "meme",
    "jellyjelly_idr": "meme", "mubarak_idr": "meme",
    "trollsol_idr": "meme",
    "xlm_idr": "payment", "xrp_idr": "payment",
    "sui_idr": "layer1",  "dot_idr": "layer1",
    "arb_idr": "layer2",  "op_idr": "layer2",
    "pol_idr": "layer2",
    "link_idr": "oracle", "fet_idr": "ai_token",
    "render_idr": "ai_token",
    "enj_idr": "gaming",  "fun_idr": "gaming",
    "hype_idr": "defi",   "myx_idr": "defi",
    "uni_idr": "defi",
    "pengu_idr": "nft",   "spx_idr": "meme",
    "islm_idr": "local_idr",
}

def get_pair_category(pair_id: str) -> str:
    """Classify pair ke kategori."""
    if pair_id in LEAD_LAG_PAIRS:
        return "LEAD_LAG"
    if pair_id in FUTURES_PROXY_PAIRS:
        return "FUTURES_PROXY"
    return "INDODAX_ONLY"

def get_binance_symbol(pair_id: str) -> str | None:
    """Get Binance USDT symbol — dengan explicit mapping."""
    # Check explicit lead-lag map first
    explicit = LEAD_LAG_PAIRS.get(pair_id)
    if explicit:
        return explicit
    # Check futures proxy
    futures = FUTURES_PROXY_PAIRS.get(pair_id)
    if futures:
        return futures
    # Auto-derive fallback (bukan XLMIDR lagi!)
    base = pair_id.replace("_idr", "").replace("_usdt", "")
    return f"{base.upper()}USDT"

def get_pair_sector(pair_id: str) -> str:
    return PAIR_SECTORS.get(pair_id, "unknown")

# === PORTFOLIO CONFIGURATION ===
PORTFOLIO_CONFIG = {
    "max_concurrent_positions": 5,
    "max_budget_pct_per_pos":   0.20,
    "min_budget_idr":           10_000,
    "max_lead_lag_positions":   3,
    "max_indodax_only_positions": 2,
    "max_same_sector":          2,
}

class Position:
    """Single position tracking."""
    def __init__(self, pair_id: str, entry_price: float,
                 budget_idr: float, category: str, phase: str = "MID"):
        self.pair_id       = pair_id
        self.entry_price   = entry_price
        self.budget_idr    = budget_idr
        self.category      = category
        self.phase         = phase
        self.stop_price    = entry_price * (1 - 0.05)  # default 5%
        self.peak_price    = entry_price
        self.entry_time    = time.time()
        self.partial_tp_done = False
        self.partial_tp_triggered = False
        self.unrealized_pnl_idr = 0.0
        self.profit_pct    = 0.0

    def update_price(self, current_price: float):
        self.peak_price  = max(self.peak_price, current_price)
        pnl = ((current_price - self.entry_price) / self.entry_price)
        self.profit_pct           = pnl
        self.unrealized_pnl_idr   = self.budget_idr * pnl

class PortfolioManager:
    """Manages up to 5 concurrent positions."""

    def __init__(self):
        self._lock       = threading.Lock()
        self.positions: dict[str, Position] = {}
        self.realized_pnl_today: float = 0.0
        self.daily_pnl_pct: float = 0.0

    def can_open(self, pair_id: str, category: str) -> tuple[bool, str]:
        with self._lock:
            if pair_id in self.positions:
                return False, "Already in position"
            n = len(self.positions)
            if n >= PORTFOLIO_CONFIG["max_concurrent_positions"]:
                return False, f"Max {PORTFOLIO_CONFIG['max_concurrent_positions']} positions"

            ll = sum(1 for p in self.positions.values() if p.category == "LEAD_LAG")
            lo = sum(1 for p in self.positions.values() if p.category == "INDODAX_ONLY")
            if category == "LEAD_LAG" and ll >= PORTFOLIO_CONFIG["max_lead_lag_positions"]:
                return False, "Max lead-lag positions"
            if category == "INDODAX_ONLY" and lo >= PORTFOLIO_CONFIG["max_indodax_only_positions"]:
                return False, "Max local positions"

            sector = get_pair_sector(pair_id)
            sector_count = sum(1 for p in self.positions.values()
                               if get_pair_sector(p.pair_id) == sector)
            if sector_count >= PORTFOLIO_CONFIG["max_same_sector"]:
                return False, f"Sector {sector} full"

            return True, "OK"

    def open_position(self, pair_id: str, entry_price: float,
                      budget_idr: float, category: str, phase: str = "MID"):
        with self._lock:
            self.positions[pair_id] = Position(
                pair_id, entry_price, budget_idr, category, phase
            )
        print(
            f"[PORTFOLIO] OPEN {pair_id} @ {entry_price:.6f} "
            f"Rp{budget_idr:,.0f} [{len(self.positions)}/5]", flush=True
        )

    def close_position(self, pair_id: str, exit_price: float, reason: str):
        with self._lock:
            pos = self.positions.pop(pair_id, None)
        if pos:
            pnl = (exit_price - pos.entry_price) / pos.entry_price * pos.budget_idr
            self.realized_pnl_today += pnl
            hold_min = (time.time() - pos.entry_time) / 60
            print(
                f"[PORTFOLIO] CLOSE {pair_id} pnl=Rp{pnl:+.0f} "
                f"({pnl/pos.budget_idr:+.2%}) hold={hold_min:.0f}m reason={reason} "
                f"[{len(self.positions)}/5]", flush=True
            )
            return pnl
        return 0.0

    def get_pnl_state(self) -> str:
        pnl = self.daily_pnl_pct
        if pnl <= -0.02:  return "HARD_STOP"
        if pnl <= -0.01:  return "CRITICAL"
        if pnl <= -0.005: return "WARNING"
        return "HEALTHY"

    def get_available_budget(self, total_equity: float) -> float:
        with self._lock:
            allocated = sum(p.budget_idr for p in self.positions.values())
        available = total_equity - allocated
        max_per   = total_equity * PORTFOLIO_CONFIG["max_budget_pct_per_pos"]
        return max(0, min(available, max_per))


# Singleton
portfolio_manager = PortfolioManager()

# =============================================
# PURE TECHNICAL DETECTOR — Indodax-only pairs
# Untuk koin tanpa Binance pair (WHITEWHALE, BR, DRX, BIO, dll)
# =============================================

INDODAX_OHLCV_URL = "https://indodax.com/tradingview/history_v2"
INDODAX_TICKERS_URL = "https://indodax.com/api/tickers"

def fetch_candles(pair_id: str, tf: int = 15, count: int = 25) -> list[dict]:
    """Ambil OHLCV dari Indodax tradingview API."""
    import time, urllib.request
    base = pair_id.replace("_idr", "").upper()
    symbol = f"{base}/IDR"
    now = int(time.time())
    from_ts = now - (tf * 60 * count)
    url = f"{INDODAX_OHLCV_URL}?symbol={symbol}&tf={tf}&from={from_ts}&to={now}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        times  = data.get("t", [])
        opens  = data.get("o", data.get("Open", []))
        highs  = data.get("h", data.get("High", []))
        lows   = data.get("l", data.get("Low", []))
        closes = data.get("c", data.get("Close", []))
        # Ensure it's OHLC format
        candles = []
        for i in range(len(times)):
            candles.append({
                "t": int(times[i]),
                "o": float(opens[i]), "h": float(highs[i]),
                "l": float(lows[i]),  "c": float(closes[i]),
                "v": float(data.get("v", [])[i]) if "v" in data and i < len(data["v"]) else 0
            })
        return candles
    except Exception as e:
        print(f"[CANDLE] {pair_id}: {e}", flush=True)
        return []

def fetch_order_book_depth(pair_id: str) -> dict | None:
    """Fetch order book depth for imbalance analysis."""
    import urllib.request
    url = f"https://indodax.com/api/depth/{pair_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None

def check_order_book_imbalance(depth: dict | None) -> float:
    """Calculate Bid/Ask volume ratio for the first 10 levels. Returns ratio."""
    if not depth or "buy" not in depth or "sell" not in depth:
        return 1.0
    try:
        bid_vol = sum(float(b[1]) for b in depth["buy"][:10])
        ask_vol = sum(float(s[1]) for s in depth["sell"][:10])
        return bid_vol / max(ask_vol, 1e-9)
    except Exception:
        return 1.0

def calc_bollinger(closes: list[float], period: int = 20, std_mult: float = 2.0) -> dict | None:
    """Hitung Bollinger Band dari list close prices."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((c - sma) ** 2 for c in window) / period
    std = math.sqrt(variance)
    return {
        "upper": sma + std_mult * std,
        "middle": sma,
        "lower": sma - std_mult * std,
        "std": std,
        "bandwidth": (std_mult * 2 * std) / sma if sma > 0 else 0
    }

def calc_rsi(closes: list[float], period: int = 14) -> float:
    """Hitung RSI dari list close prices."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i-1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    gains = gains[-period:]
    losses = losses[-period:]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze_pure_technical(pair_id: str, ticker: dict) -> dict:
    """
    Analisis teknikal murni untuk koin indodax-only.
    Refined v6.2: Bollinger Divergence, RSI Guard, Order Book Imbalance.
    """
    import time
    price     = float(ticker.get("last", 0))
    vol_24h   = float(ticker.get("vol_idr", 0))
    high_24h  = float(ticker.get("high", price))
    low_24h   = float(ticker.get("low", price))
    bid       = float(ticker.get("buy", price * 0.99))
    ask       = float(ticker.get("sell", price * 1.01))

    if price <= 0:
        return {"recommendation": "SKIP", "score": 0, "reason": "invalid price"}

    # Ambil candle data
    candles = fetch_candles(pair_id, tf=15, count=25)
    closes  = [c["c"] for c in candles] if candles else []
    volumes = [c["v"] for c in candles] if candles else []

    score   = 0.0
    reasons = []

    # === 1. VOLUME LEGITIMACY (0-30 poin) ===
    if vol_24h < 500_000_000:  # < 500 juta (User Audit Penalty)
        score -= 25
        reasons.append(f"vol kecil Rp{vol_24h/1e9:.1f}B")
    elif vol_24h > 5_000_000_000:
        score += 30
        reasons.append(f"vol besar Rp{vol_24h/1e9:.1f}B")
    elif vol_24h > 1_000_000_000:
        score += 20
        reasons.append(f"vol OK Rp{vol_24h/1e9:.1f}B")

    # Volume spike 1h vs avg
    if len(volumes) >= 4:
        avg_vol = sum(volumes[:-1]) / max(len(volumes)-1, 1)
        last_vol = volumes[-1]
        vol_ratio = last_vol / max(avg_vol, 1)
        if vol_ratio >= 3.0:
            score += 25
            reasons.append(f"vol spike {vol_ratio:.1f}x")
        elif vol_ratio >= 2.0:
            score += 15
            reasons.append(f"vol spike {vol_ratio:.1f}x")

    # === 2. BOLLINGER BAND & DIVERGENCE (0-25 poin) ===
    bb = calc_bollinger(closes) if len(closes) >= 20 else None
    bb_pct = 0.5
    if bb:
        bb_range = bb["upper"] - bb["lower"]
        bb_pct = (price - bb["lower"]) / max(bb_range, 1e-9)

        # Check Divergence: Price Up, Volume Down
        if len(closes) >= 5 and len(volumes) >= 5:
            price_trend = closes[-1] > closes[-4]
            vol_trend   = volumes[-1] < volumes[-4]
            if price_trend and vol_trend and bb_pct > 0.8:
                score -= 20
                reasons.append("divergensi bearish")

        if bb_pct < 0.35:
            score += 25
            reasons.append(f"BB bawah ({bb_pct:.0%})")
        elif bb_pct < 0.60:
            score += 16
        elif bb_pct > 0.95:
            score -= 20
            reasons.append("BB overbought")

    # === 3. RSI GUARD (Hard Veto) ===
    rsi = calc_rsi(closes) if len(closes) >= 15 else 50.0
    if rsi > 82:
        return {"recommendation": "SKIP", "score": 0, "reason": f"RSI extreme {rsi:.0f}"}
    if rsi < 35:
        score += 15
        reasons.append(f"RSI oversold {rsi:.0f}")
    elif rsi > 70:
        score -= 10

    # === 4. ORDER BOOK IMBALANCE (0-20 poin) ===
    depth = fetch_order_book_depth(pair_id)
    ob_ratio = check_order_book_imbalance(depth)
    if ob_ratio >= 2.5:
        score += 20
        reasons.append(f"OB imbalance {ob_ratio:.1f}x")
    elif ob_ratio >= 1.5:
        score += 10
    elif ob_ratio < 0.6:
        score -= 15
        reasons.append(f"OB weak {ob_ratio:.1f}x")

# =============================================
# CONVICTION SCORE ENGINE — Bucket B
# =============================================

class ConvictionScoreCalculator:
    """Algoritma scoring murni matematis untuk koin lokal."""

    @staticmethod
    def compute(pair_id: str, ticker: dict, closes: list[float],
                volumes: list[float], depth: dict | None) -> dict:
        price = float(ticker.get("last", 0))
        vol_24h = float(ticker.get("vol_idr", 0))
        high_24h = float(ticker.get("high", price))
        low_24h = float(ticker.get("low", price))

        # 1. Volume Spike Score (0.30)
        # avg_vol_7d (approx from 15m candles * 4 * 24 * 7 -> way too many, use last 24h avg)
        avg_vol = statistics.mean(volumes) if volumes else 1.0
        cur_vol = volumes[-1] if volumes else 0
        volume_spike = min(1.0, cur_vol / max(avg_vol, 1e-9))

        # 2. Breakout Score (0.25)
        bb = calc_bollinger(closes)
        breakout = 0.5
        if bb:
            breakout = (price - bb["lower"]) / max(bb["upper"] - bb["lower"], 1e-9)
            breakout = max(0.0, min(1.0, breakout))

        # 3. Orderbook Score (0.25)
        bid_vol = sum(float(b[1]) for b in depth["buy"][:10]) if depth else 1.0
        ask_vol = sum(float(s[1]) for s in depth["sell"][:10]) if depth else 1.0
        ob_score = bid_vol / max(bid_vol + ask_vol, 1e-9)

        # 4. Momentum Score (0.20)
        rsi = calc_rsi(closes)
        momentum = max(0.0, min(1.0, (75 - rsi) / 75))

        final_score = (
            0.30 * volume_spike +
            0.25 * breakout +
            0.25 * ob_score +
            0.20 * momentum
        )

        # === HARD BLOCKS ===
        blocks = []
        if (price - low_24h) / max(low_24h, 1e-9) > 0.50:
            blocks.append("Pump > 50%")
        if bb and price > bb["upper"]:
            blocks.append("Price > Upper BB")
        if rsi > 80:
            blocks.append("RSI > 80")
        if vol_24h < 500_000_000:
            blocks.append("Vol < 500M IDR")
        # BTC Regime Guard check will be in main logic

        return {
            "score": round(final_score, 3),
            "blocks": blocks,
            "rsi": rsi,
            "ob_ratio": bid_vol / max(ask_vol, 1e-9),
            "recommendation": "ENTER" if (final_score >= 0.85 and not blocks) else "SKIP"
        }

class RiskLadder:
    """Cascade Loss Intelligence state machine."""

    @staticmethod
    def get_mode(daily_pnl_pct: float, wins_today: int, losses_today: int, consecutive_losses: int) -> str:
        if daily_pnl_pct < -0.02: return "HARD_STOP"
        if consecutive_losses >= 3: return "RESTRICTED"
        if consecutive_losses >= 2: return "DEFENSIVE"
        if losses_today >= 1: return "CAUTION"
        return "GROWTH"

    @staticmethod
    def get_kelly_multiplier(mode: str) -> float:
        return {
            "GROWTH": 1.0,
            "CAUTION": 0.8,
            "DEFENSIVE": 0.5,
            "RESTRICTED": 0.3,
            "HARD_STOP": 0.0
        }.get(mode, 0.5)

# =============================================
# WHAT-IF ENGINE — Matematis, tidak butuh AI
# =============================================

MAKER_FEE = 0.0004   # 0.04% LIMIT order (prioritas)
TAKER_FEE = 0.0055   # 0.55% MARKET order (mahal)
PPH_SELL  = 0.0021   # 0.21% PPh sisi jual
# --- DYNAMIC FEE GOVERNOR (v9.1.1) ---
INDODAX_BASE_FEE = 0.003  # 0.3%
INDODAX_TAX_PPH  = 0.001  # 0.1% (PMK 68)
INDODAX_TAX_PPN  = 0.0011 # 0.11% (Dikenakan pada fee, bukan nilai transaksi)

# Total All-in Taker Fee (Safe Estimate)
TAKER_FEE = INDODAX_BASE_FEE + INDODAX_TAX_PPH + (INDODAX_BASE_FEE * INDODAX_TAX_PPN)
MAKER_FEE = 0.000  # Indodax Maker sering 0% atau promo

def get_current_fees():
    """AI-Integrated Fee Check. Bisa di-update via API di masa depan."""
    return {"taker": TAKER_FEE, "maker": MAKER_FEE}

def calculate_round_trip(spread_pct, slippage_pct):
    fees = get_current_fees()
    # Cost = Spread/2 + Slippage + Entry Fee + Exit Fee
    return (spread_pct / 2) + slippage_pct + fees['taker'] + fees['taker']

def simulate_what_if(
    pair_id: str,
    budget_idr: float,
    spread_pct: float = 0.015,
    slippage_pct: float = 0.012,
    target_pct: float = 0.025,
    trailing_stop_pct: float = 0.05,
    use_market_entry: bool = False,
    use_market_exit: bool = False,
) -> dict:
    """
    Simulasi what-if lengkap sebelum setiap entry.
    Return: keputusan ENTER/REDUCE/SKIP + semua angka.
    """
    fee_entry = TAKER_FEE if use_market_entry else MAKER_FEE
    fee_exit  = TAKER_FEE if use_market_exit  else MAKER_FEE

    round_trip_cost = (spread_pct / 2) + slippage_pct + fee_entry + fee_exit + PPH_SELL
    breakeven_pct   = round_trip_cost
    net_pct         = target_pct - round_trip_cost
    max_loss_pct    = trailing_stop_pct + round_trip_cost
    max_loss_idr    = budget_idr * max_loss_pct
    reward_idr      = budget_idr * max(net_pct, 0)
    rr              = reward_idr / max(max_loss_idr, 1)

    # Win rate & Memory from Bayesian-Kelly Engine (Trinity v6.2)
    le_stats = None
    if _learning_engine:
        le_stats = _learning_engine.get(pair_id)
        win_rate = le_stats.win_probability
    else:
        # Fallback to local trade logger stats
        pair_stats = trade_logger.get_pair_stats(pair_id)
        win_rate = pair_stats.get("win_rate", 0.5)

    ev_idr = (win_rate * reward_idr) - ((1 - win_rate) * max_loss_idr)

    # Kelly fraction (using LE stats if available)
    kelly_f = 0.02 # Default min
    if le_stats:
        kelly_f = le_stats.kelly_fraction()
    else:
        if rr > 0:
            kelly_f = max(0.01, min(0.12, (win_rate - ((1 - win_rate) / rr)) * 0.5))

    # Apply Risk Ladder Multiplier (Cascade Loss Protection)
    risk_mode = _metrics.get("risk_mode", "GROWTH")
    kelly_multiplier = RiskLadder.get_kelly_multiplier(risk_mode)
    kelly_f *= kelly_multiplier

    # Decision Gate Trinity v6.2
    penalty = _learning_engine.score_penalty(pair_id) if _learning_engine else 0.0
    min_net = 0.015 # Hard floor for Trinity

    decision = "ENTER"
    reason   = f"EV Positive (Mode: {risk_mode})"

    if risk_mode == "HARD_STOP":
        decision = "SKIP"
        reason = "System HARD STOP active"
    elif ev_idr <= 0:
        decision = "SKIP"
        reason   = f"EV Negative (Rp{ev_idr:,.0f})"
    elif kelly_f <= 0.005:
        decision = "SKIP"
        reason   = f"Kelly Sizing too small ({kelly_f:.3f})"
    elif net_pct < min_net:
        decision = "SKIP"
        reason   = f"Net target too thin ({net_pct:.2%})"

    return {
        "decision": decision,
        "reason":   reason,
        "ev_idr":   round(ev_idr, 0),
        "win_rate": round(win_rate, 3),
        "kelly_f":  round(kelly_f, 3),
        "risk_mode": risk_mode,
        "rr":       round(rr, 2),
        "net_pct":  round(net_pct, 4),
        "penalty":  round(penalty, 2),
        "breakeven_pct": round(breakeven_pct, 4),
        "reward_idr":    round(reward_idr, 0),
        "max_loss_idr":  round(max_loss_idr, 0)
    }

def what_if_untung_banyak(pnl_pct: float, equity_idr: float) -> dict:
    """Apa yang harus dilakukan saat untung banyak?"""
    if pnl_pct >= 0.10:  # +10%
        return {
            "action": "TIGHTEN_TRAILING",
            "trailing_stop": 0.015,
            "partial_tp_now": True,
            "partial_tp_size": 0.60,
            "reason": f"Profit besar +{pnl_pct:.1%} — lock 60% profit segera"
        }
    elif pnl_pct >= 0.05:  # +5%
        return {
            "action": "TIGHTEN_TRAILING",
            "trailing_stop": 0.02,
            "partial_tp_now": True,
            "partial_tp_size": 0.40,
            "reason": f"Profit bagus +{pnl_pct:.1%} — lock 40%, trailing ketat"
        }
    elif pnl_pct >= 0.025:  # +2.5%
        return {
            "action": "NORMAL_TRAILING",
            "trailing_stop": 0.035,
            "partial_tp_now": False,
            "reason": f"Profit normal +{pnl_pct:.1%} — trailing stop normal"
        }
    return {"action": "HOLD", "reason": f"Profit kecil +{pnl_pct:.1%} — tunggu"}

def what_if_rugi(pnl_pct: float, equity_idr: float, daily_pnl_pct: float) -> dict:
    """Apa yang harus dilakukan saat rugi?"""
    if abs(pnl_pct) >= 0.05:  # -5% per posisi
        return {
            "action": "CUT_LOSS_NOW",
            "use_market": True,
            "reason": f"Posisi rugi -{abs(pnl_pct):.1%} — cut loss SEKARANG"
        }
    elif daily_pnl_pct <= -0.02:  # daily -2%
        return {
            "action": "HARD_STOP_ALL",
            "reason": f"Daily PnL {daily_pnl_pct:.1%} — stop semua trading"
        }
    elif daily_pnl_pct <= -0.01:  # daily -1%
        return {
            "action": "DEFENSIVE_MODE",
            "reason": f"Daily PnL {daily_pnl_pct:.1%} — mode defensif"
        }
    return {"action": "MONITOR", "reason": f"Rugi wajar {pnl_pct:.1%}"}

def what_if_ketinggalan_entry(signal_age_ms: float, price_change_pct: float) -> str:
    """Ketinggalan signal — harus gimana?"""
    if signal_age_ms < 200 and abs(price_change_pct) < 2.0:
        return "ENTER_MARKET"          # Masih bisa, pakai MARKET
    elif signal_age_ms < 500 and abs(price_change_pct) < 1.5:
        return "ENTER_LIMIT_AGGRESSIVE" # Limit agresif
    elif abs(price_change_pct) >= 5.0:
        return "WAIT_PULLBACK"         # Sudah terlambat, tunggu koreksi
    return "SKIP"

def what_if_dekat_peak(bb_pct: float, rsi: float, volume_trend: str,
                        current_profit_pct: float) -> dict:
    """Deteksi dekat peak dan tentukan exit strategy."""
    peak_signals = 0
    reasons = []

    if bb_pct > 0.90:
        peak_signals += 1
        reasons.append(f"BB overbought {bb_pct:.0%}")
    if rsi > 72:
        peak_signals += 1
        reasons.append(f"RSI overbought {rsi:.0f}")
    if volume_trend == "decreasing":
        peak_signals += 1
        reasons.append("volume menurun")
    if current_profit_pct > 0.05:
        peak_signals += 1
        reasons.append(f"profit besar {current_profit_pct:.1%}")

    if peak_signals >= 3:
        return {
            "near_peak": True,
            "action": "PARTIAL_EXIT",
            "exit_pct": 0.70,
            "tighten_trailing": 0.015,
            "reason": " + ".join(reasons)
        }
    elif peak_signals >= 2:
        return {
            "near_peak": True,
            "action": "TIGHTEN_TRAILING",
            "exit_pct": 0,
            "tighten_trailing": 0.025,
            "reason": " + ".join(reasons)
        }
    return {"near_peak": False, "action": "CONTINUE", "reason": "tidak ada sinyal peak"}

_last_30min_review = 0.0
_score_multiplier  = 1.0
_allowed_tiers_override: list | None = None
_day_start_time = time.time()

def run_30min_math_review():
    global _score_multiplier, _allowed_tiers_override

    stats = trade_logger.get_today_stats()
    equity = _get_total_equity_estimate() or 0.0
    pnl_pct = (portfolio_manager.realized_pnl_today / equity) if equity > 0 else 0.0
    loss_idr = abs(min(pnl_pct, 0) * equity)

    from datetime import datetime, timedelta
    now_wib      = datetime.utcnow() + timedelta(hours=7)
    midnight_wib = now_wib.replace(hour=0,minute=0,second=0) + timedelta(days=1)
    hours_left   = (midnight_wib - now_wib).total_seconds() / 3600

    elapsed_hrs  = max((time.time() - _day_start_time) / 3600, 0.5)
    trades_per_h = stats["total"] / elapsed_hrs if stats["total"] > 0 else 1.5
    trades_left  = trades_per_h * hours_left
    ev_idr       = stats["ev_idr"]

    to_recover = loss_idr / max(ev_idr, 1) if ev_idr > 0 else float("inf")

    # Keputusan berbasis math
    if ev_idr <= 0 and stats["total"] >= 3:
        action = "TIGHTEN_FILTER"
        _score_multiplier = min(_score_multiplier * 1.20, 1.5)
        _allowed_tiers_override = ["A"]
    elif to_recover > trades_left * 2.0:
        action = "PREPARE_STOP"
        _score_multiplier = min(_score_multiplier * 1.15, 1.5)
        _allowed_tiers_override = ["A"]
    elif to_recover > trades_left:
        action = "DEFENSIVE"
        _score_multiplier = min(_score_multiplier * 1.10, 1.4)
        _allowed_tiers_override = ["A", "B"]
    elif stats["win_rate"] >= 0.65 and ev_idr > 0:
        action = "CONTINUE_OPTIMAL"
        _score_multiplier = max(_score_multiplier * 0.97, 1.0)
        _allowed_tiers_override = None
    else:
        action = "CONTINUE"
        _score_multiplier = 1.0
        _allowed_tiers_override = None

    pnl_emoji = "🟢" if pnl_pct >= 0 else ("🟡" if pnl_pct >= -0.01 else "🔴")
    report = (
        f"📊 [{now_wib.strftime('%H:%M')} WIB] 30min Review\n"
        f"{pnl_emoji} PnL: {pnl_pct:+.2%} | Equity: Rp{equity:,.0f}\n"
        f"📈 {stats['total']} trade ({stats['wins']}W/{stats['losses']}L) "
        f"WR={stats['win_rate']:.0%}\n"
        f"💰 EV: Rp{ev_idr:+,.0f}/trade | PF={stats['pf']:.2f}\n"
        f"⏰ Sisa {hours_left:.1f}h | Recover: {to_recover:.0f} trade\n"
        f"🎯 Action: {action} | Threshold: x{_score_multiplier:.2f}"
    )
    _telegram_send(report)
    print(f"[30MIN] {action} | WR={stats['win_rate']:.0%} EV={ev_idr:.0f}", flush=True)

    # Simpan ke Supabase
    _sync_snapshot_to_supabase(pnl_pct, equity, stats, action)

_last_supabase_sync_time = 0.0
_last_supabase_pnl = 0.0

def _sync_snapshot_to_supabase(pnl_pct, equity, stats, action):
    """Sync performance snapshot ke Supabase dengan logika Throttling Otonom."""
    global _last_supabase_sync_time, _last_supabase_pnl
    
    # Otak Penghemat: Jangan kirim kalau baru saja kirim (< 1 jam) 
    # KECUALI ada perubahan PnL signifikan (> 0.5%)
    time_since_sync = time.time() - _last_supabase_sync_time
    pnl_diff = abs(pnl_pct - _last_supabase_pnl)
    
    if time_since_sync < 3600 and pnl_diff < 0.005 and action != "MANUAL_TRIGGER":
        return

    if LOCAL_FIRST_STORAGE and not SUPABASE_BACKUP_ENABLED:
        return
    import threading
    def do_sync():
        try:
            import urllib.request
            supabase_url = os.environ.get("SUPABASE_URL", "")
            supabase_key = os.environ.get("SUPABASE_ANON_KEY", "")
            if not supabase_url: return
            payload = json.dumps({
                "equity_idr": equity,
                "daily_pnl_pct": pnl_pct,
                "daily_pnl_idr": pnl_pct * equity,
                "pnl_state": portfolio_manager.get_pnl_state(),
                "win_rate_today": stats.get("win_rate", 0),
                "ev_per_trade_idr": stats.get("ev_idr", 0),
                "trades_today": stats.get("total", 0),
                "action_taken": action,
                "threshold_multiplier": _score_multiplier,
            }).encode()
            req = urllib.request.Request(
                f"{supabase_url}/rest/v1/performance_snapshots",
                data=payload,
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
            _last_supabase_sync_time = time.time()
            _last_supabase_pnl = pnl_pct
        except Exception as e:
            print(f"[SNAPSHOT] Supabase sync error: {e}", flush=True)
    threading.Thread(target=do_sync, daemon=True).start()

def run_resource_governor():
    """Otak Penghemat Disk: Hapus log lama secara otonom."""
    print("[GOVERNOR] Autonomous Resource Governor Active.", flush=True)
    while not _shutdown_event.is_set():
        try:
            import shutil
            # 1. Cek Disk Space
            total, used, free = shutil.disk_usage("/")
            free_gb = free // (2**30)
            
            if free_gb < 5:
                print(f"[GOVERNOR] Disk Low ({free_gb}GB). Purging old logs...", flush=True)
                # Sesuaikan dengan screenshot: Infrastructure/logs
                log_dir = Path(__file__).parent.parent / "Infrastructure" / "logs"
                if log_dir.exists():
                    now = time.time()
                    for f in log_dir.glob("*.log*"):
                        if f.stat().st_mtime < (now - 3 * 86400): # 3 hari
                            f.unlink()
                            print(f"[GOVERNOR] Deleted old log: {f.name}", flush=True)
            
        except Exception as e:
            print(f"[GOVERNOR] Error: {e}", flush=True)
        if _shutdown_event.wait(timeout=21600): break # Tiap 6 jam

_screen_cache_local: list = []
_last_screen_time = 0.0
_bb_cache_local: dict = {}

async def screen_indodax_only_pairs() -> list[dict]:
    """
    Universal Screener: Scan SEMUA koin Indodax.
    Focus: Mencari koin dengan volume & momentum tinggi yang tidak ada di Binance.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(INDODAX_TICKERS_URL, timeout=10) as r:
            raw = json.loads(r.read())
        tickers = raw.get("tickers", raw)
    except Exception as e:
        print(f"[SCREEN] Tickers fetch failed: {e}", flush=True)
        return []

    candidates = []
    # Scan seluruh universe Indodax
    for pair_id, ticker in tickers.items():
        # Filter 1: Bukan Stablecoin / Base pair
        if "_usdt" in pair_id or "idrt" in pair_id or pair_id == "btc_idr":
            continue

        # Filter 2: Bukan koin Lead-Lag (sudah dihandle radar Binance)
        if pair_id in LEAD_LAG_PAIRS:
            continue

        # Filter 3: Liquidity Guard (Min 500jt volume 24 jam)
        vol_24h = float(ticker.get("vol_idr", 0))
        if vol_24h < 500_000_000:
            continue

        # Filter 4: Momentum Check (Last price vs Low 24h)
        last = float(ticker.get("last", 0))
        low = float(ticker.get("low", last))
        high = float(ticker.get("high", last))
        if last <= low: continue # No momentum

        # Deep Analysis hanya untuk yang lolos filter awal
        analysis = analyze_pure_technical(pair_id, ticker)
        if analysis["recommendation"] == "SKIP":
            continue

        candidates.append({
            "pair_id": pair_id,
            "category": "INDODAX_ONLY",
            "analysis": analysis,
            "vol_24h_idr": vol_24h,
            "composite_score": analysis["score"]
        })

    # Sort berdasarkan skor teknikal terbaik
    candidates.sort(key=lambda x: x["composite_score"], reverse=True)

    if candidates:
        top = candidates[0]
        a   = top["analysis"]
        print(
            f"[SCREEN-UNIVERSAL] Found {len(candidates)} candidates. "
            f"Top: {top['pair_id']} score={a['score']} OB={a['ob_ratio']} RSI={a['rsi']}",
            flush=True
        )

    return candidates[:8]



def _process_signal_multipos(msg: dict):
    """
    Entry gate untuk multi-position system Trinity v6.2.
    Implementasi 'Papan Tulis' (Global Consensus) & Veto Logic.
    """
    global _global_whiteboard

    source = msg.get("source", "BINANCE")
    msg_type = msg.get("msgType", msg.get("type", "SIGNAL"))

    # === 1. UPDATE PAPAN TULIS (BACKGROUND) ===
    if msg_type == "TICKER_UPDATE":
        symbol = msg.get("symbol", "")
        if not symbol: return

        wb_entry = _global_whiteboard.setdefault(symbol, {"binance": None, "cryptocom": None})
        if source == "CRYPTOCOM":
            wb_entry["cryptocom"] = msg.get("price")
        else:
            wb_entry["binance"] = msg.get("price")
        wb_entry["ts"] = time.time()
        
        # === UPDATE PRICE HISTORY (FIFO) ===
        price = safe_float(msg.get("price"))
        if price > 0:
            hist = _price_history.setdefault(symbol, [])
            bounded_append(hist, price, max_size=200)
            
        return # Update papan tulis saja, jangan lanjut eksekusi

    pair_id = msg.get("pairId", msg.get("pair_id", ""))
    if not pair_id: return

    category = get_pair_category(pair_id)
    # === 1.5 SOVEREIGN GATE (Trinity Gate 0) ===
    score = float(msg.get("pumpScore", msg.get("pump_score", 80))) / 100.0
    ev = float(msg.get("ev", 0.15))
    can_enter, reason, allocated_size = _can_enter(pair_id, msg_type, score, ev)
    if not can_enter:
        if "QUARANTINE" not in reason: # Avoid log spam for cooldowns
            print(f"[v7][GATE_REJECT] {pair_id}: {reason}", flush=True)
        return
    
    msg["sovereign_size_idr"] = allocated_size

    # === 2. VALIDASI KILAT (GLOBAL CONSENSUS - BUCKET A) ===
    if category == "LEAD_LAG":
        binance_sym = get_binance_symbol(pair_id)
        if binance_sym:
            wb = _global_whiteboard.get(binance_sym)
            if not wb or not wb.get("binance") or not wb.get("cryptocom"):
                print(f"[KIBOT][VETO] WARN {pair_id} - Missing consensus data, proceeding to AI Gate", flush=True)
            else:
                diff = abs(wb["binance"] - wb["cryptocom"]) / wb["binance"]
                if diff > 0.015:
                    print(f"[KIBOT][VETO] Rejected {pair_id} - Consensus failed (Spread {diff:.2%})", flush=True)
                    return

        # BTC Regime Guard
        if _market_regime == "BREAKDOWN_PANIC":
            print(f"[KIBOT][VETO] Rejected {pair_id} - Market Regime Panic", flush=True)
            return

    # === 3. GATE 1: DYNAMIC THRESHOLD & RISK LADDER ===
    risk_mode = _metrics["risk_mode"]
    if risk_mode == "HARD_STOP": return

    score = raw_score * _score_multiplier
    min_score = 55 if category == "INDODAX_ONLY" else 45

    # Defensive Mode: Bucket B Disabled
    if risk_mode == "DEFENSIVE" and category == "INDODAX_ONLY":
        return

    if score < min_score:
        return

    # === GATE 2: PORTFOLIO & CAPACITY ===
    can_open, reason = portfolio_manager.can_open(pair_id, category)
    if not can_open: return

    # === GATE 3: CONVICTION SCORE (BUCKET B) ===
    if category == "INDODAX_ONLY":
        snapshot = _load_indodax_ticker_snapshot()
        ticker = snapshot.get(pair_id)
        if not ticker: return

        # Fresh Technical Data
        candles = fetch_candles(pair_id, tf=15, count=25)
        closes = [c["c"] for c in candles]
        volumes = [c["v"] for c in candles]
        depth = fetch_order_book_depth(pair_id)

        analysis = ConvictionScoreCalculator.compute(pair_id, ticker, closes, volumes, depth)
        if analysis["recommendation"] != "ENTER":
            print(f"[KIBOT][BUCKET_B] {pair_id} Rejected: {analysis['blocks']}", flush=True)
            return

        msg.update(analysis) # merge results

    # === GATE 4: WHAT-IF & KELLY SIZING ===
    current_equity = _get_total_equity_estimate() or 0.0
    available_budget = portfolio_manager.get_available_budget(current_equity)

    # Enforce Bucket B 60% Deployment Cap (40% reserve)
    if category == "INDODAX_ONLY":
        available_budget = min(available_budget, current_equity * 0.50 * 0.60) # 60% of 50% allocation

    sim = simulate_what_if(
        pair_id, available_budget,
        target_pct=msg.get("target_pct", 0.025),
        trailing_stop_pct=msg.get("trailing_stop_pct", 0.05),
        use_market_entry=(raw_score >= 80)
    )

    if sim["decision"] == "SKIP":
        _metric_inc("whatif_skips_today")
        return

    # Kelly Sizing
    budget_idr = min(available_budget, current_equity * sim["kelly_f"])

    if budget_idr < PORTFOLIO_CONFIG["min_budget_idr"]:
        return

    # === EXECUTE ENTRY ===
    _metric_inc("whatif_enters_today")
    trade_id = trade_logger.record_entry(
        pair_id, float(msg.get("price", 0)), budget_idr,
        category, msg.get("pump_phase", "MID"), score,
        "MARKET" if sim.get("use_market_entry") else "LIMIT",
        "AGGRESSIVE" if category != "INDODAX_ONLY" else "STABLE"
    )

    portfolio_manager.open_position(
        pair_id, float(msg.get("price", 0)), budget_idr, category,
        phase=msg.get("pump_phase", "MID")
    )

    _broadcast_udp({
        "kind": "lead_lag_breakout",
        "msgType": "SMART_ENTRY",
        "pairId": pair_id,
        "price": msg.get("price"),
        "budget_idr": budget_idr,
        "orderType": "MARKET" if sim["use_market"] else "LIMIT",
        "category": "AGGRESSIVE" if category != "INDODAX_ONLY" else "STABLE",
        "confidence": float(msg.get("pumpScore", msg.get("pump_score", 0.70))),
        "expectedNetPct": float(msg.get("target_pct", 0.025)),
        "shortTermReturnPct": float(msg.get("pump_24h_pct", 0.0)),
        "sentAtEpochMs": int(time.time() * 1000),
        "expiresAtEpochMs": int((time.time() + 60) * 1000),
        "traceId": trade_id,
        "senderBotId": "kibot_manager_trinity"
    })

def _process_local_signal(msg: dict):
    """Handle signals from the local Indodax anomaly engine."""
    pair_id = str(msg.get("pairId") or msg.get("pair") or msg.get("symbol") or "").lower().strip()
    if not pair_id:
        return

    price = float(msg.get("price") or 0.0)
    if price <= 0:
        snapshot = _load_indodax_ticker_snapshot()
        ticker = snapshot.get(pair_id, {})
        price = float(ticker.get("last") or 0.0)
    if price <= 0:
        return

    raw_score = float(
        msg.get("score")
        or msg.get("conviction")
        or msg.get("pumpScore")
        or msg.get("pump_score")
        or 0.0
    )
    if raw_score <= 1.0:
        raw_score *= 100.0

    # Enrich signal for multi-position vetting
    refined = {
        "source": "KIBOT_LOCAL_ENGINE",
        "type": "LOCAL_PUMP_SIGNAL",
        "pairId": pair_id,
        "price": price,
        "pumpScore": raw_score,
        "reason": msg.get("reason", "Local anomaly detected"),
        "pump_phase": "EARLY", # Local signals are by definition early
        "target_pct": 0.035,   # Conservative target for local anomalies
        "trailing_stop_pct": 0.02,
        "timestamp": msg.get("timestamp", time.time())
    }
    _process_signal_multipos(refined)

def _check_portfolio_pnl():
    """Monitor positions via Trinity What-If logic."""
    equity = _get_total_equity_estimate() or 0.0
    daily_pnl = (portfolio_manager.realized_pnl_today / equity) if equity > 0 else 0.0

    for pair_id, pos in list(portfolio_manager.positions.items()):
        try:
            snapshot = _load_indodax_ticker_snapshot()
            ticker = snapshot.get(pair_id, {})
            price_now = float(ticker.get("last", 0.0))
            if price_now <= 0: continue

            pos.update_price(price_now)
            pnl_pct = pos.profit_pct

            # Decide via What-If logic
            if pnl_pct > 0:
                decision = what_if_untung_banyak(pnl_pct, equity)
            else:
                decision = what_if_rugi(pnl_pct, equity, daily_pnl)

            if decision["action"] in ("CUT_LOSS_NOW", "EXIT_NOW", "HARD_STOP_ALL"):
                # Find matching trade log entry via Learning Engine
                open_trade = trade_logger.get_open_trade_for_pair(pair_id)
                trade_id = open_trade["trade_id"] if open_trade else "unknown"

                trade_logger.record_exit(trade_id, price_now, decision["reason"])
                portfolio_manager.close_position(pair_id, price_now, decision["reason"])

                _broadcast_udp({
                    "msgType": "SMART_EXIT",
                    "pairId": pair_id,
                    "reason": f"TRINITY_{decision['action']}",
                    "orderType": "MARKET" if decision.get("use_market") else "LIMIT",
                    "traceId": trade_id
                })
            elif decision["action"] == "TIGHTEN_TRAILING":
                # Update local position stop level logic
                pass

        except Exception as e:
            print(f"[TRINITY][MONITOR] {pair_id} err: {e}", flush=True)


def run_discovery_loop():
    """AI-CMS discovery every 6 hours."""
    while not _shutdown_event.is_set():
        try:
            asyncio.run(run_ai_coin_discovery())
        except Exception as e:
            print(f"[KIBOT][AI-CMS] Discovery loop error: {e}", flush=True)
        if _shutdown_event.wait(timeout=21600): break

def run_portfolio_monitor_loop():
    """Real-time portfolio monitoring every 30s."""
    while not _shutdown_event.is_set():
        try:
            _check_portfolio_pnl()
        except Exception as e:
            print(f"[KIBOT][PORTFOLIO] Monitor loop error: {e}", flush=True)
        if _shutdown_event.wait(timeout=60): break  # Increased from 30s to 60s

def run_local_signal_engine_manager():
    """Starts and monitors the kibot_local_signal.py script."""
    import subprocess
    cmd = [sys.executable, str(Path(__file__).parent / "kibot_local_signal.py")]
    print(f"[KIBOT][SIGNAL-MGR] Starting local signal engine: {' '.join(cmd)}", flush=True)

    while not _shutdown_event.is_set():
        try:
            # We want to catch the output, so we use Popen
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )

            # Print output in real-time
            for line in proc.stdout:
                if line.strip():
                    print(f"[SIGNAL-PROC] {line.strip()}", flush=True)
                if _shutdown_event.is_set():
                    proc.terminate()
                    break

            proc.wait()
            if not _shutdown_event.is_set():
                print(f"[KIBOT][SIGNAL-MGR] Signal engine exited with code {proc.returncode}. Restarting in 5s...", flush=True)
                time.sleep(5)
        except Exception as e:
            print(f"[KIBOT][SIGNAL-MGR] Manager error: {e}. Restarting in 10s...", flush=True)
            time.sleep(10)


import math

def _fetch_candles_indodax(pair_id: str, tf: int = 15, count: int = 20) -> list[dict]:
    import urllib.request, json
    base = pair_id.replace("_idr","").upper()
    symbol = f"{base}/IDR"
    now = int(time.time())
    from_ts = now - (tf * 60 * count)
    url = (f"https://indodax.com/tradingview/history_v2"
           f"?symbol={symbol}&tf={tf}&from={from_ts}&to={now}")
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        candles = []
        times = data.get("t", [])
        opens = data.get("o", data.get("Open", []))
        highs = data.get("h", data.get("High", []))
        lows  = data.get("l", data.get("Low", []))
        closes = data.get("c", data.get("Close", []))
        if not times or len(times) == 0:
            return []
        for i in range(len(times)):
            candles.append({
                "t": times[i], "o": float(opens[i]),
                "h": float(highs[i]), "l": float(lows[i]),
                "c": float(closes[i])
            })
        return candles
    except Exception as e:
        print(f"[CANDLE] {pair_id}: {e}", flush=True)
        return []

def calculate_bollinger_bands(data_in: str | list, period: int = 20, std_dev: float = 2.0, window: int = None) -> Any:
    """
    Calculates Bollinger Bands. 
    Supports:
    1. data_in as string (pair_id) -> fetches candles (cached/network).
    2. data_in as list (prices) -> calculates from list.
    """
    if window is not None: period = window # Support legacy 'window' arg
    
    if isinstance(data_in, list):
        if len(data_in) < period:
            return (0.0, 0.0, 0.0) if window else None
        closes = data_in[-period:]
        sma = sum(closes) / period
        variance = sum((c - sma) ** 2 for c in closes) / period
        std = math.sqrt(variance)
        if window: # Match line 8153 expectation: return tuple
             return sma + (std_dev * std), sma, sma - (std_dev * std)
        return {
            "upper": sma + (std_dev * std),
            "middle": sma,
            "lower": sma - (std_dev * std),
            "std": std
        }

    pair_id = data_in
    candles = _fetch_candles_indodax(pair_id, tf=15, count=period + 5)
    if len(candles) < period:
        return None
    closes = [c["c"] for c in candles[-period:]]
    sma = sum(closes) / period
    variance = sum((c - sma) ** 2 for c in closes) / period
    std = math.sqrt(variance)
    return {
        "upper": sma + (std_dev * std),
        "middle": sma,
        "lower": sma - (std_dev * std),
        "std": std,
        "pair": pair_id
    }

def analyze_indodax_only(pair_id: str, ticker: dict, bb: dict) -> dict:
    """
    Analisis koin Indodax-only tanpa lead-lag signal.
    Return: entry recommendation berdasarkan pure technicals.
    """
    price     = float(ticker.get("last", 0))
    vol_1h    = float(ticker.get("vol_idr_1h", 0))
    vol_24h   = float(ticker.get("vol_idr", 0))
    high_24h  = float(ticker.get("high", price))
    low_24h   = float(ticker.get("low", price))

    score = 0.0
    reasons = []

    # === VOLUME ANOMALY ===
    # Koin indodax-only sering pump karena volume spike organik lokal
    avg_vol_per_hour = vol_24h / 24
    vol_ratio_1h = vol_1h / max(avg_vol_per_hour, 1)

    if vol_ratio_1h >= 5.0:
        score += 30
        reasons.append(f"VOLUME SPIKE EKSTREM: {vol_ratio_1h:.1f}x avg")
    elif vol_ratio_1h >= 3.0:
        score += 22
        reasons.append(f"Volume spike kuat: {vol_ratio_1h:.1f}x avg")
    elif vol_ratio_1h >= 2.0:
        score += 12
        reasons.append(f"Volume spike moderate: {vol_ratio_1h:.1f}x avg")
    else:
        score += 0
        reasons.append(f"Volume normal: {vol_ratio_1h:.1f}x avg")

    # Volume minimum untuk masuk
    if vol_24h < 100_000_000:  # < 100M IDR
        score -= 25
        reasons.append(f"Volume terlalu kecil: Rp{vol_24h/1e9:.2f}B")

    # === BB POSITION ===
    if bb:
        bb_pct = (price - bb["lower"]) / max(bb["upper"] - bb["lower"], 0.001)
        if bb_pct < 0.40:
            score += 25
            reasons.append(f"Di bawah BB middle ({bb_pct:.0%}) — banyak ruang")
        elif bb_pct < 0.65:
            score += 16
            reasons.append(f"BB mid zone ({bb_pct:.0%})")
        elif bb_pct > 0.92:
            score -= 15
            reasons.append(f"OVERBOUGHT BB ({bb_pct:.0%})")

    # === PUMP PHASE ===
    pos_in_range = (price - low_24h) / max(high_24h - low_24h, 0.001)
    if pos_in_range < 0.35:
        score += 20
        reasons.append(f"EARLY phase ({pos_in_range:.0%} dari range)")
    elif pos_in_range < 0.60:
        score += 14
        reasons.append(f"MID phase ({pos_in_range:.0%} dari range)")
    elif pos_in_range > 0.88:
        score -= 18
        reasons.append(f"LATE/PEAK ({pos_in_range:.0%}) — risiko tinggi")

    # === SPREAD CHECK (indodax-only biasanya spread lebar) ===
    bid = float(ticker.get("buy", price * 0.99))
    ask = float(ticker.get("sell", price * 1.01))
    spread_pct = (ask - bid) / max(bid, 0.001)

    if spread_pct > 0.05:  # > 5% spread
        score -= 20
        reasons.append(f"SPREAD LEBAR: {spread_pct:.1%} — exit sulit")
    elif spread_pct > 0.02:
        score -= 8
        reasons.append(f"Spread medium: {spread_pct:.1%}")

    # === MINIMUM SCORE UNTUK INDODAX-ONLY ===
    # Lebih ketat dari lead-lag karena tidak ada konfirmasi Binance
    min_score = 55  # Lebih tinggi dari lead-lag (45)

    recommendation = "ENTER" if score >= min_score else "SKIP"
    if pos_in_range > 0.88:
        recommendation = "SKIP"  # Override — terlambat

    return {
        "pair_id": pair_id,
        "category": "INDODAX_ONLY",
        "score": round(score, 1),
        "recommendation": recommendation,
        "phase": ("EARLY" if pos_in_range < 0.35
                  else "MID" if pos_in_range < 0.60
                  else "LATE" if pos_in_range < 0.88 else "PEAK"),
        "vol_ratio": round(vol_ratio_1h, 2),
        "bb_position": bb_pct if bb else None,
        "spread_pct": round(spread_pct, 4),
        "reasoning": " | ".join(reasons[:4]),
    }

DISCOVERY_PROMPT = """
Kamu adalah crypto market analyst untuk trading bot Indonesia.
Tugas: Identifikasi koin yang SEDANG atau AKAN SEGERA pump di Indodax.

Cari dan analisis:
1. Koin baru listing di Indodax dalam 7 hari terakhir
2. Koin yang sedang ramai di Twitter/X Indonesia dengan tag #Indodax
3. Koin yang volume Indodax naik > 200% dari kemarin
4. Koin yang ada di Binance dan harganya mulai naik (lead-lag candidate)
5. Meme coin atau AI token yang viral di Solana ecosystem

Untuk setiap koin yang ditemukan, berikan:
- symbol (contoh: "PIPPIN")
- indodax_pair (contoh: "pippin_idr" — HANYA jika ada di Indodax)
- binance_pair (contoh: "PIPPINUSDT" — HANYA jika ada di Binance spot)
- category: "LEAD_LAG" / "INDODAX_ONLY" / "FUTURES_ONLY"
- reason: kenapa menarik (max 30 kata)
- urgency: "NOW" / "WATCH" / "MONITOR"

Format respons HANYA JSON array, tidak ada teks lain:
[{"symbol":"XXX","indodax_pair":"xxx_idr","binance_pair":null,"category":"INDODAX_ONLY","reason":"...","urgency":"WATCH"}]

Batasan:
- Jangan rekomendasikan koin yang tidak ada di Indodax
- Jangan rekomendasikan koin dengan volume < 50M IDR/hari
- Jangan rekomendasikan koin yang sudah pump > 80% dalam 24 jam
- Selalu berikan data faktual, bukan spekulasi
"""

async def run_ai_coin_discovery():
    """
    Jalankan AI untuk cari koin baru/sedang ramai.
    Math sistem yang decide apakah worth masuk.
    """
    import json

    # Coba semua AI provider (fallback chain)
    discovery_result = None
    for provider in ["groq", "openrouter", "cohere", "gemini"]:
        try:
            # Note: call_ai_provider must be defined in this script
            raw = await call_ai_provider(provider, DISCOVERY_PROMPT)
            # Parse JSON dari response
            # Strip markdown kalau ada
            clean = raw.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()

            coins = json.loads(clean)
            if isinstance(coins, list) and len(coins) > 0:
                discovery_result = coins
                print(f"[AI-CMS] {provider} found {len(coins)} new candidates", flush=True)
                break
        except Exception as e:
            # print(f"[AI-CMS] {provider} failed: {e}")
            continue

    if not discovery_result:
        print("[AI-CMS] No discovery result — using existing pair list", flush=True)
        return

    # Validasi setiap koin yang ditemukan AI
    validated_new = []
    for coin in discovery_result:
        pair_id = coin.get("indodax_pair", "")
        if not pair_id or not pair_id.endswith("_idr"):
            continue

        # Cek apakah ada di Indodax live
        # Note: fetch_indodax_ticker must be defined
        ticker = await fetch_indodax_ticker(pair_id)
        if not ticker:
            continue

        vol_24h = float(ticker.get("vol_idr", 0))
        if vol_24h < 50_000_000:
            continue

        category = coin.get("category", "INDODAX_ONLY")
        binance_pair = coin.get("binance_pair")

        # Lead-lag removed (Binance disabled)

        # Update local pairs
        if category == "INDODAX_ONLY":
            if pair_id not in INDODAX_ONLY_PAIRS:
                INDODAX_ONLY_PAIRS.append(pair_id)
                print(f"[AI-CMS] NEW local pair: {pair_id}", flush=True)

        validated_new.append({
            "pair_id": pair_id,
            "category": category,
            "reason": coin.get("reason", "AI discovered"),
            "urgency": coin.get("urgency", "WATCH"),
            "vol_24h": vol_24h,
        })

    if validated_new:
        # Telegram report
        msg = f"🤖 [AI-CMS] {len(validated_new)} koin baru ditemukan:\n"
        for c in validated_new[:5]:
            urgency_emoji = "🔥" if c["urgency"] == "NOW" else "👀"
            msg += (f"{urgency_emoji} {c['pair_id'].replace('_idr','').upper()}: "
                    f"{c['reason']}\n")
        _telegram_send(msg)

        # Jika ada koin dengan urgency NOW → langsung masuk queue screening
        # Note: _priority_scan_queue must exist or be handled
        urgent = [c for c in validated_new if c["urgency"] == "NOW"]
        if urgent:
            print(f"[AI-CMS] {len(urgent)} URGENT coins → priority queue", flush=True)
            for c in urgent:
                # Fallback to simple set if queue doesn't exist
                if 'priority_scan_queue' in globals():
                    priority_scan_queue.add(c["pair_id"])


_bb_cache = {}
_screen_cache = []
_last_screen_time = 0.0

# HTTP state cache untuk menghindari blocking di /api/state handler
_http_state_cache = {}
_http_state_cache_ts = 0.0
_http_state_cache_lock = threading.RLock()

def _http_state_cache_refresh_loop() -> None:
    """Background thread yang terus refresh cache setiap 1 detik (non-blocking dengan executor)"""
    global _http_state_cache, _http_state_cache_ts, _http_state_cache_lock
    print("[KIBOT][HTTP_CACHE] Cache refresh thread started", flush=True)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="http-snapshot-")
    while not _shutdown_event.is_set():
        try:
            # Run snapshot generation in separate thread (executor)
            future = executor.submit(_http_state_payload)
            snapshot = future.result(timeout=5.0)  # 5 second timeout
            
            with _http_state_cache_lock:
                _http_state_cache = snapshot
                _http_state_cache_ts = time.time()
            time.sleep(1.0)
        except Exception as e:
            print(f"[KIBOT][HTTP_CACHE][ERROR] {e}", flush=True)
            time.sleep(2.0)

def screen_all_pairs() -> list[dict]:
    import urllib.request, json

    INDODAX_TICKERS_URL = "https://indodax.com/api/tickers"
    try:
        with urllib.request.urlopen(INDODAX_TICKERS_URL, timeout=10) as r:
            data = json.loads(r.read())
        tickers = data.get("tickers", data)
    except Exception as e:
        print(f"[SCREEN] Cannot fetch tickers: {e}", flush=True)
        return []

    candidates = []
    for pair_id, ticker in tickers.items():
        try:
            if not pair_id.endswith("_idr"): continue

            vol_24h = float(ticker.get("vol_idr", 0))
            if vol_24h < 50_000_000: continue

            price = float(ticker.get("last", 0))
            high = float(ticker.get("high", price))
            low = float(ticker.get("low", price))
            if price <= 0: continue

            mid_24h = (high + low) / 2
            pump_24h_pct = (price - low) / max(low, 0.001) * 100
            if pump_24h_pct > 80: continue

            binance_sym = get_binance_symbol(pair_id)

            bb = _bb_cache.get(pair_id)
            if not bb:
                bb = calculate_bollinger_bands(pair_id)
                if bb: _bb_cache[pair_id] = bb

            bb_pos = 0.5
            if bb:
                bb_range = bb["upper"] - bb["lower"]
                if bb_range > 0: bb_pos = (price - bb["lower"]) / bb_range

            if bb_pos > 0.92: continue

            score = 0
            if vol_24h > 500_000_000: score += 25
            elif vol_24h > 200_000_000: score += 15
            else: score += 5

            position_in_range = (price - low) / max(high - low, 0.001)
            if position_in_range < 0.4: score += 25
            elif position_in_range < 0.65: score += 18
            elif position_in_range < 0.85: score += 8
            else: score -= 10

            if bb_pos < 0.5: score += 20
            elif bb_pos < 0.75: score += 12

            if binance_sym: score += 10
            if score < 45: continue

            candidates.append({
                "pair_id": pair_id, "score": score, "price": price,
                "vol_24h": vol_24h, "pump_24h_pct": pump_24h_pct,
                "position_in_range": position_in_range, "bb_position": bb_pos,
                "has_binance": bool(binance_sym), "binance_symbol": binance_sym,
            })
        except Exception as e:
            pass

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:15]

@dataclass
class TrailingConfig:
    phase: str
    activation_pct: float
    callback_pct: float
    partial_tp_pct: float
    partial_tp_size: float

TRAILING_CONFIGS = {
    "EARLY": TrailingConfig("EARLY", 0.02, 0.015, 0.04, 0.3),
    "MID":   TrailingConfig("MID",   0.015, 0.012, 0.03, 0.4),
    "LATE":  TrailingConfig("LATE",  0.01, 0.01, 0.02, 0.5),
}

def update_trailing_stop(pair_id: str, price_now: float, phase: str = "MID"):
    """
    Update trailing stop logic.
    Tightens stop as profit grows.
    """
    if pair_id not in _active_trails:
        return None

    trail = _active_trails[pair_id]
    entry_price = trail["entry_price"]
    current_profit_pct = (price_now - entry_price) / entry_price

    # Update high water mark
    if price_now > trail["max_price"]:
        trail["max_price"] = price_now

    config = TRAILING_CONFIGS.get(phase, TRAILING_CONFIGS["MID"])

    # Check Partial Take Profit
    if not trail.get("partial_tp_done") and current_profit_pct >= config.partial_tp_trigger:
        print(f"[KIBOT][TRAIL] {pair_id} Partial TP Triggered at {current_profit_pct:.2%}", flush=True)
        # In actual exec, this would call smart_exit(pair_id, size=config.partial_tp_size)
        trail["partial_tp_done"] = True
        return "PARTIAL_TP"

    # Dynamic trailing adjustment
    # Semakin tinggi profit, semakin ketat trailnya
    dynamic_callback = config.callback_pct
    if current_profit_pct > 0.05:
        dynamic_callback *= 0.8 # Tighten by 20%
    if current_profit_pct > 0.10:
        dynamic_callback *= 0.6 # Tighten by 40%

    stop_price = trail["max_price"] * (1 - dynamic_callback)

    if price_now <= stop_price:
        print(f"[KIBOT][TRAIL] {pair_id} Stop Hit! Exit at {price_now} (Profit: {current_profit_pct:.2%})", flush=True)
        return "EXIT_NOW"

    return None

def _get_position_size_pct(kelly_recommended: float) -> float:
    """Modul 4: Dynamic Sizing"""
    size_pct = kelly_recommended * TRADING_CAPITAL_PCT
    return max(0.01, min(size_pct, 1.0))

def smart_entry(pair_id: str, analysis: PumpAnalysis, budget_idr: float, trace_id: str):
    """
    Decide between MARKET or LIMIT entry based on pump phase.
    """
    if _WHATIF_AVAILABLE:
        try:
            tf = analyze_timeframes(pair_id)
            eq = tf.entry_quality()
            if eq not in ["A", "A-", "B"]:
                print(f"[KIBOT][SMART_ENTRY] Multi-Timeframe Score {eq} for {pair_id} is too weak. Aborting entry.", flush=True)
                return

            # Fetch Kelly size from What-If logic
            import json
            try:
                whatif_data = json.load(open("state/whatif_results.json"))
                pair_sim = whatif_data.get("results", {}).get(pair_id, {})
                kelly_size = pair_sim.get("kellySizeRecommended", 0.05)
                adj_pct = _get_position_size_pct(kelly_size)
                budget_idr = budget_idr * adj_pct
            except Exception:
                pass

        except Exception as e:
            print(f"[KIBOT][SMART_ENTRY] Analysis error: {e}", flush=True)

    # Sizing constraints
    if budget_idr < MIN_POSITION_IDR:
        print(f"[KIBOT][SMART_ENTRY] Budget {budget_idr} below min position {MIN_POSITION_IDR}. Aborting.", flush=True)
        return
    budget_idr = min(budget_idr, MAX_POSITION_IDR)
    use_market = False
    if analysis.legitimacy_score >= 85 and analysis.pump_phase == "EARLY":
        use_market = True
        print(f"[KIBOT][SMART_ENTRY] Urgent High-Confidence EARLY pump. Using MARKET for {pair_id}", flush=True)
    elif analysis.legitimacy_score >= 70:
        use_market = True
        print(f"[KIBOT][SMART_ENTRY] High-Confidence pump. Using MARKET for {pair_id}", flush=True)
    else:
        print(f"[KIBOT][SMART_ENTRY] Moderate-Confidence. Using LIMIT at mid-price for {pair_id}", flush=True)

    msg = {
        "msgType": "DETECTOR_HIT",
        "kind": "lead_lag_breakout",
        "pairId": pair_id,
        "traceId": trace_id,
        "budgetIdr": budget_idr,
        "use_market": use_market,
        "phase": analysis.pump_phase,
        "legitimacy_score": analysis.legitimacy_score,
        "expectedNetPct": analysis.exit_target_pct,
        "trailingStopPct": analysis.stop_loss_pct,
        "confidence": analysis.legitimacy_score / 100.0,
        "senderBotId": "kibot_trinity_v5"
    }
    _broadcast_udp(msg)

def smart_exit(pair_id: str, reason: str, trace_id: str, size_multiplier: float = 1.0):
    """
    Decide between MARKET or LIMIT exit based on urgency.
    """
    use_market = False
    if "emergency" in reason.lower() or "stop_hit" in reason.lower():
        use_market = True
        print(f"[KIBOT][SMART_EXIT] Urgent exit ({reason}). Using MARKET for {pair_id}", flush=True)

    msg = {
        "msgType": "EMERGENCY_VETO_SELL",
        "kind": "lead_lag_breakout",
        "pairId": pair_id,
        "traceId": trace_id,
        "use_market": use_market,
        "reason": reason,
        "size_multiplier": size_multiplier,
        "senderBotId": "kibot_trinity_v5"
    }
    _broadcast_udp(msg)

def run_30min_math_review():
    """
    Mathematical review of session performance v6.0.
    Adjusts trading aggressiveness based on yield.
    """
    global _last_math_review_at, _math_review_last_action, _math_review_last_reason

    now = time.time()
    if (now - _last_math_review_at) < 1800:
        return

    _last_math_review_at = now
    if not _math_review_trade_journal:
        return

    print("[KIBOT][MATH] Running 30-minute performance review...", flush=True)

    wins = [t for t in _math_review_trade_journal if t["gross_pnl_pct"] > 0]
    win_rate = len(wins) / len(_math_review_trade_journal)
    avg_pnl = sum(t["gross_pnl_pct"] for t in _math_review_trade_journal) / len(_math_review_trade_journal)

    report = (
        f"📊 TRINITY MATH REVIEW (30m)\n"
        f"Trades: {len(_math_review_trade_journal)}\n"
        f"Win Rate: {win_rate:.1%}\n"
        f"Avg PnL: {avg_pnl:.2%}\n"
    )

    action = "HOLD"
    reason = "Normal performance"

    if win_rate < 0.40 and len(_math_review_trade_journal) >= 5:
        action = "TIGHTEN"
        reasonArr = "Win rate low, raising legitimacy threshold +5"
        # In actual exec, we would modify a global threshold
        report += "⚠️ Performance low. Tightening filters.\n"
    elif win_rate > 0.70:
        action = "RELAX"
        reason = "Performance excellent, maintaining aggressive entry"
        report += "🔥 Performance excellent. System optimized.\n"

    _math_review_last_action = action
    _math_review_last_reason = reason
    _telegram_send(report)

    # Reset journal for next 30m
    _math_review_trade_journal.clear()

def _is_one_shot_eligible(msg: Dict[str, Any], score: float) -> bool:

    if _one_shot_used_today or _full_stop_active:
        return False
    signal_age_ms = float(msg.get("signalAgeMs") or msg.get("signal_age_ms") or 999.0)
    has_volume_spike = bool(msg.get("volumeSpike") or msg.get("volume_spike") or False)
    confidence = float(msg.get("confidence") or 0.0)
    return signal_age_ms < 200 and score >= 8.0 and has_volume_spike and confidence >= 0.80


def _activate_one_shot(pair_id: str, budget_idr: float) -> float:
    global _one_shot_used_today
    equity = _get_total_equity_estimate() or budget_idr
    max_budget = equity * 0.20
    actual_budget = min(budget_idr, max_budget)
    _one_shot_used_today = True
    _telegram_send(
        f"⚡ ONE_SHOT ACTIVATED: {pair_id}\n"
        f"Budget: Rp{actual_budget:,.0f} (max 20% equity)\n"
        f"Jika gagal, FULL_STOP sampai midnight WIB"
    )
    return actual_budget


def _record_one_shot_result(pnl_idr: float) -> None:
    global _one_shot_result, _full_stop_active
    if pnl_idr > 0:
        _one_shot_result = "WIN"
        _full_stop_active = False
        _telegram_send(f"✅ ONE_SHOT WIN +Rp{pnl_idr:,.0f}. Kembali ke WARNING mode.")
    else:
        _one_shot_result = "LOSS"
        _full_stop_active = True
        _telegram_send(f"🛑 ONE_SHOT FAILED Rp{pnl_idr:,.0f}. FULL_STOP aktif sampai midnight WIB.")


def _daily_reset_extra_state() -> None:
    global _one_shot_used_today, _one_shot_result, _full_stop_active, _last_math_review_at
    _one_shot_used_today = False
    _one_shot_result = None
    _full_stop_active = False
    _last_math_review_at = 0.0


def _record_trade_result(pair_id: str, *, gross_pnl_pct: float, entry_time: float) -> None:
    pair_key = pair_id.lower().strip()
    if not pair_key:
        pair_key = "unknown"
    _math_review_trade_journal.append(
        {
            "pair": pair_key,
            "gross_pnl_pct": float(gross_pnl_pct),
            "entry_time": float(entry_time),
        }
    )
    if _one_shot_used_today and _one_shot_result is None:
        _record_one_shot_result(gross_pnl_pct)
    if len(_math_review_trade_journal) > 500:
        del _math_review_trade_journal[:-500]


def _safe_isoformat(epoch_seconds: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(epoch_seconds if epoch_seconds is not None else time.time(), tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _env_first(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return default

# Configuration Constants (Initialized via _init_config)
SUPABASE_URL = ""
SUPABASE_ANON_KEY = ""
SUPABASE_SERVICE_ROLE_KEY = ""
SUPABASE_KEY = ""
SUPABASE_USER_EMAIL = ""
SUPABASE_USER_PASSWORD = ""
TIMEOUT = 12.0
UDP_BIND_HOST = "0.0.0.0"
UDP_BIND_PORT = 9998
KiBot_UDP_HOST = "127.0.0.1"
KiBot_UDP_PORT = 9999
MANAGER_HEARTBEAT_INTERVAL_SEC = 1.0
TAKER_FEE_PCT = 0.51
STALE_SIGNAL_ABORT_MS = 800
FOMO_GUARD_PCT = 15.0

def _init_config():
    global SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_KEY
    global SUPABASE_USER_EMAIL, SUPABASE_USER_PASSWORD, TIMEOUT
    global UDP_BIND_HOST, UDP_BIND_PORT, KiBot_UDP_HOST, KiBot_UDP_PORT
    global MANAGER_HEARTBEAT_INTERVAL_SEC
    global TAKER_FEE_PCT, STALE_SIGNAL_ABORT_MS, FOMO_GUARD_PCT

    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY or ""
    SUPABASE_USER_EMAIL = os.getenv("SUPABASE_USER_EMAIL", "")
    SUPABASE_USER_PASSWORD = os.getenv("SUPABASE_USER_PASSWORD", "")
    TIMEOUT = float(os.getenv("KIBOT_MANAGER_HTTP_TIMEOUT_SEC", "12"))
    UDP_BIND_HOST = os.getenv("KIBOT_MANAGER_UDP_BIND_HOST", "127.0.0.1")
    UDP_BIND_PORT = int(os.getenv("KIBOT_MANAGER_UDP_BIND_PORT", "9998"))
    KiBot_UDP_HOST = os.getenv("KiBot_UDP_HOST", "127.0.0.1")
    KiBot_UDP_PORT = int(os.getenv("KiBot_UDP_PORT", "9999"))
    MANAGER_HEARTBEAT_INTERVAL_SEC = float(os.getenv("KIBOT_MANAGER_HEARTBEAT_INTERVAL_SEC", "1.0"))
    TAKER_FEE_PCT = float(os.getenv("KiBot_TAKER_FEE_PCT", "0.51"))
    STALE_SIGNAL_ABORT_MS = int(os.getenv("KIBOT_STALE_SIGNAL_MS", "800"))
    FOMO_GUARD_PCT = float(os.getenv("KIBOT_FOMO_GUARD_PCT", "15.0"))

_init_config()
FOMO_LIMIT_CORRECTION_PCT = float(os.getenv("KIBOT_FOMO_LIMIT_CORRECTION_PCT", "4.0"))
COINGECKO_BASE = os.getenv("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3")
NEWS_SCAN_INTERVAL_SEC = int(os.getenv("KIBOT_NEWS_SCAN_INTERVAL_SEC", "45"))
BINANCE_ANNOUNCEMENT_RSS = os.getenv(
    "BINANCE_ANNOUNCEMENT_RSS",
    "https://www.binance.com/en/support/announcement/rss",
)
COINGECKO_NEWS_FEED = os.getenv(
    "COINGECKO_NEWS_FEED",
    "https://www.coingecko.com/en/rss",
)
POST_MORTEM_ENABLED = os.getenv("KIBOT_POST_MORTEM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
POST_MORTEM_API_URL = os.getenv("KIBOT_POST_MORTEM_API_URL", "")
POST_MORTEM_API_KEY = os.getenv("KIBOT_POST_MORTEM_API_KEY", "")
POST_MORTEM_MODEL = os.getenv("KIBOT_POST_MORTEM_MODEL", "llama-3.1-8b-instant")
POST_MORTEM_TIMEOUT_SEC = float(os.getenv("KIBOT_POST_MORTEM_TIMEOUT_SEC", "12"))
AI_APPROVAL_MIN_SCORE = float(os.getenv("AI_APPROVAL_MIN_SCORE", "0.58"))
AI_APPROVAL_MIN_EXPECTED_NET_PCT = float(os.getenv("AI_APPROVAL_MIN_EXPECTED_NET_PCT", "0.0025"))
AI_APPROVAL_INSTANT_MIN_SCORE = 0.52
AI_APPROVAL_INSTANT_MIN_EXPECTED_NET_PCT = 0.0010
INDODAX_TAKER_FEE = float(os.getenv("KIBOT_INDODAX_TAKER_FEE", "0.003"))
INDODAX_MAKER_FEE = float(os.getenv("KIBOT_INDODAX_MAKER_FEE", "0.0015"))
ROUND_TRIP_TAKER_COST = float(os.getenv("KIBOT_ROUND_TRIP_TAKER_COST", "0.006"))
ROUND_TRIP_MAKER_COST = float(os.getenv("KIBOT_ROUND_TRIP_MAKER_COST", "0.003"))
SLIPPAGE_BUFFER = float(os.getenv("KIBOT_SLIPPAGE_BUFFER", "0.002"))
MIN_GROSS_PROFIT_TARGET = float(os.getenv("KIBOT_MIN_GROSS_PROFIT_TARGET", "0.011"))
PARTIAL_TP_TRIGGER = float(os.getenv("KIBOT_PARTIAL_TP_TRIGGER", "0.012"))
PARTIAL_TP_SIZE = float(os.getenv("KIBOT_PARTIAL_TP_SIZE", "0.40"))
TRAILING_STOP_MIN_PCT = float(os.getenv("KIBOT_TRAILING_STOP_MIN_PCT", "0.015"))
POST_MORTEM_BLACKLIST_ENABLED = os.getenv("KIBOT_POST_MORTEM_BLACKLIST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
POST_MORTEM_BLACKLIST_MINUTES = int(os.getenv("KIBOT_POST_MORTEM_BLACKLIST_MINUTES", "30"))
POST_MORTEM_BLACKLIST_NET_LOSS_IDR = float(os.getenv("KIBOT_POST_MORTEM_BLACKLIST_NET_LOSS_IDR", "500"))
POST_MORTEM_BLACKLIST_PNL_PCT = float(os.getenv("KIBOT_POST_MORTEM_BLACKLIST_PNL_PCT", "-1.0"))
MINIMUM_VIABLE_CAPITAL_IDR = float(os.getenv("KIBOT_MINIMUM_VIABLE_CAPITAL_IDR", "0"))
MINIMUM_POSITION_SIZE_IDR = float(os.getenv("KIBOT_MINIMUM_POSITION_SIZE_IDR", "10000"))
MAXIMUM_POSITION_SIZE_IDR = float(os.getenv("KIBOT_MAXIMUM_POSITION_SIZE_IDR", "15000"))
MAXIMUM_ACTIVE_POSITIONS = int(os.getenv("KIBOT_MAXIMUM_ACTIVE_POSITIONS", "2"))
INDODAX_ALL_IN_TAKER_FEE_PCT = float(os.getenv("KIBOT_INDODAX_ALL_IN_TAKER_FEE_PCT", "0.0055"))
INDODAX_ALL_IN_MAKER_FEE_PCT = float(os.getenv("KIBOT_INDODAX_ALL_IN_MAKER_FEE_PCT", "0.0004"))
INDODAX_LIMIT_FILL_RATE = float(os.getenv("KIBOT_INDODAX_LIMIT_FILL_RATE", "0.70"))
ADAPTIVE_CAPITAL_ENABLED = os.getenv("KIBOT_ADAPTIVE_CAPITAL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
LOCAL_FIRST_STORAGE = os.getenv("KIBOT_LOCAL_FIRST_STORAGE", "true").lower() in {"1", "true", "yes", "on"}
# EMERGENCY SHUTDOWN - Supabase Quota Breach (249% Egress)
SUPABASE_BACKUP_ENABLED = False
LOCAL_FIRST_STORAGE = True
ABSOLUTE_MIN_POSITION_SIZE_IDR = float(os.getenv("KIBOT_ABSOLUTE_MIN_POSITION_SIZE_IDR", str(MINIMUM_POSITION_SIZE_IDR)))
ADAPTIVE_MICRO_MAX_POSITION_PCT = float(os.getenv("KIBOT_ADAPTIVE_MICRO_MAX_POSITION_PCT", "0.18"))
ADAPTIVE_BUILDUP_MAX_POSITION_PCT = float(os.getenv("KIBOT_ADAPTIVE_BUILDUP_MAX_POSITION_PCT", "0.15"))
ADAPTIVE_NORMAL_MAX_POSITION_PCT = float(os.getenv("KIBOT_ADAPTIVE_NORMAL_MAX_POSITION_PCT", "0.12"))
ADAPTIVE_EXPANSION_MAX_POSITION_PCT = float(os.getenv("KIBOT_ADAPTIVE_EXPANSION_MAX_POSITION_PCT", "0.10"))
ADAPTIVE_FREE_CASH_BUFFER_PCT = float(os.getenv("KIBOT_ADAPTIVE_FREE_CASH_BUFFER_PCT", "0.35"))
ADAPTIVE_RECOVERY_MAX_POSITION_PCT = float(os.getenv("KIBOT_ADAPTIVE_RECOVERY_MAX_POSITION_PCT", "0.10"))
MICRO_ACCOUNT_MIN_ORDER_BUFFER_PCT = float(os.getenv("KIBOT_MICRO_ACCOUNT_MIN_ORDER_BUFFER_PCT", "1.15"))
MICRO_ACCOUNT_FREE_CASH_BUFFER_PCT = float(os.getenv("KIBOT_MICRO_ACCOUNT_FREE_CASH_BUFFER_PCT", "0.50"))
MICRO_ACCOUNT_MAX_RISK_PCT = float(os.getenv("KIBOT_MICRO_ACCOUNT_MAX_RISK_PCT", "0.40"))
MATH_REVIEW_MIN_TRADES = int(os.getenv("KIBOT_MATH_REVIEW_MIN_TRADES", "3"))
MATH_REVIEW_SMALL_LOSS_GRACE_PCT = float(os.getenv("KIBOT_MATH_REVIEW_SMALL_LOSS_GRACE_PCT", "0.01"))
SURVIVAL_MODE = os.getenv("KIBOT_SURVIVAL_MODE", "true").lower() in {"1", "true", "yes", "on"}
SURVIVAL_MODE_EQUITY_THRESHOLD_IDR = float(os.getenv("KIBOT_SURVIVAL_MODE_EQUITY_THRESHOLD_IDR", "200000"))
SURVIVAL_ALLOWED_PAIRS = tuple(
    pair.strip().lower()
    for pair in os.getenv(
        "KIBOT_SURVIVAL_ALLOWED_PAIRS",
        "xlm_idr,doge_idr,xrp_idr,trx_idr,ada_idr,bnb_idr,enj_idr,fun_idr,arb_idr,inj_idr,ondo_idr,wld_idr,tia_idr,ethfi_idr,sol_idr,near_idr,hbar_idr,link_idr,atom_idr,avax_idr,ton_idr,sui_idr,pol_idr,ldo_idr,op_idr,render_idr,grt_idr,lunc_idr,pepe_idr,shib_idr,bonk_idr,wif_idr,floki_idr,bome_idr,cat_idr,fartcoin_idr",
    ).split(",")
    if pair.strip()
)
SURVIVAL_MIN_DAILY_VOLUME_IDR = float(os.getenv("KIBOT_SURVIVAL_MIN_DAILY_VOLUME_IDR", "500000000"))
SURVIVAL_MAX_SPREAD_PCT = float(os.getenv("KIBOT_SURVIVAL_MAX_SPREAD_PCT", "0.008"))
SURVIVAL_MAX_SLIPPAGE_PCT = float(os.getenv("KIBOT_SURVIVAL_MAX_SLIPPAGE_PCT", "0.010"))
SURVIVAL_TARGET_PROFIT_PCT = float(os.getenv("KIBOT_SURVIVAL_TARGET_PROFIT_PCT", "0.025"))
SURVIVAL_HARD_STOP_PCT = float(os.getenv("KIBOT_SURVIVAL_HARD_STOP_PCT", "0.01"))
CAPITAL_BUCKET_NORMAL_THRESHOLD_IDR = float(os.getenv("KIBOT_CAPITAL_BUCKET_NORMAL_THRESHOLD_IDR", "100000"))
CAPITAL_BUCKET_CONSERVATIVE_THRESHOLD_IDR = float(os.getenv("KIBOT_CAPITAL_BUCKET_CONSERVATIVE_THRESHOLD_IDR", str(MINIMUM_VIABLE_CAPITAL_IDR)))
CAPITAL_BUCKET_EXPANSION_THRESHOLD_IDR = float(os.getenv("KIBOT_CAPITAL_BUCKET_EXPANSION_THRESHOLD_IDR", "300000"))
CAPITAL_BUCKET_FULL_EXPANSION_THRESHOLD_IDR = float(os.getenv("KIBOT_CAPITAL_BUCKET_FULL_EXPANSION_THRESHOLD_IDR", "750000"))

PAIR_CONFIG: Dict[str, Dict[str, Any]] = {
    "xlm_idr": {"tier": "A", "max_size_idr": 15000.0, "min_target_profit_pct": 0.020, "max_spread_pct": 0.010, "max_slippage_pct": 0.012},
    "doge_idr": {"tier": "A", "max_size_idr": 15000.0, "min_target_profit_pct": 0.020, "max_spread_pct": 0.010, "max_slippage_pct": 0.012},
    "xrp_idr": {"tier": "A", "max_size_idr": 15000.0, "min_target_profit_pct": 0.020, "max_spread_pct": 0.010, "max_slippage_pct": 0.012},
    "trx_idr": {"tier": "A", "max_size_idr": 15000.0, "min_target_profit_pct": 0.020, "max_spread_pct": 0.012, "max_slippage_pct": 0.012},
    "ada_idr": {"tier": "A", "max_size_idr": 15000.0, "min_target_profit_pct": 0.020, "max_spread_pct": 0.012, "max_slippage_pct": 0.012},
    "bnb_idr": {"tier": "B", "max_size_idr": 12000.0, "min_target_profit_pct": 0.025, "max_spread_pct": 0.015, "max_slippage_pct": 0.015},
    "enj_idr": {"tier": "B", "max_size_idr": 12000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "fun_idr": {"tier": "B", "max_size_idr": 12000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "arb_idr": {"tier": "B", "max_size_idr": 12000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "inj_idr": {"tier": "B", "max_size_idr": 12000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "ondo_idr": {"tier": "B", "max_size_idr": 12000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "wld_idr": {"tier": "B", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "tia_idr": {"tier": "B", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "ethfi_idr": {"tier": "B", "max_size_idr": 10000.0, "min_target_profit_pct": 0.035, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "sol_idr": {"tier": "B", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "near_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "hbar_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "link_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.025, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "atom_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.025, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "avax_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.025, "max_spread_pct": 0.018, "max_slippage_pct": 0.018},
    "ton_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "sui_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "pol_idr": {"tier": "C", "max_size_idr": 10000.0, "min_target_profit_pct": 0.030, "max_spread_pct": 0.020, "max_slippage_pct": 0.020},
    "ldo_idr": {"tier": "C", "max_size_idr": 8000.0, "min_target_profit_pct": 0.035, "max_spread_pct": 0.022, "max_slippage_pct": 0.022},
    "op_idr": {"tier": "C", "max_size_idr": 8000.0, "min_target_profit_pct": 0.035, "max_spread_pct": 0.022, "max_slippage_pct": 0.022},
    "render_idr": {"tier": "C", "max_size_idr": 8000.0, "min_target_profit_pct": 0.035, "max_spread_pct": 0.022, "max_slippage_pct": 0.022},
    "grt_idr": {"tier": "C", "max_size_idr": 8000.0, "min_target_profit_pct": 0.035, "max_spread_pct": 0.022, "max_slippage_pct": 0.022},
    "lunc_idr": {"tier": "C", "max_size_idr": 6000.0, "min_target_profit_pct": 0.040, "max_spread_pct": 0.025, "max_slippage_pct": 0.025},
    "pepe_idr": {"tier": "D", "max_size_idr": 6000.0, "min_target_profit_pct": 0.040, "max_spread_pct": 0.025, "max_slippage_pct": 0.025},
    "shib_idr": {"tier": "D", "max_size_idr": 6000.0, "min_target_profit_pct": 0.040, "max_spread_pct": 0.025, "max_slippage_pct": 0.025},
    "bonk_idr": {"tier": "D", "max_size_idr": 6000.0, "min_target_profit_pct": 0.045, "max_spread_pct": 0.028, "max_slippage_pct": 0.028},
    "wif_idr": {"tier": "D", "max_size_idr": 6000.0, "min_target_profit_pct": 0.045, "max_spread_pct": 0.028, "max_slippage_pct": 0.028},
    "floki_idr": {"tier": "D", "max_size_idr": 5000.0, "min_target_profit_pct": 0.045, "max_spread_pct": 0.030, "max_slippage_pct": 0.030},
    "bome_idr": {"tier": "D", "max_size_idr": 5000.0, "min_target_profit_pct": 0.050, "max_spread_pct": 0.030, "max_slippage_pct": 0.030},
    "cat_idr": {"tier": "D", "max_size_idr": 5000.0, "min_target_profit_pct": 0.050, "max_spread_pct": 0.030, "max_slippage_pct": 0.030},
    "fartcoin_idr": {"tier": "D", "max_size_idr": 5000.0, "min_target_profit_pct": 0.055, "max_spread_pct": 0.035, "max_slippage_pct": 0.035},
}


def _get_pair_config(pair_id: str) -> Dict[str, Any]:
    return dict(PAIR_CONFIG.get(str(pair_id or "").lower().strip(), {"tier": "C", "max_size_idr": 0.0, "min_target_profit_pct": SURVIVAL_TARGET_PROFIT_PCT, "max_spread_pct": SURVIVAL_MAX_SPREAD_PCT, "max_slippage_pct": SURVIVAL_MAX_SLIPPAGE_PCT}))


def _target_profit_pct_for_pair(pair_id: str) -> float:
    return float(_get_pair_config(pair_id).get("min_target_profit_pct", SURVIVAL_TARGET_PROFIT_PCT))


def _capital_bucket_tiers(equity_idr: Optional[float] = None) -> List[str]:
    equity = float(equity_idr if equity_idr is not None else (_get_total_equity_estimate() or 0.0))
    if equity < CAPITAL_BUCKET_NORMAL_THRESHOLD_IDR:
        return ["A", "B", "C", "D"]
    if equity < CAPITAL_BUCKET_CONSERVATIVE_THRESHOLD_IDR:
        return ["A"]
    if equity < CAPITAL_BUCKET_EXPANSION_THRESHOLD_IDR:
        return ["A", "B", "C"]
    if equity < CAPITAL_BUCKET_FULL_EXPANSION_THRESHOLD_IDR:
        return ["A", "B", "C", "D"]
    return ["A", "B", "C", "D"]


def _capital_risk_multiplier(equity_idr: Optional[float] = None) -> float:
    equity = float(equity_idr if equity_idr is not None else (_get_total_equity_estimate() or 0.0))
    if equity < CAPITAL_BUCKET_NORMAL_THRESHOLD_IDR:
        return 0.35
    if equity < CAPITAL_BUCKET_CONSERVATIVE_THRESHOLD_IDR:
        return 0.50
    if equity < CAPITAL_BUCKET_EXPANSION_THRESHOLD_IDR:
        return 0.70
    if equity < CAPITAL_BUCKET_FULL_EXPANSION_THRESHOLD_IDR:
        return 0.85
    return 1.0


# === KiBot HEALTH MONITORING ===
KiBot_HEARTBEAT_TIMEOUT_SEC = 15.0
_last_KiBot_heartbeat_at: float = 0.0
_KiBot_healthy: bool = True

def _check_KiBot_health() -> bool:
    """Checks if KiBot (Tokyo Node) is healthy based on heartbeats."""
    global _KiBot_healthy, _last_KiBot_heartbeat_at
    now = time.time()
    if _last_KiBot_heartbeat_at == 0.0:
        return True
    # If we haven't received a heartbeat in 3x timeout, mark as unhealthy
    if now - _last_KiBot_heartbeat_at > (KiBot_HEARTBEAT_TIMEOUT_SEC * 3):
        if _KiBot_healthy:
            # Avoid spamming but log the transition
            if _last_KiBot_heartbeat_at > 0: # Only log if we once had a heartbeat
                print(f"[v7][HEALTH_ALARM] KiBot heartbeat timeout (last={_last_KiBot_heartbeat_at}, now={now})", flush=True)
            _KiBot_healthy = False
    return _KiBot_healthy


DAILY_SUMMARY_ENABLED = os.getenv("KIBOT_DAILY_SUMMARY_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
CORRELATION_ENABLED = os.getenv("KIBOT_CORRELATION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
CORRELATION_INTERVAL_SEC = int(os.getenv("KIBOT_CORRELATION_INTERVAL_SEC", "1800"))
CORRELATION_API_URL = os.getenv("KIBOT_CORRELATION_API_URL", POST_MORTEM_API_URL)
CORRELATION_API_KEY = os.getenv("KIBOT_CORRELATION_API_KEY", POST_MORTEM_API_KEY)
CORRELATION_MODEL = os.getenv("KIBOT_CORRELATION_MODEL", POST_MORTEM_MODEL)
CORRELATION_TIMEOUT_SEC = float(os.getenv("KIBOT_CORRELATION_TIMEOUT_SEC", "20"))
AI_ROUTER_ENABLED = os.getenv("KIBOT_AI_ROUTER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
AI_PROVIDER_ORDER = [
    token.strip().lower()
    for token in os.getenv(
        "KIBOT_AI_PROVIDER_ORDER",
        "groq,openrouter,ollama,cohere,gemini",
    ).split(",")
    if token.strip()
]
AI_REQUEST_TIMEOUT_SEC = float(os.getenv("KIBOT_AI_REQUEST_TIMEOUT_SEC", "18"))
AI_PROVIDER_DEFAULT_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_DEFAULT_COOLDOWN_SEC", "600"))
AI_PROVIDER_NETWORK_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_NETWORK_COOLDOWN_SEC", "180"))
AI_PROVIDER_RATE_LIMIT_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_RATE_LIMIT_COOLDOWN_SEC", "3600"))
AI_PROVIDER_EMPTY_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_EMPTY_COOLDOWN_SEC", "120"))
STATE_ROOT = Path(os.getenv("KIBOT_MANAGER_STATE_DIR", str(Path.cwd() / ".state")))
PROVIDER_STATE_PATH = Path(
    os.getenv("KIBOT_MANAGER_PROVIDER_STATE_FILE", str(STATE_ROOT / "ai_provider_state.json"))
)
RUNTIME_NOTE_PATH = Path(
    os.getenv("KIBOT_MANAGER_RUNTIME_NOTE_FILE", str(STATE_ROOT / "runtime_note.json"))
)
RUNTIME_NOTE_MIN_INTERVAL_SEC = int(os.getenv("KIBOT_MANAGER_RUNTIME_NOTE_MIN_INTERVAL_SEC", "15"))
DAILY_SUMMARY_PATH = Path(os.getenv("KIBOT_MANAGER_DAILY_SUMMARY_FILE", str(STATE_ROOT / "daily_summary.json")))
DAILY_REPORT_PATH = Path(os.getenv("KIBOT_MANAGER_DAILY_REPORT_FILE", str(STATE_ROOT / "daily_report.json")))
DAILY_REPORT_HISTORY_PATH = Path(os.getenv("KIBOT_MANAGER_DAILY_REPORT_HISTORY_FILE", str(STATE_ROOT / "daily_report_history.json")))
LEARNING_REVIEW_PATH = Path(os.getenv("KIBOT_MANAGER_LEARNING_REVIEW_FILE", str(STATE_ROOT / "learning_review.json")))
LEARNING_REVIEW_HISTORY_PATH = Path(os.getenv("KIBOT_MANAGER_LEARNING_REVIEW_HISTORY_FILE", str(STATE_ROOT / "learning_review_history.json")))
PATTERN_LIBRARY_PATH = Path(os.getenv("KIBOT_MANAGER_PATTERN_LIBRARY_FILE", str(STATE_ROOT / "pattern_library.json")))
DECISION_LEDGER_PATH = Path(os.getenv("KIBOT_MANAGER_DECISION_LEDGER_FILE", str(STATE_ROOT / "decision_ledger.jsonl")))
DAILY_CYCLE_STATE_PATH = Path(os.getenv("KIBOT_MANAGER_DAILY_CYCLE_FILE", str(STATE_ROOT / "daily_cycle_state.json")))
TRADE_LOG_RUNTIME_PATH = Path(os.getenv("KIBOT_MANAGER_TRADE_LOG_FILE", str(Path.cwd() / "state/trade_log.jsonl")))
TRADE_SUMMARY_RUNTIME_PATH = Path(os.getenv("KIBOT_MANAGER_TRADE_SUMMARY_FILE", str(Path.cwd() / "state/trade_summary.json")))
PAIR_MEMORY_PATH = Path(os.getenv("KIBOT_MANAGER_PAIR_MEMORY_FILE", str(STATE_ROOT / "pair_memory.json")))
WHATIF_RESULTS_PATH = Path(os.getenv("KIBOT_MANAGER_WHATIF_RESULTS_FILE", str(STATE_ROOT / "whatif_results.json")))
SCANNER_FEED_LOCAL_PATH = Path(
    os.getenv(
        "KIBOT_MANAGER_SCANNER_FEED_FILE",
        str(Path.cwd() / "state" / "scanners" / "global_scanner_feed.json"),
    )
)
REMOTE_SCANNER_FEED_ENABLED = os.getenv("KIBOT_REMOTE_SCANNER_FEED_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
REMOTE_SCANNER_FEED_BOT_ID = os.getenv("KIBOT_REMOTE_SCANNER_FEED_BOT_ID", "KiBot")
REMOTE_SCANNER_FEED_CATEGORY = os.getenv("KIBOT_REMOTE_SCANNER_FEED_CATEGORY", "scanner_feed_cycle")
REMOTE_SCANNER_FEED_POLL_SEC = int(os.getenv("KIBOT_REMOTE_SCANNER_FEED_POLL_SEC", "20"))
REMOTE_SCANNER_FEED_MAX_AGE_SEC = int(os.getenv("KIBOT_REMOTE_SCANNER_FEED_MAX_AGE_SEC", "180"))
REMOTE_SCANNER_FEED_MAX_SIGNALS = int(os.getenv("KIBOT_REMOTE_SCANNER_FEED_MAX_SIGNALS", "24"))
REMOTE_SCANNER_FEED_STATE_PATH = Path(
    os.getenv(
        "KIBOT_REMOTE_SCANNER_FEED_STATE_FILE",
        str(STATE_ROOT / "remote_scanner_feed_state.json"),
    )
)
GOVERNOR_DIRECTIVES_PATH = Path(
    os.getenv(
        "KIBOT_GOVERNOR_FILE",
        str(STATE_ROOT / "governor_directives.json"),
    )
)
GOVERNOR_STATE_PATH = Path(
    os.getenv(
        "KIBOT_GOVERNOR_STATE_FILE",
        str(STATE_ROOT / "governor_state.json"),
    )
)
GOVERNOR_MIN_REFRESH_SEC = int(os.getenv("KIBOT_GOVERNOR_MIN_REFRESH_SEC", "90"))
GOVERNOR_MAX_STALE_SEC = int(os.getenv("KIBOT_GOVERNOR_MAX_STALE_SEC", "900"))
GOVERNOR_EVENT_COOLDOWN_SEC = int(os.getenv("KIBOT_GOVERNOR_EVENT_COOLDOWN_SEC", "120"))
GOVERNOR_FAST_LOOP_SEC = int(os.getenv("KIBOT_GOVERNOR_FAST_LOOP_SEC", "30"))
GOVERNOR_MEDIUM_LOOP_SEC = int(os.getenv("KIBOT_GOVERNOR_MEDIUM_LOOP_SEC", "300"))
PAIR_MEMORY_ROLLING_WINDOW = int(os.getenv("KIBOT_PAIR_MEMORY_ROLLING_WINDOW", "50"))
PAIR_MEMORY_MIN_TRADES_FOR_WINRATE = int(os.getenv("KIBOT_PAIR_MEMORY_MIN_TRADES_FOR_WINRATE", "3"))
AI_BATCH_REVIEW_INTERVAL_SEC = int(os.getenv("KIBOT_AI_BATCH_REVIEW_INTERVAL_SEC", str(6 * 60 * 60)))

OLLAMA_API_KEY = _env_first("OLLAMA_API_KEY", "KIBOT_OLLAMA_GATEWAY_TOKEN")
OLLAMA_MODEL = os.getenv("KIBOT_OLLAMA_MODEL", "qwen3:0.6b")
OLLAMA_API_URL = os.getenv("KIBOT_OLLAMA_BASE_URL", "http://127.0.0.1:11435/api/chat")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_URL = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")

GEMINI_API_KEY = _env_first("GEMINI_API_KEY", "GEMINI_SUPPORT_API_KEY")
GEMINI_MODEL = _env_first("GEMINI_MODEL", "GEMINI_SUPPORT_MODEL", default="gemini-2.0-flash-lite")
GEMINI_API_URL = os.getenv("GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
COHERE_MODEL = os.getenv("COHERE_MODEL", "command-r")
COHERE_API_URL = os.getenv("COHERE_API_URL", "https://api.cohere.com/v2/chat")

BLACKBOX_API_KEY = os.getenv("BLACKBOX_API_KEY", "")
BLACKBOX_MODEL = os.getenv("BLACKBOX_MODEL", "blackboxai/openai/gpt-4o-mini")
BLACKBOX_API_URL = os.getenv("BLACKBOX_API_URL", "https://api.blackbox.ai/v1/chat/completions")

_ai_provider_last_status: Dict[str, Any] = {
    "provider": "",
    "task": "",
    "at_epoch_ms": 0,
    "ok": False,
}
COINGECKO_TRENDING_INTERVAL_SEC = int(os.getenv("KIBOT_COINGECKO_TRENDING_INTERVAL_SEC", "300"))
INDODAX_SUMMARIES_URL = os.getenv("INDODAX_SUMMARIES_URL", "https://indodax.com/api/summaries")
INDODAX_TICKER_CACHE_TTL_SEC = int(os.getenv("KIBOT_INDODAX_TICKER_CACHE_TTL_SEC", "600"))
EMERGENCY_SELL_NEGATIVE_PNL_PCT = float(os.getenv("KIBOT_EMERGENCY_SELL_NEGATIVE_PNL_PCT", "-2.2"))
EMERGENCY_SELL_COOLDOWN_SEC = int(os.getenv("KIBOT_EMERGENCY_SELL_COOLDOWN_SEC", "20"))
API_HEALTH_CHECK_INTERVAL_SEC = float(os.getenv("KIBOT_API_HEALTH_CHECK_INTERVAL_SEC", "15"))
API_HEALTH_FAIL_THRESHOLD = int(os.getenv("KIBOT_API_HEALTH_FAIL_THRESHOLD", "2"))
CONTROL_PLANE_TIMEOUT_SEC = float(os.getenv("KIBOT_CONTROL_PLANE_TIMEOUT_SEC", "3.0"))
CONTROL_PLANE_STALE_SEC = float(os.getenv("KIBOT_CONTROL_PLANE_STALE_SEC", "30"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("KIBOT_DAILY_LOSS_LIMIT_PCT", "0.02"))
WIB_UTC_OFFSET_HOURS = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))
DAILY_GUARD_STATE_PATH = Path(os.getenv("KIBOT_MANAGER_DAILY_GUARD_FILE", str(STATE_ROOT / "daily_guard.json")))
MANAGER_GATE_STATE_PATH = Path(os.getenv("KIBOT_MANAGER_GATE_STATE_FILE", str(STATE_ROOT / "manager_gate.json")))
LOCAL_RUNTIME_STATE_URLS = [
    item.strip()
    for item in os.getenv(
        "KIBOT_MANAGER_RUNTIME_STATE_URLS",
        "http://127.0.0.1:8787/api/state,http://127.0.0.1:8788/api/state",
    ).split(",")
    if item.strip()
]
LEARNING_REVIEW_INTERVAL_SEC = int(os.getenv("KIBOT_LEARNING_REVIEW_INTERVAL_SEC", "1800"))
MIDNIGHT_RESET_RETRY_SEC = int(os.getenv("KIBOT_MIDNIGHT_RESET_RETRY_SEC", "60"))
MIDNIGHT_RESET_ALERT_AFTER_SEC = int(os.getenv("KIBOT_MIDNIGHT_RESET_ALERT_AFTER_SEC", "600"))
EXTERNAL_CASHFLOW_AUTO_DETECT_IDR = float(os.getenv("KIBOT_EXTERNAL_CASHFLOW_AUTO_DETECT_IDR", "10000"))
EXTERNAL_CASHFLOW_AUTO_DETECT_PCT = float(os.getenv("KIBOT_EXTERNAL_CASHFLOW_AUTO_DETECT_PCT", "0.12"))
SAFE_ENTRY_MSG_TYPES = {"DETECTOR_HIT", "INSTANT_BUY_ANOMALY", "LEAD_LAG_SIGNAL"}
EXIT_MSG_TYPES = {"SELL_WALL_SURGE", "MOMENTUM_LOSS", "TRAILING_STOP_HIT", "THESIS_INVALID_EXIT"}
# Maximum size for unbounded caches
_SEEN_NEWS_IDS_MAX_SIZE = int(os.getenv("KIBOT_SEEN_NEWS_IDS_MAX_SIZE", "5000"))
_seen_news_ids: set[str] = set()
_seen_news_ids_timestamps: Dict[str, float] = {}  # Track when IDs were added for TTL cleanup
_indodax_ticker_cache: set[str] = set()
_indodax_ticker_snapshot: Dict[str, Dict[str, Any]] = {}
_indodax_ticker_cache_at: float = 0.0
_coingecko_trending_cache: Dict[str, Any] = {"coins": [], "fetched_at_epoch_ms": 0}
_last_sector_map: Dict[str, list[str]] = {}
_active_positions_cache: Dict[str, Dict[str, Any]] = {}
_emergency_sell_cooldown_until: Dict[str, float] = {}
_last_active_positions_log_at: float = 0.0
_last_runtime_note_write_at: float = 0.0
_recent_runtime_events: List[Dict[str, Any]] = []
_veto_metrics: Dict[str, int] = {"approved": 0, "rejected": 0, "sell_confirmed": 0, "emergency_sell": 0}
_api_fail_streak: int = 0
_api_health_state: str = "HEALTHY"
_control_plane_healthy: bool = True
_control_plane_last_success_at: float = 0.0
_capital_sufficient_since_at: float = 0.0
_normal_mode_promotion_grace_sec: float = float(os.getenv("KIBOT_NORMAL_PROMOTION_GRACE_SEC", "1800"))
_gate_state: Dict[str, Any] = _load_json_file(
    MANAGER_GATE_STATE_PATH,
    {
        "mode": "CONSERVATIVE",
        "entry_state": "HEALTHY",
        "reason": "",
        "updated_at": "",
        "daily_hard_stop": False,
        "daily_hard_stop_reset_at": "",
        "daily_hard_stop_reason": "",
    },
)
_daily_guard_state: Dict[str, Any] = _load_json_file(
    DAILY_GUARD_STATE_PATH,
    {
        "date": "",
        "start_of_day_equity": None,
        "current_equity": None,
        "daily_pnl_pct": None,
        "external_cashflow_idr": 0.0,
        "external_cashflow_detected_at": "",
        "external_cashflow_reason": "",
        "hard_stopped": False,
        "triggered_at": "",
        "reset_at": "",
        "reason": "",
    },
)
_daily_cycle_state: Dict[str, Any] = _load_json_file(
    DAILY_CYCLE_STATE_PATH,
    {
        "active_wib_date": _wib_today_str(),
        "pending_new_date": "",
        "pending_previous_date": "",
        "pending_started_at": "",
        "last_liquidation_emit_at": "",
        "last_daily_report_date": "",
        "last_reset_completed_date": "",
        "alert_sent_for_pending_cycle": False,
    },
)
_pair_memory: Dict[str, Dict[str, Any]] = _load_json_file(PAIR_MEMORY_PATH, {})
_local_runtime_state_cache: Dict[str, Any] = {}
_local_runtime_state_cache_at: float = 0.0
_local_runtime_state_cache_ttl_sec = float(os.getenv("KIBOT_MANAGER_RUNTIME_CACHE_TTL_SEC", "2.5"))


def _clean_pair_memory() -> None:
    invalid_keys = [key for key in _pair_memory.keys() if not key or key.strip().lower() in {"unknown", "null", "none"}]
    if not invalid_keys:
        return
    for key in invalid_keys:
        _pair_memory.pop(key, None)
        print(f"[KIBOT][LEARNING] removed invalid pair_memory key='{key}'", flush=True)
    _write_json_file(PAIR_MEMORY_PATH, _pair_memory)


_clean_pair_memory()


_provider_runtime_state: Dict[str, Dict[str, Any]] = _load_json_file(PROVIDER_STATE_PATH, {})
_pair_cooldown_state: Dict[str, Dict[str, Any]] = _load_json_file(STATE_ROOT / "pair_cooldowns.json", {})
_pair_cooldowns = _pair_cooldown_state
_remote_scanner_feed_state: Dict[str, Any] = _load_json_file(
    REMOTE_SCANNER_FEED_STATE_PATH,
    {
        "last_created_at": "",
        "last_feed_id": "",
        "last_success_at": "",
        "last_poll_at": "",
        "last_error": "",
        "cycles_seen": 0,
        "signals_ingested": 0,
        "recent_signal_ids": [],
    },
)
_governor_directives: Dict[str, Any] = _load_json_file(GOVERNOR_DIRECTIVES_PATH, {})
_governor_state: Dict[str, Any] = _load_json_file(
    GOVERNOR_STATE_PATH,
    {
        "last_refresh_at": "",
        "last_reason": "",
        "last_profile": "",
        "last_provider": "",
        "last_plan_id": "",
        "last_plan_state": "",
        "last_fingerprint": "",
        "last_event_fingerprint": "",
        "refresh_count": 0,
        "last_error": "",
    },
)


def _save_pair_cooldown_state() -> None:
    _write_json_file(STATE_ROOT / "pair_cooldowns.json", _pair_cooldown_state)


def _save_remote_scanner_feed_state() -> None:
    _write_json_file(REMOTE_SCANNER_FEED_STATE_PATH, _remote_scanner_feed_state)


def _save_governor_state() -> None:
    _write_json_file(GOVERNOR_STATE_PATH, _governor_state)


def _save_governor_directives() -> None:
    _write_json_file(GOVERNOR_DIRECTIVES_PATH, _governor_directives)


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = float(default)
    return max(float(minimum), min(float(maximum), numeric))


def _normalize_pair_id(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.endswith("_idr"):
        return raw
    return f"{raw}_idr"


def _unique_text_items(values: Any, *, limit: int = 6, item_limit: int = 120) -> List[str]:
    items: List[str] = []
    if not isinstance(values, (list, tuple, set)):
        return items
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        text = text[:item_limit]
        if text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _default_governor_directives() -> Dict[str, Any]:
    return {
        "plan_id": "fallback-default",
        "plan_generated_at": "",
        "expires_at": "",
        "plan_ttl_sec": 900,
        "plan_state": "ACTIVE",
        "strategy_mode": "NEUTRAL",
        "brain_mode": "CONTROLLED",
        "market_regime": "UNKNOWN",
        "capital_posture": "BALANCED",
        "reason": "default_adaptive_governor",
        "why": ["adaptive default posture"],
        "updated_at": "",
        "provider": "",
        "model": "",
        "confidence": 0.55,
        "effective_confidence": 0.55,
        "confidence_decay_per_hour": 0.08,
        "fallback_if_expired": "SURVIVAL_MODE",
        "what_could_make_this_wrong": [],
        "ops_alerts": [],
        "scanner": {
            "weights": {
                "BINANCE": 0.30,
                "BYBIT": 0.25,
                "KUCOIN": 0.20,
                "CRYPTOCOM": 0.15,
                "MEXC": 0.10,
            },
            "msc_min": 0.60,
        },
        "capital": {
            "ratio": {"LEAD_LAG": 0.50, "LOCAL_PUMP": 0.50},
            "max_per_trade": 0.25,
            "risk_pct_multiplier": 1.0,
            "free_cash_buffer_pct": ADAPTIVE_FREE_CASH_BUFFER_PCT,
            "micro_entry_floor_idr": float(ABSOLUTE_MIN_POSITION_SIZE_IDR),
        },
        "risk": {
            "lock_ratio": 0.30,
            "daily_loss_limit_pct": abs(float(DAILY_LOSS_LIMIT_PCT)) * 100.0,
            "pair_cooldown_minutes": 60,
            "trailing_tightness": "BASE",
        },
        "survival": {
            "equity_threshold_idr": float(SURVIVAL_MODE_EQUITY_THRESHOLD_IDR),
            "allowed_tiers": ["A", "B"],
            "min_target_profit_pct": float(SURVIVAL_TARGET_PROFIT_PCT),
            "max_spread_pct": float(SURVIVAL_MAX_SPREAD_PCT),
            "max_slippage_pct": float(SURVIVAL_MAX_SLIPPAGE_PCT),
        },
        "execution": {
            "focus_pairs": [],
            "avoid_pairs": [],
            "budget_boost": 1.0,
            "focus_boost": 1.0,
        },
        "indodax": {
            "allow_entries": True,
            "max_open_positions": 3,
            "budget_per_trade_idr": 0.0,
            "focus_pairs": [],
            "avoid_pairs": [],
            "preferred_style": "ADAPTIVE_SPOT",
        },
        "polymarket": {
            "allow_execution": True,
            "max_risk_pct": 0.8,
            "focus_markets": [],
        },
    }


def _governor_daily_loss_limit_fraction() -> Optional[float]:
    raw_risk = _governor_directives.get("risk") if isinstance(_governor_directives, dict) else {}
    raw_limit = raw_risk.get("daily_loss_limit_pct") if isinstance(raw_risk, dict) else None
    numeric = _parse_numeric(raw_limit)
    if numeric is None:
        return None
    numeric = abs(float(numeric))
    return numeric / 100.0 if numeric > 0.5 else numeric


def _sanitize_governor_directives(raw: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    defaults = _default_governor_directives()
    capital_profile = context.get("capital_profile") if isinstance(context.get("capital_profile"), dict) else {}
    runtime = context.get("runtime") if isinstance(context.get("runtime"), dict) else {}
    equity_now = max(0.0, float(_parse_numeric(capital_profile.get("equity_idr")) or 0.0))
    capital_mode = str(capital_profile.get("mode") or "NORMAL").upper()
    tiny_account = capital_mode in {"MICRO", "BUILDUP"} or (0.0 < equity_now < 150_000.0)
    plan_generated_at = str(raw.get("plan_generated_at") or raw.get("updated_at") or _safe_isoformat()).strip()
    plan_generated_epoch = _iso_to_epoch(plan_generated_at) or time.time()
    plan_ttl_sec = int(
        _clamp_float(
            raw.get("plan_ttl_sec"),
            180,
            21_600,
            defaults["plan_ttl_sec"],
        )
    )
    expires_at = str(raw.get("expires_at") or "").strip()
    expires_at_epoch = _iso_to_epoch(expires_at)
    if expires_at_epoch <= 0.0 or expires_at_epoch <= plan_generated_epoch:
        expires_at = _safe_isoformat(plan_generated_epoch + plan_ttl_sec)

    strategy_mode = str(raw.get("strategy_mode") or defaults["strategy_mode"]).upper()
    if strategy_mode not in {"DEFENSIVE", "NEUTRAL", "OPPORTUNISTIC"}:
        strategy_mode = "NEUTRAL"
    brain_mode = str(raw.get("brain_mode") or defaults["brain_mode"]).upper()
    if brain_mode not in {"SURVIVAL", "CONTROLLED", "CONTROLLED_AGGRESSIVE", "FULL_ATTACK"}:
        brain_mode = {
            "DEFENSIVE": "SURVIVAL",
            "NEUTRAL": "CONTROLLED",
            "OPPORTUNISTIC": "CONTROLLED_AGGRESSIVE",
        }.get(strategy_mode, defaults["brain_mode"])
    market_regime = str(raw.get("market_regime") or defaults["market_regime"]).upper()
    if market_regime not in {"RISK_OFF", "MIXED", "RISK_ON", "BREAKOUT", "SIDEWAYS", "UNKNOWN"}:
        market_regime = "UNKNOWN"
    capital_posture = str(raw.get("capital_posture") or defaults["capital_posture"]).strip().upper()[:48] or defaults["capital_posture"]
    fallback_if_expired = str(raw.get("fallback_if_expired") or defaults["fallback_if_expired"]).upper()
    if fallback_if_expired not in {"SURVIVAL_MODE", "DEFENSIVE_MODE", "HOLD_LAST"}:
        fallback_if_expired = defaults["fallback_if_expired"]

    weights = {}
    raw_weights = raw.get("scanner", {}).get("weights") if isinstance(raw.get("scanner"), dict) else {}
    if isinstance(raw_weights, dict):
        for key in defaults["scanner"]["weights"].keys():
            numeric = _parse_numeric(raw_weights.get(key))
            if numeric is not None and numeric > 0:
                weights[key] = float(numeric)
    if not weights:
        weights = dict(defaults["scanner"]["weights"])
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        weights = dict(defaults["scanner"]["weights"])
        weight_sum = sum(weights.values())
    weights = {key: round(float(value) / weight_sum, 4) for key, value in weights.items()}

    raw_ratio = raw.get("capital", {}).get("ratio") if isinstance(raw.get("capital"), dict) else {}
    lead_lag_ratio = _clamp_float(
        raw_ratio.get("LEAD_LAG") if isinstance(raw_ratio, dict) else None,
        0.20,
        0.80,
        defaults["capital"]["ratio"]["LEAD_LAG"],
    )
    local_pump_ratio = _clamp_float(
        raw_ratio.get("LOCAL_PUMP") if isinstance(raw_ratio, dict) else None,
        0.20,
        0.80,
        defaults["capital"]["ratio"]["LOCAL_PUMP"],
    )
    ratio_sum = max(lead_lag_ratio + local_pump_ratio, 1e-9)
    ratio = {
        "LEAD_LAG": round(lead_lag_ratio / ratio_sum, 4),
        "LOCAL_PUMP": round(local_pump_ratio / ratio_sum, 4),
    }

    risk_pct_default = defaults["capital"]["risk_pct_multiplier"]
    if tiny_account and strategy_mode == "OPPORTUNISTIC":
        risk_pct_default = 1.05
    elif strategy_mode == "DEFENSIVE":
        risk_pct_default = 0.82
    max_per_trade_default = 0.22 if tiny_account else defaults["capital"]["max_per_trade"]
    if strategy_mode == "DEFENSIVE":
        max_per_trade_default = min(max_per_trade_default, 0.18 if tiny_account else 0.22)
    elif strategy_mode == "OPPORTUNISTIC":
        max_per_trade_default = min(0.30, max_per_trade_default + (0.03 if not tiny_account else 0.01))

    micro_entry_floor_default = float(ABSOLUTE_MIN_POSITION_SIZE_IDR)
    if tiny_account and equity_now > 0:
        micro_entry_floor_default = float(ABSOLUTE_MIN_POSITION_SIZE_IDR)

    trailing_tightness = str(raw.get("risk", {}).get("trailing_tightness") or defaults["risk"]["trailing_tightness"]).upper()
    if trailing_tightness not in {"TIGHTER", "BASE", "LOOSER"}:
        trailing_tightness = "BASE"

    allowed_tiers = raw.get("survival", {}).get("allowed_tiers") if isinstance(raw.get("survival"), dict) else None
    normalized_tiers = [str(item).upper() for item in (allowed_tiers or []) if str(item).upper() in {"A", "B", "C"}]
    if not normalized_tiers:
        normalized_tiers = list(defaults["survival"]["allowed_tiers"])

    focus_pairs = [_normalize_pair_id(item) for item in list(raw.get("execution", {}).get("focus_pairs") or []) if _normalize_pair_id(item)]
    avoid_pairs = [_normalize_pair_id(item) for item in list(raw.get("execution", {}).get("avoid_pairs") or []) if _normalize_pair_id(item)]
    focus_pairs = list(dict.fromkeys([pair for pair in focus_pairs if pair not in avoid_pairs]))[:6]
    avoid_pairs = list(dict.fromkeys(avoid_pairs))[:6]
    raw_indodax = raw.get("indodax") if isinstance(raw.get("indodax"), dict) else {}
    indodax_focus_pairs = [
        _normalize_pair_id(item)
        for item in list(raw_indodax.get("focus_pairs") or focus_pairs)
        if _normalize_pair_id(item)
    ]
    indodax_avoid_pairs = [
        _normalize_pair_id(item)
        for item in list(raw_indodax.get("avoid_pairs") or avoid_pairs)
        if _normalize_pair_id(item)
    ]
    indodax_focus_pairs = list(dict.fromkeys([pair for pair in indodax_focus_pairs if pair not in indodax_avoid_pairs]))[:6]
    indodax_avoid_pairs = list(dict.fromkeys(indodax_avoid_pairs))[:6]
    default_max_positions = 2 if tiny_account else 3
    if brain_mode in {"CONTROLLED_AGGRESSIVE", "FULL_ATTACK"} and not tiny_account:
        default_max_positions = 4 if brain_mode == "CONTROLLED_AGGRESSIVE" else 5
    runtime_positions = len(_extract_state_holdings(runtime)) if isinstance(runtime, dict) else 0
    max_position_hint = float(_parse_numeric(capital_profile.get("max_position_idr")) or 0.0)
    budget_cap_default = round(max_position_hint, 2) if max_position_hint > 0 else 0.0
    raw_polymarket = raw.get("polymarket") if isinstance(raw.get("polymarket"), dict) else {}

    daily_loss_limit_pct = _clamp_float(
        raw.get("risk", {}).get("daily_loss_limit_pct") if isinstance(raw.get("risk"), dict) else None,
        0.9 if tiny_account else 1.2,
        2.2 if tiny_account else 3.5,
        defaults["risk"]["daily_loss_limit_pct"],
    )

    directives = {
        "plan_id": str(raw.get("plan_id") or f"governor-{int(plan_generated_epoch)}")[:80],
        "plan_generated_at": plan_generated_at,
        "expires_at": expires_at,
        "plan_ttl_sec": plan_ttl_sec,
        "plan_state": "ACTIVE",
        "strategy_mode": strategy_mode,
        "brain_mode": brain_mode,
        "market_regime": market_regime,
        "capital_posture": capital_posture,
        "reason": str(raw.get("reason") or defaults["reason"])[:220],
        "why": _unique_text_items(raw.get("why") or [], limit=5, item_limit=140),
        "updated_at": _safe_isoformat(),
        "provider": str(raw.get("provider") or ""),
        "model": str(raw.get("model") or ""),
        "confidence": round(
            _clamp_float(
                raw.get("confidence"),
                0.0,
                1.0,
                defaults["confidence"],
            ),
            4,
        ),
        "effective_confidence": round(
            _clamp_float(
                raw.get("confidence"),
                0.0,
                1.0,
                defaults["confidence"],
            ),
            4,
        ),
        "confidence_decay_per_hour": round(
            _clamp_float(
                raw.get("confidence_decay_per_hour"),
                0.0,
                0.50,
                defaults["confidence_decay_per_hour"],
            ),
            4,
        ),
        "fallback_if_expired": fallback_if_expired,
        "what_could_make_this_wrong": _unique_text_items(
            raw.get("what_could_make_this_wrong") or [],
            limit=6,
            item_limit=160,
        ),
        "ops_alerts": _unique_text_items(raw.get("ops_alerts") or [], limit=6, item_limit=180),
        "scanner": {
            "weights": weights,
            "msc_min": round(
                _clamp_float(
                    raw.get("scanner", {}).get("msc_min") if isinstance(raw.get("scanner"), dict) else None,
                    0.48 if tiny_account else 0.45,
                    0.88,
                    defaults["scanner"]["msc_min"],
                ),
                4,
            ),
        },
        "capital": {
            "ratio": ratio,
            "max_per_trade": round(
                _clamp_float(
                    raw.get("capital", {}).get("max_per_trade") if isinstance(raw.get("capital"), dict) else None,
                    0.08 if tiny_account else 0.10,
                    0.26 if tiny_account else 0.40,
                    max_per_trade_default,
                ),
                4,
            ),
            "risk_pct_multiplier": round(
                _clamp_float(
                    raw.get("capital", {}).get("risk_pct_multiplier") if isinstance(raw.get("capital"), dict) else None,
                    0.55,
                    1.10 if tiny_account else 1.25,
                    risk_pct_default,
                ),
                4,
            ),
            "free_cash_buffer_pct": round(
                _clamp_float(
                    raw.get("capital", {}).get("free_cash_buffer_pct") if isinstance(raw.get("capital"), dict) else None,
                    0.28 if tiny_account else 0.20,
                    0.92,
                    defaults["capital"]["free_cash_buffer_pct"],
                ),
                4,
            ),
            "micro_entry_floor_idr": round(
                _clamp_float(
                    raw.get("capital", {}).get("micro_entry_floor_idr") if isinstance(raw.get("capital"), dict) else None,
                    float(ABSOLUTE_MIN_POSITION_SIZE_IDR),
                    25_000.0,
                    micro_entry_floor_default,
                ),
                2,
            ),
        },
        "risk": {
            "lock_ratio": round(
                _clamp_float(
                    raw.get("risk", {}).get("lock_ratio") if isinstance(raw.get("risk"), dict) else None,
                    0.20,
                    0.60,
                    defaults["risk"]["lock_ratio"],
                ),
                4,
            ),
            "daily_loss_limit_pct": round(daily_loss_limit_pct, 4),
            "pair_cooldown_minutes": int(
                _clamp_float(
                    raw.get("risk", {}).get("pair_cooldown_minutes") if isinstance(raw.get("risk"), dict) else None,
                    15,
                    180,
                    defaults["risk"]["pair_cooldown_minutes"],
                )
            ),
            "trailing_tightness": trailing_tightness,
        },
        "survival": {
            "equity_threshold_idr": round(
                _clamp_float(
                    raw.get("survival", {}).get("equity_threshold_idr") if isinstance(raw.get("survival"), dict) else None,
                    50_000.0,
                    300_000.0,
                    defaults["survival"]["equity_threshold_idr"],
                ),
                2,
            ),
            "allowed_tiers": normalized_tiers,
            "min_target_profit_pct": round(
                _clamp_float(
                    raw.get("survival", {}).get("min_target_profit_pct") if isinstance(raw.get("survival"), dict) else None,
                    0.008,
                    0.050,
                    defaults["survival"]["min_target_profit_pct"],
                ),
                4,
            ),
            "max_spread_pct": round(
                _clamp_float(
                    raw.get("survival", {}).get("max_spread_pct") if isinstance(raw.get("survival"), dict) else None,
                    0.002,
                    0.020,
                    defaults["survival"]["max_spread_pct"],
                ),
                4,
            ),
            "max_slippage_pct": round(
                _clamp_float(
                    raw.get("survival", {}).get("max_slippage_pct") if isinstance(raw.get("survival"), dict) else None,
                    0.002,
                    0.030,
                    defaults["survival"]["max_slippage_pct"],
                ),
                4,
            ),
        },
        "execution": {
            "focus_pairs": focus_pairs,
            "avoid_pairs": avoid_pairs,
            "budget_boost": round(
                _clamp_float(
                    raw.get("execution", {}).get("budget_boost") if isinstance(raw.get("execution"), dict) else None,
                    0.80,
                    1.25,
                    defaults["execution"]["budget_boost"],
                ),
                4,
            ),
            "focus_boost": round(
                _clamp_float(
                    raw.get("execution", {}).get("focus_boost") if isinstance(raw.get("execution"), dict) else None,
                    1.0,
                    1.20,
                    defaults["execution"]["focus_boost"],
                ),
                4,
            ),
        },
        "indodax": {
            "allow_entries": bool(raw_indodax.get("allow_entries", True)),
            "max_open_positions": int(
                _clamp_float(
                    raw_indodax.get("max_open_positions"),
                    max(1, runtime_positions or 1),
                    8,
                    default_max_positions,
                )
            ),
            "budget_per_trade_idr": round(
                _clamp_float(
                    raw_indodax.get("budget_per_trade_idr"),
                    0.0,
                    max(50_000.0, max_position_hint or 500_000.0),
                    budget_cap_default,
                ),
                2,
            ),
            "focus_pairs": indodax_focus_pairs,
            "avoid_pairs": indodax_avoid_pairs,
            "preferred_style": str(raw_indodax.get("preferred_style") or "ADAPTIVE_SPOT")[:48],
        },
        "polymarket": {
            "allow_execution": bool(raw_polymarket.get("allow_execution", True)),
            "max_risk_pct": round(
                _clamp_float(
                    raw_polymarket.get("max_risk_pct"),
                    0.0,
                    5.0,
                    defaults["polymarket"]["max_risk_pct"],
                ),
                4,
            ),
            "focus_markets": _unique_text_items(raw_polymarket.get("focus_markets") or [], limit=6, item_limit=120),
        },
    }
    if not directives["why"]:
        directives["why"] = [directives["reason"]]
    return directives


def _governor_effective_directives() -> Dict[str, Any]:
    merged = _default_governor_directives()
    raw = _governor_directives if isinstance(_governor_directives, dict) else {}
    for section in ("scanner", "capital", "risk", "survival", "execution", "indodax", "polymarket"):
        if isinstance(raw.get(section), dict):
            merged[section].update(raw.get(section) or {})
    for key in (
        "plan_id",
        "plan_generated_at",
        "expires_at",
        "plan_ttl_sec",
        "plan_state",
        "strategy_mode",
        "brain_mode",
        "market_regime",
        "capital_posture",
        "reason",
        "updated_at",
        "provider",
        "model",
        "confidence",
        "effective_confidence",
        "confidence_decay_per_hour",
        "fallback_if_expired",
    ):
        if raw.get(key) not in (None, ""):
            merged[key] = raw.get(key)
    for key in ("why", "what_could_make_this_wrong", "ops_alerts"):
        if isinstance(raw.get(key), list):
            merged[key] = list(raw.get(key) or [])
    generated_epoch = _iso_to_epoch(str(merged.get("plan_generated_at") or merged.get("updated_at") or "")) or 0.0
    expires_epoch = _iso_to_epoch(str(merged.get("expires_at") or "")) or 0.0
    now = time.time()
    age_sec = max(0.0, now - generated_epoch) if generated_epoch > 0 else 0.0
    base_confidence = float(_parse_numeric(merged.get("confidence")) or 0.55)
    decay_per_hour = float(_parse_numeric(merged.get("confidence_decay_per_hour")) or 0.08)
    effective_confidence = max(0.0, min(1.0, base_confidence - ((age_sec / 3600.0) * decay_per_hour)))
    merged["effective_confidence"] = round(effective_confidence, 4)
    merged["plan_age_sec"] = round(age_sec, 2)
    merged["plan_is_expired"] = bool(expires_epoch > 0 and now >= expires_epoch)
    if merged["plan_is_expired"]:
        fallback_mode = str(merged.get("fallback_if_expired") or "SURVIVAL_MODE").upper()
        merged["ops_alerts"] = _unique_text_items(
            list(merged.get("ops_alerts") or []) + [f"governor plan expired -> {fallback_mode.lower()}"],
            limit=6,
            item_limit=180,
        )
        if fallback_mode == "SURVIVAL_MODE":
            merged["plan_state"] = "EXPIRED_SURVIVAL"
            merged["strategy_mode"] = "DEFENSIVE"
            merged["brain_mode"] = "SURVIVAL"
            merged["capital_posture"] = "PRESERVE"
            merged["reason"] = f"expired_plan_survival:{merged.get('reason')}"
            merged["capital"]["risk_pct_multiplier"] = min(
                float(_parse_numeric(merged["capital"].get("risk_pct_multiplier")) or 1.0),
                0.82,
            )
            merged["capital"]["free_cash_buffer_pct"] = max(
                float(_parse_numeric(merged["capital"].get("free_cash_buffer_pct")) or ADAPTIVE_FREE_CASH_BUFFER_PCT),
                0.55,
            )
            merged["execution"]["budget_boost"] = min(
                float(_parse_numeric(merged["execution"].get("budget_boost")) or 1.0),
                0.85,
            )
            merged["execution"]["focus_boost"] = min(
                float(_parse_numeric(merged["execution"].get("focus_boost")) or 1.0),
                1.0,
            )
            merged["indodax"]["allow_entries"] = False
        elif fallback_mode == "DEFENSIVE_MODE":
            merged["plan_state"] = "EXPIRED_DEFENSIVE"
            merged["strategy_mode"] = "DEFENSIVE"
            merged["brain_mode"] = "CONTROLLED"
            merged["capital_posture"] = "PRESERVE"
        else:
            merged["plan_state"] = "EXPIRED_HOLD_LAST"
    else:
        merged["plan_state"] = str(raw.get("plan_state") or merged.get("plan_state") or "ACTIVE")
    return merged


def _pair_memory_brief(*, limit: int = 6) -> Dict[str, Any]:
    ranked: List[Dict[str, Any]] = []
    for pair_id, memory in _pair_memory.items():
        if not pair_id:
            continue
        trade_count = int(memory.get("trade_count") or 0)
        if trade_count <= 0:
            continue
        ranked.append(
            {
                "pair": pair_id,
                "trade_count": trade_count,
                "win_rate": round(_get_pair_win_rate_now(pair_id), 4),
                "avg_slippage_pct": round(_get_pair_avg_slippage(pair_id, fallback=0.0), 4),
                "cooldown": bool(_is_pair_on_cooldown(pair_id)),
                "fake_pump_count": int(memory.get("fake_pump_count") or 0),
            }
        )
    best_pairs = sorted(ranked, key=lambda item: (item["win_rate"], item["trade_count"]), reverse=True)[:limit]
    worst_pairs = sorted(
        ranked,
        key=lambda item: (item["win_rate"], -item["fake_pump_count"], -item["trade_count"]),
    )[:limit]
    return {
        "best_pairs": best_pairs,
        "worst_pairs": worst_pairs,
    }


def _build_governor_context(profile: str = "fast") -> Dict[str, Any]:
    profile = str(profile or "fast").strip().lower()
    brain_snapshot = _brain.snapshot() if hasattr(_brain, "snapshot") else {}
    capital_profile = _adaptive_capital_profile()
    trade_metrics = _get_trade_metrics_today()
    runtime_state = _fetch_local_runtime_state(timeout_sec=0.35, max_cache_age_sec=2.5)
    whatif_payload = _load_json_file(WHATIF_RESULTS_PATH, {})
    learning_review = _load_json_file(LEARNING_REVIEW_PATH, {})
    daily_summary = _load_daily_summary()
    latest_report = _load_json_file(DAILY_REPORT_PATH, {})
    pattern_library = _load_pattern_library()
    pair_memory_brief = _pair_memory_brief(limit=4 if profile == "fast" else 6)
    top_whatif = [
        str(pair).lower()
        for pair in list(whatif_payload.get("topOpportunities") or [])[: (3 if profile == "fast" else 5)]
        if str(pair).strip()
    ]
    remote_summary = {
        "cycles_seen": int(_remote_scanner_feed_state.get("cycles_seen") or 0),
        "signals_ingested": int(_remote_scanner_feed_state.get("signals_ingested") or 0),
        "last_feed_id": str(_remote_scanner_feed_state.get("last_feed_id") or ""),
        "last_success_at": str(_remote_scanner_feed_state.get("last_success_at") or ""),
    }
    polymarket = brain_snapshot.get("polymarket") if isinstance(brain_snapshot.get("polymarket"), dict) else {}
    focus_markets = []
    for item in list(polymarket.get("top_markets") or [])[: (2 if profile == "fast" else 4)]:
        if not isinstance(item, dict):
            continue
        focus_markets.append(
            {
                "question": str(item.get("question") or ""),
                "slug": str(item.get("slug") or ""),
                "score": round(float(item.get("score") or 0.0), 4),
                "execution_style": str(item.get("execution_style") or ""),
            }
        )
    maker_candidates = []
    for item in list(polymarket.get("maker_candidates") or [])[: (1 if profile == "fast" else 3)]:
        if not isinstance(item, dict):
            continue
        maker_candidates.append(
            {
                "question": str(item.get("question") or ""),
                "maker_score": round(float(item.get("maker_score") or 0.0), 4),
                "reward_daily_rate": round(float(item.get("reward_daily_rate") or 0.0), 4),
                "execution_style": str(item.get("execution_style") or ""),
            }
        )
    alpha_candidates = []
    for item in list(polymarket.get("alpha_candidates") or [])[: (1 if profile == "fast" else 3)]:
        if not isinstance(item, dict):
            continue
        alpha_candidates.append(
            {
                "mapped_pair": str(item.get("mapped_pair") or ""),
                "asset": str(item.get("asset") or ""),
                "direction": str(item.get("direction") or ""),
                "alpha_score": round(float(item.get("alpha_score") or 0.0), 4),
                "signal_score": round(float(item.get("signal_score") or 0.0), 4),
            }
        )
    cross_market_bias: Dict[str, Any] = {}
    for asset, item in list((polymarket.get("cross_market_bias") or {}).items())[:4]:
        if not isinstance(item, dict):
            continue
        cross_market_bias[str(asset)] = {
            "direction": str(item.get("direction") or ""),
            "score": round(float(item.get("score") or 0.0), 4),
            "count": int(item.get("count") or 0),
            "mapped_pairs": list(item.get("mapped_pairs") or [])[:2],
        }
    sovereign_review = daily_summary.get("last_sovereign_review") if isinstance(daily_summary.get("last_sovereign_review"), dict) else {}
    market_pulse = brain_snapshot.get("market_pulse") if isinstance(brain_snapshot.get("market_pulse"), dict) else {}
    market_summary = {
        "risk_bias": str(market_pulse.get("risk_bias") or "UNKNOWN").upper(),
        "headline_count": int(market_pulse.get("headline_count") or 0),
        "summary": str(market_pulse.get("summary") or "")[:160],
        "watch_symbols": [str(item).upper() for item in list(market_pulse.get("watch_symbols") or [])[: (2 if profile == "fast" else 4)]],
    }
    performance_summary = {
        "daily_pnl_pct": _daily_guard_state.get("daily_pnl_pct"),
        "hard_stop_active": bool(_daily_guard_state.get("hard_stopped")),
        "total_trades": int(trade_metrics.get("total_trades") or 0),
        "wins": int(trade_metrics.get("wins") or 0),
        "losses": int(trade_metrics.get("losses") or 0),
        "win_rate": round(float(_parse_numeric(trade_metrics.get("win_rate")) or 0.0), 4),
        "ev_per_trade": round(float(_parse_numeric(trade_metrics.get("ev_per_trade")) or 0.0), 4),
        "profit_factor": round(float(_parse_numeric(trade_metrics.get("profit_factor")) or 0.0), 4),
        "whatif_enter_rate": round(
            float(_metrics.get("whatif_enters_today", 0))
            / max(float(_metrics.get("whatif_enters_today", 0)) + float(_metrics.get("whatif_skips_today", 0)), 1.0),
            4,
        ),
        "entries_blocked_brain": int(_metrics.get("entries_blocked_brain", 0)),
        "entries_brain_reduced": int(_metrics.get("entries_brain_reduced", 0)),
    }
    capital_summary = {
        "mode": str(capital_profile.get("mode") or ""),
        "reason": str(capital_profile.get("reason") or ""),
        "equity_idr": round(float(_parse_numeric(capital_profile.get("equity_idr")) or 0.0), 2),
        "free_cash_idr": round(float(_parse_numeric(capital_profile.get("free_cash_idr")) or 0.0), 2),
        "max_position_idr": round(float(_parse_numeric(capital_profile.get("max_position_idr")) or 0.0), 2),
        "min_position_idr": round(float(_parse_numeric(capital_profile.get("min_position_idr")) or 0.0), 2),
        "risk_pct_per_trade": round(float(_parse_numeric(capital_profile.get("risk_pct_per_trade")) or 0.0), 4),
        "daily_loss_limit_pct": round(float(_parse_numeric(capital_profile.get("daily_loss_limit_pct")) or 0.0), 4),
        "trading_allowed": bool(capital_profile.get("trading_allowed")),
        "strategy_mode": str(capital_profile.get("strategy_mode") or ""),
    }
    runtime_connections = runtime_state.get("connections") if isinstance(runtime_state.get("connections"), dict) else {}
    runtime_summary = {
        "node_status": str(runtime_state.get("nodeStatus") or ""),
        "status_message": str(runtime_state.get("statusMessage") or "")[:140],
        "connections": {
            str(name): str(state)
            for name, state in list(runtime_connections.items())[:5]
        },
        "active_pairs": _extract_state_holdings(runtime_state)[: (3 if profile == "fast" else 6)],
    }
    gate_summary = {
        "entry_state": str(_gate_state.get("entry_state") or ""),
        "mode": str(_gate_state.get("mode") or ""),
        "reason": str(_gate_state.get("reason") or "")[:160],
        "control_plane_healthy": bool(_control_plane_healthy),
        "api_fail_streak": int(_api_fail_streak or 0),
    }
    return {
        "governor_profile": profile.upper(),
        "governor_interval_target_sec": GOVERNOR_FAST_LOOP_SEC if profile == "fast" else GOVERNOR_MEDIUM_LOOP_SEC,
        "market": market_summary,
        "ai_critic": brain_snapshot.get("ai_critic") if isinstance(brain_snapshot.get("ai_critic"), dict) else {},
        "performance": performance_summary,
        "capital_profile": capital_summary,
        "trade_metrics": trade_metrics,
        "scanner_feed": remote_summary,
        "polymarket": {
            "ready": polymarket.get("ready"),
            "analysis_ready": polymarket.get("analysis_ready"),
            "execution_enabled": polymarket.get("execution_enabled"),
            "focus_markets": focus_markets,
            "cross_market_bias": cross_market_bias,
            "maker_candidates": maker_candidates,
            "alpha_candidates": alpha_candidates,
            "ops_alerts": list(polymarket.get("ops_alerts") or [])[:4],
        },
        "runtime": runtime_summary,
        "memory": {
            "daily_summary": {
                "coins_bought_today": list(daily_summary.get("coins_bought_today") or [])[:8],
                "loss_blacklist_pairs": list(daily_summary.get("loss_blacklist_pairs") or [])[:8],
                "recent_notes": list(daily_summary.get("recent_notes") or [])[: (2 if profile == "fast" else 5)],
                "last_sovereign_review": {
                    "tomorrow_mode": sovereign_review.get("tomorrow_mode"),
                    "focus_pairs": list(sovereign_review.get("focus_pairs") or [])[:4],
                    "root_causes": list(sovereign_review.get("root_causes") or [])[:3],
                    "parameter_recommendations": list(sovereign_review.get("parameter_recommendations") or [])[:4],
                },
            },
            "learning_review": {
                "summary": learning_review.get("summary"),
                "strategy": learning_review.get("strategy"),
                "lessons": list(learning_review.get("lessons") or [])[: (2 if profile == "fast" else 4)],
                "risks": list(learning_review.get("risks") or [])[: (2 if profile == "fast" else 4)],
            },
            "daily_report": {
                "report_date": latest_report.get("report_date"),
                "daily_pnl_pct": latest_report.get("daily_pnl_pct"),
                "weekly_pnl_pct": latest_report.get("weekly_pnl_pct"),
                "next_strategy": latest_report.get("next_strategy"),
            },
            "pattern_library": {
                "weekly_patterns": list(pattern_library.get("weekly_patterns") or [])[:3],
                "ops_incidents": list(pattern_library.get("ops_incidents") or [])[:3],
            },
        },
        "pair_memory": pair_memory_brief,
        "whatif_top_opportunities": top_whatif,
        "math_review": {
            "last_action": _math_review_last_action,
            "last_reason": _math_review_last_reason,
        },
        "gate": gate_summary,
    }


def _governor_event_fingerprint(context: Dict[str, Any]) -> str:
    payload = {
        "market_risk_bias": str(context.get("market", {}).get("risk_bias") or "UNKNOWN"),
        "capital_mode": str(context.get("capital_profile", {}).get("mode") or "NORMAL"),
        "capital_allowed": bool(context.get("capital_profile", {}).get("trading_allowed")),
        "daily_pnl_bucket": round(float(_parse_numeric(context.get("performance", {}).get("daily_pnl_pct")) or 0.0), 3),
        "hard_stop": bool(context.get("performance", {}).get("hard_stop_active")),
        "entry_state": str(context.get("gate", {}).get("entry_state") or ""),
        "top_whatif": list(context.get("whatif_top_opportunities") or [])[:3],
        "remote_feed": str(context.get("scanner_feed", {}).get("last_feed_id") or ""),
        "runtime_connections": context.get("runtime", {}).get("connections") if isinstance(context.get("runtime"), dict) else {},
        "loss_blacklist": list(context.get("memory", {}).get("daily_summary", {}).get("loss_blacklist_pairs") or [])[:3],
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _fallback_governor_raw(context: Dict[str, Any], *, failure_reason: str, profile: str = "fast") -> Dict[str, Any]:
    profile = str(profile or "fast").strip().lower()
    capital_profile = context.get("capital_profile") if isinstance(context.get("capital_profile"), dict) else {}
    gate = context.get("gate") if isinstance(context.get("gate"), dict) else {}
    market = context.get("market") if isinstance(context.get("market"), dict) else {}
    polymarket = context.get("polymarket") if isinstance(context.get("polymarket"), dict) else {}
    runtime = context.get("runtime") if isinstance(context.get("runtime"), dict) else {}
    memory = context.get("memory") if isinstance(context.get("memory"), dict) else {}
    top_whatif = [str(item).lower() for item in list(context.get("whatif_top_opportunities") or []) if str(item).strip()]
    blacklist = [
        _normalize_pair_id(item)
        for item in list(memory.get("daily_summary", {}).get("loss_blacklist_pairs") or [])
        if _normalize_pair_id(item)
    ][:6]
    risk_bias = str(market.get("risk_bias") or "UNKNOWN").upper()
    trading_allowed = bool(capital_profile.get("trading_allowed"))
    hard_stop = bool(context.get("performance", {}).get("hard_stop_active"))
    gate_healthy = bool(gate.get("control_plane_healthy", True)) and str(gate.get("entry_state") or "HEALTHY") == "HEALTHY"
    scanner_only = _is_scanner_only_node()
    daily_pnl_pct = float(_parse_numeric(context.get("performance", {}).get("daily_pnl_pct")) or 0.0)

    strategy_mode = "NEUTRAL"
    brain_mode = "CONTROLLED"
    capital_posture = "BALANCED"
    confidence = 0.48
    why: List[str] = []
    if scanner_only:
        strategy_mode = "DEFENSIVE"
        capital_posture = "PRESERVE"
        confidence = 0.44
        why.append("scanner-only node uses passive sovereign fallback")
    elif hard_stop or not trading_allowed or not gate_healthy or daily_pnl_pct <= -0.010:
        strategy_mode = "DEFENSIVE"
        brain_mode = "SURVIVAL"
        capital_posture = "PRESERVE"
        confidence = 0.42
        why.append("capital or gate health requires defensive fallback")
    elif risk_bias == "RISK_ON" and daily_pnl_pct >= -0.003 and top_whatif:
        strategy_mode = "OPPORTUNISTIC"
        brain_mode = "CONTROLLED_AGGRESSIVE"
        capital_posture = "DEPLOY_70PCT"
        confidence = 0.58
        why.append("risk-on market with actionable opportunities")
    else:
        why.append("AI unavailable, using heuristic sovereign fallback")

    max_position_idr = float(_parse_numeric(capital_profile.get("max_position_idr")) or 0.0)
    free_cash_buffer_pct = 0.55 if strategy_mode == "DEFENSIVE" else ADAPTIVE_FREE_CASH_BUFFER_PCT
    risk_multiplier = 0.82 if strategy_mode == "DEFENSIVE" else (1.05 if strategy_mode == "OPPORTUNISTIC" else 1.0)
    cross_market_bias = polymarket.get("cross_market_bias") if isinstance(polymarket.get("cross_market_bias"), dict) else {}
    bullish_assets = [
        asset.upper()
        for asset, detail in cross_market_bias.items()
        if isinstance(detail, dict)
        and asset.lower() in {"btc", "eth", "sol", "xrp", "doge", "bnb", "ada", "sui", "ltc"}
        and str(detail.get("direction") or "").upper() == "LONG"
        and float(_parse_numeric(detail.get("score")) or 0.0) >= 0.55
    ]
    focus_pairs = [_normalize_pair_id(item) for item in top_whatif[:4] if _normalize_pair_id(item)]
    if bullish_assets and not focus_pairs:
        focus_pairs = [_normalize_pair_id(f"{asset.lower()}_idr") for asset in bullish_assets[:3]]
    if not focus_pairs and risk_bias == "RISK_ON":
        focus_pairs = [_normalize_pair_id(item) for item in ["btc_idr", "sol_idr"]]
    elif not focus_pairs:
        focus_pairs = [_normalize_pair_id(item) for item in ["btc_idr"]]
    focus_pairs = [pair for pair in focus_pairs if pair not in blacklist][:4]
    allow_entries = trading_allowed and not hard_stop and gate_healthy and not scanner_only
    return {
        "plan_id": f"fallback-{int(time.time())}",
        "plan_generated_at": _safe_isoformat(),
        "plan_ttl_sec": 360 if profile == "fast" else 900,
        "reason": f"ai_governor_fallback:{profile}:{failure_reason}",
        "why": why,
        "brain_mode": brain_mode,
        "market_regime": risk_bias if risk_bias in {"RISK_OFF", "MIXED", "RISK_ON"} else "UNKNOWN",
        "capital_posture": capital_posture,
        "confidence": confidence,
        "confidence_decay_per_hour": 0.06,
        "fallback_if_expired": "SURVIVAL_MODE",
        "what_could_make_this_wrong": [
            "scanner signal quality degrades",
            "control plane or API state becomes stale",
            "market correlation shifts abruptly",
        ],
        "ops_alerts": [
            f"ai governor fallback active on {str(runtime.get('node_status') or 'node')}",
        ],
        "strategy_mode": strategy_mode,
        "scanner": {
            "weights": {
                "BINANCE": 0.32,
                "BYBIT": 0.24,
                "KUCOIN": 0.20,
                "CRYPTOCOM": 0.14,
                "MEXC": 0.10,
            },
            "msc_min": 0.68 if strategy_mode == "DEFENSIVE" else 0.60,
        },
        "capital": {
            "ratio": {"LEAD_LAG": 0.55, "LOCAL_PUMP": 0.45},
            "max_per_trade": 0.18 if strategy_mode == "DEFENSIVE" else 0.24,
            "risk_pct_multiplier": risk_multiplier,
            "free_cash_buffer_pct": free_cash_buffer_pct,
            "micro_entry_floor_idr": float(capital_profile.get("min_position_idr") or ABSOLUTE_MIN_POSITION_SIZE_IDR),
        },
        "risk": {
            "lock_ratio": 0.36 if strategy_mode == "DEFENSIVE" else 0.30,
            "daily_loss_limit_pct": abs(float(_current_daily_loss_limit_pct())) * 100.0,
            "pair_cooldown_minutes": 60 if strategy_mode == "DEFENSIVE" else 45,
            "trailing_tightness": "TIGHTER" if strategy_mode == "DEFENSIVE" else "BASE",
        },
        "survival": {
            "equity_threshold_idr": float(SURVIVAL_MODE_EQUITY_THRESHOLD_IDR),
            "allowed_tiers": ["A", "B"],
            "min_target_profit_pct": float(SURVIVAL_TARGET_PROFIT_PCT),
            "max_spread_pct": float(SURVIVAL_MAX_SPREAD_PCT),
            "max_slippage_pct": float(SURVIVAL_MAX_SLIPPAGE_PCT),
        },
        "execution": {
            "focus_pairs": focus_pairs,
            "avoid_pairs": blacklist,
            "budget_boost": 0.90 if strategy_mode == "DEFENSIVE" else 1.0,
            "focus_boost": 1.03 if strategy_mode == "OPPORTUNISTIC" else 1.0,
        },
        "indodax": {
            "allow_entries": allow_entries,
            "max_open_positions": 2 if strategy_mode == "DEFENSIVE" else 3,
            "budget_per_trade_idr": max_position_idr,
            "focus_pairs": focus_pairs,
            "avoid_pairs": blacklist,
            "preferred_style": "FALLBACK_DISCIPLINED_SPOT",
        },
        "polymarket": {
            "allow_execution": bool(polymarket.get("ready")) and not scanner_only,
            "max_risk_pct": 0.5 if strategy_mode == "DEFENSIVE" else 0.8,
            "focus_markets": _unique_text_items(polymarket.get("top_markets") or polymarket.get("focus_markets") or [], limit=4, item_limit=120),
        },
        "provider": "heuristic",
        "model": "local-fallback",
        "refresh_profile": profile.upper(),
    }


def _refresh_governor_directives(*, force: bool = False, reason: str = "loop", profile: str = "fast") -> Optional[Dict[str, Any]]:
    global _governor_directives
    profile = str(profile or "fast").strip().lower()
    now = time.time()
    last_refresh_at = _iso_to_epoch(str(_governor_state.get("last_refresh_at") or "")) or 0.0
    context = _build_governor_context(profile=profile)
    event_fingerprint = _governor_event_fingerprint(context)
    stale = (now - last_refresh_at) >= GOVERNOR_MAX_STALE_SEC
    changed = event_fingerprint != str(_governor_state.get("last_event_fingerprint") or "")
    if not force:
        if not stale and not changed:
            return _governor_effective_directives()
        if changed and (now - last_refresh_at) < GOVERNOR_EVENT_COOLDOWN_SEC:
            return _governor_effective_directives()
        if (now - last_refresh_at) < GOVERNOR_MIN_REFRESH_SEC:
            return _governor_effective_directives()
    prompt_type = "STRATEGY_GOVERNOR_FAST" if profile == "fast" else "STRATEGY_GOVERNOR_MEDIUM"
    raw = query_ai(
        prompt_type,
        context,
        cache_ttl_minutes=3 if profile == "fast" else 8,
        force_refresh=force or changed,
    )
    if not isinstance(raw, dict) or not raw:
        current_directives = _governor_effective_directives()
        current_provider = str(current_directives.get("provider") or "")
        current_expired = bool(current_directives.get("plan_is_expired"))
        if current_directives and current_provider not in {"", "heuristic", "local-fallback"} and not current_expired:
            preserved = dict(current_directives)
            ops_alerts = [str(item) for item in list(preserved.get("ops_alerts") or []) if str(item).strip()]
            ops_alert = f"ai governor refresh missed ({profile})"
            if ops_alert not in ops_alerts:
                ops_alerts.append(ops_alert)
            preserved["ops_alerts"] = ops_alerts[-4:]
            preserved["plan_state"] = "ACTIVE"
            preserved["reason"] = f"{str(preserved.get('reason') or 'ai_governor_plan')}+refresh_missed:{profile}"
            raw = preserved
        else:
            raw = _fallback_governor_raw(context, failure_reason="empty_governor_response", profile=profile)
        _governor_state["last_error"] = "empty_governor_response"
    sanitized = _sanitize_governor_directives(raw, context)
    sanitized["trigger_reason"] = reason
    sanitized["refresh_profile"] = profile.upper()
    _governor_directives = sanitized
    _save_governor_directives()
    _governor_state.update(
        {
            "last_refresh_at": sanitized.get("updated_at") or _safe_isoformat(now),
            "last_reason": reason,
            "last_profile": profile.upper(),
            "last_provider": str(sanitized.get("provider") or ""),
            "last_plan_id": str(sanitized.get("plan_id") or ""),
            "last_plan_state": str(sanitized.get("plan_state") or "ACTIVE"),
            "last_fingerprint": hashlib.md5(json.dumps(sanitized, sort_keys=True).encode("utf-8")).hexdigest(),
            "last_event_fingerprint": event_fingerprint,
            "refresh_count": int(_governor_state.get("refresh_count") or 0) + 1,
            "last_error": "",
        }
    )
    _save_governor_state()
    _append_runtime_event(
        "strategy_governor_refresh",
        {
            "reason": reason,
            "profile": profile.upper(),
            "plan_id": sanitized.get("plan_id"),
            "provider": sanitized.get("provider"),
            "brain_mode": sanitized.get("brain_mode"),
            "strategy_mode": sanitized.get("strategy_mode"),
        },
    )
    _append_jsonl(
        DECISION_LEDGER_PATH,
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "profile": profile.upper(),
            "reason": reason,
            "plan_id": sanitized.get("plan_id"),
            "provider": sanitized.get("provider"),
            "brain_mode": sanitized.get("brain_mode"),
            "market_regime": sanitized.get("market_regime"),
            "capital_posture": sanitized.get("capital_posture"),
            "confidence": sanitized.get("effective_confidence") or sanitized.get("confidence"),
            "focus_pairs": list((sanitized.get("indodax") or {}).get("focus_pairs") or [])[:4],
            "focus_markets": list((sanitized.get("polymarket") or {}).get("focus_markets") or [])[:4],
            "why": list(sanitized.get("why") or [])[:4],
            "ops_alerts": list(sanitized.get("ops_alerts") or [])[:4],
        },
    )
    print(
        f"[KIBOT][GOVERNOR] refreshed profile={profile} reason={reason} provider={sanitized.get('provider') or '?'} "
        f"brain={sanitized.get('brain_mode') or 'CONTROLLED'} mode={sanitized.get('strategy_mode') or 'NEUTRAL'} "
        f"plan={sanitized.get('plan_id') or '?'}",
        flush=True,
    )
    return sanitized


def _save_gate_state() -> None:
    _write_json_file(MANAGER_GATE_STATE_PATH, _gate_state)


def _save_daily_guard_state() -> None:
    _write_json_file(DAILY_GUARD_STATE_PATH, _daily_guard_state)


def _save_daily_cycle_state() -> None:
    _write_json_file(DAILY_CYCLE_STATE_PATH, _daily_cycle_state)


def _save_pair_memory_state() -> None:
    _write_json_file(PAIR_MEMORY_PATH, _pair_memory)


def _operational_wib_date() -> str:
    return str(_daily_cycle_state.get("active_wib_date") or _wib_today_str())


def _midnight_reset_pending() -> bool:
    return bool(str(_daily_cycle_state.get("pending_new_date") or "").strip())


def _extract_equity_estimate(runtime_state: Dict[str, Any]) -> float | None:
    if runtime_state:
        for field in (
            "totalEquityIdr",
            "total_equity_idr",
            "portfolioValueIdr",
            "portfolio_value_idr",
            "balanceIdr",
            "balance_idr",
            "totalValueIdr",
            "total_value_idr",
        ):
            numeric = _parse_numeric(runtime_state.get(field))
            if numeric is not None and numeric > 0:
                return numeric
    current_equity = _daily_guard_state.get("current_equity")
    if isinstance(current_equity, (int, float)) and float(current_equity) > 0:
        return float(current_equity)
    for payload_key in ("totalValueIdr", "portfolioValueIdr", "total_value_idr", "balanceIdr", "balance_idr"):
        value = _daily_guard_state.get(payload_key)
        if isinstance(value, (int, float)) and float(value) > 0:
            return float(value)
    return None


def _fetch_local_runtime_state(timeout_sec: float = 2.0, max_cache_age_sec: float | None = None) -> Dict[str, Any]:
    global _local_runtime_state_cache, _local_runtime_state_cache_at
    now = time.time()
    cache_ttl = _local_runtime_state_cache_ttl_sec if max_cache_age_sec is None else max(max_cache_age_sec, 0.0)
    if _local_runtime_state_cache and (now - _local_runtime_state_cache_at) <= cache_ttl:
        return dict(_local_runtime_state_cache)
    for url in LOCAL_RUNTIME_STATE_URLS:
        try:
            response = requests.get(url, timeout=timeout_sec)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload:
                payload.setdefault("_state_url", url)
                _local_runtime_state_cache = dict(payload)
                _local_runtime_state_cache_at = now
                return payload
        except Exception:
            continue
    if _local_runtime_state_cache:
        stale_payload = dict(_local_runtime_state_cache)
        stale_payload["_state_cache_stale"] = True
        return stale_payload
    return {}


def _default_pair_memory() -> Dict[str, Any]:
    return {
        "slippage_history": [],
        "spread_observed": [],
        "win_rate_by_hour": {},
        "last_loss_at": None,
        "cooldown_until": None,
        "fake_pump_count": 0,
        "avg_execution_latency_ms": 0.0,
        "trade_count": 0,
        "win_count": 0,
        "last_updated_at": "",
    }


def _wib_hour_now() -> int:
    return (datetime.now(timezone.utc) + timedelta(hours=WIB_UTC_OFFSET_HOURS)).hour


def _pair_memory_for(pair_id: str) -> Dict[str, Any]:
    pair_key = pair_id.lower().strip()
    if not pair_key:
        return _default_pair_memory()
    memory = _pair_memory.setdefault(pair_key, _default_pair_memory())
    if "trade_count" not in memory:
        memory.update(_default_pair_memory())
    return memory


def _update_pair_memory(
    pair_id: str,
    *,
    pnl_pct: float,
    slippage_pct: float | None = None,
    spread_pct: float | None = None,
    actual_latency_ms: float | None = None,
    fake_pump: bool = False,
    loss_threshold_pct: float = 0.75,
    cooldown_sec: int = 60 * 60,
) -> None:
    pair_key = pair_id.lower().strip()
    if not pair_key or pair_key in {"unknown", "null", "none"}:
        print(f"[KIBOT][LEARNING][WARN] skip invalid pair_id='{pair_id}'", flush=True)
        return
    memory = _pair_memory_for(pair_key)
    if slippage_pct is not None:
        history = list(memory.get("slippage_history") or [])
        history.append(float(slippage_pct))
        memory["slippage_history"] = history[-PAIR_MEMORY_ROLLING_WINDOW:]
    if spread_pct is not None:
        history = list(memory.get("spread_observed") or [])
        history.append(float(spread_pct))
        memory["spread_observed"] = history[-PAIR_MEMORY_ROLLING_WINDOW:]
    if actual_latency_ms is not None and actual_latency_ms > 0:
        current = float(memory.get("avg_execution_latency_ms") or 0.0)
        count = int(memory.get("trade_count") or 0)
        memory["avg_execution_latency_ms"] = round(((current * count) + actual_latency_ms) / (count + 1), 3)
    hour_bucket = str(_wib_hour_now())
    win_rate_by_hour = memory.setdefault("win_rate_by_hour", {})
    hour_stats = win_rate_by_hour.setdefault(hour_bucket, {"wins": 0, "total": 0})
    hour_stats["total"] += 1
    memory["trade_count"] = int(memory.get("trade_count") or 0) + 1
    if pnl_pct > 0:
        hour_stats["wins"] += 1
        memory["win_count"] = int(memory.get("win_count") or 0) + 1
    else:
        memory["last_loss_at"] = datetime.now(timezone.utc).isoformat()
        if pnl_pct <= -abs(loss_threshold_pct):
            memory["cooldown_until"] = time.time() + cooldown_sec
    if fake_pump:
        memory["fake_pump_count"] = int(memory.get("fake_pump_count") or 0) + 1
    memory["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    memory["avg_pnl"] = round(
        ((float(memory.get("avg_pnl") or 0.0) * max(0, int(memory.get("trade_count") or 0) - 1)) + float(pnl_pct))
        / max(1, int(memory.get("trade_count") or 0)),
        5,
    )
    memory["win_rate_7d"] = round(
        float(memory.get("win_count") or 0) / max(1, int(memory.get("trade_count") or 0)),
        5,
    )
    _pair_memory[pair_key] = memory
    _save_pair_memory_state()


def _get_pair_avg_slippage(pair_id: str, fallback: float = 0.0) -> float:
    memory = _pair_memory.get(pair_id.lower().strip(), {})
    history = memory.get("slippage_history") or []
    if not history:
        return fallback
    return sum(float(value) for value in history) / len(history)


def _get_pair_win_rate_now(pair_id: str) -> float:
    memory = _pair_memory.get(pair_id.lower().strip(), {})
    hour_bucket = str(_wib_hour_now())
    hour_stats = (memory.get("win_rate_by_hour") or {}).get(hour_bucket)
    if not hour_stats or int(hour_stats.get("total") or 0) < PAIR_MEMORY_MIN_TRADES_FOR_WINRATE:
        return 0.5
    total = float(hour_stats.get("total") or 0)
    return float(hour_stats.get("wins") or 0) / total if total > 0 else 0.5


def _is_pair_on_cooldown(pair_id: str) -> bool:
    memory = _pair_memory.get(pair_id.lower().strip(), {})
    cooldown_until = memory.get("cooldown_until")
    if cooldown_until is None:
        return False
    try:
        return time.time() < float(cooldown_until)
    except Exception:
        return False


def _daily_summary_market_regime() -> str:
    regime = _gate_state.get("market_regime")
    if regime:
        return str(regime)
    return str(_load_daily_summary().get("market_regime") or "UNKNOWN")


def _next_wib_midnight_iso() -> str:
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc + timedelta(hours=WIB_UTC_OFFSET_HOURS)
    midnight_wib = datetime.combine(now_wib.date() + timedelta(days=1), datetime.min.time())
    reset_utc = midnight_wib - timedelta(hours=WIB_UTC_OFFSET_HOURS)
    return reset_utc.replace(tzinfo=timezone.utc).isoformat()


def _entry_state_is_suspended() -> bool:
    return str(_gate_state.get("entry_state") or "HEALTHY").upper() != "HEALTHY"


def _set_entry_state(entry_state: str, *, reason: str = "", daily_hard_stop: bool | None = None) -> None:
    normalized = entry_state.upper().strip() or "HEALTHY"
    _gate_state["entry_state"] = normalized
    _gate_state["reason"] = reason
    _gate_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    if daily_hard_stop is not None:
        _gate_state["daily_hard_stop"] = bool(daily_hard_stop)
    _save_gate_state()


def _suspend_new_entries(reason: str, *, daily_hard_stop: bool = False) -> None:
    current = str(_gate_state.get("entry_state") or "HEALTHY").upper()
    if current == "SUSPENDED" and _gate_state.get("reason") == reason and bool(_gate_state.get("daily_hard_stop")) == bool(daily_hard_stop):
        return
    _set_entry_state("SUSPENDED", reason=reason, daily_hard_stop=daily_hard_stop)
    _append_runtime_event("entry_suspended", {"reason": reason, "daily_hard_stop": daily_hard_stop})
    print(f"[KIBOT][GATE] entry suspended reason={reason} daily_hard_stop={daily_hard_stop}", flush=True)


def _resume_new_entries(reason: str) -> None:
    if not _entry_state_is_suspended():
        return
    if bool(_gate_state.get("daily_hard_stop")):
        return
    _set_entry_state("HEALTHY", reason=reason, daily_hard_stop=False)
    _append_runtime_event("entry_resumed", {"reason": reason})
    print(f"[KIBOT][GATE] entry resumed reason={reason}", flush=True)


def _set_conservative_mode(reason: str) -> None:
    if str(_gate_state.get("mode") or "CONSERVATIVE").upper() == "CONSERVATIVE":
        return
    _gate_state["mode"] = "CONSERVATIVE"
    _gate_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _gate_state["reason"] = reason
    _save_gate_state()
    _append_runtime_event("trading_mode_changed", {"mode": "CONSERVATIVE", "reason": reason})
    print(f"[KIBOT][MODE] switched to CONSERVATIVE reason={reason}", flush=True)


def _set_level_3_mode(reason: str) -> None:
    if str(_gate_state.get("mode") or "").upper() == "LEVEL_3":
        return
    _gate_state["mode"] = "LEVEL_3"
    _gate_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _gate_state["reason"] = reason
    _save_gate_state()
    _append_runtime_event("trading_mode_changed", {"mode": "LEVEL_3", "reason": reason})
    print(f"[v7][MODE] switched to LEVEL_3 reason={reason}", flush=True)

def _set_normal_mode(reason: str) -> None:
    if str(_gate_state.get("mode") or "CONSERVATIVE").upper() == "NORMAL":
        return
    _gate_state["mode"] = "NORMAL"
    _gate_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    _gate_state["reason"] = reason
    _save_gate_state()
    _append_runtime_event("trading_mode_changed", {"mode": "NORMAL", "reason": reason})
    print(f"[KIBOT][MODE] switched to NORMAL reason={reason}", flush=True)


def _record_control_plane_success() -> None:
    global _control_plane_healthy, _control_plane_last_success_at, _api_fail_streak, _api_health_state
    _control_plane_healthy = True
    _control_plane_last_success_at = time.time()
    if _api_fail_streak != 0 or _api_health_state != "HEALTHY":
        _api_fail_streak = 0
        _api_health_state = "HEALTHY"
        print("[KIBOT][HEALTH] API/control-plane recovered", flush=True)
        _append_runtime_event("api_health", {"state": "HEALTHY"})


def _record_control_plane_failure(reason: str) -> None:
    global _control_plane_healthy, _api_fail_streak, _api_health_state
    _control_plane_healthy = False
    _api_fail_streak += 1
    if _api_fail_streak >= API_HEALTH_FAIL_THRESHOLD:
        if _api_health_state != "SUSPENDED":
            _api_health_state = "SUSPENDED"
            _append_runtime_event("api_health", {"state": "SUSPENDED", "reason": reason, "streak": _api_fail_streak})
            print(f"[KIBOT][HEALTH] API suspended reason={reason} streak={_api_fail_streak}", flush=True)
        _suspend_new_entries(reason="API health fail streak")
    else:
        if _api_health_state != "DEGRADED":
            _api_health_state = "DEGRADED"
            _append_runtime_event("api_health", {"state": "DEGRADED", "reason": reason, "streak": _api_fail_streak})
        print(f"[KIBOT][HEALTH] API degraded reason={reason} streak={_api_fail_streak}", flush=True)


def _daily_guard_reset_due() -> bool:
    reset_at = str(_daily_guard_state.get("reset_at") or "")
    if not reset_at:
        return False
    try:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(reset_at)
    except Exception:
        return False


def _refresh_daily_guard_from_equity(current_equity: float | None) -> None:
    logical_today = _operational_wib_date()
    if not _daily_guard_state.get("date"):
        _daily_guard_state.update(
            {
                "date": logical_today,
                "start_of_day_equity": current_equity,
                "current_equity": current_equity,
                "daily_pnl_pct": None,
                "external_cashflow_idr": 0.0,
                "external_cashflow_detected_at": "",
                "external_cashflow_reason": "",
                "hard_stopped": False,
                "triggered_at": "",
                "reset_at": "",
                "reason": "",
            }
        )
        _save_daily_guard_state()
        return
    if _daily_guard_state.get("date") != logical_today:
        if current_equity is not None:
            _daily_guard_state["current_equity"] = current_equity
            _save_daily_guard_state()
        return


def _reconcile_daily_guard_day_rollover() -> None:
    global _ai_failure_streak, _ai_healthy
    today = _operational_wib_date()
    if _daily_guard_state.get("date") == today:
        return

    # NEW DAY - Reset Trinity Fixed State
    _entry_loss_count.clear()
    _last_entry.clear()
    _signal_seen.clear()
    # [SOVEREIGN] Legacy Reset
    pass
    _ai_failure_streak = 0
    _ai_healthy = True

    if not _daily_guard_state.get("date"):
        _daily_guard_state.update(
            {
                "date": today,
                "start_of_day_equity": _daily_guard_state.get("current_equity"),
                "daily_pnl_pct": 0.0,
                "external_cashflow_idr": 0.0,
                "external_cashflow_detected_at": "",
                "external_cashflow_reason": "",
                "hard_stopped": False,
                "triggered_at": "",
                "reset_at": "",
                "reason": "",
            }
        )
        _save_daily_guard_state()
        _hard_stop.initial_capital = float(_daily_guard_state.get("start_of_day_equity") or 0.0)
        _save_daily_state()
        return
    _append_runtime_event(
        "daily_rollover_pending",
        {
            "stored_date": _daily_guard_state.get("date"),
            "target_date": today,
        },
    )

def _ensure_hard_stop_consistency() -> None:
    """Clear stale hard-stop flags when the stored PnL no longer breaches today's limit."""
    try:
        daily_pnl_pct = _daily_guard_state.get("daily_pnl_pct")
        if daily_pnl_pct is None:
            return
        daily_pnl_pct = float(daily_pnl_pct)
    except Exception:
        return
    limit = -abs(_current_daily_loss_limit_pct())
    if not bool(_daily_guard_state.get("hard_stopped")) and not bool(_gate_state.get("daily_hard_stop")):
        return
    # If we are not breaching the limit anymore for the current day, treat previous hard-stop as stale.
    if daily_pnl_pct > limit:
        _daily_guard_state["hard_stopped"] = False
        _daily_guard_state["triggered_at"] = ""
        _daily_guard_state["reset_at"] = ""
        _daily_guard_state["reason"] = ""
        _save_daily_guard_state()
        _gate_state["daily_hard_stop"] = False
        _gate_state["daily_hard_stop_reason"] = ""
        _gate_state["daily_hard_stop_reset_at"] = ""
        _save_gate_state()
        _resume_new_entries("hard stop cleared (pnl recovered/new day)")


def _trigger_daily_hard_stop(current_equity: float | None, daily_pnl_pct: float) -> None:
    reset_at = _next_wib_midnight_iso()
    _daily_guard_state.update(
        {
            "hard_stopped": True,
            "current_equity": current_equity,
            "daily_pnl_pct": daily_pnl_pct,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "reset_at": reset_at,
            "reason": "daily_loss_limit_hit",
        }
    )
    _save_daily_guard_state()
    _gate_state["daily_hard_stop"] = True
    _gate_state["daily_hard_stop_reset_at"] = reset_at
    _gate_state["daily_hard_stop_reason"] = "daily_loss_limit_hit"
    _save_gate_state()
    _set_level_3_mode("Daily Hard Stop")
    _suspend_new_entries("daily_loss_limit_hit", daily_hard_stop=True)
    _append_runtime_event("daily_hard_stop", {"daily_pnl_pct": daily_pnl_pct, "reset_at": reset_at})
    _metric_inc("entries_blocked_hard_stop")
    print(f"[KIBOT][GATE] daily hard stop triggered pnl_pct={daily_pnl_pct:.4f} reset_at={reset_at}", flush=True)


def _check_daily_loss_limit(current_equity: float | None = None) -> None:
    if current_equity is None:
        current_equity = _get_total_equity_estimate()
        if current_equity is None:
            current_equity = float(_daily_guard_state.get("current_equity") or 0.0) or None
    _refresh_daily_guard_from_equity(current_equity)
    actual_today = _wib_today_str()
    if _daily_guard_state.get("hard_stopped") and _daily_guard_reset_due():
        if str(_daily_guard_state.get("date") or "") != actual_today:
            return
        _daily_guard_state.update({"hard_stopped": False, "reason": "", "triggered_at": ""})
        _save_daily_guard_state()
        _gate_state["daily_hard_stop"] = False
        _gate_state["daily_hard_stop_reason"] = ""
        _gate_state["daily_hard_stop_reset_at"] = ""
        _save_gate_state()
        _resume_new_entries("daily hard stop reset")
        print("[KIBOT][GATE] daily hard stop reset", flush=True)
    start_equity = float(_daily_guard_state.get("start_of_day_equity") or 0.0)
    if not start_equity or not current_equity:
        return
    external_cashflow = float(_daily_guard_state.get("external_cashflow_idr") or 0.0)
    net_equity = float(current_equity) - external_cashflow
    daily_pnl_pct = (net_equity - start_equity) / start_equity
    _daily_guard_state["current_equity"] = float(current_equity)
    _daily_guard_state["daily_pnl_pct"] = daily_pnl_pct
    _save_daily_guard_state()
    if daily_pnl_pct <= -abs(_current_daily_loss_limit_pct()) and not bool(_daily_guard_state.get("hard_stopped")):
        _trigger_daily_hard_stop(current_equity, daily_pnl_pct)


def _recent_trade_activity_window_sec(window_sec: int = 180) -> bool:
    cutoff = time.time() - max(window_sec, 30)
    for event in reversed(_recent_runtime_events[-25:]):
        try:
            ts = str(event.get("at") or "")
            if not ts:
                continue
            event_dt = datetime.fromisoformat(ts)
            if event_dt.replace(tzinfo=timezone.utc).timestamp() < cutoff:
                continue
            if str(event.get("kind") or "").lower() in {
                "execution_filled",
                "fill",
                "book_entry",
                "partial_sell",
                "force_exit",
                "entry_approved",
            }:
                return True
        except Exception:
            continue
    return False


def _maybe_register_external_cashflow(current_equity: float | None) -> None:
    if current_equity is None:
        return
    start_equity = _parse_numeric(_daily_guard_state.get("start_of_day_equity"))
    prev_equity = _parse_numeric(_daily_guard_state.get("current_equity"))
    if not start_equity or prev_equity is None or prev_equity <= 0:
        return
    if _active_position_pairs():
        return
    if _recent_trade_activity_window_sec():
        return
    delta = float(current_equity) - float(prev_equity)
    min_delta = max(EXTERNAL_CASHFLOW_AUTO_DETECT_IDR, start_equity * EXTERNAL_CASHFLOW_AUTO_DETECT_PCT)
    if abs(delta) < min_delta:
        return
    _daily_guard_state["external_cashflow_idr"] = float(_daily_guard_state.get("external_cashflow_idr") or 0.0) + delta
    _daily_guard_state["external_cashflow_detected_at"] = datetime.now(timezone.utc).isoformat()
    _daily_guard_state["external_cashflow_reason"] = "auto_detected_balance_jump"
    _daily_guard_state["current_equity"] = float(current_equity)
    _save_daily_guard_state()
    _append_runtime_event(
        "external_cashflow",
        {
            "delta_idr": round(delta, 2),
            "reason": "auto_detected_balance_jump",
            "equity_idr": round(float(current_equity), 2),
        },
    )
    print(f"[KIBOT][CASHFLOW] external cashflow detected delta=Rp{delta:,.0f}", flush=True)


def _bootstrap_daily_guard_from_KiBot() -> None:
    # Only bootstrap missing context; do not re-trigger hard stops from external labels.
    if _daily_guard_state.get("start_of_day_equity") is not None and _daily_guard_state.get("current_equity") is not None:
        return
    payload = _fetch_local_runtime_state(timeout_sec=2.0)
    if not payload:
        return

    daily_pnl_pct = None
    for key in ("pnlTodayPct", "pnl_today_pct", "dailyPnlPct", "daily_pnl_pct"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            daily_pnl_pct = float(value)
            break
    if daily_pnl_pct is None:
        label = str(payload.get("pnlTodayPctLabel") or payload.get("dailyPnlPctLabel") or "")
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*%$", label)
        if match:
            try:
                daily_pnl_pct = float(match.group(1))
            except Exception:
                daily_pnl_pct = None
    # daily_pnl_pct is best-effort; never used to force a hard stop in bootstrap.

    current_equity = None
    for key in ("totalValueIdr", "portfolioValueIdr", "total_value_idr"):
        current_equity = _parse_numeric(payload.get(key))
        if current_equity is not None:
            break

    if current_equity is not None:
        _refresh_daily_guard_from_equity(current_equity)
        _maybe_register_external_cashflow(current_equity)
        if daily_pnl_pct is not None and _daily_guard_state.get("daily_pnl_pct") is None:
            _daily_guard_state["daily_pnl_pct"] = daily_pnl_pct
            _daily_guard_state["current_equity"] = current_equity
            _save_daily_guard_state()
    if daily_pnl_pct is not None and _daily_guard_state.get("daily_pnl_pct") is None:
        _daily_guard_state["daily_pnl_pct"] = daily_pnl_pct
        _daily_guard_state["current_equity"] = current_equity
def _health_gate_loop() -> None:
    while not _shutdown_event.is_set():
        try:
            if _check_KiBot_health():
                _record_control_plane_success()
            else:
                _record_control_plane_failure("KiBot_unhealthy")
            _check_daily_loss_limit()
            _ensure_hard_stop_consistency()
            _maybe_auto_promote_trading_mode()

            # Bug #2: AI Persistent Offline Check
            global _ai_healthy
            now = time.time()
            if (now - _ai_last_success) > 900 and _ai_failure_streak >= 3:
                if _ai_healthy:
                    _ai_healthy = False
                    print("[v7][AI_SILENCE] No AI success in 15m. Suspending entry.", flush=True)
                    _telegram_send("\ud83d\udea8 AI SILENCE: No response in 15m. Suspended.")

        except Exception as error:
            print(f"[KIBOT][HEALTH][ERROR] gate loop failed reason={error}", flush=True)
        _shutdown_event.wait(API_HEALTH_CHECK_INTERVAL_SEC)


def _build_performance_summary() -> Dict[str, Any]:
    pair_stats: Dict[str, Any] = {}
    for pair_id, memory in _pair_memory.items():
        pair_stats[pair_id] = {
            "win_rate_now": _get_pair_win_rate_now(pair_id),
            "avg_slippage_pct": round(_get_pair_avg_slippage(pair_id, fallback=0.0), 4),
            "on_cooldown": _is_pair_on_cooldown(pair_id),
            "trade_count": int(memory.get("trade_count") or 0),
            "fake_pump_count": int(memory.get("fake_pump_count") or 0),
        }
    return {
        "period_hours": 6,
        "daily_pnl_pct": _daily_guard_state.get("daily_pnl_pct"),
        "hard_stop_active": bool(_daily_guard_state.get("hard_stopped")),
        "api_fail_streak": _api_fail_streak,
        "cp_healthy": _control_plane_healthy,
        "mode": str(_gate_state.get("mode") or "CONSERVATIVE"),
        "entry_state": str(_gate_state.get("entry_state") or "HEALTHY"),
        "pair_stats": pair_stats,
    }


def _hours_until_midnight_wib() -> float:
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc + timedelta(hours=7)
    midnight_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max((midnight_wib - now_wib).total_seconds() / 3600.0, 0.0)


def _get_trade_metrics_today() -> Dict[str, Any]:
    trades = list(_math_review_trade_journal)
    if not trades:
        for row in _trade_records_for_wib_date(_operational_wib_date()):
            if str(row.get("side") or "").upper() != "SELL":
                continue
            pnl_pct = _normalized_trade_net_pnl_pct(row)
            if pnl_pct is None:
                continue
            trades.append({"gross_pnl_pct": pnl_pct})
    total_trades = len(trades)
    wins = sum(1 for row in trades if float(row.get("gross_pnl_pct") or 0.0) > 0)
    losses = total_trades - wins
    total_gross_pnl = sum(float(row.get("gross_pnl_pct") or 0.0) for row in trades)
    total_wins = sum(float(row.get("gross_pnl_pct") or 0.0) for row in trades if float(row.get("gross_pnl_pct") or 0.0) > 0)
    total_losses = sum(abs(float(row.get("gross_pnl_pct") or 0.0)) for row in trades if float(row.get("gross_pnl_pct") or 0.0) <= 0)
    win_rate = wins / max(total_trades, 1)
    avg_win = total_wins / max(wins, 1)
    avg_loss = total_losses / max(losses, 1)
    ev_per_trade = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)
    profit_factor = total_wins / max(total_losses, 1e-9)
    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "ev_per_trade": ev_per_trade,
        "profit_factor": profit_factor,
        "total_gross_pnl": total_gross_pnl,
    }


def _run_math_review() -> Dict[str, Any]:
    metrics = _get_trade_metrics_today()
    equity = _get_total_equity_estimate() or 0.0
    pnl_pct = float(_daily_guard_state.get("daily_pnl_pct") or 0.0)
    current_loss_idr = abs(min(pnl_pct, 0.0) * equity)
    min_trade_sample = max(1, int(MATH_REVIEW_MIN_TRADES))
    small_loss_grace_idr = max(1000.0, equity * max(MATH_REVIEW_SMALL_LOSS_GRACE_PCT, 0.0))
    hours_left = _hours_until_midnight_wib()
    avg_trades_per_hour = metrics["total_trades"] / max((time.time() - _bot_start_time) / 3600.0, 0.5)
    trades_possible = avg_trades_per_hour * hours_left
    ev_per_trade = float(metrics["ev_per_trade"])
    if current_loss_idr <= 0:
        trades_to_recover = 0.0
    elif ev_per_trade > 0:
        trades_to_recover = current_loss_idr / ev_per_trade
    elif ev_per_trade <= 0:
        trades_to_recover = float("inf")
    else:
        trades_to_recover = 0.0

    if metrics["total_trades"] < min_trade_sample:
        action = "WAIT_FOR_SAMPLE"
        reason = f"Need >= {min_trade_sample} realized trades before strict recovery gate (have {metrics['total_trades']})"
        if str(_gate_state.get("reason") or "").startswith("math_review_"):
            _resume_new_entries("math_review_wait_for_sample")
    elif current_loss_idr <= small_loss_grace_idr:
        action = "CONTINUE"
        reason = f"Loss Rp{current_loss_idr:,.0f} within grace Rp{small_loss_grace_idr:,.0f}"
        if str(_gate_state.get("reason") or "").startswith("math_review_"):
            _resume_new_entries("math_review_loss_within_grace")
    elif ev_per_trade <= 0 and metrics["total_trades"] >= min_trade_sample:
        action = "TIGHTEN_FILTER"
        reason = f"EV/trade <= 0 after {metrics['total_trades']} trades"
        _set_conservative_mode("math_review_ev_negative")
        if str(_gate_state.get("reason") or "").startswith("math_review_"):
            _resume_new_entries("math_review_tighten_filter")
    elif current_loss_idr > 0 and trades_to_recover > trades_possible * 1.5:
        action = "HARD_STOP"
        reason = f"Recovery too far: need {trades_to_recover:.1f}, possible {trades_possible:.1f}"
        _set_conservative_mode("math_review_recovery_impossible")
        _suspend_new_entries("math_review_recovery_impossible")
    elif current_loss_idr > 0 and trades_to_recover > trades_possible:
        action = "DEFENSIVE"
        reason = f"Recovery tight: need {trades_to_recover:.1f}, possible {trades_possible:.1f}"
        if str(_gate_state.get("reason") or "").startswith("math_review_"):
            _resume_new_entries("math_review_defensive")
    elif metrics["win_rate"] >= 0.60 and ev_per_trade > 0:
        action = "CONTINUE_OPTIMAL"
        reason = f"WR={metrics['win_rate']:.0%}, EV/trade=Rp{ev_per_trade:,.0f}"
        if not bool(_daily_guard_state.get("hard_stopped")) and _api_fail_streak == 0 and _control_plane_healthy:
            _set_normal_mode("math_review_optimal")
            _resume_new_entries("math_review_optimal")
    else:
        action = "CONTINUE"
        reason = f"WR={metrics['win_rate']:.0%}, EV/trade=Rp{ev_per_trade:,.0f}"
        if str(_gate_state.get("reason") or "").startswith("math_review_"):
            _resume_new_entries("math_review_continue")

    report = (
        f"📊 30min Math Review\n"
        f"PnL: {pnl_pct:+.2%} | Trades: {metrics['total_trades']} ({metrics['wins']}W/{metrics['losses']}L)\n"
        f"WR: {metrics['win_rate']:.0%} | PF: {metrics['profit_factor']:.2f} | EV/trade: Rp{ev_per_trade:+,.0f}\n"
        f"Hours left: {hours_left:.1f} | Trades possible: {trades_possible:.1f}\n"
        f"Action: {action}\n"
        f"Reason: {reason}"
    )
    _telegram_send(report)
    _append_runtime_event(
        "math_review",
        {
            "action": action,
            "reason": reason,
            "metrics": metrics,
            "hours_left": round(hours_left, 2),
            "trades_possible": round(trades_possible, 2),
        },
    )
    print(f"[KIBOT][MATH_REVIEW] action={action} reason={reason}", flush=True)
    return {"action": action, "reason": reason, "metrics": metrics}


# DELETED Duplicate _math_review_loop


def _apply_ai_recommendation(recommendation: Dict[str, Any]) -> None:
    if not isinstance(recommendation, dict):
        return
    for pair in recommendation.get("pairs_to_cooldown", []):
        if isinstance(pair, str) and pair.strip():
            _cooldown_pair(pair, reason="ai_batch_review", minutes=60)
    mode = str(recommendation.get("mode_recommendation") or "no_change")
    if mode == "CONSERVATIVE":
        _set_conservative_mode("ai_batch_review")
    elif mode == "NORMAL" and not bool(_daily_guard_state.get("hard_stopped")) and _api_fail_streak == 0 and _control_plane_healthy:
        _set_normal_mode("ai_batch_review")
    _append_runtime_event("ai_batch_review", recommendation)


def _run_ai_batch_review() -> None:
    summary = _build_performance_summary()
    prompt = (
        "Kamu adalah risk analyst untuk autonomous crypto trading bot.\n"
        "Filosofi: survival first, compounding gradual.\n\n"
        f"Data performa 6 jam terakhir:\n{json.dumps(summary, ensure_ascii=True, indent=2)}\n\n"
        "Berikan rekomendasi JSON dengan keys: "
        "\"pairs_to_cooldown\", \"mode_recommendation\", \"reasoning\"."
    )
    try:
        text, provider = _call_ai_router(
            task="batch_review",
            system_prompt="Jawab JSON singkat saja.",
            user_prompt=prompt,
            model_hint=POST_MORTEM_MODEL,
            timeout_sec=min(POST_MORTEM_TIMEOUT_SEC, 20.0),
        )
        if not text:
            return
        parsed = _parse_json_candidate(text)
        if isinstance(parsed, dict) and parsed:
            _apply_ai_recommendation(parsed)
            print(f"[KIBOT][AI_REVIEW] provider={provider} applied={json.dumps(parsed, ensure_ascii=True)[:240]}", flush=True)
    except Exception as error:
        print(f"[KIBOT][AI_REVIEW][WARN] failed reason={error}", flush=True)


def _ai_batch_review_loop() -> None:
    while not _shutdown_event.is_set():
        try:
            _run_ai_batch_review()
        except Exception as error:
            print(f"[KIBOT][AI_REVIEW][ERROR] {error}", flush=True)
        _shutdown_event.wait(AI_BATCH_REVIEW_INTERVAL_SEC)


def _cooldown_pair(pair: str, *, reason: str, minutes: int, metadata: Dict[str, Any] | None = None) -> None:
    pair_key = pair.lower().strip()
    if not pair_key:
        return
    now_ts = time.time()
    until_ts = now_ts + max(60, minutes * 60)
    _pair_cooldown_state[pair_key] = {
        "until_epoch": until_ts,
        "reason": reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    _save_pair_cooldown_state()
    _append_runtime_event(
        "pair_cooldown_set",
        {"pair": pair_key, "reason": reason, "minutes": minutes},
    )


def _pair_cooldown_active(pair: str) -> Tuple[bool, str]:
    pair_key = pair.lower().strip()
    if not pair_key:
        return False, ""
    state = _pair_cooldown_state.get(pair_key, {})
    until_ts = float(state.get("until_epoch") or 0.0)
    now_ts = time.time()
    if until_ts <= now_ts:
        if pair_key in _pair_cooldown_state:
            del _pair_cooldown_state[pair_key]
            _save_pair_cooldown_state()
        return False, ""
    return True, str(state.get("reason") or "cooldown_active")


def _default_daily_summary(date_str: str | None = None) -> Dict[str, Any]:
    return {
        "date": date_str or _operational_wib_date(),
        "ai_success": {},
        "ai_failure": {},
        "veto_metrics": {},
        "loss_blacklist_pairs": [],
        "coins_bought_today": [],
        "coins_sold_today": [],
        "recent_notes": [],
        "learning_reviews": [],
        "last_learning_review": {},
        "last_sovereign_review": {},
    }


def _load_daily_summary() -> Dict[str, Any]:
    logical_today = _operational_wib_date()
    data = _load_json_file(DAILY_SUMMARY_PATH, _default_daily_summary(logical_today))
    if not isinstance(data, dict):
        return _default_daily_summary(logical_today)
    if not data.get("date"):
        data["date"] = logical_today
    if data.get("date") != logical_today:
        data = _default_daily_summary(logical_today)
    base = _default_daily_summary(str(data.get("date") or logical_today))
    base.update(data)
    return base


def _update_daily_summary(kind: str, detail: Dict[str, Any]) -> None:
    if not DAILY_SUMMARY_ENABLED:
        return
    summary = _load_daily_summary()
    if kind == "ai_success":
        provider = str(detail.get("provider") or "")
        if provider:
            summary["ai_success"][provider] = int(summary["ai_success"].get(provider) or 0) + 1
    elif kind == "ai_failure":
        provider = str(detail.get("provider") or "")
        if provider:
            summary["ai_failure"][provider] = int(summary["ai_failure"].get(provider) or 0) + 1
    elif kind == "veto_metric":
        name = str(detail.get("name") or "")
        if name:
            summary["veto_metrics"][name] = int(summary["veto_metrics"].get(name) or 0) + 1
    elif kind == "loss_blacklist":
        pair = str(detail.get("pair") or "")
        if pair and pair not in summary["loss_blacklist_pairs"]:
            summary["loss_blacklist_pairs"].append(pair)
    elif kind == "coin_bought":
        pair = str(detail.get("pair") or "").lower().strip()
        if pair and pair not in summary["coins_bought_today"]:
            summary["coins_bought_today"].append(pair)
    elif kind == "coin_sold":
        pair = str(detail.get("pair") or "").lower().strip()
        if pair and pair not in summary["coins_sold_today"]:
            summary["coins_sold_today"].append(pair)
    elif kind == "learning_review":
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "summary": str(detail.get("summary") or "").strip(),
            "strategy": str(detail.get("strategy") or "").strip(),
            "lessons": list(detail.get("lessons") or []),
            "risks": list(detail.get("risks") or []),
        }
        reviews = list(summary.get("learning_reviews") or [])
        reviews.append(entry)
        summary["learning_reviews"] = reviews[-16:]
        summary["last_learning_review"] = entry
    elif kind == "sovereign_review":
        summary["last_sovereign_review"] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "summary": str(detail.get("summary") or "").strip(),
            "root_causes": list(detail.get("root_causes") or []),
            "missed_opportunities": list(detail.get("missed_opportunities") or []),
            "lessons": list(detail.get("lessons") or []),
            "risks": list(detail.get("risks") or []),
            "parameter_recommendations": list(detail.get("parameter_recommendations") or []),
            "tomorrow_mode": str(detail.get("tomorrow_mode") or "").strip(),
            "tomorrow_focus": list(detail.get("tomorrow_focus") or []),
            "source": str(detail.get("source") or "").strip(),
        }
    note_line = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "detail": detail,
    }
    recent_notes = list(summary.get("recent_notes") or [])
    recent_notes.append(note_line)
    summary["recent_notes"] = recent_notes[-25:]
    _write_json_file(DAILY_SUMMARY_PATH, summary)


def _append_runtime_event(kind: str, detail: Dict[str, Any]) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    _recent_runtime_events.append(
        {
            "at": now_iso,
            "kind": kind,
            "detail": detail,
        }
    )
    if len(_recent_runtime_events) > 40:
        del _recent_runtime_events[:-40]


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception as error:
        print(f"[KIBOT][JSONL][WARN] append failed path={path.name} reason={error}", flush=True)


def _load_pattern_library() -> Dict[str, Any]:
    data = _load_json_file(
        PATTERN_LIBRARY_PATH,
        {
            "updated_at": "",
            "weekly_patterns": [],
            "pair_bias": {},
            "ops_incidents": [],
            "daily_reviews": [],
        },
    )
    return data if isinstance(data, dict) else {}


def _save_pattern_library(library: Dict[str, Any]) -> None:
    _write_json_file(PATTERN_LIBRARY_PATH, library)


def _load_trade_log_records() -> List[Dict[str, Any]]:
    if not TRADE_LOG_RUNTIME_PATH.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with open(TRADE_LOG_RUNTIME_PATH, "r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except Exception:
                    continue
                if isinstance(item, dict):
                    records.append(item)
    except Exception as error:
        print(f"[KIBOT][TRADE_LOG][WARN] read failed reason={error}", flush=True)
    return records


def _extract_reason_pnl_pct(exit_reason: Any) -> float | None:
    text = str(exit_reason or "").strip()
    if not text:
        return None
    match = re.search(r"\bpnl=([+-]?\d+(?:\.\d+)?)%", text, flags=re.IGNORECASE)
    if match:
        try:
            return float(match.group(1)) / 100.0
        except Exception:
            return None
    match = re.search(r"\bat ([+-]?\d+(?:\.\d+)?)%", text, flags=re.IGNORECASE)
    if match:
        try:
            value = float(match.group(1))
        except Exception:
            return None
        if value < 0.0:
            return value / 100.0
    return None


def _normalized_trade_net_pnl_pct(record: Dict[str, Any]) -> float | None:
    direct = _parse_numeric(record.get("netPnlPct") or record.get("net_pnl_pct") or record.get("pnl_pct"))
    filled_price = _parse_numeric(record.get("filledPrice") or record.get("filled_price"))
    inferred = _extract_reason_pnl_pct(record.get("exitReason") or record.get("exit_reason"))
    if inferred is not None:
        if direct is None:
            return inferred
        if filled_price is None or filled_price <= 0.0 or (direct < -0.90 and inferred > 0):
            return inferred
    return direct


def _trade_records_for_wib_date(target_date: str) -> List[Dict[str, Any]]:
    if not target_date:
        return []
    rows: List[Dict[str, Any]] = []
    for record in _load_trade_log_records():
        trade_date = _to_wib_date_string(record.get("timestamp") or record.get("ts") or record.get("entry_at"))
        if trade_date == target_date:
            rows.append(record)
    return rows


def _load_learning_review_history() -> List[Dict[str, Any]]:
    data = _load_json_file(LEARNING_REVIEW_HISTORY_PATH, [])
    return data if isinstance(data, list) else []


def _save_learning_review(review: Dict[str, Any]) -> None:
    _write_json_file(LEARNING_REVIEW_PATH, review)
    history = [item for item in _load_learning_review_history() if item.get("at") != review.get("at")]
    history.append(review)
    history = sorted(history, key=lambda item: str(item.get("at") or ""))[-96:]
    _write_json_file(LEARNING_REVIEW_HISTORY_PATH, history)


def _store_daily_report(report: Dict[str, Any]) -> None:
    _write_json_file(DAILY_REPORT_PATH, report)
    history = _load_json_file(DAILY_REPORT_HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []
    history = [item for item in history if item.get("report_date") != report.get("report_date")]
    history.append(report)
    history = sorted(history, key=lambda item: str(item.get("report_date") or ""))[-30:]
    _write_json_file(DAILY_REPORT_HISTORY_PATH, history)


def _reset_intraday_metrics() -> None:
    global _veto_metrics
    for name in (
        "market_orders_today",
        "limit_orders_today",
        "entries_blocked_hard_stop",
        "entries_blocked_learn_gate",
        "entries_blocked_whatif",
        "entries_blocked_brain",
        "entries_brain_reduced",
        "whatif_skips_today",
        "whatif_enters_today",
    ):
        _metrics[name] = 0
    _metrics["fee_bleed_est_idr"] = 0.0
    _math_review_trade_journal.clear()
    _veto_metrics = {"approved": 0, "rejected": 0, "sell_confirmed": 0, "emergency_sell": 0}


def _active_position_pairs() -> List[str]:
    pairs = {pair.lower().strip() for pair in _active_positions_cache.keys() if str(pair).strip()}
    for pair in _current_balance_snapshot().get("holdings_pairs") or []:
        normalized = str(pair).lower().strip()
        if normalized:
            pairs.add(normalized)
    return sorted(pairs)


def _extract_state_holdings(payload: Dict[str, Any]) -> List[str]:
    holdings = payload.get("holdingsDetailed")
    pairs: List[str] = []
    if isinstance(holdings, list):
        for item in holdings:
            if not isinstance(item, dict):
                continue
            pair = str(item.get("pairId") or "").lower().strip()
            if pair:
                pairs.append(pair)
                continue
            asset = str(item.get("assetCode") or item.get("symbol") or "").lower().strip()
            if asset and asset != "idr":
                pairs.append(f"{asset}_idr")
    active_positions = payload.get("activePositions")
    if isinstance(active_positions, list):
        for item in active_positions:
            if not isinstance(item, dict):
                continue
            pair = str(item.get("pairId") or item.get("pair") or "").lower().strip()
            if pair:
                if "_" not in pair and pair != "idr":
                    pair = f"{pair}_idr"
                pairs.append(pair)
    return sorted(dict.fromkeys(pairs))


def _current_balance_snapshot() -> Dict[str, Any]:
    payload = _fetch_local_runtime_state(timeout_sec=2.0)
    equity = None
    free_cash = None
    for key in ("totalEquityIdr", "total_equity_idr", "portfolioValueIdr", "portfolio_value_idr", "totalValueIdr", "total_value_idr"):
        equity = _parse_numeric(payload.get(key))
        if equity is not None:
            break
    for key in ("freeIdr", "free_idr", "freeCashIdr", "free_cash_idr", "freeIdrLabel"):
        free_cash = _parse_numeric(payload.get(key))
        if free_cash is not None:
            break
    if equity is None:
        equity = _get_total_equity_estimate()
    return {
        "equity_idr": equity,
        "free_cash_idr": free_cash,
        "holdings_pairs": _extract_state_holdings(payload),
        "payload": payload,
    }


def _build_daily_report_payload(report_date: str) -> Dict[str, Any]:
    records = _trade_records_for_wib_date(report_date)
    sells = [item for item in records if str(item.get("side") or "").upper() == "SELL"]
    buys = [item for item in records if str(item.get("side") or "").upper() == "BUY"]
    current_summary = _load_daily_summary()
    governor = _governor_effective_directives()
    report_guard = dict(_daily_guard_state) if str(_daily_guard_state.get("date") or "") == report_date else {}
    start_balance = _parse_numeric(report_guard.get("start_of_day_equity"))
    end_balance = _parse_numeric(report_guard.get("current_equity"))
    if end_balance is None:
        latest_balance_after = None
        for row in reversed(records):
            latest_balance_after = _parse_numeric(row.get("balanceAfter") or row.get("balance_after"))
            if latest_balance_after is not None:
                break
        end_balance = latest_balance_after
    if end_balance is None:
        end_balance = _current_balance_snapshot().get("equity_idr")
    daily_pnl_idr = sum((_parse_numeric(item.get("netPnlIdr") or item.get("net_pnl_idr")) or 0.0) for item in sells)
    daily_pnl_pct = _parse_numeric(report_guard.get("daily_pnl_pct"))
    if daily_pnl_pct is None and start_balance and end_balance is not None and start_balance > 0:
        daily_pnl_pct = (end_balance - start_balance) / start_balance
    if start_balance is not None and end_balance is not None:
        daily_pnl_idr = end_balance - start_balance

    report_day = datetime.fromisoformat(report_date).date()
    weekly_sells: List[Dict[str, Any]] = []
    for record in _load_trade_log_records():
        trade_date = _to_wib_date_string(record.get("timestamp") or record.get("ts") or record.get("entry_at"))
        if not trade_date:
            continue
        try:
            trade_day = datetime.fromisoformat(trade_date).date()
        except Exception:
            continue
        if 0 <= (report_day - trade_day).days <= 6 and str(record.get("side") or "").upper() == "SELL":
            weekly_sells.append(record)
    weekly_pnl_idr = sum((_parse_numeric(item.get("netPnlIdr") or item.get("net_pnl_idr")) or 0.0) for item in weekly_sells)
    # BUG FIX: Use a more adaptive base. Start with estimated start-of-week equity,
    # but floor it to 10% of current equity or 10k IDR to prevent percentage explosions.
    current_eq = (end_balance or 0.0)
    weekly_base = max(current_eq - weekly_pnl_idr, current_eq * 0.1, 10000.0)
    weekly_pnl_pct = weekly_pnl_idr / weekly_base
    
    wins = sum(1 for item in sells if (_parse_numeric(item.get("netPnlIdr") or item.get("net_pnl_idr")) or 0.0) > 0)
    losses = max(len(sells) - wins, 0)
    
    # Improved coin tracking: Coins traded today (bought OR sold)
    traded_today = sorted(
        dict.fromkeys(
            [str(item.get("pair") or item.get("pairId") or "").lower().strip() for item in buys + sells if str(item.get("pair") or item.get("pairId") or "").strip()]
            + list(current_summary.get("coins_bought_today") or [])
        )
    )
    
    learning_reviews = [item for item in _load_learning_review_history() if str(item.get("wib_date") or "") == report_date]
    latest_learning = learning_reviews[-1] if learning_reviews else (current_summary.get("last_learning_review") or {})
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_date": report_date,
        "start_balance_idr": start_balance,
        "end_balance_idr": end_balance,
        "daily_pnl_idr": daily_pnl_idr,
        "daily_pnl_pct": daily_pnl_pct,
        "weekly_pnl_idr": weekly_pnl_idr,
        "weekly_pnl_pct": weekly_pnl_pct,
        "closed_trades": len(sells),
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / max(len(sells), 1)) if sells else 0.0,
        "coins_bought_today": traded_today,
        "last_learning_review": latest_learning,
        "brain_plan": {
            "plan_id": governor.get("plan_id"),
            "plan_state": governor.get("plan_state"),
            "brain_mode": governor.get("brain_mode"),
            "market_regime": governor.get("market_regime"),
            "capital_posture": governor.get("capital_posture"),
            "reason": governor.get("reason"),
            "why": list(governor.get("why") or [])[:4],
            "confidence": governor.get("effective_confidence") or governor.get("confidence"),
            "expires_at": governor.get("expires_at"),
            "ops_alerts": list(governor.get("ops_alerts") or [])[:4],
            "focus_pairs": list((governor.get("indodax") or {}).get("focus_pairs") or [])[:5],
            "risks_to_watch": list(governor.get("what_could_make_this_wrong") or [])[:4],
        },
        "lessons": list(latest_learning.get("lessons") or []),
        "next_strategy": str(latest_learning.get("strategy") or latest_learning.get("summary") or "Prioritaskan pair high-trust, tekan kerugian, dan jaga rotasi modal tetap cepat.").strip(),
        "risks": list(latest_learning.get("risks") or []),
        "sovereign_review": current_summary.get("last_sovereign_review") if isinstance(current_summary.get("last_sovereign_review"), dict) else {},
        "green_target": {
            "target_pct": float(os.getenv("KIBOT_GREEN_TARGET_DAILY_PCT", "0.003")),
            "gap_pct": max(float(os.getenv("KIBOT_GREEN_TARGET_DAILY_PCT", "0.003")) - float(daily_pnl_pct or 0.0), 0.0),
            "status": (
                "AHEAD"
                if float(daily_pnl_pct or 0.0) >= float(os.getenv("KIBOT_GREEN_TARGET_DAILY_PCT", "0.003"))
                else ("CHASING_GREEN" if float(daily_pnl_pct or 0.0) >= 0.0 else "RECOVERY_MODE")
            ),
        },
    }
    _store_daily_report(report)
    return report


def _build_sovereign_daily_review_fallback(report: Dict[str, Any]) -> Dict[str, Any]:
    daily_pct = float(_parse_numeric(report.get("daily_pnl_pct")) or 0.0)
    weekly_pct = float(_parse_numeric(report.get("weekly_pnl_pct")) or 0.0)
    brain_plan = report.get("brain_plan") if isinstance(report.get("brain_plan"), dict) else {}
    focus_pairs = list(brain_plan.get("focus_pairs") or [])[:4]
    root_causes: List[str] = []
    missed: List[str] = []
    lessons: List[str] = []
    risks: List[str] = list(report.get("risks") or [])[:3]
    params: List[str] = []

    if daily_pct < 0:
        root_causes.append("PnL harian negatif menandakan posture atau filter entry belum cukup ketat.")
        params.append("Naikkan standar entry untuk pair dengan win-rate lemah dan spread kurang bersih.")
    if weekly_pct < 0:
        root_causes.append("PnL mingguan masih di bawah nol, jadi pair memory dan rotasi modal harus lebih disiplin.")
        params.append("Turunkan agresi modal sampai dua sesi hijau berturut-turut tercapai.")
    if int(report.get("closed_trades") or 0) == 0:
        root_causes.append("Hari ini hampir tidak ada trade tutup, sehingga stagnasi perlu dijelaskan dari sisi gate, modal, atau kualitas sinyal.")
        missed.append("Periksa peluang yang lolos scan tetapi tertahan gate terlalu lama.")
    if not focus_pairs:
        missed.append("Belum ada fokus pair yang cukup kuat dari sovereign plan terakhir.")
    else:
        lessons.append("Gunakan fokus pair dari brain plan sebagai shortlist utama, bukan menebar entry ke pair abu-abu.")
    if not risks:
        risks.append("Perubahan regime mendadak dan stale state lintas server bisa membuat plan salah arah.")
    if not lessons:
        lessons.append("Pertahankan kualitas sinyal di atas frekuensi; target utama tetap pertumbuhan yang konsisten.")

    tomorrow_mode = "CONTROLLED"
    if daily_pct <= -0.01 or weekly_pct <= -0.03:
        tomorrow_mode = "SURVIVAL"
    elif daily_pct > 0.003 and weekly_pct >= 0:
        tomorrow_mode = "CONTROLLED_AGGRESSIVE"

    return {
        "summary": " | ".join((root_causes or lessons)[:2]),
        "root_causes": root_causes[:4],
        "missed_opportunities": missed[:4],
        "lessons": lessons[:4],
        "risks": risks[:4],
        "parameter_recommendations": params[:4],
        "tomorrow_mode": tomorrow_mode,
        "tomorrow_focus": focus_pairs,
        "source": "heuristic_fallback",
    }


def _run_sovereign_daily_review(report: Dict[str, Any]) -> Dict[str, Any]:
    fallback = _build_sovereign_daily_review_fallback(report)
    result = dict(fallback)
    polymarket_snapshot = _brain.snapshot().get("polymarket") if hasattr(_brain, "snapshot") else {}
    if AI_ROUTER_ENABLED:
        try:
            ai_result = query_ai(
                "SOVEREIGN_DAILY_REVIEW",
                {
                    "daily_report": report,
                    "latest_learning": _load_json_file(LEARNING_REVIEW_PATH, {}),
                    "pair_memory": _pair_memory_brief(limit=6),
                    "polymarket": polymarket_snapshot if isinstance(polymarket_snapshot, dict) else {},
                },
                cache_ttl_minutes=30,
                force_refresh=True,
            )
            if isinstance(ai_result, dict) and ai_result:
                result = {
                    "summary": str(ai_result.get("summary") or fallback.get("summary") or "").strip(),
                    "root_causes": _coerce_learning_list(ai_result.get("root_causes") or fallback.get("root_causes"))[:5],
                    "missed_opportunities": _coerce_learning_list(ai_result.get("missed_opportunities") or fallback.get("missed_opportunities"))[:5],
                    "lessons": _coerce_learning_list(ai_result.get("lessons") or fallback.get("lessons"))[:5],
                    "risks": _coerce_learning_list(ai_result.get("risks") or fallback.get("risks"))[:5],
                    "parameter_recommendations": _coerce_learning_list(ai_result.get("parameter_recommendations") or fallback.get("parameter_recommendations"))[:5],
                    "tomorrow_mode": str(ai_result.get("tomorrow_mode") or fallback.get("tomorrow_mode") or "CONTROLLED").strip().upper(),
                    "tomorrow_focus": _coerce_learning_list(ai_result.get("tomorrow_focus") or fallback.get("tomorrow_focus"))[:5],
                    "source": str(ai_result.get("provider") or ai_result.get("source") or "ai_router"),
                }
        except Exception as error:
            print(f"[KIBOT][SOVEREIGN_REVIEW][WARN] ai review failed reason={error}", flush=True)
    result["at"] = datetime.now(timezone.utc).isoformat()
    result["report_date"] = str(report.get("report_date") or _operational_wib_date())
    _update_daily_summary("sovereign_review", result)
    library = _load_pattern_library()
    reviews = [item for item in list(library.get("daily_reviews") or []) if item.get("report_date") != result["report_date"]]
    reviews.append(result)
    library["daily_reviews"] = sorted(reviews, key=lambda item: str(item.get("report_date") or ""))[-30:]
    incidents = list(library.get("ops_incidents") or [])
    for item in list(result.get("risks") or [])[:2]:
        incidents.append({"at": result["at"], "risk": item, "report_date": result["report_date"]})
    library["ops_incidents"] = incidents[-30:]
    if result.get("tomorrow_focus"):
        pair_bias = library.get("pair_bias") if isinstance(library.get("pair_bias"), dict) else {}
        for pair in list(result.get("tomorrow_focus") or [])[:5]:
            pair_key = _normalize_pair_id(pair)
            if not pair_key:
                continue
            entry = pair_bias.get(pair_key) if isinstance(pair_bias.get(pair_key), dict) else {}
            entry["last_focus_at"] = result["at"]
            entry["last_mode"] = result.get("tomorrow_mode")
            pair_bias[pair_key] = entry
        library["pair_bias"] = pair_bias
    weekly_patterns = list(library.get("weekly_patterns") or [])
    if result.get("summary"):
        weekly_patterns.append({"at": result["at"], "summary": result["summary"], "report_date": result["report_date"]})
    library["weekly_patterns"] = weekly_patterns[-20:]
    library["updated_at"] = result["at"]
    _save_pattern_library(library)
    _append_runtime_event(
        "sovereign_daily_review",
        {
            "summary": result.get("summary"),
            "tomorrow_mode": result.get("tomorrow_mode"),
            "focus": list(result.get("tomorrow_focus") or [])[:4],
            "source": result.get("source"),
        },
    )
    _append_jsonl(
        DECISION_LEDGER_PATH,
        {
            "at": result["at"],
            "profile": "SLOW_REVIEW",
            "reason": "daily_postmortem",
            "report_date": result["report_date"],
            "summary": result.get("summary"),
            "tomorrow_mode": result.get("tomorrow_mode"),
            "tomorrow_focus": list(result.get("tomorrow_focus") or [])[:5],
            "source": result.get("source"),
        },
    )
    return result


def _render_daily_report_text(report: Dict[str, Any]) -> str:
    daily_pct = (_parse_numeric(report.get("daily_pnl_pct")) or 0.0) * 100.0
    weekly_pct = (_parse_numeric(report.get("weekly_pnl_pct")) or 0.0) * 100.0
    green_target = report.get("green_target") if isinstance(report.get("green_target"), dict) else {}
    brain_plan = report.get("brain_plan") if isinstance(report.get("brain_plan"), dict) else {}
    green_target_pct = (_parse_numeric(green_target.get("target_pct")) or 0.0) * 100.0
    green_gap_pct = (_parse_numeric(green_target.get("gap_pct")) or 0.0) * 100.0
    bought = ", ".join(str(item).upper() for item in list(report.get("coins_bought_today") or [])[:8]) or "tidak ada"
    lessons = list(report.get("lessons") or [])[:3]
    sovereign_review = report.get("sovereign_review") if isinstance(report.get("sovereign_review"), dict) else {}
    if not lessons:
        lessons = [str(report.get("next_strategy") or "Fokus ke pair paling bersih, kurangi whipsaw, dan pertahankan disiplin exit.")]
    lines = [
        f"📘 KiBot Midnight Report — {report.get('report_date', '?')} WIB",
        "",
        f"Saldo akhir hari: Rp{(_parse_numeric(report.get('end_balance_idr')) or 0.0):,.0f}",
        f"PnL hari ini: {daily_pct:+.2f}% (Rp{(_parse_numeric(report.get('daily_pnl_idr')) or 0.0):,.0f})",
        f"PnL 7 hari: {weekly_pct:+.2f}% (Rp{(_parse_numeric(report.get('weekly_pnl_idr')) or 0.0):,.0f})",
        f"Target hijau harian: +{green_target_pct:.2f}% | gap tersisa: {green_gap_pct:.2f}%",
        f"Trade tutup: {int(report.get('closed_trades') or 0)} | Win rate: {float(report.get('win_rate') or 0.0) * 100:.0f}%",
        f"Koin dibeli hari ini: {bought}",
        "",
        "Pelajaran untuk sesi berikutnya:",
    ]
    for lesson in lessons:
        lines.append(f"• {lesson}")
    strategy = str(report.get("next_strategy") or "").strip()
    if brain_plan:
        lines.extend(
            [
                "",
                (
                    "Brain posture: "
                    f"{str(brain_plan.get('brain_mode') or '?')} | "
                    f"regime {str(brain_plan.get('market_regime') or '?')} | "
                    f"confidence {(float(_parse_numeric(brain_plan.get('confidence')) or 0.0) * 100):.0f}%"
                ),
            ]
        )
        why_items = list(brain_plan.get("why") or [])[:2]
        if why_items:
            lines.append("Kenapa posture ini:")
            for item in why_items:
                lines.append(f"• {item}")
        focus_pairs = ", ".join(str(item).upper() for item in list(brain_plan.get("focus_pairs") or [])[:4])
        if focus_pairs:
            lines.append(f"Fokus pair: {focus_pairs}")
        ops_alerts = list(brain_plan.get("ops_alerts") or [])[:2]
        if ops_alerts:
            lines.append("Alert sistem:")
            for item in ops_alerts:
                lines.append(f"• {item}")
        risks_to_watch = list(brain_plan.get("risks_to_watch") or [])[:2]
        if risks_to_watch:
            lines.append("Yang bisa bikin rencana ini salah:")
            for item in risks_to_watch:
                lines.append(f"• {item}")
    if sovereign_review:
        root_causes = list(sovereign_review.get("root_causes") or [])[:2]
        if root_causes:
            lines.extend(["", "Akar masalah hari ini:"])
            for item in root_causes:
                lines.append(f"• {item}")
        missed = list(sovereign_review.get("missed_opportunities") or [])[:2]
        if missed:
            lines.append("Peluang yang perlu diburu/diusut:")
            for item in missed:
                lines.append(f"• {item}")
        params = list(sovereign_review.get("parameter_recommendations") or [])[:2]
        if params:
            lines.append("Perubahan yang direkomendasikan:")
            for item in params:
                lines.append(f"• {item}")
        tomorrow_mode = str(sovereign_review.get("tomorrow_mode") or "").strip()
        tomorrow_focus = ", ".join(str(item).upper() for item in list(sovereign_review.get("tomorrow_focus") or [])[:4])
        if tomorrow_mode:
            lines.append(f"Mode besok: {tomorrow_mode}")
        if tomorrow_focus:
            lines.append(f"Fokus besok: {tomorrow_focus}")
    if strategy:
        lines.extend(["", f"Strategi besok: {strategy}"])
    return "\n".join(lines)


def _collect_learning_review_snapshot() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=LEARNING_REVIEW_INTERVAL_SEC)
    recent_events = [
        event
        for event in _recent_runtime_events
        if (_parse_datetime(event.get("at")) or now) >= window_start
    ]
    event_counts: Dict[str, int] = {}
    why_not: Dict[str, int] = {}
    screen_focus: List[str] = []
    for event in recent_events:
        kind = str(event.get("kind") or "unknown")
        event_counts[kind] = event_counts.get(kind, 0) + 1
        detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
        if kind in {"learning_block", "what_if", "emergency_veto_sell", "daily_hard_stop"}:
            reason = str(detail.get("reason") or detail.get("recommendation") or kind).strip()
            why_not[reason] = why_not.get(reason, 0) + 1
        top_pair = str(detail.get("top_pair") or detail.get("pair") or "").lower().strip()
        if top_pair:
            screen_focus.append(top_pair)
    balance = _current_balance_snapshot()
    trade_metrics = _get_trade_metrics_today()
    whatif_payload = _load_json_file(WHATIF_RESULTS_PATH, {})
    top_whatif = []
    for pair in list(whatif_payload.get("topOpportunities") or [])[:5]:
        if isinstance(pair, str) and pair.strip():
            top_whatif.append(pair.strip().lower())
    top_screen_candidates = []
    for item in list(_screen_cache or [])[:5]:
        if not isinstance(item, dict):
            continue
        analysis = item.get("analysis")
        top_screen_candidates.append(
            {
                "pair": str(item.get("pair_id") or "").lower(),
                "score": round(float(getattr(analysis, "legitimacy_score", 0.0) or 0.0), 2),
                "phase": str(getattr(analysis, "pump_phase", "") or ""),
                "recommendation": str(getattr(analysis, "entry_recommendation", "") or ""),
            }
        )
    active_positions = [
        {
            "pair": pair,
            "pnl_pct": _parse_numeric(row.get("pnlPct") or row.get("pnl_pct")) or 0.0,
            "entry_price": _parse_numeric(row.get("entryPrice") or row.get("entry_price")),
        }
        for pair, row in list(_active_positions_cache.items())[:8]
        if isinstance(row, dict)
    ]
    brain_snapshot = _brain.snapshot() if hasattr(_brain, "snapshot") else {}
    return {
        "at_utc": now.isoformat(),
        "wib_date": _operational_wib_date(),
        "market_regime": _daily_summary_market_regime() if DAILY_SUMMARY_ENABLED else "UNKNOWN",
        "daily_pnl_pct": _daily_guard_state.get("daily_pnl_pct"),
        "external_cashflow_idr": _daily_guard_state.get("external_cashflow_idr"),
        "external_cashflow_reason": _daily_guard_state.get("external_cashflow_reason"),
        "equity_idr": balance.get("equity_idr"),
        "free_cash_idr": balance.get("free_cash_idr"),
        "trade_metrics": trade_metrics,
        "active_positions": active_positions,
        "active_position_pairs": _active_position_pairs(),
        "scan_focus_pairs": list(dict.fromkeys(screen_focus))[:6],
        "top_screen_candidates": top_screen_candidates,
        "whatif_top_opportunities": top_whatif,
        "event_counts": event_counts,
        "why_not_counts": why_not,
        "veto_metrics": dict(_veto_metrics),
        "daily_guard": {
            "hard_stopped": bool(_daily_guard_state.get("hard_stopped")),
            "reason": str(_daily_guard_state.get("reason") or ""),
            "reset_at": str(_daily_guard_state.get("reset_at") or ""),
        },
        "brain_context": {
            "daily_target": brain_snapshot.get("daily_target", {}),
            "market_pulse": brain_snapshot.get("market_pulse", {}),
            "watch_reviews": list(brain_snapshot.get("watch_reviews") or [])[:3],
            "provider_status": brain_snapshot.get("provider_status", {}),
        },
        "math_review": {
            "last_action": _math_review_last_action,
            "last_reason": _math_review_last_reason,
        },
        "recent_notes": list(_load_daily_summary().get("recent_notes") or [])[-8:],
    }


def _build_learning_review_fallback(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    trade_metrics = snapshot.get("trade_metrics") if isinstance(snapshot.get("trade_metrics"), dict) else {}
    veto_metrics = snapshot.get("veto_metrics") if isinstance(snapshot.get("veto_metrics"), dict) else {}
    why_not_counts = snapshot.get("why_not_counts") if isinstance(snapshot.get("why_not_counts"), dict) else {}
    top_screen_candidates = snapshot.get("top_screen_candidates") if isinstance(snapshot.get("top_screen_candidates"), list) else []
    top_whatif = snapshot.get("whatif_top_opportunities") if isinstance(snapshot.get("whatif_top_opportunities"), list) else []
    brain_context = snapshot.get("brain_context") if isinstance(snapshot.get("brain_context"), dict) else {}
    brain_market_pulse = brain_context.get("market_pulse") if isinstance(brain_context.get("market_pulse"), dict) else {}
    brain_daily_target = brain_context.get("daily_target") if isinstance(brain_context.get("daily_target"), dict) else {}
    daily_pnl_pct = _parse_numeric(snapshot.get("daily_pnl_pct")) or 0.0
    active_pairs = [str(item).lower() for item in list(snapshot.get("active_position_pairs") or []) if str(item).strip()]

    lessons: List[str] = []
    risks: List[str] = []
    strategy_parts: List[str] = []

    if daily_pnl_pct <= -0.015:
        lessons.append("PnL intraday sedang tertekan; kecilkan agresi dan prioritaskan validasi ulang sebelum entry baru.")
        risks.append("Loss lanjutan bisa memicu hard stop harian bila entry dipaksakan.")
        strategy_parts.append("mode defensif")
    elif daily_pnl_pct >= 0.01:
        lessons.append("PnL masih sehat; pertahankan tempo tapi jangan longgarkan threshold terlalu cepat.")
        strategy_parts.append("kunci profit yang sudah ada")

    if str(brain_market_pulse.get("risk_bias") or "").upper() == "RISK_OFF":
        lessons.append("Market pulse eksternal sedang risk-off; naikkan standar entry dan prioritaskan proteksi modal.")
        risks.append("Headline eksternal mengarah ke risk-off, jadi breakout palsu lebih berbahaya.")
    elif str(brain_market_pulse.get("risk_bias") or "").upper() == "RISK_ON":
        strategy_parts.append("manfaatkan risk-on hanya pada pair yang tetap lolos veto")

    target_status = str(brain_daily_target.get("status") or "")
    target_gap_pct = (_parse_numeric(brain_daily_target.get("gap_pct")) or 0.0) * 100.0
    if target_status == "RECOVERY_MODE":
        strategy_parts.append("recovery bertahap untuk kembali hijau")
    elif target_status == "CHASING_GREEN" and target_gap_pct > 0:
        strategy_parts.append(f"kejar target hijau dengan gap {target_gap_pct:.2f}% tanpa longgarkan guardrail")

    total_trades = int(trade_metrics.get("total_trades") or 0)
    win_rate = float(trade_metrics.get("win_rate") or 0.0)
    ev_per_trade = float(trade_metrics.get("ev_per_trade") or 0.0)
    if total_trades >= 3 and ev_per_trade <= 0:
        lessons.append("EV/trade belum positif; fokus ke pair yang lolos veto bersih dan skip setup abu-abu.")
        risks.append("Trade tambahan dengan expectancy negatif akan memperdalam fee bleed.")
    elif total_trades >= 3 and win_rate >= 0.6 and ev_per_trade > 0:
        lessons.append("Expectancy 30 menit terakhir positif; lanjutkan pada cluster pair yang win-rate-nya konsisten.")

    rejected = int(veto_metrics.get("rejected") or 0)
    approved = int(veto_metrics.get("approved") or 0)
    if rejected > max(approved * 2, 6):
        lessons.append("Mayoritas scan masih tertolak veto; threshold scan perlu fokus ke pair paling likuid dan paling sinkron.")
        strategy_parts.append("prioritaskan kualitas di atas frekuensi")

    if why_not_counts:
        top_reason = sorted(why_not_counts.items(), key=lambda item: item[1], reverse=True)[0][0]
        risks.append(f"Why-not terbanyak saat ini: {top_reason}.")

    if active_pairs:
        lessons.append(f"Review posisi aktif: {', '.join(pair.upper() for pair in active_pairs[:4])}. Exit harus didahulukan sebelum rotasi baru.")

    if top_screen_candidates:
        screen_focus = ", ".join(
            candidate["pair"].upper()
            for candidate in top_screen_candidates
            if isinstance(candidate, dict) and candidate.get("pair")
        )
        if screen_focus:
            strategy_parts.append(f"pantau fokus scan {screen_focus}")

    if top_whatif:
        strategy_parts.append(
            "sinkronkan peluang scan dengan what-if terbaik " + ", ".join(str(pair).upper() for pair in top_whatif[:3])
        )

    if not lessons:
        lessons.append("Data 30 menit terakhir belum kuat; pertahankan filter saat ini dan kumpulkan sample yang lebih bersih.")
    if not risks:
        risks.append("Waspadai whipsaw pada pair momentum pendek dan fee bleed dari exit terlalu cepat.")
    if not strategy_parts:
        strategy_parts.append("pertahankan risk gate sekarang")

    summary = " | ".join(lessons[:2])
    strategy = "; ".join(dict.fromkeys(strategy_parts))
    return {
        "summary": summary,
        "strategy": strategy,
        "lessons": lessons[:5],
        "risks": risks[:5],
        "source": "heuristic_fallback",
    }


def _coerce_learning_text(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
            try:
                parsed = ast.literal_eval(stripped)
                if parsed is not value:
                    return _coerce_learning_text(parsed)
            except Exception:
                pass
        return stripped
    if isinstance(value, dict):
        for key in ("summary", "strategy", "action", "reason", "status", "message"):
            nested = _coerce_learning_text(value.get(key))
            if nested:
                return nested
        flattened = [f"{key}: {_coerce_learning_text(item)}" for key, item in value.items() if _coerce_learning_text(item)]
        return "; ".join(flattened)
    if isinstance(value, list):
        return "; ".join(filter(None, (_coerce_learning_text(item) for item in value)))
    if value is None:
        return ""
    return str(value).strip()


def _coerce_learning_list(value: Any) -> List[str]:
    if isinstance(value, list):
        items = value
    else:
        parsed = _coerce_learning_text(value)
        return [parsed] if parsed else []
    out: List[str] = []
    for item in items:
        text = _coerce_learning_text(item)
        if text:
            out.append(text)
    return out


def _run_strategy_learning_review() -> Dict[str, Any]:
    snapshot = _collect_learning_review_snapshot()
    fallback = _build_learning_review_fallback(snapshot)
    result = {
        "at": snapshot["at_utc"],
        "wib_date": snapshot["wib_date"],
        "summary": str(fallback.get("summary") or "Belum cukup data 30 menit terakhir; pertahankan risk gate saat ini."),
        "strategy": str(fallback.get("strategy") or "Jaga modal, prioritaskan pair dengan why-not rendah dan veto rejection minim."),
        "lessons": list(fallback.get("lessons") or []),
        "risks": list(fallback.get("risks") or []),
        "source": str(fallback.get("source") or "fallback"),
    }
    if AI_ROUTER_ENABLED:
        prompt = (
            "Kamu adalah assistant pembelajaran strategi untuk bot trading crypto.\n"
            "PENTING: dilarang memberi instruksi BUY/SELL langsung. Fokusmu hanya evaluasi belajar, guardrail, dan strategi 30 menit berikutnya.\n"
            "Gunakan pendekatan refleksi cepat: ringkas apa yang gagal, apa yang bekerja, kenapa veto/why-not muncul, dan bagaimana menyesuaikan strategi 30 menit berikutnya tanpa memberi instruksi trading langsung.\n"
            "Jawab JSON dengan keys: summary, strategy, lessons, risks.\n\n"
            f"Data 30 menit terakhir:\n{json.dumps(snapshot, ensure_ascii=True, indent=2)}"
        )
        try:
            routed_text, provider = _call_ai_router(
                task="learning_review",
                system_prompt="Jawab JSON singkat. Hindari instruksi trading langsung.",
                user_prompt=prompt,
                model_hint=POST_MORTEM_MODEL,
                timeout_sec=min(POST_MORTEM_TIMEOUT_SEC, 18.0),
            )
            parsed = _parse_json_candidate(routed_text) if routed_text else None
            if isinstance(parsed, dict) and parsed:
                result = {
                    "at": snapshot["at_utc"],
                    "wib_date": snapshot["wib_date"],
                    "summary": _coerce_learning_text(parsed.get("summary") or result["summary"]),
                    "strategy": _coerce_learning_text(parsed.get("strategy") or result["strategy"]),
                    "lessons": _coerce_learning_list(parsed.get("lessons") or result["lessons"])[:5],
                    "risks": _coerce_learning_list(parsed.get("risks") or result["risks"])[:5],
                    "source": provider or "ai_router",
                }
        except Exception as error:
            print(f"[KIBOT][LEARNING_REVIEW][WARN] ai review failed reason={error}", flush=True)
    _save_learning_review(result)
    _update_daily_summary(
        "learning_review",
        {
            "summary": result.get("summary"),
            "strategy": result.get("strategy"),
            "lessons": result.get("lessons"),
            "risks": result.get("risks"),
        },
    )
    _append_runtime_event(
        "learning_review",
        {
            "summary": result.get("summary"),
            "strategy": result.get("strategy"),
            "source": result.get("source"),
        },
    )
    _write_runtime_note(force=True)
    return result


def _strategy_learning_loop() -> None:
    last_run_at = 0.0
    while not _shutdown_event.is_set():
        try:
            now_ts = time.time()
            if (now_ts - last_run_at) >= max(300, LEARNING_REVIEW_INTERVAL_SEC):
                last_run_at = now_ts
                _run_strategy_learning_review()
        except Exception as error:
            print(f"[KIBOT][LEARNING_REVIEW][ERROR] {error}", flush=True)
        if _shutdown_event.wait(30.0):
            break


def _emit_midnight_liquidation_for_pairs(pairs: List[str]) -> None:
    for pair in pairs:
        _emit_emergency_veto_sell(
            pair=pair,
            reason="midnight_reset_liquidation",
            confidence=0.99,
            expected_net_pct=0.15,
            extra_payload={"cycle": "daily_midnight_reset"},
        )


def _complete_midnight_reset(new_date: str, *, reason: str) -> None:
    current_equity = _current_balance_snapshot().get("equity_idr")
    _daily_guard_state.update(
        {
            "date": new_date,
            "start_of_day_equity": current_equity,
            "current_equity": current_equity,
            "daily_pnl_pct": 0.0,
            "external_cashflow_idr": 0.0,
            "external_cashflow_detected_at": "",
            "external_cashflow_reason": "",
            "hard_stopped": False,
            "triggered_at": "",
            "reset_at": "",
            "reason": "",
        }
    )
    _save_daily_guard_state()
    _gate_state["daily_hard_stop"] = False
    _gate_state["daily_hard_stop_reason"] = ""
    _gate_state["daily_hard_stop_reset_at"] = ""
    _save_gate_state()
    _daily_reset_extra_state()
    _reset_intraday_metrics()
    _daily_cycle_state.update(
        {
            "active_wib_date": new_date,
            "pending_new_date": "",
            "pending_previous_date": "",
            "pending_started_at": "",
            "last_liquidation_emit_at": "",
            "last_reset_completed_date": new_date,
            "alert_sent_for_pending_cycle": False,
        }
    )
    _save_daily_cycle_state()
    _write_json_file(DAILY_SUMMARY_PATH, _default_daily_summary(new_date))
    _resume_new_entries(f"midnight_reset_completed:{reason}")
    _append_runtime_event("midnight_reset_completed", {"new_date": new_date, "reason": reason})
    _write_runtime_note(force=True)


def _start_midnight_rollover(previous_date: str, new_date: str) -> None:
    report = _build_daily_report_payload(previous_date)
    report["sovereign_review"] = _run_sovereign_daily_review(report)
    _store_daily_report(report)
    _telegram_send(_render_daily_report_text(report), category="daily_report")
    _daily_cycle_state["last_daily_report_date"] = previous_date
    _save_daily_cycle_state()
    pairs = _active_position_pairs()
    if not pairs:
        _complete_midnight_reset(new_date, reason="no_active_positions")
        return
    _daily_cycle_state.update(
        {
            "pending_new_date": new_date,
            "pending_previous_date": previous_date,
            "pending_started_at": datetime.now(timezone.utc).isoformat(),
            "last_liquidation_emit_at": datetime.now(timezone.utc).isoformat(),
            "last_daily_report_date": previous_date,
            "alert_sent_for_pending_cycle": False,
        }
    )
    _save_daily_cycle_state()
    _suspend_new_entries("midnight_reset_liquidation")
    _emit_midnight_liquidation_for_pairs(pairs)
    _append_runtime_event("midnight_reset_started", {"from_date": previous_date, "to_date": new_date, "pairs": pairs})
    _write_runtime_note(force=True)


def _daily_cycle_loop() -> None:
    while not _shutdown_event.is_set():
        try:
            actual_today = _wib_today_str()
            pending_new_date = str(_daily_cycle_state.get("pending_new_date") or "")
            if pending_new_date:
                active_pairs = _active_position_pairs()
                if active_pairs:
                    last_emit = _parse_datetime(_daily_cycle_state.get("last_liquidation_emit_at"))
                    now = datetime.now(timezone.utc)
                    if last_emit is None or (now - last_emit).total_seconds() >= MIDNIGHT_RESET_RETRY_SEC:
                        _daily_cycle_state["last_liquidation_emit_at"] = now.isoformat()
                        _save_daily_cycle_state()
                        _emit_midnight_liquidation_for_pairs(active_pairs)
                    pending_started = _parse_datetime(_daily_cycle_state.get("pending_started_at")) or now
                    if (
                        not bool(_daily_cycle_state.get("alert_sent_for_pending_cycle"))
                        and (now - pending_started).total_seconds() >= MIDNIGHT_RESET_ALERT_AFTER_SEC
                    ):
                        _telegram_send(
                            f"🚨 Midnight reset masih menunggu posisi rata. Pairs: {', '.join(active_pairs[:6]).upper()}",
                            category="urgent",
                        )
                        _daily_cycle_state["alert_sent_for_pending_cycle"] = True
                        _save_daily_cycle_state()
                else:
                    _complete_midnight_reset(pending_new_date, reason="positions_flat")
            elif _operational_wib_date() != actual_today:
                _start_midnight_rollover(_operational_wib_date(), actual_today)
        except Exception as error:
            print(f"[KIBOT][MIDNIGHT][ERROR] {error}", flush=True)
        if _shutdown_event.wait(15.0):
            break


def _heartbeat_loop() -> None:
    interval = max(0.05, MANAGER_HEARTBEAT_INTERVAL_SEC)
    while not _shutdown_event.is_set():
        try:
            _emit_trinity_heartbeat()
            _append_runtime_event("trinity_heartbeat_emit", {"sender": "kibot"})
        except Exception as error:
            print(f"[KIBOT][HEARTBEAT][WARN] emit failed reason={error}", flush=True)
        if _shutdown_event.wait(timeout=interval):
            break


def _write_runtime_note(*, force: bool = False) -> None:
    global _last_runtime_note_write_at
    now_ts = time.time()
    if not force and (now_ts - _last_runtime_note_write_at) < max(5, RUNTIME_NOTE_MIN_INTERVAL_SEC):
        return
    _last_runtime_note_write_at = now_ts
    note = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "service": "kibot_manager",
        "operational_wib_date": _operational_wib_date(),
        "actual_wib_date": _wib_today_str(),
        "midnight_reset_pending": _midnight_reset_pending(),
        "daily_cycle_state": dict(_daily_cycle_state),
        "host_bind": f"{UDP_BIND_HOST}:{UDP_BIND_PORT}",
        "KiBot_target": f"{KiBot_UDP_HOST}:{KiBot_UDP_PORT}" if KiBot_UDP_HOST else "",
        "system_state": str(_gate_state.get("entry_state") or "HEALTHY"),
        "trading_mode": str(_gate_state.get("mode") or "CONSERVATIVE"),
        "api_fail_streak": _api_fail_streak,
        "control_plane_healthy": _control_plane_healthy,
        "daily_hard_stop": bool(_daily_guard_state.get("hard_stopped") or _gate_state.get("daily_hard_stop")),
        "daily_pnl_pct": _daily_guard_state.get("daily_pnl_pct"),
        "external_cashflow_idr": _daily_guard_state.get("external_cashflow_idr"),
        "daily_hard_stop_reset_at": _gate_state.get("daily_hard_stop_reset_at") or _daily_guard_state.get("reset_at"),
        "ai_router_enabled": AI_ROUTER_ENABLED,
        "ai_provider_order": _iter_ai_provider_order(),
        "ai_provider_last_status": dict(_ai_provider_last_status),
        "provider_runtime_state": _provider_runtime_state,
        "tracked_active_positions": sorted(_active_positions_cache.keys()),
        "pair_memory_preview": {
            pair_id: {
                "trade_count": int(memory.get("trade_count") or 0),
                "win_rate_now": round(_get_pair_win_rate_now(pair_id), 3),
                "avg_slippage_pct": round(_get_pair_avg_slippage(pair_id, fallback=0.0), 4),
                "cooldown": _is_pair_on_cooldown(pair_id),
                "fake_pump_count": int(memory.get("fake_pump_count") or 0),
            }
            for pair_id, memory in list(_pair_memory.items())[:10]
        },
        "pair_cooldowns": _pair_cooldown_state,
        "remote_scanner_feed": dict(_remote_scanner_feed_state),
        "capital_profile": _adaptive_capital_profile(),
        "strategy_governor": {
            "directives": _governor_effective_directives(),
            "state": dict(_governor_state),
            "loop_targets": {
                "fast_sec": GOVERNOR_FAST_LOOP_SEC,
                "medium_sec": GOVERNOR_MEDIUM_LOOP_SEC,
            },
        },
        "veto_metrics": _veto_metrics,
        "sector_count": len(_last_sector_map),
        "sector_preview": {key: value[:5] for key, value in list(_last_sector_map.items())[:5]},
        "latest_learning_review": _load_json_file(LEARNING_REVIEW_PATH, {}),
        "pattern_library": _load_pattern_library(),
        "brain_assist": _brain.snapshot(),
        "recent_events": list(_recent_runtime_events[-15:]),
    }
    try:
        _write_json_file(RUNTIME_NOTE_PATH, note)
    except Exception as error:
        print(f"[KIBOT][NOTE][WARN] write failed reason={error}", flush=True)


def _classify_provider_failure(message: str) -> Tuple[int, str]:
    raw = (message or "").lower()
    if any(token in raw for token in ["429", "rate", "quota", "too many requests"]):
        return AI_PROVIDER_RATE_LIMIT_COOLDOWN_SEC, "rate_limited"
    if any(token in raw for token in ["timeout", "temporarily", "connection", "network", "bad gateway"]):
        return AI_PROVIDER_NETWORK_COOLDOWN_SEC, "transient_network"
    if "empty_response" in raw:
        return AI_PROVIDER_EMPTY_COOLDOWN_SEC, "empty_response"
    return AI_PROVIDER_DEFAULT_COOLDOWN_SEC, "generic_failure"


def _provider_rank(provider: str) -> Tuple[int, float]:
    state = _provider_runtime_state.get(provider, {})
    success = int(state.get("success_count") or 0)
    failure = int(state.get("failure_count") or 0)
    last_success = float(state.get("last_success_epoch") or 0.0)
    return (success - (failure * 2), last_success)


def _iter_ai_provider_order() -> List[str]:
    configured = [provider for provider in AI_PROVIDER_ORDER if provider]
    return sorted(
        configured,
        key=lambda provider: (
            -_provider_rank(provider)[0],
            -_provider_rank(provider)[1],
            configured.index(provider),
        ),
    )


def _provider_is_available(provider: str, now_ts: float) -> Tuple[bool, str]:
    state = _provider_runtime_state.get(provider, {})
    cooldown_until = float(state.get("cooldown_until_epoch") or 0.0)
    if cooldown_until > now_ts:
        return False, str(state.get("reason") or "cooldown_active")
    return True, ""


def _remember_provider_success(provider: str, task: str) -> None:
    now_ts = time.time()
    state = dict(_provider_runtime_state.get(provider, {}))
    state.update(
        {
            "task": task,
            "last_success_epoch": now_ts,
            "cooldown_until_epoch": 0,
            "reason": "",
            "success_count": int(state.get("success_count") or 0) + 1,
        }
    )
    _provider_runtime_state[provider] = state
    _write_json_file(PROVIDER_STATE_PATH, _provider_runtime_state)
    _update_daily_summary("ai_success", {"provider": provider, "task": task})


def _remember_provider_failure(provider: str, task: str, error_message: str) -> str:
    now_ts = time.time()
    cooldown_sec, reason = _classify_provider_failure(error_message)
    state = dict(_provider_runtime_state.get(provider, {}))
    state.update(
        {
            "task": task,
            "last_failure_epoch": now_ts,
            "cooldown_until_epoch": now_ts + max(30, cooldown_sec),
            "reason": reason,
            "last_error": error_message[:320],
            "failure_count": int(state.get("failure_count") or 0) + 1,
        }
    )
    _provider_runtime_state[provider] = state
    _write_json_file(PROVIDER_STATE_PATH, _provider_runtime_state)
    _update_daily_summary("ai_failure", {"provider": provider, "task": task, "reason": reason})
    return reason


def _parse_json_candidate(text: str) -> Any:
    raw = (text or "").strip()
    raw = "".join(c for c in raw if not (0xD800 <= ord(c) <= 0xDFFF))
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    fenced = re.search(r"\{[\s\S]*\}", raw)
    if fenced:
        try:
            return json.loads(fenced.group(0))
        except Exception:
            return {}
    return {}


def _extract_assistant_text(payload: Any) -> str:
    if isinstance(payload, str):
        raw = payload.strip()
        return "".join(c for c in raw if not (0xD800 <= ord(c) <= 0xDFFF))
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        msg = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
            if texts:
                return "\n".join(texts).strip()
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list) and content:
            first = content[0] if isinstance(content[0], dict) else {}
            text = first.get("text")
            if isinstance(text, str):
                return text.strip()
        if isinstance(content, str):
            return content.strip()
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first.get("content"), dict) else {}
        parts = content.get("parts")
        if isinstance(parts, list) and parts:
            first_part = parts[0] if isinstance(parts[0], dict) else {}
            text = first_part.get("text")
            if isinstance(text, str):
                return text.strip()
    return ""


def _provider_has_credentials(provider: str) -> bool:
    p = provider.lower().strip()
    if p == "ollama":
        return bool(OLLAMA_API_KEY and OLLAMA_API_URL)
    if p == "groq":
        return bool(GROQ_API_KEY)
    if p == "gemini":
        return bool(GEMINI_API_KEY)
    if p == "openrouter":
        return bool(OPENROUTER_API_KEY)
    if p == "cohere":
        return bool(COHERE_API_KEY)
    if p == "blackbox":
        return bool(BLACKBOX_API_KEY)
    return False


def _call_openai_compatible(
    *,
    provider: str,
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: float,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=timeout_sec)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        raise RuntimeError(f"{provider} network error: {type(e).__name__}")
    if response.status_code >= 300:
        raise RuntimeError(f"{provider} status={response.status_code} body={response.text[:240]}")
    return _extract_assistant_text(response.json() or {})


def _call_gemini(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: float,
) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("gemini missing key")
    base = GEMINI_API_URL.rstrip("/")
    # Use API key in header instead of URL to avoid leaking in logs
    url = f"{base}/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"System:\n{system_prompt}\n\nUser:\n{user_prompt}"},
                ],
            },
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 700,
            "responseMimeType": "text/plain",
        },
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        raise RuntimeError(f"gemini network error: {type(e).__name__}")
    if response.status_code >= 300:
        raise RuntimeError(f"gemini status={response.status_code} body={response.text[:240]}")
    return _extract_assistant_text(response.json() or {})


def _call_cohere(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: float,
) -> str:
    if not COHERE_API_KEY:
        raise RuntimeError("cohere missing key")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {COHERE_API_KEY}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    try:
        response = requests.post(COHERE_API_URL, headers=headers, json=payload, timeout=timeout_sec)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        raise RuntimeError(f"cohere network error: {type(e).__name__}")
    if response.status_code >= 300:
        raise RuntimeError(f"cohere status={response.status_code} body={response.text[:240]}")
    return _extract_assistant_text(response.json() or {})


def _call_ollama(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_sec: float,
) -> str:
    if not OLLAMA_API_KEY:
        raise RuntimeError("ollama missing gateway token")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OLLAMA_API_KEY}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
        "keep_alive": os.getenv("KIBOT_OLLAMA_KEEP_ALIVE", "10m"),
        "options": {"temperature": 0.1},
    }
    payload["think"] = _ollama_think_value()
    try:
        response = requests.post(OLLAMA_API_URL, headers=headers, json=payload, timeout=timeout_sec)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        raise RuntimeError(f"ollama network error: {type(e).__name__}")
    if response.status_code >= 300:
        raise RuntimeError(f"ollama status={response.status_code} body={response.text[:240]}")
    return _extract_assistant_text(response.json() or {})


def _ollama_think_value() -> Any:
    raw = os.getenv("KIBOT_OLLAMA_THINK_LEVEL", "").strip().lower()
    if not raw:
        return False
    if raw in {"0", "false", "no", "off", "nothink"}:
        return False
    if raw in {"1", "true", "yes", "on", "think"}:
        return True
    return raw


def _call_provider(
    provider: str,
    *,
    system_prompt: str,
    user_prompt: str,
    model_hint: str = "",
    timeout_sec: float = AI_REQUEST_TIMEOUT_SEC,
) -> str:
    p = provider.lower().strip()
    hint = str(model_hint or "").strip()
    provider_model_hint = hint
    if p == "openrouter" and hint and "/" not in hint:
        provider_model_hint = ""
    elif p == "cohere" and hint and not hint.startswith("command"):
        provider_model_hint = ""
    elif p == "gemini" and hint and not hint.startswith("gemini"):
        provider_model_hint = ""
    elif p == "nvidia" and hint and "/" not in hint:
        provider_model_hint = ""
    if p == "ollama":
        return _call_ollama(
            model=provider_model_hint or OLLAMA_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_sec=timeout_sec,
        )
    if p == "groq":
        return _call_openai_compatible(
            provider="groq",
            api_url=GROQ_API_URL,
            api_key=GROQ_API_KEY,
            model=provider_model_hint or GROQ_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_sec=timeout_sec,
        )
    if p == "openrouter":
        return _call_openai_compatible(
            provider="openrouter",
            api_url=OPENROUTER_API_URL,
            api_key=OPENROUTER_API_KEY,
            model=provider_model_hint or OPENROUTER_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_sec=timeout_sec,
        )
    if p == "blackbox":
        return _call_openai_compatible(
            provider="blackbox",
            api_url=BLACKBOX_API_URL,
            api_key=BLACKBOX_API_KEY,
            model=model_hint or BLACKBOX_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_sec=timeout_sec,
        )
    if p == "cohere":
        return _call_cohere(
            model=provider_model_hint or COHERE_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_sec=timeout_sec,
        )
    if p == "gemini":
        return _call_gemini(
            model=provider_model_hint or GEMINI_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_sec=timeout_sec,
        )
    raise RuntimeError(f"unsupported provider={provider}")


def _call_ai_router(
    *,
    task: str,
    system_prompt: str,
    user_prompt: str,
    model_hint: str = "",
    timeout_sec: float = AI_REQUEST_TIMEOUT_SEC,
) -> Tuple[str, str]:
    global _ai_healthy, _ai_failure_streak, _ai_last_success
    if not AI_ROUTER_ENABLED:
        return "", ""
    provider_errors: Dict[str, str] = {}
    now_ts = time.time()
    for provider in _iter_ai_provider_order():
        if not _provider_has_credentials(provider):
            provider_errors[provider] = "missing_credentials"
            continue
        available, reason = _provider_is_available(provider, now_ts)
        if not available:
            provider_errors[provider] = f"cooldown:{reason}"
            continue
        try:
            raw_text = _call_provider(
                provider,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_hint=model_hint,
                timeout_sec=timeout_sec,
            )
            text = "".join(c for c in raw_text.strip() if not (0xD800 <= ord(c) <= 0xDFFF))
            if not text:
                provider_errors[provider] = "empty_response"
                continue
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            _ai_provider_last_status.update(
                {
                    "provider": provider,
                    "task": task,
                    "at_epoch_ms": now_ms,
                    "ok": True,
                },
            )
            _remember_provider_success(provider, task)
            if not _ai_healthy:
                _ai_healthy = True
                _telegram_send(f"\u2705 AI RECOVERED: {provider} is back online.")
            _ai_failure_streak = 0
            _ai_last_success = time.time()

            _append_runtime_event(
                "ai_provider_success",
                {"provider": provider, "task": task},
            )
            _broadcast_udp(
                {
                    "msgType": "AI_PROVIDER_STATUS",
                    "senderBotId": "kibot",
                    "task": task,
                    "provider": provider,
                    "ok": True,
                    "sentAtEpochMs": now_ms,
                },
            )
            _write_runtime_note(force=True)
            return text, provider
        except Exception as error:
            error_text = str(error)
            reason = _remember_provider_failure(provider, task, error_text)
            provider_errors[provider] = f"{reason}:{error_text}"
            _append_runtime_event(
                "ai_provider_failure",
                {"provider": provider, "task": task, "reason": reason},
            )
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    _ai_provider_last_status.update(
        {
            "provider": "",
            "task": task,
            "at_epoch_ms": now_ms,
            "ok": False,
        },
    )
    _broadcast_udp(
        {
            "msgType": "AI_PROVIDER_STATUS",
            "senderBotId": "kibot",
            "task": task,
            "provider": "",
            "ok": False,
            "errors": provider_errors,
            "sentAtEpochMs": now_ms,
        },
    )
    _append_runtime_event(
        "ai_router_unavailable",
        {"task": task, "errors": provider_errors},
    )
    _write_runtime_note(force=True)

    # ALL AI FAILED (Bug #2)
    _ai_failure_streak += 1
    if _ai_healthy:
        _ai_healthy = False
        _telegram_send("\ud83d\udea8 AI OFFLINE: All providers failed. Entry suspended.")

    return "", ""


def _headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY or SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _supabase_bearer_token(force_refresh: bool = False) -> str:
    if SUPABASE_SERVICE_ROLE_KEY:
        return SUPABASE_SERVICE_ROLE_KEY
    if (
        not force_refresh
        and _supabase_auth_state.get("access_token")
        and float(_supabase_auth_state.get("expires_at") or 0.0) > time.time()
    ):
        return str(_supabase_auth_state.get("access_token"))
    if not (SUPABASE_URL and SUPABASE_ANON_KEY and SUPABASE_USER_EMAIL and SUPABASE_USER_PASSWORD):
        return SUPABASE_KEY
    response = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={
            "email": SUPABASE_USER_EMAIL,
            "password": SUPABASE_USER_PASSWORD,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload.get("access_token") or "")
    expires_in = int(payload.get("expires_in") or 3600)
    if token:
        _supabase_auth_state["access_token"] = token
        _supabase_auth_state["expires_at"] = time.time() + max(60, expires_in - 120)
        _supabase_auth_state["last_error"] = ""
        _supabase_auth_state["last_ok_at"] = _safe_isoformat()
    return token or SUPABASE_KEY


def _authenticated_headers() -> Dict[str, str]:
    bearer = _supabase_bearer_token()
    return {
        "apikey": SUPABASE_ANON_KEY or SUPABASE_KEY,
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
    }


def _iso_to_epoch(value: str) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _load_local_scanner_feed() -> Dict[str, Any]:
    return _load_json_file(SCANNER_FEED_LOCAL_PATH, {})


def _normalize_remote_scanner_signal(signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(signal, dict):
        return None
    pair_id = str(signal.get("pair_indodax") or "").strip().lower()
    exchange = str(signal.get("exchange") or "").strip().upper()
    if not pair_id or not exchange:
        return None
    normalized = dict(signal)
    normalized["type"] = "MULTI_SCANNER_SIGNAL"
    normalized["pair_indodax"] = pair_id
    normalized["exchange"] = exchange
    normalized["base_symbol"] = str(normalized.get("base_symbol") or "").upper()
    normalized["timestamp"] = str(normalized.get("timestamp") or _safe_isoformat())
    normalized["signal_uid"] = str(
        normalized.get("signal_uid")
        or f"{exchange}:{pair_id}:{normalized['timestamp']}"
    )
    return normalized


def _fetch_remote_scanner_feed_cycles(limit: int = 6) -> List[Dict[str, Any]]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    params: Dict[str, str] = {
        "bot_id": f"eq.{REMOTE_SCANNER_FEED_BOT_ID}",
        "category": f"eq.{REMOTE_SCANNER_FEED_CATEGORY}",
        "select": "created_at,metadata,message",
        "order": "created_at.asc",
        "limit": str(max(1, limit)),
    }
    last_created_at = str(_remote_scanner_feed_state.get("last_created_at") or "").strip()
    if last_created_at:
        params["created_at"] = f"gt.{last_created_at}"
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/logs",
        headers=_authenticated_headers(),
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _ensure_env() -> None:
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY/SUPABASE_ANON_KEY")
    # KiBot_UDP_HOST has a default. No need to crash if missing.
    if missing:
        raise RuntimeError(f"Missing env: {', '.join(missing)}")


# Redundant definition removed.


def _emit_trinity_heartbeat() -> None:
    """Sends KIBOT heartbeat to self and updates Redis"""
    global _redis
    try:
        if _redis:
            _redis.set("trinity:heartbeat:batam", time.time())
            _redis.expire("trinity:heartbeat:batam", 60)
    except:
        pass
    sent_at = int(time.time() * 1000)
    for sender_bot_id in ("kibot", "KiBot"):
        payload = {
            "kind": "trinity_state",
            "msgType": "HEARTBEAT",
            "senderBotId": sender_bot_id,
            "sentAtEpochMs": sent_at,
            "activePair": "",
            "safeModeArmed": False,
        }
        _broadcast_udp(payload)


def _coingecko_track_record_score(pair: str) -> float:
    symbol = pair.split("_", 1)[0].lower()
    try:
        response = requests.get(
            f"{COINGECKO_BASE}/search",
            params={"query": symbol},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            return 0.62
        data = response.json() or {}
        coins = data.get("coins") or []
        base_score = 0.8 if coins else 0.58
        adaptive_penalty = _get_adaptive_score_penalty(pair)
        return max(0.0, base_score - adaptive_penalty)
    except Exception as error:
        print(f"[KIBOT][WARN] CoinGecko API error pair={pair} reason={error}", flush=True)
        return 0.60


def _get_adaptive_score_penalty(pair: str) -> float:
    memory = _pair_memory.get(pair.lower().strip(), {})
    trade_count = int(memory.get("trade_count") or 0)
    if trade_count < 3:
        return 0.0
    win_rate = float(memory.get("win_rate_7d") or 0.5)
    avg_pnl = float(memory.get("avg_pnl") or 0.0)
    penalty = 0.0
    if win_rate < 0.30:
        penalty += 0.20
    elif win_rate < 0.40:
        penalty += 0.10
    elif win_rate < 0.50:
        penalty += 0.05
    if avg_pnl < -0.008:
        penalty += 0.10
    if _learning_enabled and _learning_engine is not None:
        penalty += float(_learning_engine.score_penalty(pair))
    return min(penalty, 0.30)


def _fetch_coingecko_trending() -> list[dict[str, Any]]:
    try:
        response = requests.get(
            f"{COINGECKO_BASE}/search/trending",
            timeout=TIMEOUT,
        )
        if response.status_code >= 300:
            return []
        body = response.json() or {}
        items = body.get("coins") or []
        out: list[dict[str, Any]] = []
        for item in items[:12]:
            coin = (item or {}).get("item") or {}
            symbol = str(coin.get("symbol") or "").lower().strip()
            if not symbol:
                continue
            out.append(
                {
                    "symbol": symbol,
                    "name": str(coin.get("name") or symbol),
                    "rank": int(coin.get("market_cap_rank") or 0),
                    "score": int(item.get("score") or 0),
                }
            )
        return out
    except Exception as error:
        print(f"[KIBOT][COINGECKO][ERROR] trending fetch failed reason={error}", flush=True)
        return []


def _refresh_coingecko_trending_cache() -> None:
    global _coingecko_trending_cache
    coins = _fetch_coingecko_trending()
    if not coins:
        return
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    _coingecko_trending_cache = {"coins": coins, "fetched_at_epoch_ms": now_ms}
    preview = ",".join(c["symbol"] for c in coins[:5])
    print(f"[KIBOT][COINGECKO][TRENDING] count={len(coins)} top={preview}", flush=True)


def _get_coingecko_trending_cache() -> list[dict[str, Any]]:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    last_ms = int(_coingecko_trending_cache.get("fetched_at_epoch_ms") or 0)
    if (now_ms - last_ms) > max(60_000, COINGECKO_TRENDING_INTERVAL_SEC * 1000):
        _refresh_coingecko_trending_cache()
    return list(_coingecko_trending_cache.get("coins") or [])


def _estimate_exit_viability(expected_move_pct: float, slippage_pct: float) -> Dict[str, float]:
    total_cost_pct = max(0.0, slippage_pct) + max(0.0, TAKER_FEE_PCT)
    net_profit_pct = expected_move_pct - total_cost_pct
    return {
        "expected_move_pct": round(expected_move_pct, 4),
        "slippage_pct": round(slippage_pct, 4),
        "taker_fee_pct": round(TAKER_FEE_PCT, 4),
        "total_cost_pct": round(total_cost_pct, 4),
        "net_profit_pct": round(net_profit_pct, 4),
    }


def _effective_fee_pct() -> float:
    return (
        INDODAX_LIMIT_FILL_RATE * INDODAX_ALL_IN_MAKER_FEE_PCT
        + (1.0 - INDODAX_LIMIT_FILL_RATE) * INDODAX_ALL_IN_TAKER_FEE_PCT
    )


def _get_total_equity_estimate() -> float:
    """Estimasi total aset (IDR + Koin) dari cluster."""
    try:
        e = _extract_equity_estimate(_fetch_local_runtime_state(timeout_sec=2.0, max_cache_age_sec=5.0))
        if e is not None: return float(e)
    except: pass

    import urllib.request, json, re
    for url in LOCAL_RUNTIME_STATE_URLS:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                payload = json.loads(r.read())
                val = payload.get("portfolioValueIdr") or payload.get("totalValueIdr", 0)
                if isinstance(val, str):
                    clean_val = re.sub(r"[^\d,.]", "", val.replace("Rp", "")).replace(",", ".")
                    if clean_val and clean_val != ".":
                        return float(clean_val)
                elif val:
                    res = float(val)
                    if res > 0: print(f"[v7][EQUITY_FETCH] Found Rp{res:,.0f} from {url}", flush=True)
                    return res
        except: continue
    return 0.0


def _manager_role() -> str:
    raw = str(os.getenv("KIBOT_MANAGER_ROLE", "") or "").strip().upper()
    if raw:
        return raw
    if str(os.getenv("KIBOT_SCANNER_ONLY", "") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return "SCANNER"
    return "EXECUTOR"


def _is_scanner_only_node() -> bool:
    return _manager_role() in {"SCANNER", "SCANNER_ONLY", "RADAR", "RADAR_ONLY"}


def _adaptive_capital_profile(
    *,
    equity: Optional[float] = None,
    free_cash: Optional[float] = None,
    daily_pnl_pct: Optional[float] = None,
) -> Dict[str, Any]:
    directives = _governor_effective_directives()
    capital_directives = directives.get("capital") if isinstance(directives.get("capital"), dict) else {}
    equity_val = _parse_numeric(equity)
    if equity_val is None:
        equity_val = _get_total_equity_estimate()
    balance_snapshot = _current_balance_snapshot()
    free_cash_val = _parse_numeric(free_cash)
    if free_cash_val is None:
        free_cash_val = _parse_numeric(balance_snapshot.get("free_cash_idr"))
    if free_cash_val is None:
        free_cash_val = equity_val
    pnl_val = _parse_numeric(daily_pnl_pct)
    if pnl_val is None:
        pnl_val = _parse_numeric(_daily_guard_state.get("daily_pnl_pct")) or 0.0

    profile = {
        "enabled": ADAPTIVE_CAPITAL_ENABLED,
        "equity_idr": round(float(equity_val or 0.0), 2),
        "free_cash_idr": round(float(free_cash_val or 0.0), 2),
        "daily_pnl_pct": round(float(pnl_val or 0.0), 4),
        "mode": "NORMAL",
        "reason": "capital_adaptive_normal",
        "risk_pct_per_trade": 0.12,
        "min_position_idr": float(capital_directives.get("micro_entry_floor_idr") or ABSOLUTE_MIN_POSITION_SIZE_IDR),
        "max_position_idr": float(MAXIMUM_POSITION_SIZE_IDR),
        "daily_loss_limit_pct": round(_current_daily_loss_limit_pct(), 4),
        "trading_allowed": True,
        "strategy_mode": directives.get("strategy_mode") or "NEUTRAL",
    }
    if not ADAPTIVE_CAPITAL_ENABLED:
        return profile

    if _is_scanner_only_node():
        profile.update(
            {
                "mode": "RADAR_ONLY",
                "reason": "scanner_node_passive",
                "risk_pct_per_trade": 0.0,
                "max_position_idr": 0.0,
                "trading_allowed": False,
            }
        )
        return profile

    equity_now = float(equity_val or 0.0)
    free_cash_now = max(float(free_cash_val or 0.0), 0.0)
    if equity_now <= 0.0:
        profile.update(
            {
                "mode": "PAUSED",
                "reason": "missing_equity_snapshot",
                "max_position_idr": 0.0,
                "trading_allowed": False,
            }
        )
        return profile

    if bool(_daily_guard_state.get("hard_stopped")):
        profile.update(
            {
                "mode": "HARD_STOP",
                "reason": "daily_loss_limit_hit",
                "max_position_idr": 0.0,
                "trading_allowed": False,
            }
        )
        return profile

    min_position_floor = max(
        float(ABSOLUTE_MIN_POSITION_SIZE_IDR),
        float(_parse_numeric(capital_directives.get("micro_entry_floor_idr")) or ABSOLUTE_MIN_POSITION_SIZE_IDR),
    )

    if free_cash_now < min_position_floor * MICRO_ACCOUNT_MIN_ORDER_BUFFER_PCT:
        profile.update(
            {
                "mode": "PAUSED",
                "reason": f"free_cash_below_min_order:{free_cash_now:.0f}",
                "max_position_idr": 0.0,
                "trading_allowed": False,
            }
        )
        return profile

    if pnl_val <= -0.015:
        mode = "RECOVERY"
        risk_pct = ADAPTIVE_RECOVERY_MAX_POSITION_PCT
        reason = "daily_drawdown_recovery"
    elif equity_now < 75_000:
        mode = "MICRO"
        floor_risk_pct = (ABSOLUTE_MIN_POSITION_SIZE_IDR / max(equity_now, 1.0)) * MICRO_ACCOUNT_MIN_ORDER_BUFFER_PCT
        risk_pct = min(
            MICRO_ACCOUNT_MAX_RISK_PCT,
            max(ADAPTIVE_MICRO_MAX_POSITION_PCT, floor_risk_pct),
        )
        reason = "micro_balance_preservation"
    elif equity_now < 150_000:
        mode = "BUILDUP"
        risk_pct = ADAPTIVE_BUILDUP_MAX_POSITION_PCT
        reason = "small_balance_build_up"
    elif equity_now < 500_000:
        mode = "NORMAL"
        risk_pct = ADAPTIVE_NORMAL_MAX_POSITION_PCT
        reason = "normal_balance_discipline"
    else:
        mode = "EXPANSION"
        risk_pct = ADAPTIVE_EXPANSION_MAX_POSITION_PCT
        reason = "capital_expansion_discipline"

    strategy_mode = str(directives.get("strategy_mode") or "NEUTRAL").upper()
    risk_pct *= float(_parse_numeric(capital_directives.get("risk_pct_multiplier")) or 1.0)
    if strategy_mode == "DEFENSIVE":
        risk_pct *= 0.92
    elif strategy_mode == "OPPORTUNISTIC" and mode not in {"RECOVERY", "HARD_STOP"}:
        risk_pct *= 1.03

    free_cash_buffer_pct = float(
        _parse_numeric(capital_directives.get("free_cash_buffer_pct")) or ADAPTIVE_FREE_CASH_BUFFER_PCT
    )
    if mode == "MICRO":
        free_cash_buffer_pct = max(free_cash_buffer_pct, MICRO_ACCOUNT_FREE_CASH_BUFFER_PCT)
    elif mode == "BUILDUP":
        free_cash_buffer_pct = max(free_cash_buffer_pct, 0.42)

    max_position = min(
        MAXIMUM_POSITION_SIZE_IDR,
        equity_now * risk_pct,
        free_cash_now * free_cash_buffer_pct,
    )
    min_position = min_position_floor
    tiny_balance_mode = mode in {"MICRO", "BUILDUP"} and equity_now < 150_000
    if tiny_balance_mode and max_position < min_position_floor:
        max_position = min_position_floor
    trading_allowed = free_cash_now >= min_position_floor * MICRO_ACCOUNT_MIN_ORDER_BUFFER_PCT and max_position >= min_position_floor
    if not trading_allowed:
        reason = f"{reason}:position_floor_unmet"
    elif tiny_balance_mode:
        reason = f"{reason}:min_order_override"

    profile.update(
        {
            "mode": mode,
            "reason": reason,
            "risk_pct_per_trade": round(risk_pct, 4),
            "min_position_idr": round(max(min_position, 0.0), 2),
            "max_position_idr": round(max(max_position, 0.0), 2),
            "trading_allowed": trading_allowed,
        }
    )
    return profile


def _check_minimum_capital() -> bool:
    profile = _adaptive_capital_profile()
    if profile.get("trading_allowed"):
        return True
    print(
        f"[KIBOT][CAPITAL] entry suspended mode={profile.get('mode')} "
        f"equity=Rp{profile.get('equity_idr', 0):,.0f} free_cash=Rp{profile.get('free_cash_idr', 0):,.0f} "
        f"reason={profile.get('reason')}",
        flush=True,
    )
    return False


def _capital_is_sufficient() -> bool:
    return bool(_adaptive_capital_profile().get("trading_allowed"))


def _maybe_auto_promote_trading_mode() -> None:
    global _capital_sufficient_since_at
    if bool(_daily_guard_state.get("hard_stopped")):
        _capital_sufficient_since_at = 0.0
        _set_conservative_mode("hard stop active")
        return
    if not _control_plane_healthy or _api_fail_streak > 0:
        _capital_sufficient_since_at = 0.0
        _set_conservative_mode("control plane unhealthy")
        return
    if not _capital_is_sufficient():
        _capital_sufficient_since_at = 0.0
        _set_conservative_mode(str(_adaptive_capital_profile().get("reason") or "capital_insufficient"))
        return
    if _capital_sufficient_since_at <= 0.0:
        _capital_sufficient_since_at = time.time()
    if (time.time() - _capital_sufficient_since_at) < _normal_mode_promotion_grace_sec:
        _set_conservative_mode("capital sufficient grace period")
        return

    # Bug #2 & #4: AI Health Mode Sync
    if not _ai_healthy:
        _set_level_3_mode("AI Offline/Silent")
        return

    if _is_survival_mode():
        _set_conservative_mode("survival mode active")
        return
    _set_normal_mode("capital sufficient and healthy")


def _is_survival_mode() -> bool:
    if not SURVIVAL_MODE:
        return False
    directives = _governor_effective_directives()
    survival_cfg = directives.get("survival") if isinstance(directives.get("survival"), dict) else {}
    equity = _get_total_equity_estimate()
    if equity is None:
        return True
    threshold = float(_parse_numeric(survival_cfg.get("equity_threshold_idr")) or SURVIVAL_MODE_EQUITY_THRESHOLD_IDR)
    return equity < threshold


def _apply_survival_filters(pair_id: str, budget_idr: float, spread_pct: float = 0.0, slippage_pct: float = 0.0) -> tuple[bool, str]:
    directives = _governor_effective_directives()
    survival_cfg = directives.get("survival") if isinstance(directives.get("survival"), dict) else {}
    capital_profile = _adaptive_capital_profile()
    min_position_idr = float(capital_profile.get("min_position_idr") or ABSOLUTE_MIN_POSITION_SIZE_IDR)
    max_position_idr = float(capital_profile.get("max_position_idr") or 0.0)
    if not bool(capital_profile.get("trading_allowed")):
        return False, f"capital_profile:{capital_profile.get('reason')}"
    if budget_idr < min_position_idr:
        return False, f"capital_profile: budget {budget_idr:.0f} below adaptive floor {min_position_idr:.0f}"
    if max_position_idr > 0 and budget_idr > max_position_idr:
        return False, f"capital_profile: budget {budget_idr:.0f} above adaptive cap {max_position_idr:.0f}"
    if not _is_survival_mode():
        return True, "normal_mode"
    pair_key = str(pair_id or "").lower().strip()
    pair_cfg = _get_pair_config(pair_key)
    allowed_tiers = {
        str(item).upper()
        for item in list(survival_cfg.get("allowed_tiers") or [])
        if str(item).strip()
    } or set(_capital_bucket_tiers())
    if pair_key not in SURVIVAL_ALLOWED_PAIRS and pair_cfg.get("tier") not in allowed_tiers:
        return False, f"survival_mode: {pair_key} not allowed"
    max_size_idr = float(pair_cfg.get("max_size_idr") or MAXIMUM_POSITION_SIZE_IDR)
    max_size_idr *= _capital_risk_multiplier()
    min_target_profit_pct = float(
        _parse_numeric(survival_cfg.get("min_target_profit_pct"))
        or pair_cfg.get("min_target_profit_pct")
        or SURVIVAL_TARGET_PROFIT_PCT
    )
    max_spread_pct = float(
        _parse_numeric(survival_cfg.get("max_spread_pct"))
        or pair_cfg.get("max_spread_pct")
        or SURVIVAL_MAX_SPREAD_PCT
    )
    max_slippage_pct = float(
        _parse_numeric(survival_cfg.get("max_slippage_pct"))
        or pair_cfg.get("max_slippage_pct")
        or SURVIVAL_MAX_SLIPPAGE_PCT
    )
    if budget_idr < min_position_idr:
        return False, f"survival_mode: budget {budget_idr:.0f} below min position {min_position_idr:.0f}"
    if budget_idr > min(max_position_idr or MAXIMUM_POSITION_SIZE_IDR, max_size_idr):
        return False, f"survival_mode: budget {budget_idr:.0f} above max position {min(max_position_idr or MAXIMUM_POSITION_SIZE_IDR, max_size_idr):.0f}"
    if spread_pct > max_spread_pct:
        return False, f"survival_mode: spread {spread_pct:.3%} too wide"
    if slippage_pct > max_slippage_pct:
        return False, f"survival_mode: slippage {slippage_pct:.3%} too high"
    if min_target_profit_pct <= 0:
        return False, f"survival_mode: invalid target profit config for {pair_key}"
    return True, "ok"


def _simulate_what_if(
    *,
    pair_id: str,
    entry_price: float,
    budget_idr: float,
    spread_pct: float,
    slippage_pct: float,
    trailing_stop_pct: float = 0.05,
    target_profit_pct: float = 0.018,
) -> Dict[str, Any]:
    historical_slippage = _get_pair_avg_slippage(pair_id, fallback=slippage_pct)
    historical_win_rate = _get_pair_win_rate_now(pair_id)
    effective_slippage = max(float(slippage_pct), float(historical_slippage))
    eff_fee_pct = _effective_fee_pct()
    round_trip_cost_pct = (max(0.0, spread_pct) / 2.0) + effective_slippage + (eff_fee_pct * 2.0)
    breakeven_move_pct = round_trip_cost_pct
    expected_net_pct = target_profit_pct - round_trip_cost_pct
    max_loss_pct = trailing_stop_pct + round_trip_cost_pct
    max_loss_idr = budget_idr * max_loss_pct
    reward_idr = budget_idr * expected_net_pct
    risk_reward_ratio = (reward_idr / max_loss_idr) if max_loss_idr > 0 else 0.0
    expected_value = (historical_win_rate * reward_idr) - ((1.0 - historical_win_rate) * max_loss_idr)
    if expected_net_pct <= 0:
        recommendation = "SKIP"
    elif risk_reward_ratio < 1.0:
        recommendation = "SKIP"
    elif expected_value <= 0:
        recommendation = "SKIP"
    elif risk_reward_ratio < 1.5 or historical_win_rate < 0.45:
        recommendation = "REDUCE_SIZE"
    else:
        recommendation = "ENTER"
    return {
        "pair_id": pair_id,
        "entry_price": entry_price,
        "budget_idr": budget_idr,
        "expected_net_pct": round(expected_net_pct, 4),
        "breakeven_move_pct": round(breakeven_move_pct, 4),
        "fee_round_trip_pct": round(eff_fee_pct * 2.0, 4),
        "max_loss_idr": round(max_loss_idr, 0),
        "win_probability": round(historical_win_rate, 3),
        "risk_reward_ratio": round(risk_reward_ratio, 2),
        "recommendation": recommendation,
        "historical_slippage_pct": round(historical_slippage, 4),
        "effective_slippage_pct": round(effective_slippage, 4),
    }


def _should_use_market_order(msg: Dict[str, Any], pair_id: str) -> bool:
    signal_age_ms = float(msg.get("signalAgeMs") or msg.get("signal_age_ms") or 999.0)
    price_change_1m_pct = float(msg.get("priceChange1mPct") or msg.get("price_change_1m_pct") or 0.0)
    volume_spike = bool(msg.get("volumeSpike") or msg.get("volume_spike") or False)
    confidence = float(msg.get("confidence") or 0.0)
    breakout_urgent = bool(msg.get("breakout_urgent") or msg.get("breakoutUrgent") or False)
    if breakout_urgent:
        return True
    is_breakout = signal_age_ms < 150 and abs(price_change_1m_pct) > 0.5 and volume_spike and confidence >= 0.75
    if not is_breakout:
        return False
    what_if = _simulate_what_if(
        pair_id=pair_id,
        entry_price=float(msg.get("entryPrice") or msg.get("entry_price") or msg.get("price") or 0.0),
        budget_idr=float(msg.get("budgetIdr") or msg.get("budget_idr") or msg.get("quoteBudgetIdr") or MINIMUM_POSITION_SIZE_IDR),
        spread_pct=float(msg.get("spreadPct") or msg.get("spread_pct") or 0.0),
        slippage_pct=float(msg.get("slippagePct") or msg.get("slippage_pct") or 0.0),
        trailing_stop_pct=float(msg.get("trailingStopPct") or 0.05),
        target_profit_pct=float(msg.get("targetProfitPct") or msg.get("target_profit_pct") or _target_profit_pct_for_pair(pair_id)),
    )
    return what_if["recommendation"] != "SKIP"


@dataclass
class PumpAnalysis:
    pair_id: str
    legitimacy_score: float
    pump_phase: str
    entry_recommendation: str
    exit_target_pct: float
    stop_loss_pct: float
    risk_reward: float
    reasoning: str


def analyze_pump_legitimacy(
    *,
    pair_id: str,
    price_now: float,
    price_24h_ago: float,
    price_1h_ago: float,
    price_15m_ago: float,
    volume_24h_idr: float,
    volume_1h_idr: float,
    high_24h: float,
    low_24h: float,
    bollinger_upper: float,
    bollinger_middle: float,
    bollinger_lower: float,
    has_binance_pair: bool,
    binance_price_change_pct: float = 0.0,
) -> PumpAnalysis:
    score = 0.0
    reasons: list[str] = []
    avg_hourly_volume = max(volume_24h_idr / 24.0, 1.0)
    volume_ratio_1h = volume_1h_idr / avg_hourly_volume
    if volume_ratio_1h > 3.0:
        score += 25
        reasons.append(f"volume 1h {volume_ratio_1h:.1f}x avg")
    elif volume_ratio_1h > 2.0:
        score += 18
        reasons.append(f"volume 1h {volume_ratio_1h:.1f}x avg")
    elif volume_ratio_1h > 1.5:
        score += 10
        reasons.append(f"volume 1h {volume_ratio_1h:.1f}x avg")
    else:
        reasons.append(f"volume weak {volume_ratio_1h:.1f}x")

    if volume_24h_idr < 100_000_000:
        score -= 20
        reasons.append("illiquid")
    elif volume_24h_idr > 1_000_000_000:
        score += 10
        reasons.append("liquid")

    range_span = max(high_24h - low_24h, 0.000001)
    position_in_range = (price_now - low_24h) / range_span
    if position_in_range < 0.4:
        phase = "EARLY"
        score += 25
    elif position_in_range < 0.65:
        phase = "MID"
        score += 18
    elif position_in_range < 0.85:
        phase = "LATE"
        score += 8
    elif position_in_range < 0.95:
        phase = "PEAK"
        score -= 5
    else:
        phase = "POST_PEAK"
        score -= 20

    bb_range = max(bollinger_upper - bollinger_lower, 0.000001)
    bb_position = (price_now - bollinger_lower) / bb_range
    if bb_position < 0.5:
        score += 20
    elif bb_position < 0.75:
        score += 12
    elif bb_position < 0.9:
        score += 5
    else:
        score -= 15

    momentum_15m = ((price_now - price_15m_ago) / max(price_15m_ago, 0.000001)) * 100.0
    momentum_1h = ((price_now - price_1h_ago) / max(price_1h_ago, 0.000001)) * 100.0
    if momentum_15m > 1.0 and momentum_1h > 3.0:
        score += 15
    elif momentum_15m > 0.5:
        score += 8
    elif momentum_15m < 0:
        score -= 10

    if has_binance_pair:
        if binance_price_change_pct > 3.0:
            score += 15
        elif binance_price_change_pct > 1.0:
            score += 8
    else:
        score -= 5

    score = max(0.0, min(100.0, score))
    if phase == "EARLY":
        exit_target, stop_loss = 0.08, 0.03
    elif phase == "MID":
        exit_target, stop_loss = 0.05, 0.025
    elif phase == "LATE":
        exit_target, stop_loss = 0.03, 0.02
    else:
        exit_target, stop_loss = 0.02, 0.015
    rr = exit_target / max(stop_loss, 0.001)
    if score >= 70 and rr >= 2.0:
        rec = "ENTER_NOW"
    elif score >= 55 and rr >= 1.5:
        rec = "ENTER_NOW"
    elif score >= 40 and phase in ("LATE", "PEAK"):
        rec = "WAIT_PULLBACK"
    elif score < 30 or phase == "POST_PEAK":
        rec = "DANGER"
    else:
        rec = "SKIP"
    return PumpAnalysis(
        pair_id=pair_id,
        legitimacy_score=round(score, 1),
        pump_phase=phase,
        entry_recommendation=rec,
        exit_target_pct=exit_target,
        stop_loss_pct=stop_loss,
        risk_reward=round(rr, 2),
        reasoning=" | ".join(reasons[:4]),
    )


def _estimate_bollinger(price_now: float, low_24h: float, high_24h: float) -> tuple[float, float, float]:
    span = max(high_24h - low_24h, 0.000001)
    middle = low_24h + span * 0.5
    upper = low_24h + span * 0.85
    lower = low_24h + span * 0.15
    return upper, middle, lower


def screen_all_pairs() -> list[dict[str, Any]]:
    tickers = _load_indodax_ticker_snapshot()
    candidates: list[dict[str, Any]] = []
    for pair_id, row in tickers.items():
        try:
            vol_24h = float(row.get("vol_idr") or row.get("volume_idr") or 0.0)
            if vol_24h < 200_000_000:
                continue
            price_now = float(row.get("last") or row.get("close") or 0.0)
            if price_now <= 0.0:
                continue
            high_24h = float(row.get("high") or price_now)
            low_24h = float(row.get("low") or price_now)
            open_24h = float(row.get("open") or price_now)
            price_15m_ago = float(row.get("last_15m") or row.get("price_15m") or open_24h)
            price_1h_ago = float(row.get("last_1h") or row.get("price_1h") or open_24h)
            price_24h_ago = float(row.get("open") or row.get("price_24h") or open_24h)
            pump_pct_24h = ((price_now - price_24h_ago) / max(price_24h_ago, 0.000001)) * 100.0
            if pump_pct_24h > 80.0:
                continue
            pump_pct_15m = ((price_now - price_15m_ago) / max(price_15m_ago, 0.000001)) * 100.0
            if pump_pct_15m < 0.3:
                continue
            volume_1h = float(row.get("vol_1h_idr") or vol_24h / 24.0 * 1.5)
            bb_upper, bb_middle, bb_lower = _estimate_bollinger(price_now, low_24h, high_24h)
            has_binance = bool(row.get("binance_pair") or row.get("binance") or False)
            binance_change = float(row.get("binance_price_change_pct") or 0.0)
            analysis = analyze_pump_legitimacy(
                pair_id=pair_id,
                price_now=price_now,
                price_24h_ago=price_24h_ago,
                price_1h_ago=price_1h_ago,
                price_15m_ago=price_15m_ago,
                volume_24h_idr=vol_24h,
                volume_1h_idr=volume_1h,
                high_24h=high_24h,
                low_24h=low_24h,
                bollinger_upper=bb_upper,
                bollinger_middle=bb_middle,
                bollinger_lower=bb_lower,
                has_binance_pair=has_binance,
                binance_price_change_pct=binance_change,
            )
            if analysis.legitimacy_score < 55 or analysis.entry_recommendation in {"SKIP", "DANGER"} or analysis.risk_reward < 1.5:
                continue
            candidates.append(
                {
                    "pair_id": pair_id,
                    "analysis": analysis,
                    "price_now": price_now,
                    "pump_pct_24h": pump_pct_24h,
                    "volume_24h_idr": vol_24h,
                    "composite_score": analysis.legitimacy_score * 0.6 + analysis.risk_reward * 10.0,
                }
            )
        except Exception:
            continue
    candidates.sort(key=lambda item: item["composite_score"], reverse=True)
    return candidates[:10]


_screen_cache: list[dict[str, Any]] = []
_last_screen_time = 0.0
_last_pnl_check = 0.0


def _pair_screen_loop() -> None:
    global _screen_cache, _last_screen_time
    while not _shutdown_event.is_set():
        try:
            now = time.time()
            if (now - _last_screen_time) >= 900.0:
                _last_screen_time = now
                _screen_cache = screen_all_pairs()
                if _screen_cache:
                    top = _screen_cache[0]
                    print(
                        f"[KIBOT][SCREEN] top={top['pair_id']} score={top['analysis'].legitimacy_score:.1f} phase={top['analysis'].pump_phase}",
                        flush=True,
                    )
                    _append_runtime_event(
                        "pair_screen_update",
                        {
                            "top_pair": top["pair_id"],
                            "score": top["analysis"].legitimacy_score,
                            "phase": top["analysis"].pump_phase,
                            "count": len(_screen_cache),
                        },
                    )
                    _write_runtime_note()
        except Exception as error:
            print(f"[KIBOT][WARN] pair_screen_loop error: {error}", flush=True)
        if _shutdown_event.wait(timeout=30.0):
            break


def _apply_dynamic_trailing(pump_phase: str, current_profit_pct: float) -> float:
    directives = _governor_effective_directives()
    tightness = str(directives.get("risk", {}).get("trailing_tightness") or "BASE").upper()
    if pump_phase == "EARLY":
        base = 0.02 if current_profit_pct >= 0.05 else 0.04
    elif pump_phase == "MID":
        base = 0.015 if current_profit_pct >= 0.03 else 0.03
    elif pump_phase == "LATE":
        base = 0.01 if current_profit_pct >= 0.015 else 0.02
    else:
        base = 0.01
    if tightness == "TIGHTER":
        return max(0.006, base * 0.82)
    if tightness == "LOOSER":
        return min(0.06, base * 1.18)
    return base


def _run_30min_math_review() -> Dict[str, Any]:
    metrics = _get_trade_metrics_today()
    equity = _get_total_equity_estimate() or 0.0
    pnl_pct = float(_daily_guard_state.get("daily_pnl_pct") or 0.0)
    hours_left = _hours_until_midnight_wib()
    avg_trades_per_hour = metrics["total_trades"] / max((time.time() - _bot_start_time) / 3600.0, 0.5)
    trades_possible = avg_trades_per_hour * hours_left
    loss_idr = abs(min(pnl_pct, 0.0) * equity)
    ev = float(metrics["ev_per_trade"])
    if ev > 0 and loss_idr > 0:
        trades_to_recover = loss_idr / ev
    else:
        trades_to_recover = float("inf") if ev <= 0 else 0.0
    if ev <= 0 and metrics["total_trades"] >= 3:
        action = "TIGHTEN_FILTER"
    elif trades_to_recover > trades_possible * 1.5:
        action = "PREPARE_STOP"
    elif trades_to_recover > trades_possible:
        action = "DEFENSIVE"
    elif metrics["win_rate"] >= 0.60 and ev > 0:
        action = "CONTINUE_OPTIMAL"
    else:
        action = "CONTINUE"
    report = (
        f"📊 30min Math Review\n"
        f"PnL: {pnl_pct:+.2%} | Trades: {metrics['total_trades']} ({metrics['wins']}W/{metrics['losses']}L)\n"
        f"WR: {metrics['win_rate']:.0%} | PF: {metrics['profit_factor']:.2f} | EV/trade: Rp{ev:+,.0f}\n"
        f"Hours left: {hours_left:.1f} | Trades possible: {trades_possible:.1f}\n"
        f"Action: {action}"
    )
    _telegram_send(report)
    _append_runtime_event(
        "math_review",
        {
            "action": action,
            "metrics": metrics,
            "hours_left": round(hours_left, 2),
            "trades_possible": round(trades_possible, 2),
        },
    )
    return {"action": action, "metrics": metrics}


def _maybe_run_30min_math_review() -> None:
    global _last_math_review_at
    now = time.time()
    if (now - _last_math_review_at) >= 1800.0:
        _last_math_review_at = now
        run_30min_math_review()


def _current_daily_loss_limit_pct() -> float:
    default_limit = 0.01 if _is_survival_mode() else abs(float(DAILY_LOSS_LIMIT_PCT))
    override_limit = _governor_daily_loss_limit_fraction()
    return override_limit if override_limit is not None else default_limit


def _upsert_trade_history(entry: Dict[str, Any]) -> None:
    if LOCAL_FIRST_STORAGE and not SUPABASE_BACKUP_ENABLED:
        return
    headers = _headers()
    headers["Prefer"] = "return=minimal"
    primary_url = f"{SUPABASE_URL}/rest/v1/trade_history"
    try:
        response = requests.post(primary_url, headers=headers, json=entry, timeout=CONTROL_PLANE_TIMEOUT_SEC)
        if response.status_code < 300:
            _record_control_plane_success()
            return
        if response.status_code != 404:
            response.raise_for_status()
        _record_control_plane_success()
    except Exception as error:
        _record_control_plane_failure(f"trade_history_upsert:{error}")
    # Fallback when table trade_history is absent on this project.
    fallback_url = f"{SUPABASE_URL}/rest/v1/logs"
    fallback_payload = {
        "bot_id": "kibot",
        "device_id": "kibot-manager",
        "term": 0,
        "level": "INFO",
        "category": "BOOK_ENTRY",
        "message": json.dumps(entry, ensure_ascii=True),
        "metadata": {"source": "kibot_manager", "fallback_from": "trade_history"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        fallback_resp = requests.post(fallback_url, headers=headers, json=fallback_payload, timeout=CONTROL_PLANE_TIMEOUT_SEC)
        fallback_resp.raise_for_status()
        _record_control_plane_success()
    except Exception as error:
        _record_control_plane_failure(f"trade_history_fallback:{error}")
        raise


def _book_entry_from_execution(msg: Dict[str, Any]) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    gross = float(msg.get("gross_pnl_idr") or 0.0)
    est_cost = float(msg.get("estimated_cost_idr") or 0.0)
    net = gross - est_cost
    pair_id = str(msg.get("pair") or msg.get("pairId") or "unknown").lower().strip()
    pnl_pct = float(msg.get("pnl_pct") or msg.get("pnlPct") or 0.0)
    slippage_pct = float(msg.get("slippage_pct") or 0.0)
    spread_pct = float(msg.get("spread_pct") or 0.0)
    actual_latency_ms = float(msg.get("latency_ms") or 0.0)
    fake_pump = bool(msg.get("fake_pump") or False)
    _update_pair_memory(
        pair_id,
        pnl_pct=pnl_pct,
        slippage_pct=slippage_pct,
        spread_pct=spread_pct,
        actual_latency_ms=actual_latency_ms,
        fake_pump=fake_pump,
    )
    if _learning_enabled and _learning_engine is not None:
        used_limit_order = str(msg.get("order_type") or msg.get("orderType") or "limit").lower() == "limit"
        if used_limit_order:
            _metric_inc("limit_orders_today")
        else:
            _metric_inc("market_orders_today")
            _metric_add("fee_bleed_est_idr", abs(net) * 0.0 + max(300.0, abs(gross) * 0.006))
        _learning_engine.record_trade(pair_id, pnl_pct, used_limit_order=used_limit_order)
    try:
        _record_trade_result(pair_id, gross_pnl_pct=pnl_pct, entry_time=float(msg.get("entry_timestamp") or msg.get("timestamp") or time.time()))
    except Exception as error:
        print(f"[KIBOT][MATH_REVIEW][WARN] trade record failed pair={pair_id} reason={error}", flush=True)
    print(
        f"[KIBOT][LEARNING] pair_memory updated pair={pair_id} pnl_pct={pnl_pct:.4f} slippage_pct={slippage_pct:.4f}",
        flush=True,
    )
    try:
        _upsert_trade_history(
            {
                "pair_id": msg.get("pair") or msg.get("pairId") or "unknown",
                "status": "BOOK_ENTRY",
                "source_bot": "kibot",
                "message": json.dumps(
                    {
                        "trace_id": msg.get("traceId"),
                        "gross_pnl_idr": gross,
                        "estimated_cost_idr": est_cost,
                        "net_pnl_idr": net,
                        "mode": "TRINITY_V3",
                    },
                    ensure_ascii=True,
                ),
                "created_at": now_iso,
                "updated_at": now_iso,
            }
        )
        print(
            f"[KIBOT][LEDGER] BOOK_ENTRY pair={msg.get('pair')} net={net:.4f} trace={msg.get('traceId')}",
            flush=True,
        )
        _append_runtime_event(
            "book_entry",
            {"pair": pair_id, "net_pnl_idr": round(net, 4), "trace_id": msg.get("traceId")},
        )
        _write_runtime_note()
    except Exception as error:
        print(
            f"[KIBOT][LEDGER][WARN] upsert failed pair={msg.get('pair')} trace={msg.get('traceId')} reason={error}",
            flush=True,
        )
    if POST_MORTEM_ENABLED and net < 0:
        _update_pair_memory(
            pair_id,
            pnl_pct=pnl_pct,
            slippage_pct=slippage_pct,
            spread_pct=spread_pct,
            fake_pump=True,
        )
        thread = threading.Thread(
            target=evaluate_foolish_trade,
            args=(
                {
                    "trace_id": msg.get("traceId"),
                    "pair": pair_id,
                    "gross_pnl_idr": gross,
                    "estimated_cost_idr": est_cost,
                    "net_pnl_idr": net,
                    "pnl_pct": float(msg.get("pnl_pct") or msg.get("pnlPct") or 0.0),
                    "slippage_pct": float(msg.get("slippage_pct") or 0.0),
                    "hold_seconds": float(msg.get("hold_seconds") or 0.0),
                    "closed_at": now_iso,
                },
            ),
            daemon=True,
            name="kibot-postmortem",
        )
        thread.start()


def evaluate_foolish_trade(trade_data: Dict[str, Any]) -> None:
    system_prompt = "Anda evaluator pasca-trade. Jawab JSON singkat: {\"mistake\":\"...\",\"action\":\"...\",\"tighten\":{...}}"
    user_prompt = json.dumps(trade_data, ensure_ascii=True)
    routed_text, provider = _call_ai_router(
        task="post_mortem",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_hint=POST_MORTEM_MODEL,
        timeout_sec=POST_MORTEM_TIMEOUT_SEC,
    )
    if routed_text:
        print(
            f"[KIBOT][POST_MORTEM] provider={provider} trace={trade_data.get('trace_id')} result={routed_text[:320]}",
            flush=True,
        )
        parsed = _parse_json_candidate(routed_text)
        pair = str(trade_data.get("pair") or "").lower().strip()
        net_pnl = float(trade_data.get("net_pnl_idr") or 0.0)
        pnl_pct = float(trade_data.get("pnl_pct") or 0.0)
        action_text = json.dumps(parsed, ensure_ascii=True).lower() if parsed else routed_text.lower()
        if POST_MORTEM_BLACKLIST_ENABLED and pair and (
            "blacklist" in action_text
            or "freeze" in action_text
            or net_pnl <= -abs(POST_MORTEM_BLACKLIST_NET_LOSS_IDR)
            or pnl_pct <= POST_MORTEM_BLACKLIST_PNL_PCT
        ):
            _cooldown_pair(
                pair,
                reason="post_mortem_loss_blacklist",
                minutes=POST_MORTEM_BLACKLIST_MINUTES,
                metadata={"trace_id": trade_data.get("trace_id"), "provider": provider, "net_pnl_idr": net_pnl},
            )
            _update_daily_summary("loss_blacklist", {"pair": pair, "provider": provider})
            _write_runtime_note(force=True)
        return
    if not POST_MORTEM_API_URL:
        print("[KIBOT][POST_MORTEM] skipped (router+legacy unavailable).", flush=True)
        return
    payload = {
        "model": POST_MORTEM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    headers = {"Content-Type": "application/json"}
    if POST_MORTEM_API_KEY:
        headers["Authorization"] = f"Bearer {POST_MORTEM_API_KEY}"
    try:
        response = requests.post(
            POST_MORTEM_API_URL,
            headers=headers,
            json=payload,
            timeout=POST_MORTEM_TIMEOUT_SEC,
        )
        if response.status_code >= 300:
            print(
                f"[KIBOT][POST_MORTEM][WARN] status={response.status_code} body={response.text[:240]}",
                flush=True,
            )
            return
        result = response.json()
        print(
            f"[KIBOT][POST_MORTEM] evaluated trace={trade_data.get('trace_id')} result={json.dumps(result, ensure_ascii=True)[:320]}",
            flush=True,
        )
    except Exception as error:
        print(f"[KIBOT][POST_MORTEM][ERROR] trace={trade_data.get('trace_id')} reason={error}", flush=True)


def force_evaluate_recent_loss() -> None:
    if not POST_MORTEM_ENABLED:
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        url = f"{SUPABASE_URL}/rest/v1/trade_history"
        headers = _headers()
        params = {
            "select": "message,created_at,pair_id",
            "status": "eq.BOOK_ENTRY",
            "order": "created_at.desc",
            "limit": "20",
        }
        response = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        if response.status_code >= 300:
            return
        rows = response.json() or []
        for row in rows:
            message = row.get("message")
            if not isinstance(message, str) or not message.strip():
                continue
            try:
                payload = json.loads(message)
            except Exception:
                continue
            net = float(payload.get("net_pnl_idr") or 0.0)
            if net >= 0:
                continue
            evaluate_foolish_trade(
                {
                    "trace_id": payload.get("trace_id") or f"forced-{int(time.time())}",
                    "pair": row.get("pair_id") or "unknown",
                    "gross_pnl_idr": float(payload.get("gross_pnl_idr") or 0.0),
                    "estimated_cost_idr": float(payload.get("estimated_cost_idr") or 0.0),
                    "net_pnl_idr": net,
                    "slippage_pct": float(payload.get("slippage_pct") or 0.0),
                    "hold_seconds": float(payload.get("hold_seconds") or 0.0),
                    "closed_at": row.get("created_at"),
                    "trigger": "force_recent_loss_eval",
                }
            )
            print(f"[KIBOT][POST_MORTEM][FORCE] recent loss evaluated pair={row.get('pair_id')} net={net:.4f}", flush=True)
            return
    except Exception as error:
        print(f"[KIBOT][POST_MORTEM][FORCE][ERROR] {error}", flush=True)


def _get_dynamic_fomo_guard(price_idr: float) -> float:
    """
    FOMO guard = seberapa jauh pump yang masih boleh dikejar.
    Prinsip: masuk early, bukan saat sudah puncak (Tekan Kerugian).
    """
    if price_idr < 50.0:
        return 18.0   # Micro-cap: max 18% (was 35%)
    elif price_idr < 500.0:
        return 12.0   # Mid-cap: max 12% (was 22%)
    else:
        return 8.0    # Big-cap: max 8% (was 15%)


def _on_KiBot_heartbeat_received():
    """Called when heartbeat UDP packet received from KiBot"""
    global _last_KiBot_heartbeat_at, _KiBot_healthy, _redis
    _last_KiBot_heartbeat_at = time.time()
    try:
        if _redis:
            _redis.set("trinity:heartbeat:tokyo", _last_KiBot_heartbeat_at)
            _redis.expire("trinity:heartbeat:tokyo", 60)
    except:
        pass
    if not _KiBot_healthy:
        print("[KIBOT][RECOVERY] KiBot heartbeat restored!", flush=True)
    _KiBot_healthy = True


def _on_KiBot_heartbeat_received():
    """Called when heartbeat UDP packet received from KiBot (Singapore)"""
    global _last_KiBot_heartbeat_at, _KiBot_healthy, _redis
    _last_KiBot_heartbeat_at = time.time()
    try:
        if _redis:
            _redis.set("trinity:heartbeat:singapore", _last_KiBot_heartbeat_at)
            _redis.expire("trinity:heartbeat:singapore", 60)
    except:
        pass
    if not _KiBot_healthy:
        _KiBot_healthy = True
        print("[KIBOT][RECOVERY] KiBot heartbeat restored! (Singapore is BACK)", flush=True)


def _is_KiBot_healthy() -> bool:
    """Returns True if KiBot is healthy (heartbeat within timeout)"""
    global _KiBot_healthy
    now = time.time()
    if _last_KiBot_heartbeat_at == 0.0:
        return True # Assume healthy at boot
    
    timeout = float(os.getenv("KIBOT_EXECUTOR_TIMEOUT_SEC", "30.0"))
    if (now - _last_KiBot_heartbeat_at) > timeout:
        if _KiBot_healthy:
            _KiBot_healthy = False
            print(f"[KIBOT][CRITICAL] KiBot HEARTBEAT LOST! Singapore last seen {now - _last_KiBot_heartbeat_at:.1f}s ago", flush=True)
            _send_critical_alert("EXECUTOR_OFFLINE", {"node": "Singapore", "last_seen": now - _last_KiBot_heartbeat_at})
        return False
    return True






def _trigger_urgent_ai_scout(pair: str):
    """Signals the kibot_ai_scout to perform immediate research on a pair."""
    try:
        data = {"at": time.time(), "pair": pair}
        # _base_path points to Batam/
        urgent_file = _base_path / "state" / "urgent_scout.json"
        urgent_file.write_text(json.dumps(data), encoding="utf-8")
        print(f"[KIBOT][URGENT_SCOUT] Signal sent for {pair}", flush=True)
    except Exception as e:
        print(f"[KIBOT][ERROR] Failed to send urgent scout signal: {e}", flush=True)


def _process_signal(msg: Dict[str, Any]) -> None:
    msg_type = str(msg.get("msgType") or msg.get("type") or "").upper()

    # === HANDLE KiBot HEARTBEAT ===
    if msg_type == "HEARTBEAT" and msg.get("source") == "KiBot":
        _on_KiBot_heartbeat_received()
        return

    if msg_type == "EXECUTION_FILLED":
        _book_entry_from_execution(msg)
        return
    if msg_type == "ACTIVE_POSITIONS":
        _process_active_positions(msg)
        return
    if msg_type == "ORDERBOOK_COLLAPSE":
        _process_orderbook_collapse(msg)
        return

    if msg_type in SAFE_ENTRY_MSG_TYPES:
        try:
            _check_daily_loss_limit()
            if _is_hard_stop_active():
                _metric_inc("entries_blocked_hard_stop")
                print(
                    f"[KIBOT][BLOCK] Blocking {msg_type} - daily hard stop active",
                    flush=True,
                )
                return
        except Exception as error:
            _metric_inc("entries_blocked_hard_stop")
            print(f"[KIBOT][BLOCK] Blocking {msg_type} - hard stop guard failed reason={error}", flush=True)
            return

        if not _check_minimum_capital():
            capital_profile = _adaptive_capital_profile()
            print(f"[KIBOT][BLOCK] Blocking {msg_type} - adaptive capital guard {capital_profile.get('reason')}", flush=True)
            _set_conservative_mode(str(capital_profile.get("reason") or "adaptive_capital_guard"))
            _append_runtime_event(
                "entry_blocked",
                {"reason": str(capital_profile.get("reason") or "adaptive_capital_guard"), "msg_type": msg_type},
            )
            return

    if msg_type in EXIT_MSG_TYPES:
        pass
    elif msg_type in SAFE_ENTRY_MSG_TYPES and _entry_state_is_suspended():
        print(
            f"[KIBOT][BLOCK] Blocking {msg_type} - entry suspended state={_gate_state.get('entry_state')} reason={_gate_state.get('reason')}",
            flush=True,
        )
        return
    elif _entry_state_is_suspended():
        print(
            f"[KIBOT][BLOCK] Blocking {msg_type} - entry suspended state={_gate_state.get('entry_state')} reason={_gate_state.get('reason')}",
            flush=True,
        )
        return

    # === EARLY RETURN IF KiBot DEAD ===
    if not _check_KiBot_health():
        # Only allow EXIT signals when KiBot unhealthy
        if msg_type not in EXIT_MSG_TYPES:
            print(f"[KIBOT][BLOCK] Blocking {msg_type} - KiBot unhealthy", flush=True)
            return

    if msg_type not in (SAFE_ENTRY_MSG_TYPES | EXIT_MSG_TYPES):
        return
    # Relay original detector signal so KiBot can hold KiBot-side evidence for double-confirmation.
    _broadcast_udp(msg)
    print(
        f"[KIBOT][RELAY] msgType={msg_type} pair={msg.get('pair') or msg.get('pairId')} trace={msg.get('traceId')}",
        flush=True,
    )

    pair = str(msg.get("pair") or msg.get("pairId") or "")
    if not pair:
        print(f"[KIBOT][WARN] missing pair in msgType={msg_type}", flush=True)
        return
    pair_cfg = _get_pair_config(pair)

    if msg_type in SAFE_ENTRY_MSG_TYPES:
        score = float(msg.get("score") or 0.0)
        if _is_hard_stop_active():
            if _is_one_shot_eligible(msg, score):
                msg["one_shot_mode"] = True
            else:
                return

    if msg_type in SAFE_ENTRY_MSG_TYPES and _learning_enabled and _learning_engine is not None:
        allowed, reason = _learning_engine.should_entry(pair)
        if not allowed:
            _metric_inc("entries_blocked_learn_gate")
            print(f"[KIBOT][LEARN GATE] pair={pair} blocked reason={reason}", flush=True)
            _append_runtime_event(
                "learning_block",
                {"pair": pair, "reason": reason, "msg_type": msg_type},
            )
            return
    if msg_type in SAFE_ENTRY_MSG_TYPES:
        entry_price = float(msg.get("entryPrice") or msg.get("entry_price") or msg.get("price") or 0.0)
        budget_idr = float(msg.get("budgetIdr") or msg.get("budget_idr") or msg.get("quoteBudgetIdr") or 0.0)
        spread_pct = float(msg.get("spreadPct") or msg.get("spread_pct") or 0.0)
        slippage_pct = float(msg.get("slippagePct") or msg.get("slippage_pct") or 0.0)
        pair_cfg = _get_pair_config(pair)
        capital_profile = _adaptive_capital_profile()
        adaptive_cap = float(capital_profile.get("max_position_idr") or 0.0)
        adaptive_floor = float(capital_profile.get("min_position_idr") or ABSOLUTE_MIN_POSITION_SIZE_IDR)
        if adaptive_cap > 0.0 and budget_idr > adaptive_cap:
            print(
                f"[KIBOT][CAPITAL] pair={pair} budget reduced Rp{budget_idr:,.0f} -> Rp{adaptive_cap:,.0f} "
                f"mode={capital_profile.get('mode')} reason={capital_profile.get('reason')}",
                flush=True,
            )
            budget_idr = adaptive_cap
        if budget_idr < adaptive_floor:
            print(
                f"[KIBOT][CAPITAL] pair={pair} budget Rp{budget_idr:,.0f} below adaptive floor Rp{adaptive_floor:,.0f} "
                f"mode={capital_profile.get('mode')} reason={capital_profile.get('reason')}",
                flush=True,
            )
            return
        brain_advisory = _brain_signal_advisory(pair, msg, budget_idr, capital_profile)
        if not brain_advisory.get("allow", True):
            _metric_inc("entries_blocked_brain")
            print(
                f"[KIBOT][BRAIN BLOCK] pair={pair} symbol={brain_advisory.get('symbol')} "
                f"reason={brain_advisory.get('reason')} risk_bias={brain_advisory.get('risk_bias')}",
                flush=True,
            )
            _append_runtime_event(
                "brain_block",
                {
                    "pair": pair,
                    "symbol": brain_advisory.get("symbol"),
                    "reason": brain_advisory.get("reason"),
                    "risk_bias": brain_advisory.get("risk_bias"),
                    "strategy_next": brain_advisory.get("strategy_next"),
                },
            )
            return
        brain_budget = float(brain_advisory.get("budget_idr") or budget_idr)
        if brain_budget < budget_idr:
            _metric_inc("entries_brain_reduced")
            print(
                f"[KIBOT][BRAIN SIZE] pair={pair} budget reduced Rp{budget_idr:,.0f} -> Rp{brain_budget:,.0f} "
                f"reason={brain_advisory.get('reason')}",
                flush=True,
            )
            _append_runtime_event(
                "brain_reduce",
                {
                    "pair": pair,
                    "symbol": brain_advisory.get("symbol"),
                    "from_budget_idr": budget_idr,
                    "to_budget_idr": brain_budget,
                    "reason": brain_advisory.get("reason"),
                    "strategy_next": brain_advisory.get("strategy_next"),
                },
            )
            budget_idr = brain_budget
        target_profit_pct = float(msg.get("targetProfitPct") or msg.get("target_profit_pct") or pair_cfg.get("min_target_profit_pct") or SURVIVAL_TARGET_PROFIT_PCT)
        capital_bucket = _capital_bucket_tiers()
        if pair_cfg.get("tier") == "D":
            target_profit_pct = max(target_profit_pct, 0.04)
        elif pair_cfg.get("tier") == "C":
            target_profit_pct = max(target_profit_pct, 0.025)
        if entry_price > 0.0 and budget_idr > 0.0:
            use_market = _should_use_market_order(msg, pair) or bool(msg.get("use_market") or False)
            if use_market and not msg.get("breakout_urgent"):
                msg["breakout_urgent"] = True
            what_if = _simulate_what_if(
                pair_id=pair,
                entry_price=entry_price,
                budget_idr=budget_idr,
                spread_pct=spread_pct,
                slippage_pct=slippage_pct,
                trailing_stop_pct=float(msg.get("trailingStopPct") or 0.05),
                target_profit_pct=target_profit_pct,
            )
            _append_runtime_event("what_if", what_if)
            print(
                f"[KIBOT][WHATIF] pair={pair} tiers={','.join(capital_bucket)} ev={what_if['expected_net_pct']:.4f} rr={what_if['risk_reward_ratio']:.2f} rec={what_if['recommendation']}",
                flush=True,
            )
            if what_if["recommendation"] == "SKIP":
                _metric_inc("entries_blocked_whatif")
                _metric_inc("whatif_skips_today")
                print(f"[KIBOT][BLOCK] Blocking {msg_type} - what-if rejected", flush=True)
                return
            _metric_inc("whatif_enters_today")
            if msg.get("one_shot_mode"):
                budget_idr = _activate_one_shot(pair, budget_idr)
                use_market = True
            elif use_market and what_if["recommendation"] == "REDUCE_SIZE":
                budget_idr *= 0.5
        msg["budgetIdr"] = round(float(budget_idr), 2)
        msg["quoteBudgetIdr"] = round(float(budget_idr), 2)
        allowed, reason = _apply_survival_filters(
            pair_id=pair,
            budget_idr=budget_idr,
            spread_pct=spread_pct,
            slippage_pct=slippage_pct,
        )
        if not allowed:
            print(f"[KIBOT][SURVIVAL] pair={pair} blocked reason={reason}", flush=True)
            return
    pair_on_cooldown, cooldown_reason = _pair_cooldown_active(pair)
    if pair_on_cooldown and msg_type not in EXIT_MSG_TYPES:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        print(
            f"[KIBOT][VETO_REJECTED] pair={pair} reason=PAIR_COOLDOWN cooldown_reason={cooldown_reason}",
            flush=True,
        )
        veto = {
            "kind": "lead_lag_breakout",
            "msgType": "VETO_REJECTED",
            "traceId": str(msg.get("traceId") or f"trace-{now_ms}"),
            "senderBotId": "kibot",
            "pairId": pair,
            "trend": "UP",
            "detectedAtEpochMs": now_ms,
            "sentAtEpochMs": now_ms,
            "expiresAtEpochMs": now_ms + 3_000,
            "confidence": 0.35,
            "expectedNetPct": -0.01,
            "shortTermReturnPct": float(msg.get("shortTermReturnPct") or 0.0),
            "mediumTermReturnPct": float(msg.get("mediumTermReturnPct") or 0.0),
            "tradeActivityScore": 0.35,
            "forceRotation": False,
            "payload": {"reason": "PAIR_COOLDOWN", "cooldown_reason": cooldown_reason},
        }
        _veto_metrics["rejected"] += 1
        _update_daily_summary("veto_metric", {"name": "rejected"})
        _broadcast_udp(veto)
        _write_runtime_note()
        return
    trace_id = str(msg.get("traceId") or f"trace-{int(datetime.now(timezone.utc).timestamp() * 1000)}")
    payload = msg.get("payload", {}) if isinstance(msg.get("payload"), dict) else {}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    sent_at_ms = int(msg.get("sentAtEpochMs") or now_ms)
    signal_age_ms = max(0, now_ms - sent_at_ms)
    ttl_ms = 200 if str(pair_cfg.get("tier") or "").upper() == "C" or msg.get("one_shot_mode") else STALE_SIGNAL_ABORT_MS
    if signal_age_ms > ttl_ms:
        print(
            f"[KIBOT][VETO_REJECTED] pair={pair} reason=STALE_SIGNAL age_ms={signal_age_ms}",
            flush=True,
        )
        veto = {
            "kind": "lead_lag_breakout",
            "msgType": "VETO_REJECTED",
            "traceId": trace_id,
            "senderBotId": "kibot",
            "pairId": pair,
            "trend": "UP",
            "detectedAtEpochMs": now_ms,
            "sentAtEpochMs": now_ms,
            "expiresAtEpochMs": now_ms + 3_000,
            "confidence": 0.50,
            "expectedNetPct": -0.01,
            "shortTermReturnPct": float(msg.get("shortTermReturnPct") or 0.0),
            "mediumTermReturnPct": float(msg.get("mediumTermReturnPct") or 0.0),
            "tradeActivityScore": 0.50,
            "forceRotation": False,
            "payload": {"reason": "STALE_SIGNAL", "signal_age_ms": signal_age_ms},
        }
        _broadcast_udp(veto)
        return

    if msg_type in SAFE_ENTRY_MSG_TYPES and (not _control_plane_healthy or (time.time() - _control_plane_last_success_at) > CONTROL_PLANE_STALE_SEC):
        _suspend_new_entries("control_plane_stale")
        print(f"[KIBOT][BLOCK] Blocking {msg_type} - control-plane stale", flush=True)
        return
    expected_move_pct = float(
        payload.get("expectedMovePct")
        or msg.get("expectedMovePct")
        or msg.get("expectedNetPct")
        or 5.0
    )
    short_term_return_pct = float(
        payload.get("shortTermReturnPct")
        or msg.get("shortTermReturnPct")
        or 0.0
    )

    # Dynamic FOMO guard based on price tier
    current_price_idr = float(msg.get("lastPrice") or msg.get("currentPrice") or 0.0)
    if _is_signal_stale(msg):
        return
    if _is_duplicate_signal(msg):
        return
    fomo_limit = _get_dynamic_fomo_guard(current_price_idr)

    if msg_type == "DETECTOR_HIT":
        tickers = _load_indodax_ticker_snapshot()
        t = tickers.get(pair.lower())
        if t:
            upper, mid, lower = calculate_bollinger_bands(_price_history.get(pair.lower(), []), window=20)
            analysis = analyze_pump_legitimacy(
                pair_id=pair,
                price_now=current_price_idr,
                price_24h_ago=current_price_idr * (1 - (short_term_return_pct / 100.0)),
                price_1h_ago=current_price_idr, # Approximation
                price_15m_ago=current_price_idr, # Approximation
                volume_24h_idr=float(t.get("vol_idr") or 0.0),
                volume_1h_idr=float(t.get("vol_idr") or 0.0) / 24.0, # Approximation
                high_24h=float(t.get("high") or current_price_idr),
                low_24h=float(t.get("low") or current_price_idr),
                bollinger_upper=upper,
                bollinger_middle=mid,
                bollinger_lower=lower,
                has_binance_pair=False, # Default if not checked
            )
            print(f"[KIBOT][TRINITY] {pair} Legitimacy Score: {analysis.legitimacy_score} ({analysis.pump_phase})", flush=True)
            if analysis.legitimacy_score >= 70:
                print(f"[KIBOT][TRINITY] {pair} High legitimacy detected. Triggering urgent AI scouting...", flush=True)
                _trigger_urgent_ai_scout(pair)
            if analysis.legitimacy_score < 40:
                print(f"[KIBOT][BLOCK] {pair} REJECTED by Trinity Legitimacy Detector (Score: {analysis.legitimacy_score})", flush=True)
                return

    if msg_type == "DETECTOR_HIT" and short_term_return_pct >= fomo_limit:
        print(
            f"[KIBOT][VETO_REJECTED] pair={pair} reason=FOMO_GUARD rise_pct={short_term_return_pct:.2f} limit={fomo_limit:.1f}% price={current_price_idr:.0f}",
            flush=True,
        )
        veto = {
            "kind": "lead_lag_breakout",
            "msgType": "VETO_REJECTED",
            "traceId": trace_id,
            "senderBotId": "kibot",
            "pairId": pair,
            "trend": "UP",
            "detectedAtEpochMs": now_ms,
            "sentAtEpochMs": now_ms,
            "expiresAtEpochMs": now_ms + 3_000,
            "confidence": 0.55,
            "expectedNetPct": 0.0,
            "shortTermReturnPct": short_term_return_pct,
            "mediumTermReturnPct": float(msg.get("mediumTermReturnPct") or 0.0),
            "tradeActivityScore": 0.55,
            "forceRotation": False,
            "payload": {
                "reason": "FOMO_GUARD",
                "entry_mode": "LIMIT_PULLBACK",
                "limit_correction_pct": FOMO_LIMIT_CORRECTION_PCT,
            },
        }
        _broadcast_udp(veto)
        return
    if msg_type in {"SELL_WALL_SURGE", "MOMENTUM_LOSS"} and pair.lower() in _active_positions_cache:
        _emit_emergency_veto_sell(
            pair=pair,
            reason=f"KiBot_{msg_type.lower()}",
            trace_id=trace_id,
            confidence=0.96,
            expected_net_pct=max(0.1, expected_move_pct),
            extra_payload={"source_msg_type": msg_type},
        )
        return

    est_slippage_pct = float(payload.get("estSlippagePct") or msg.get("estSlippagePct") or 1.5)
    viability = _estimate_exit_viability(expected_move_pct, est_slippage_pct)
    score = _coingecko_track_record_score(pair)
    trending_symbols = {c.get("symbol", "").lower() for c in _get_coingecko_trending_cache()}
    pair_symbol = pair.split("_", 1)[0].lower()
    if pair_symbol in trending_symbols:
        score = min(0.98, score + 0.12)
    ai_confidence = float(payload.get("confidence") or msg.get("confidence") or score)
    min_score = AI_APPROVAL_INSTANT_MIN_SCORE if msg_type == "INSTANT_BUY_ANOMALY" else AI_APPROVAL_MIN_SCORE
    min_net = AI_APPROVAL_INSTANT_MIN_EXPECTED_NET_PCT if msg_type == "INSTANT_BUY_ANOMALY" else AI_APPROVAL_MIN_EXPECTED_NET_PCT
    if msg_type == "INSTANT_BUY_ANOMALY":
        approved = viability["net_profit_pct"] >= min_net and score >= min_score and ai_confidence >= min_score
        if approved:
            _trigger_urgent_ai_scout(pair)
    else:
        approved = viability["net_profit_pct"] >= min_net and score >= min_score and ai_confidence >= min_score

    veto_msg_type = "VETO_SELL_CONFIRMED" if msg_type in {"SELL_WALL_SURGE", "MOMENTUM_LOSS"} else "VETO_APPROVED"
    if not approved:
        veto_msg_type = "VETO_REJECTED"
        print(
            f"[KIBOT][VETO_REJECTED] pair={pair} net={viability['net_profit_pct']:.4f}% reason=AI_CONFIDENCE_GATE score={score:.3f} ai={ai_confidence:.3f}",
            flush=True,
        )
        _veto_metrics["rejected"] += 1
        _update_daily_summary("veto_metric", {"name": "rejected"})
    else:
        print(
            f"[KIBOT][{veto_msg_type}] pair={pair} net={viability['net_profit_pct']:.4f}% trackScore={score:.3f} ai={ai_confidence:.3f}",
            flush=True,
        )
        if veto_msg_type == "VETO_APPROVED":
            _veto_metrics["approved"] += 1
            _update_daily_summary("veto_metric", {"name": "approved"})
        elif veto_msg_type == "VETO_SELL_CONFIRMED":
            _veto_metrics["sell_confirmed"] += 1
            _update_daily_summary("veto_metric", {"name": "sell_confirmed"})

    veto = {
        "kind": "lead_lag_breakout",
        "msgType": veto_msg_type,
        "traceId": trace_id,
        "senderBotId": "kibot",
        "pairId": pair,
        "trend": "REVERSAL" if msg_type in {"SELL_WALL_SURGE", "MOMENTUM_LOSS"} else "UP",
        "detectedAtEpochMs": now_ms,
        "sentAtEpochMs": now_ms,
        "expiresAtEpochMs": now_ms + 3_000,
        "confidence": min(0.99, (score * 0.55) + (ai_confidence * 0.45)),
        "expectedNetPct": viability["net_profit_pct"],
        "shortTermReturnPct": expected_move_pct,
        "mediumTermReturnPct": expected_move_pct * 0.5,
        "tradeActivityScore": score,
        "forceRotation": True,
        "payload": {
            "exit_viability": viability,
            "track_record_score": score,
            "ai_confidence": ai_confidence,
            "ai_gate_min_score": min_score,
            "ai_gate_min_expected_net_pct": min_net,
            "coingecko_trending_match": pair_symbol in trending_symbols,
        },
    }
    _broadcast_udp(veto)
    _write_runtime_note()


def _extract_symbol_from_text(text: str) -> str:
    if not text:
        return ""
    upper = text.upper()
    bracketed = re.findall(r"\(([A-Z0-9]{2,12})\)", upper)
    if bracketed:
        return bracketed[0].lower()
    plain = re.findall(r"\b([A-Z]{2,8})\b", upper)
    if plain:
        common = {"NEW", "LISTING", "WILL", "SPOT", "BINANCE", "TOKEN", "MARKET"}
        filtered = [token for token in plain if token not in common]
        if filtered:
            return filtered[0].lower()
    return ""


def _cleanup_seen_news_ids() -> None:
    """Remove old entries from _seen_news_ids to prevent unbounded memory growth."""
    global _seen_news_ids, _seen_news_ids_timestamps
    now = time.time()
    ttl_sec = 3600 * 24  # 24 hours TTL
    with _state_lock:
        expired = [k for k, ts in _seen_news_ids_timestamps.items() if (now - ts) > ttl_sec]
        for k in expired:
            _seen_news_ids.discard(k)
            _seen_news_ids_timestamps.pop(k, None)
        # Also enforce max size limit
        if len(_seen_news_ids) > _SEEN_NEWS_IDS_MAX_SIZE:
            # Remove oldest entries
            sorted_by_time = sorted(_seen_news_ids_timestamps.items(), key=lambda x: x[1])
            to_remove = len(_seen_news_ids) - _SEEN_NEWS_IDS_MAX_SIZE + 100  # Remove extra buffer
            for k, _ in sorted_by_time[:to_remove]:
                _seen_news_ids.discard(k)
                _seen_news_ids_timestamps.pop(k, None)


def _scan_rss_and_initiate_detector(feed_url: str, source: str) -> None:
    global _seen_news_ids, _seen_news_ids_timestamps
    try:
        response = requests.get(feed_url, timeout=TIMEOUT)
        if response.status_code != 200:
            return
        root = ET.fromstring(response.text)
    except (requests.exceptions.RequestException, ET.ParseError) as e:
        print(f"[KIBOT][WARN] RSS parse/fetch error source={source} reason={type(e).__name__}", flush=True)
        return
    except Exception as e:
        print(f"[KIBOT][WARN] RSS unexpected error source={source} reason={e}", flush=True)
        return
    items = root.findall(".//item")[:12]
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        identity = f"{source}|{title}|{link}"
        with _state_lock:
            if identity in _seen_news_ids:
                continue
            _seen_news_ids.add(identity)
            _seen_news_ids_timestamps[identity] = time.time()
        lower_text = f"{title} {desc}".lower()
        if "list" not in lower_text and "listing" not in lower_text and "new coin" not in lower_text:
            continue
        symbol = _extract_symbol_from_text(title) or _extract_symbol_from_text(desc)
        if not symbol:
            continue
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        pair_id = f"{symbol}_idr"
        detector_hit = {
            "kind": "lead_lag_breakout",
            "msgType": "DETECTOR_HIT",
            "traceId": f"news-{source}-{symbol}-{now_ms}",
            "senderBotId": "kibot",
            "pairId": pair_id,
            "trend": "UP",
            "detectedAtEpochMs": now_ms,
            "sentAtEpochMs": now_ms,
            "expiresAtEpochMs": now_ms + 3_000,
            "confidence": 0.74,
            "expectedNetPct": 1.8,
            "shortTermReturnPct": 1.8,
            "mediumTermReturnPct": 0.9,
            "tradeActivityScore": 0.70,
            "forceRotation": True,
            "payload": {
                "source": source,
                "headline": title[:140],
                "type": "NEW_LISTING_NEWS",
            },
        }
        _broadcast_udp(detector_hit)


def _news_scanner_loop() -> None:
    cleanup_counter = 0
    while not _shutdown_event.is_set():
        try:
            _scan_rss_and_initiate_detector(BINANCE_ANNOUNCEMENT_RSS, "binance_rss")
            _scan_rss_and_initiate_detector(COINGECKO_NEWS_FEED, "coingecko_rss")
            # Cleanup seen_news_ids periodically (every ~10 iterations)
            cleanup_counter += 1
            if cleanup_counter >= 10:
                _cleanup_seen_news_ids()
                cleanup_counter = 0
        except Exception as e:
            print(f"[KIBOT][WARN] news_scanner_loop error: {e}", flush=True)
        # Use event.wait for graceful shutdown
        if _shutdown_event.wait(timeout=max(30, NEWS_SCAN_INTERVAL_SEC)):
            break


def _normalize_sector_map(raw_obj: Any) -> Dict[str, list[str]]:
    if not isinstance(raw_obj, dict):
        return {}
    out: Dict[str, list[str]] = {}
    for k, v in raw_obj.items():
        if not isinstance(k, str) or not isinstance(v, list):
            continue
        cleaned = []
        for item in v:
            if not isinstance(item, str):
                continue
            sym = item.strip().lower()
            if not sym:
                continue
            cleaned.append(sym)
        if cleaned:
            out[k.strip().lower()] = cleaned[:12]
    return out


def _load_indodax_ticker_snapshot() -> Dict[str, Dict[str, Any]]:
    global _indodax_ticker_cache, _indodax_ticker_snapshot, _indodax_ticker_cache_at
    now = time.time()
    if _indodax_ticker_cache and (now - _indodax_ticker_cache_at) < max(60, INDODAX_TICKER_CACHE_TTL_SEC):
        return _indodax_ticker_snapshot
    try:
        response = requests.get(INDODAX_SUMMARIES_URL, timeout=TIMEOUT)
        if response.status_code >= 300:
            return _indodax_ticker_snapshot
        body = response.json()
        tickers = ((body or {}).get("tickers") or {})
        pairs = set()
        snapshot: Dict[str, Dict[str, Any]] = {}
        if isinstance(tickers, dict):
            for pair_key, row in tickers.items():
                if not isinstance(pair_key, str):
                    continue
                norm = pair_key.strip().lower()
                if norm:
                    pairs.add(norm)
                    snapshot[norm] = row if isinstance(row, dict) else {}
        if pairs:
            _indodax_ticker_cache = pairs
            _indodax_ticker_snapshot = snapshot
            _indodax_ticker_cache_at = now
        return _indodax_ticker_snapshot
    except Exception:
        return _indodax_ticker_snapshot


def _load_indodax_tickers() -> set[str]:
    return set(_load_indodax_ticker_snapshot().keys())


def _sanitize_sector_map_for_indodax(raw_map: Dict[str, list[str]]) -> Dict[str, list[str]]:
    if not raw_map:
        return {}
    tickers = _load_indodax_tickers()
    if not tickers:
        return raw_map
    out: Dict[str, list[str]] = {}
    for sector, coins in raw_map.items():
        keep: list[str] = []
        for coin in coins:
            base = coin.strip().lower()
            if not base:
                continue
            if f"{base}_idr" in tickers:
                keep.append(base)
        if keep:
            out[sector] = keep
    return out


def _fetch_dynamic_correlation_map() -> Dict[str, list[str]]:
    trending = _get_coingecko_trending_cache()
    system_prompt = "Return ONLY JSON object map: {'sector_name':['coin1','coin2','coin3']} without prose."
    user_prompt = (
        "Provide a JSON map of the top 10 most active cryptocurrency sector correlations today. "
        f"CoinGecko trending snapshot: {json.dumps(trending, ensure_ascii=True)}. "
        "Prioritize sectors/coins with strongest momentum now."
    )
    routed_text, provider = _call_ai_router(
        task="correlation_matrix",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_hint=CORRELATION_MODEL,
        timeout_sec=CORRELATION_TIMEOUT_SEC,
    )
    if routed_text:
        print(f"[KIBOT][AI_CORRELATION_FETCH] provider={provider}", flush=True)
        return _normalize_sector_map(_parse_json_candidate(routed_text))
    if not CORRELATION_API_URL:
        print("[KIBOT][AI_CORRELATION_FETCH][SKIP] router+legacy unavailable.", flush=True)
        return {}
    payload = {
        "model": CORRELATION_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    headers = {"Content-Type": "application/json"}
    if CORRELATION_API_KEY:
        headers["Authorization"] = f"Bearer {CORRELATION_API_KEY}"
    response = requests.post(CORRELATION_API_URL, headers=headers, json=payload, timeout=CORRELATION_TIMEOUT_SEC)
    if response.status_code >= 300:
        return {}
    return _normalize_sector_map(_parse_json_candidate(_extract_assistant_text(response.json() or {})))


def _broadcast_dynamic_correlation_map() -> None:
    global _last_sector_map
    if not CORRELATION_ENABLED:
        return
    try:
        sectors = _fetch_dynamic_correlation_map()
        sectors = _sanitize_sector_map_for_indodax(sectors)
        if not sectors:
            return
        _last_sector_map = sectors
        msg = {
            "msgType": "CORRELATION_MATRIX",
            "senderBotId": "kibot",
            "updatedAtEpochMs": int(datetime.now(timezone.utc).timestamp() * 1000),
            "sectors": sectors,
        }
        _broadcast_udp(msg)
        print(f"[KIBOT][AI_CORRELATION_FETCH] sectors={len(sectors)}", flush=True)
        _append_runtime_event("correlation_matrix_refresh", {"sector_count": len(sectors)})
        _write_runtime_note()
    except Exception as error:
        print(f"[KIBOT][AI_CORRELATION_FETCH][ERROR] {error}", flush=True)


def _correlation_loop() -> None:
    while not _shutdown_event.is_set():
        try:
            _broadcast_dynamic_correlation_map()
        except Exception as e:
            print(f"[KIBOT][WARN] correlation_loop error: {e}", flush=True)
        if _shutdown_event.wait(timeout=max(300, CORRELATION_INTERVAL_SEC)):
            break


def _coingecko_trending_loop() -> None:
    while not _shutdown_event.is_set():
        try:
            _refresh_coingecko_trending_cache()
        except Exception as e:
            print(f"[KIBOT][WARN] coingecko_trending_loop error: {e}", flush=True)
        if _shutdown_event.wait(timeout=max(180, COINGECKO_TRENDING_INTERVAL_SEC)):
            break


def _pair_symbol(pair: str) -> str:
    return pair.split("_", 1)[0].lower().strip()


def _symbol_in_ai_sector(symbol: str) -> bool:
    if not symbol:
        return False
    for coins in _last_sector_map.values():
        if symbol in coins:
            return True
    return False


def _emit_emergency_veto_sell(
    pair: str,
    reason: str,
    trace_id: str | None = None,
    confidence: float = 0.94,
    expected_net_pct: float = 0.2,
    extra_payload: Dict[str, Any] | None = None,
) -> None:
    now = time.time()
    pair_key = pair.lower().strip()
    if not pair_key:
        return
    cooldown_until = _emergency_sell_cooldown_until.get(pair_key, 0.0)
    if now < cooldown_until:
        return
    _emergency_sell_cooldown_until[pair_key] = now + max(3, EMERGENCY_SELL_COOLDOWN_SEC)
    now_ms = int(now * 1000)
    payload_obj = {
        "reason": reason,
        "trigger": "kibot_active_overwatch",
    }
    if isinstance(extra_payload, dict):
        payload_obj.update(extra_payload)
    veto = {
        "kind": "lead_lag_breakout",
        "msgType": "EMERGENCY_VETO_SELL",
        "traceId": trace_id or f"eveto-{pair_key}-{now_ms}",
        "senderBotId": "kibot",
        "pairId": pair_key,
        "trend": "REVERSAL",
        "detectedAtEpochMs": now_ms,
        "sentAtEpochMs": now_ms,
        "expiresAtEpochMs": now_ms + 3_000,
        "confidence": confidence,
        "expectedNetPct": expected_net_pct,
        "shortTermReturnPct": -0.8,
        "mediumTermReturnPct": -0.5,
        "tradeActivityScore": 0.8,
        "forceRotation": True,
        "payload": payload_obj,
    }
    _broadcast_udp(veto)
    print(
        f"[KIBOT][EMERGENCY_VETO_SELL] pair={pair_key} reason={reason} trace={veto['traceId']}",
        flush=True,
    )
    _veto_metrics["emergency_sell"] += 1
    _update_daily_summary("veto_metric", {"name": "emergency_sell"})
    _append_runtime_event(
        "emergency_veto_sell",
        {"pair": pair_key, "reason": reason, "trace_id": veto["traceId"]},
    )
    _write_runtime_note()


def _process_orderbook_collapse(msg: Dict[str, Any]) -> None:
    pair = str(msg.get("pair") or msg.get("pairId") or "").lower().strip()
    if not pair:
        return
    if pair not in _active_positions_cache:
        return
    _emit_emergency_veto_sell(
        pair=pair,
        reason="KiBot_orderbook_collapse",
        trace_id=str(msg.get("traceId") or ""),
        confidence=0.97,
        expected_net_pct=float(msg.get("expectedNetPct") or 0.2),
        extra_payload={
            "source_msg_type": str(msg.get("msgType") or "").upper(),
            "short_term_return_pct": float(msg.get("shortTermReturnPct") or 0.0),
            "medium_term_return_pct": float(msg.get("mediumTermReturnPct") or 0.0),
        },
    )


def _process_active_positions(msg: Dict[str, Any]) -> None:
    global _last_active_positions_log_at
    positions = msg.get("positions")
    if not isinstance(positions, list):
        return
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    tracked_pairs: Dict[str, Dict[str, Any]] = {}
    for row in positions:
        if not isinstance(row, dict):
            continue
        pair = str(row.get("pairId") or "").lower().strip()
        if not pair:
            continue
        tracked_pairs[pair] = row
    # === TRINITY V5.0: TRAILING & MATH REVIEW ===
    current_cache_pairs = set(tracked_pairs.keys())
    previous_cache_pairs = set(_active_positions_cache.keys())

    # Check for new positions to start trailing
    for pair in current_cache_pairs - previous_cache_pairs:
        row = tracked_pairs[pair]
        entry_price = float(row.get("entryPrice") or row.get("price") or 0.0)
        if entry_price > 0:
            _active_trails[pair] = {
                "entry_price": entry_price,
                "max_price": entry_price,
                "partial_tp_done": False,
                "entry_time": time.time()
            }
            print(f"[KIBOT][TRAIL] Started trailing for {pair} at {entry_price}", flush=True)
            _update_daily_summary("coin_bought", {"pair": pair})

    # Check for closed positions to record math
    for pair in previous_cache_pairs - current_cache_pairs:
        if pair in _active_trails:
            trail = _active_trails.pop(pair)
            # Find the last message to get pnl
            # This is a bit tricky, but we'll use the cached pnl from before it disappeared
            last_row = _active_positions_cache.get(pair, {})
            pnl_pct = float(last_row.get("pnlPct") or 0.0)
            _record_trade_result(pair, gross_pnl_pct=pnl_pct, entry_time=trail["entry_time"])
            print(f"[KIBOT][MATH] Recorded trade for {pair}: {pnl_pct:+.2%}", flush=True)
        _update_daily_summary("coin_sold", {"pair": pair})

    # Update active trails
    for pair, row in tracked_pairs.items():
        if pair in _active_trails:
            price_now = float(row.get("lastPrice") or row.get("price") or 0.0)
            if price_now <= 0: continue

            trail_action = update_trailing_stop(pair, price_now)
            if trail_action == "PARTIAL_TP":
                smart_exit(pair, reason="TRINITY_PARTIAL_TP", trace_id=f"tp-{pair}-{int(time.time())}", size_multiplier=0.4)
            elif trail_action == "EXIT_NOW":
                smart_exit(pair, reason="TRINITY_TRAILING_STOP_HIT", trace_id=f"exit-{pair}-{int(time.time())}")

    _active_positions_cache.clear()
    _active_positions_cache.update(tracked_pairs)
    now_ts = time.time()
    if (now_ts - _last_active_positions_log_at) >= 30:
        _last_active_positions_log_at = now_ts
        print(
            f"[KIBOT][ACTIVE_POSITIONS] count={len(tracked_pairs)} pairs={','.join(sorted(tracked_pairs.keys())[:6])}",
            flush=True,
        )
        _append_runtime_event(
            "active_positions_snapshot",
            {"count": len(tracked_pairs), "pairs": sorted(tracked_pairs.keys())[:6]},
        )
        _write_runtime_note()
    relay_payload = {
        "kind": "trinity_state",
        "msgType": "ACTIVE_POSITIONS",
        "senderBotId": "kibot",
        "sentAtEpochMs": now_ms,
        "positions": list(tracked_pairs.values()),
    }
    _broadcast_udp(relay_payload)
    trending_symbols = {c.get("symbol", "").lower() for c in _get_coingecko_trending_cache()}
    for pair, row in tracked_pairs.items():
        pnl_pct = float(row.get("pnlPct") or 0.0)
        symbol = _pair_symbol(pair)
        track_score = _coingecko_track_record_score(pair)
        is_trending = symbol in trending_symbols
        in_sector = _symbol_in_ai_sector(symbol)
        if pnl_pct <= EMERGENCY_SELL_NEGATIVE_PNL_PCT and (not is_trending) and (track_score < 0.58 or not in_sector):
            _emit_emergency_veto_sell(
                pair=pair,
                reason="macro_overwatch_drop",
                confidence=0.93,
                expected_net_pct=max(0.1, abs(pnl_pct)),
                extra_payload={
                    "pnl_pct": pnl_pct,
                    "track_score": track_score,
                    "trending": is_trending,
                    "in_ai_sector": in_sector,
                },
            )


def _signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global _main_socket
    sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
    print(f"\n[KIBOT][SHUTDOWN] Received {sig_name}, initiating graceful shutdown...", flush=True)
    _shutdown_event.set()
    # Close main socket to unblock recvfrom
    if _main_socket:
        try:
            _main_socket.close()
        except Exception:
            pass
    global _http_server
    if _http_server:
        try:
            _http_server.shutdown()
        except Exception:
            pass
    _append_runtime_event("manager_shutdown", {"signal": sig_name})
    _write_runtime_note(force=True)


def _manager_gate_payload(
    runtime_state: Optional[Dict[str, Any]] = None,
    capital_profile: Optional[Dict[str, Any]] = None,
    *,
    include_runtime_state: bool = True,
) -> Dict[str, Any]:
    if runtime_state is None:
        runtime_state = (
            _fetch_local_runtime_state(timeout_sec=0.35, max_cache_age_sec=2.5)
            if include_runtime_state
            else {}
    )
    equity_estimate = _extract_equity_estimate(runtime_state)
    capital_profile = capital_profile or _adaptive_capital_profile(equity=equity_estimate)
    with _state_lock:
        if _is_scanner_only_node():
            runtime_trading_allowed = runtime_state.get("tradingAllowed")
            return {
                "system_state": "HEALTHY",
                "tradingAllowed": False,
                "runtimeTradingAllowed": runtime_trading_allowed,
                "effectiveTradingAllowed": False,
                "effectiveState": str(runtime_state.get("effectiveState") or "RUNNING"),
                "degradedReason": "",
                "hard_stop_active": False,
                "daily_pnl_pct": 0.0,
                "capital_profile": capital_profile,
            }
        capital_sufficient = bool(capital_profile.get("trading_allowed"))
        manager_trading_allowed = (
            (not _entry_state_is_suspended())
            and not bool(_daily_guard_state.get("hard_stopped"))
            and capital_sufficient
        )
        runtime_trading_allowed = runtime_state.get("tradingAllowed")
        effective_trading_allowed = (
            manager_trading_allowed and bool(runtime_trading_allowed)
            if isinstance(runtime_trading_allowed, bool)
            else manager_trading_allowed
        )
        system_state = str(_gate_state.get("entry_state") or "HEALTHY")
        degraded_reason = (
            str(_gate_state.get("reason") or _daily_guard_state.get("reason") or "")
            if system_state != "HEALTHY" or bool(_daily_guard_state.get("hard_stopped"))
            else ""
        )
        return {
            "system_state": system_state,
            "tradingAllowed": manager_trading_allowed,
            "runtimeTradingAllowed": runtime_trading_allowed,
            "effectiveTradingAllowed": effective_trading_allowed,
            "effectiveState": str(runtime_state.get("effectiveState") or ("RUNNING" if manager_trading_allowed else "DEGRADED")),
            "degradedReason": degraded_reason,
            "hard_stop_active": bool(_daily_guard_state.get("hard_stopped")),
            "daily_pnl_pct": _daily_guard_state.get("daily_pnl_pct"),
            "capital_profile": capital_profile,
        }


def _http_state_payload() -> Dict[str, Any]:
    runtime_state = _fetch_local_runtime_state(timeout_sec=0.35, max_cache_age_sec=2.5)
    equity_estimate = _extract_equity_estimate(runtime_state)
    capital_profile = _adaptive_capital_profile(equity=equity_estimate)
    gate_payload = _manager_gate_payload(runtime_state=runtime_state, capital_profile=capital_profile)
    governor_directives = _governor_effective_directives()
    with _state_lock:
        capital_sufficient = bool(capital_profile.get("trading_allowed"))
        scanner_only = _is_scanner_only_node()
        return {
            "ok": True,
            "service": "kibot-manager",
            "system_state": gate_payload["system_state"],
            "trading_mode": str(_gate_state.get("mode") or "CONSERVATIVE"),
            "effectiveState": gate_payload["effectiveState"],
            "tradingAllowed": gate_payload["tradingAllowed"],
            "runtimeTradingAllowed": gate_payload["runtimeTradingAllowed"],
            "effectiveTradingAllowed": gate_payload["effectiveTradingAllowed"],
            "marketRegime": _daily_summary_market_regime() if DAILY_SUMMARY_ENABLED else "UNKNOWN",
            "degradedReason": gate_payload["degradedReason"],
            "healthDecision": "scanner_node_passive" if scanner_only else str(_gate_state.get("reason") or ""),
            "statusMessage": (
                "Radar node healthy and forwarding scanner feed"
                if scanner_only
                else str(runtime_state.get("statusMessage") or "Server monitor connected to live feed")
            ),
            "nodeStatus": "radar" if scanner_only else str(runtime_state.get("nodeStatus") or "active"),
            "hard_stop_active": gate_payload["hard_stop_active"],
            "daily_pnl_pct": gate_payload["daily_pnl_pct"],
            "api_fail_streak": _api_fail_streak,
            "control_plane_healthy": _control_plane_healthy,
            "pair_memory_count": len(_pair_memory),
            "pairs_on_cooldown": [pair for pair in list(_pair_memory.keys()) if _is_pair_on_cooldown(pair)],
            "remote_scanner_feed": dict(_remote_scanner_feed_state.copy()),
            "capital_health": {
                "total_equity_est_idr": equity_estimate,
                "minimum_viable_idr": MINIMUM_VIABLE_CAPITAL_IDR,
                "is_capital_sufficient": capital_sufficient,
                "fee_round_trip_pct": round(_effective_fee_pct() * 2.0, 4),
                "breakeven_per_trade_pct": round((_effective_fee_pct() * 2.0) + 0.015, 4),
                "adaptive_profile": capital_profile,
                "status": (
                    f"ADAPTIVE_{capital_profile.get('mode')}"
                    if capital_sufficient
                    else f"PAUSED — {capital_profile.get('reason')}"
                ),
            },
            "strategy_governor": {
                "plan_id": governor_directives.get("plan_id"),
                "plan_state": governor_directives.get("plan_state"),
                "plan_is_expired": governor_directives.get("plan_is_expired"),
                "expires_at": governor_directives.get("expires_at"),
                "brain_mode": governor_directives.get("brain_mode"),
                "market_regime": governor_directives.get("market_regime"),
                "capital_posture": governor_directives.get("capital_posture"),
                "strategy_mode": governor_directives.get("strategy_mode"),
                "reason": governor_directives.get("reason"),
                "why": governor_directives.get("why"),
                "confidence": governor_directives.get("confidence"),
                "effective_confidence": governor_directives.get("effective_confidence"),
                "confidence_decay_per_hour": governor_directives.get("confidence_decay_per_hour"),
                "fallback_if_expired": governor_directives.get("fallback_if_expired"),
                "ops_alerts": governor_directives.get("ops_alerts"),
                "what_could_make_this_wrong": governor_directives.get("what_could_make_this_wrong"),
                "provider": governor_directives.get("provider"),
                "updated_at": governor_directives.get("updated_at"),
                "execution": governor_directives.get("execution"),
                "indodax": governor_directives.get("indodax"),
                "polymarket": governor_directives.get("polymarket"),
                "risk": governor_directives.get("risk"),
                "refresh": dict(_governor_state.copy()),
            },
            "metrics": {
                "market_orders_today": _metrics.get("market_orders_today", 0),
                "limit_orders_today": _metrics.get("limit_orders_today", 0),
                "limit_ratio": (
                    float(_metrics.get("limit_orders_today", 0))
                    / max(float(_metrics.get("limit_orders_today", 0)) + float(_metrics.get("market_orders_today", 0)), 1.0)
                ),
                "fee_bleed_est_idr": _metrics.get("fee_bleed_est_idr", 0.0),
                "entries_blocked": {
                    "hard_stop": _metrics.get("entries_blocked_hard_stop", 0),
                    "learn_gate": _metrics.get("entries_blocked_learn_gate", 0),
                    "whatif": _metrics.get("entries_blocked_whatif", 0),
                    "brain": _metrics.get("entries_blocked_brain", 0),
                },
                "entries_brain_reduced": _metrics.get("entries_brain_reduced", 0),
                "whatif_enter_rate": (
                    float(_metrics.get("whatif_enters_today", 0))
                    / max(float(_metrics.get("whatif_enters_today", 0)) + float(_metrics.get("whatif_skips_today", 0)), 1.0)
                ),
            },
            "brain_assist": _brain.snapshot(),
            "math_review": {
                "last_action": _math_review_last_action,
                "last_reason": _math_review_last_reason,
                "trade_journal_count": len(_math_review_trade_journal),
                "current_pnl_state": portfolio_manager.get_pnl_state(),
            },
            "portfolio": {
                "active_count": len(portfolio_manager.positions),
                "total_budget_allocated": sum(p.budget_idr for p in portfolio_manager.positions.values()),
                "positions": [
                    {
                        "pair": p.pair_id,
                        "category": p.category,
                        "entry_price": p.entry_price,
                        "last_price": p.last_price,
                        "pnl_pct": p.pnl_pct,
                        "hold_min": (time.time() - p.entry_time) / 60,
                        "phase": p.phase
                    } for p in portfolio_manager.positions.values()
                ]
            },
            "v6_stats": {
                "lead_lag_count": len(LEAD_LAG_PAIRS),
                "futures_proxy_count": len(FUTURES_PROXY_PAIRS),
                "indodax_only_count": len(INDODAX_ONLY_PAIRS)
            },
            "uptime_seconds": int(time.time() - _bot_start_time),
            "checked_at": _safe_isoformat(),
        }


class _ManagerStateHandler(BaseHTTPRequestHandler):
    def _safe_write(self, raw: bytes) -> None:
        try:
            self.wfile.write(raw)
        except BrokenPipeError:
            print("[KIBOT][HTTP] client closed response early", flush=True)
        except ConnectionResetError:
            print("[KIBOT][HTTP] client reset response stream", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self._safe_write(DASHBOARD_HTML.encode("utf-8"))
            return

        if self.path.startswith("/api/state"):
            global _http_state_cache, _http_state_cache_lock
            # Always serve cached snapshot (populated by background thread)
            with _http_state_cache_lock:
                payload = _http_state_cache if _http_state_cache else {"ok": False, "error": "cache_not_ready"}
            raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self._safe_write(raw)
            return
        if self.path.startswith("/api/gate"):
            payload = _manager_gate_payload(include_runtime_state=False)
            raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self._safe_write(raw)
            return
        if self.path.startswith("/api/scanner-feed"):
            payload = _load_local_scanner_feed()
            raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self._safe_write(raw)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/api/notify"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            payload = json.loads(body or "{}")
            message = str(payload.get("msg") or "").strip()
            if message:
                print(f"[KIBOT][NOTIFY] {message}", flush=True)
                _append_runtime_event("notify", {"message": message})
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}, ensure_ascii=True).encode("utf-8"))
        except Exception as error:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def _state_server_loop() -> None:
    global _http_server
    bind_host = os.getenv("KIBOT_MANAGER_HTTP_BIND_HOST", "127.0.0.1")
    bind_port = int(os.getenv("KIBOT_MANAGER_HTTP_BIND_PORT", str(UDP_BIND_PORT)))
    try:
        server = ThreadingHTTPServer((bind_host, bind_port), _ManagerStateHandler)
        _http_server = server
        print(f"[KIBOT][HTTP] state server listening on {bind_host}:{bind_port}", flush=True)
        server.serve_forever(poll_interval=0.5)
    except Exception as error:
        print(f"[KIBOT][HTTP][ERROR] failed to start state server reason={error}", flush=True)
    finally:
        _http_server = None

def _pair_screen_loop() -> None:
    global _screen_cache, _last_screen_time
    print("[KIBOT] Screener loop started.", flush=True)
    while not _shutdown_event.is_set():
        try:
            now = time.time()
            if (now - _last_screen_time) >= 900.0:
                _last_screen_time = now
                _screen_cache = screen_all_pairs()
                if _screen_cache:
                    top = _screen_cache[0]
                    print(
                        f"[KIBOT][SCREEN] top={top['pair_id']} score={top['analysis'].legitimacy_score:.1f} phase={top['analysis'].pump_phase}",
                        flush=True,
                    )
                    _append_runtime_event(
                        "pair_screen_update",
                        {
                            "top_pair": top["pair_id"],
                            "score": top["analysis"].legitimacy_score,
                            "phase": top["analysis"].pump_phase,
                            "count": len(_screen_cache),
                        },
                    )
                    _write_runtime_note()
        except Exception as error:
            print(f"[KIBOT][WARN] pair_screen_loop error: {error}", flush=True)

        if _shutdown_event.wait(timeout=30.0):
            break

def _simulation_loop() -> None:
    """
    Background thread for Bayesian What-If simulation.
    Runs every 15 minutes.
    """
    simulation_runner = globals().get("run_simulation")
    if not _WHATIF_AVAILABLE or not callable(simulation_runner):
        print("[KIBOT] Simulation engine not available (missing kibot_whatif_engine).", flush=True)
        return

    print("[KIBOT] Simulation loop started.", flush=True)
    while not _shutdown_event.is_set():
        try:
            # 1. Fetch current price snapshot
            snapshot = _load_indodax_ticker_snapshot()
            market_prices = {}
            for pair, data in snapshot.items():
                last = data.get("last")
                if last:
                    try:
                        market_prices[pair] = float(last)
                    except:
                        pass

            # 2. Run simulation
            if market_prices:
                print(f"[KIBOT][SIM] Analyzing {len(market_prices)} pairs...", flush=True)
                simulation_runner(market_prices)

        except Exception as error:
            print(f"[KIBOT][WARN] simulation_loop error: {error}", flush=True)

        if _shutdown_event.wait(timeout=900):
            break

def _math_review_loop() -> None:
    global _last_math_review_at, _math_review_last_action, _math_review_last_reason
    print("[KIBOT] Math review loop started.", flush=True)
    while not _shutdown_event.is_set():
        try:
            # 1. Update Arbitrator Balances
            indodax_bal = _current_balance_snapshot().get("equity_idr", 0.0)
            poly_bal_usdc = 0.0
            try:
                # Poll Polymarket engine (local port 11600)
                resp = requests.get(f"http://127.0.0.1:11600/api/balance", timeout=5)
                if resp.status_code == 200:
                    poly_data = resp.json()
                    poly_bal_usdc = poly_data.get("equity_usdc", 0.0)
            except Exception as e:
                print(f"[v7][ARBITRATOR] Polymarket balance poll failed: {e}", flush=True)
            
            _arbitrator.update_balances(indodax_idr=indodax_bal, polymarket_usdc=poly_bal_usdc)

            # 2. Run Periodic Review
            now = time.time()
            if (now - _last_math_review_at) >= 1800.0:
                _last_math_review_at = now
                result = _run_math_review()
                _math_review_last_action = str(result.get("action") or "UNKNOWN")
                _math_review_last_reason = str(result.get("reason") or "")
        except Exception as error:
            print(f"[KIBOT][MATH_REVIEW][ERROR] {error}", flush=True)

        if _shutdown_event.wait(timeout=60.0):
            break

def _maybe_run_30min_math_review() -> None:
    global _last_math_review_at, _math_review_last_action, _math_review_last_reason
    now = time.time()
    if (now - _last_math_review_at) >= 1800.0:
        _last_math_review_at = now
        result = _run_math_review()
        _math_review_last_action = str(result.get("action") or "UNKNOWN")
        _math_review_last_reason = str(result.get("reason") or "")
import urllib.request
from datetime import datetime, timedelta

DATA_DIR = Path(os.getenv("KIBOT_MANAGER_DATA_DIR", str(_EARLY_RUNTIME_ROOT / "data")))
DATA_DIR.mkdir(exist_ok=True)

def append_trade_to_daily_log(trade: dict):
    date_wib = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")
    log_file = DATA_DIR / f"trades_{date_wib}.json"
    trades = []
    if log_file.exists():
        try:
            trades = json.loads(log_file.read_text())
        except:
            pass
    trade["logged_at"] = time.time()
    trades.append(trade)
    log_file.write_text(json.dumps(trades, indent=2))

def run_daily_data_sync():
    today_wib = (datetime.utcnow() + timedelta(hours=7)).date()
    synced, deleted_local = 0, 0
    for data_file in sorted(DATA_DIR.glob("trades_*.json")):
        try:
            date_str = data_file.stem.replace("trades_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            age_days = (today_wib - file_date).days
            if 1 <= age_days <= 3:
                if _sync_trades_to_supabase(data_file):
                    synced += 1
            if age_days > 3:
                data_file.unlink()
                deleted_local += 1
        except Exception as e:
            print(f"[LIFECYCLE] Error {data_file}: {e}", flush=True)
    _cleanup_supabase_old_data()
    print(f"[LIFECYCLE] Sync: {synced} files, deleted: {deleted_local} files", flush=True)

def _sync_trades_to_supabase(data_file: Path) -> bool:
    if LOCAL_FIRST_STORAGE and not SUPABASE_BACKUP_ENABLED:
        return False
    try:
        trades = json.loads(data_file.read_text())
        if not trades: return True
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")
        if not url or not key: return False
        req = urllib.request.Request(f"{url}/rest/v1/trade_history", data=json.dumps(trades).encode(), headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "resolution=ignore-duplicates"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 201)
    except Exception: return False

def _cleanup_supabase_old_data():
    if LOCAL_FIRST_STORAGE and not SUPABASE_BACKUP_ENABLED:
        return
    try:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")
        if not url: return
        cutoff = datetime.utcnow() - timedelta(days=30)
        req = urllib.request.Request(f"{url}/rest/v1/trade_history?created_at=lt.{cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}", headers={"apikey": key, "Authorization": f"Bearer {key}"}, method="DELETE")
        urllib.request.urlopen(req, timeout=10)
    except Exception: pass

def keep_supabase_alive():
    if LOCAL_FIRST_STORAGE and not SUPABASE_BACKUP_ENABLED:
        return
    try:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")
        if not url: return
        req = urllib.request.Request(f"{url}/rest/v1/pair_memory_history?select=pair_id&limit=1", headers={"apikey": key, "Authorization": f"Bearer {key}"})
        urllib.request.urlopen(req, timeout=5)
    except Exception: pass

def _save_daily_state():
    """Bug #6: Persist baseline for hard stop and quarantine."""
    try:
        path = STATE_ROOT / "daily_state.json"
        data = {
            "date": _operational_wib_date(),
            "initial_capital_idr": _hard_stop.initial_capital,
            "daily_pnl": _hard_stop.daily_pnl,
            "entry_loss_count": _entry_loss_count,
            "hard_stopped": False
        }
        _write_json_file(path, data)
    except Exception as e:
        print(f"[v7][STATE_ERR] {e}", flush=True)


def _brain_watch_symbols() -> List[str]:
    symbols: List[str] = []
    for pair in _active_position_pairs()[:4]:
        base = str(pair or "").lower().split("_", 1)[0].upper()
        if base and base not in symbols:
            symbols.append(base)
    for pair in list((_load_json_file(WHATIF_RESULTS_PATH, {}) or {}).get("topOpportunities") or [])[:4]:
        base = str(pair or "").lower().split("_", 1)[0].upper()
        if base and base not in symbols:
            symbols.append(base)
    for item in list(_screen_cache or [])[:4]:
        if not isinstance(item, dict):
            continue
        pair = str(item.get("pair_id") or "").lower().split("_", 1)[0].upper()
        if pair and pair not in symbols:
            symbols.append(pair)
    if not symbols:
        symbols.extend(["BTC", "ETH", "SOL"])
    return symbols[:5]


def _brain_signal_advisory(
    pair: str,
    msg: Dict[str, Any],
    budget_idr: float,
    capital_profile: Dict[str, Any],
) -> Dict[str, Any]:
    directives = _governor_effective_directives()
    execution_cfg = directives.get("execution") if isinstance(directives.get("execution"), dict) else {}
    indodax_cfg = directives.get("indodax") if isinstance(directives.get("indodax"), dict) else {}
    strategy_mode = str(directives.get("strategy_mode") or "NEUTRAL").upper()
    brain_mode = str(directives.get("brain_mode") or "CONTROLLED").upper()
    _brain.ensure_warm(
        watch_symbols=_brain_watch_symbols(),
        context={
            "daily_pnl_pct": _daily_guard_state.get("daily_pnl_pct"),
            "equity_idr": _current_balance_snapshot().get("equity_idr"),
            "free_cash_idr": _current_balance_snapshot().get("free_cash_idr"),
            "capital_profile": capital_profile,
        },
    )
    snapshot = _brain.snapshot() if hasattr(_brain, "snapshot") else {}
    if not isinstance(snapshot, dict) or not snapshot:
        return {
            "allow": True,
            "budget_idr": budget_idr,
            "reason": "brain_snapshot_unavailable",
            "symbol": "",
            "risk_bias": "UNKNOWN",
            "strategy_next": "",
            "watch_review": {},
        }

    symbol = str(msg.get("base_symbol") or str(pair or "").split("_", 1)[0]).upper().strip()
    score = _parse_numeric(msg.get("score")) or 0.0
    market_pulse = snapshot.get("market_pulse") if isinstance(snapshot.get("market_pulse"), dict) else {}
    daily_target = snapshot.get("daily_target") if isinstance(snapshot.get("daily_target"), dict) else {}
    ai_critic = snapshot.get("ai_critic") if isinstance(snapshot.get("ai_critic"), dict) else {}
    risk_bias = str(market_pulse.get("risk_bias") or "UNKNOWN").upper()
    strategy_next = str(daily_target.get("strategy_next") or "").strip()
    top_focus = {str(item).lower() for item in list(_load_json_file(WHATIF_RESULTS_PATH, {}).get("topOpportunities") or [])[:5]}

    review = {}
    for item in list(snapshot.get("watch_reviews") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol") or "").upper() == symbol:
            review = dict(item)
            break
    approved = review.get("approved") if isinstance(review.get("approved"), bool) else None
    review_reason = str(review.get("reason") or "").strip()
    focus_pairs = {
        str(item).lower().strip()
        for item in list(indodax_cfg.get("focus_pairs") or execution_cfg.get("focus_pairs") or [])
        if str(item).strip()
    }
    avoid_pairs = {
        str(item).lower().strip()
        for item in list(indodax_cfg.get("avoid_pairs") or execution_cfg.get("avoid_pairs") or [])
        if str(item).strip()
    }
    if not bool(indodax_cfg.get("allow_entries", True)):
        return {
            "allow": False,
            "budget_idr": budget_idr,
            "reason": str(directives.get("plan_state") or "governor_entries_disabled").lower(),
            "symbol": symbol,
            "risk_bias": risk_bias,
            "strategy_next": strategy_next,
            "watch_review": review,
        }
    max_open_positions = int(_parse_numeric(indodax_cfg.get("max_open_positions")) or 0)
    active_pairs = _active_position_pairs()
    if (
        max_open_positions > 0
        and pair.lower() not in active_pairs
        and len(active_pairs) >= max_open_positions
    ):
        return {
            "allow": False,
            "budget_idr": budget_idr,
            "reason": "governor_position_cap_reached",
            "symbol": symbol,
            "risk_bias": risk_bias,
            "strategy_next": strategy_next,
            "watch_review": review,
        }

    if pair.lower() in avoid_pairs:
        return {
            "allow": False,
            "budget_idr": budget_idr,
            "reason": "governor_avoid_pair",
            "symbol": symbol,
            "risk_bias": risk_bias,
            "strategy_next": strategy_next,
            "watch_review": review,
        }

    budget_multiplier = 1.0
    if strategy_mode == "DEFENSIVE":
        budget_multiplier = min(budget_multiplier, 0.88)
    elif strategy_mode == "OPPORTUNISTIC":
        budget_multiplier = max(
            budget_multiplier,
            float(_parse_numeric(execution_cfg.get("budget_boost")) or 1.02),
        )
    if risk_bias == "RISK_OFF":
        budget_multiplier = min(budget_multiplier, 0.65 if score < 0.85 else 0.8)
    elif risk_bias == "MIXED":
        budget_multiplier = min(budget_multiplier, 0.9)

    target_status = str(daily_target.get("status") or "").upper()
    if target_status == "RECOVERY_MODE":
        budget_multiplier = min(budget_multiplier, 0.75)
    critic_posture = str(ai_critic.get("capital_posture") or "").upper()
    critic_confidence = _parse_numeric(ai_critic.get("confidence")) or 0.0
    critic_focus = {
        str(item).lower().strip()
        for item in list(ai_critic.get("focus_symbols") or [])
        if str(item or "").strip()
    }
    tiny_mode = str(capital_profile.get("mode") or "").upper() in {"MICRO", "BUILDUP"}
    if tiny_mode and (risk_bias == "RISK_OFF" or critic_posture in {"DEFENSIVE", "PROTECT"}):
        budget_multiplier = min(budget_multiplier, 0.85)
    if critic_posture in {"OPPORTUNISTIC", "AGGRESSIVE"} and approved is not False and risk_bias != "RISK_OFF":
        budget_multiplier = max(
            budget_multiplier,
            1.0 + min(0.15, max(0.0, critic_confidence) * 0.15),
        )
    elif critic_posture in {"DEFENSIVE", "PROTECT"}:
        budget_multiplier = min(budget_multiplier, 0.9)
    if symbol in {item.upper() for item in critic_focus} and risk_bias != "RISK_OFF" and approved is not False:
        budget_multiplier = max(budget_multiplier, 1.03 if critic_confidence < 0.8 else 1.08)
    if pair.lower() in focus_pairs and approved is not False:
        budget_multiplier = max(
            budget_multiplier,
            float(_parse_numeric(execution_cfg.get("focus_boost")) or 1.05),
        )

    if approved is False and review_reason in {
        "external_research_risk_off",
        "symbol_not_listed_on_indodax",
        "missing_or_zero_quote_volume",
    }:
        return {
            "allow": False,
            "budget_idr": budget_idr,
            "reason": review_reason or "brain_watch_rejected",
            "symbol": symbol,
            "risk_bias": risk_bias,
            "strategy_next": strategy_next,
            "watch_review": review,
        }

    if risk_bias == "RISK_OFF" and pair.lower() not in top_focus and score < 0.8:
        return {
            "allow": False,
            "budget_idr": budget_idr,
            "reason": "brain_risk_off_non_focus_pair",
            "symbol": symbol,
            "risk_bias": risk_bias,
            "strategy_next": strategy_next,
            "watch_review": review,
        }

    adjusted_budget = budget_idr
    if abs(budget_multiplier - 1.0) > 1e-6:
        adjusted_budget = max(ABSOLUTE_MIN_POSITION_SIZE_IDR, round(float(budget_idr) * budget_multiplier, 2))
    budget_cap = float(_parse_numeric(indodax_cfg.get("budget_per_trade_idr")) or 0.0)
    if budget_cap > 0:
        adjusted_budget = min(adjusted_budget, budget_cap)

    reason_parts: List[str] = []
    if risk_bias and risk_bias != "UNKNOWN":
        reason_parts.append(f"risk_bias={risk_bias.lower()}")
    if target_status:
        reason_parts.append(f"target={target_status.lower()}")
    if review_reason:
        reason_parts.append(f"review={review_reason}")
    if not reason_parts:
        reason_parts.append("brain_neutral")
    if strategy_mode and strategy_mode != "NEUTRAL":
        reason_parts.append(f"governor={strategy_mode.lower()}")
    if brain_mode and brain_mode != "CONTROLLED":
        reason_parts.append(f"brain={brain_mode.lower()}")

    return {
        "allow": True,
        "budget_idr": adjusted_budget,
        "reason": "+".join(reason_parts),
        "symbol": symbol,
        "risk_bias": risk_bias,
        "strategy_next": strategy_next,
        "watch_review": review,
    }


def _brain_thinking_loop():
    """Advisory-only conscience loop."""
    last_think = 0
    interval = int(os.environ.get("KIBOT_THINKING_INTERVAL_MINUTES", "15")) * 60
    while not _shutdown_event.is_set():
        try:
            if time.time() - last_think > interval:
                _brain.think(
                    _brain_watch_symbols(),
                    context={
                        "daily_pnl_pct": _daily_guard_state.get("daily_pnl_pct"),
                        "equity_idr": _current_balance_snapshot().get("equity_idr"),
                        "free_cash_idr": _current_balance_snapshot().get("free_cash_idr"),
                        "capital_profile": _adaptive_capital_profile(),
                    },
                )
                last_think = time.time()
                _write_runtime_note(force=True)
        except Exception as error:
            print(f"[KIBOT][BRAIN][WARN] advisory loop error: {error}", flush=True)
        time.sleep(10)


def _strategy_governor_loop() -> None:
    """Refresh adaptive directives with separate fast and medium sovereign loops."""
    loop_sleep_sec = int(os.getenv("KIBOT_GOVERNOR_LOOP_SEC", "10"))
    last_fast_refresh_at = 0.0
    last_medium_refresh_at = 0.0
    startup_profile = "medium" if _is_scanner_only_node() else "fast"
    try:
        _refresh_governor_directives(force=True, reason="startup", profile=startup_profile)
        _write_runtime_note(force=True)
        now_ts = time.time()
        last_fast_refresh_at = now_ts
        last_medium_refresh_at = now_ts
    except Exception as error:
        print(f"[KIBOT][GOVERNOR][WARN] initial refresh failed: {error}", flush=True)
    while not _shutdown_event.is_set():
        try:
            now_ts = time.time()
            context = _build_governor_context(profile="fast")
            event_fingerprint = _governor_event_fingerprint(context)
            last_event_fingerprint = str(_governor_state.get("last_event_fingerprint") or "")
            last_refresh_at = _iso_to_epoch(str(_governor_state.get("last_refresh_at") or "")) or 0.0
            stale = (time.time() - last_refresh_at) >= GOVERNOR_MAX_STALE_SEC
            due_fast = (now_ts - last_fast_refresh_at) >= max(15, GOVERNOR_FAST_LOOP_SEC)
            due_medium = (now_ts - last_medium_refresh_at) >= max(120, GOVERNOR_MEDIUM_LOOP_SEC)
            if event_fingerprint != last_event_fingerprint:
                reason = "trade_event" if _recent_trade_activity_window_sec(300) else "context_shift"
                _refresh_governor_directives(reason=reason, profile="fast")
                _write_runtime_note(force=True)
                last_fast_refresh_at = now_ts
            elif due_fast:
                _refresh_governor_directives(reason="fast_cycle", profile="fast")
                _write_runtime_note(force=True)
                last_fast_refresh_at = now_ts
            if due_medium:
                _refresh_governor_directives(force=True, reason="medium_cycle", profile="medium")
                _write_runtime_note(force=True)
                last_medium_refresh_at = now_ts
            elif stale:
                _refresh_governor_directives(reason="stale_refresh", profile="fast")
                _write_runtime_note(force=True)
        except Exception as error:
            print(f"[KIBOT][GOVERNOR][WARN] loop error: {error}", flush=True)
        if _shutdown_event.wait(timeout=max(10, loop_sleep_sec)):
            break


def _rotation_governor_loop() -> None:
    """Check for rotation opportunities every 5 minutes."""
    print("[KIBOT][ROTATION] governor loop started", flush=True)
    while not _shutdown_event.is_set():
        try:
            # 1. Get all active positions
            positions = position_manager.all()
            if not positions:
                _shutdown_event.wait(60)
                continue

            # 2. Get waitlisted signals (high confidence)
            # We look at the MSC engine's waitlist
            # _msc_engine is defined as a global
            waitlist = _msc_engine.get_waitlist()
            if not waitlist:
                _shutdown_event.wait(60)
                continue

            # 3. Evaluate rotation
            for pos in positions:
                for signal in waitlist:
                    res = _rotation_engine.evaluate_rotation(pos, signal, {})
                    if res.get("approved"):
                        print(f"[v7][ROTATION] ACTION: {res['reason']}", flush=True)
                        # Execute rotation: Close current, the signal will be picked up by the normal entry loop
                        _relay_to_KiBot({"type": "FORCE_EXIT", "pair": pos['pairId'], "reason": "rotation_opportunity"})
                        # We only do one rotation per cycle to avoid thrashing
                        break
        except Exception as e:
            print(f"[v7][ROTATION][ERROR] loop error: {e}", flush=True)
        
        if _shutdown_event.wait(300): # Check every 5 minutes
            break
def _universe_discovery_loop() -> None:
    """Periodically discovers new high-liquidity coins."""
    print("[KIBOT][UNIVERSE] discovery loop started", flush=True)
    while not _shutdown_event.is_set():
        try:
            new_coins = auto_discover_new_coins(min_vol_idr=500_000_000)
            if new_coins:
                print(f"[KIBOT][UNIVERSE] NEW COINS DISCOVERED: {new_coins}", flush=True)
                telegram_send(f"🚀 **Sovereign Discovery**: New coins onboarded to Universe: {', '.join(new_coins)}")
                # Refresh engine universe immediately
                engine.refresh_universe()
        except Exception as e:
            print(f"[KIBOT][UNIVERSE][ERROR] Discovery error: {e}", flush=True)
        
        if _shutdown_event.wait(300): # Check every 5 minutes
            break

def _remote_scanner_feed_loop() -> None:
    if not REMOTE_SCANNER_FEED_ENABLED:
        print("[KIBOT][REMOTE_SCANNER_FEED] disabled", flush=True)
        return
    print(
        f"[KIBOT][REMOTE_SCANNER_FEED] poll started bot_id={REMOTE_SCANNER_FEED_BOT_ID} "
        f"category={REMOTE_SCANNER_FEED_CATEGORY} interval={REMOTE_SCANNER_FEED_POLL_SEC}s",
        flush=True,
    )
    while not _shutdown_event.is_set():
        try:
            _remote_scanner_feed_state["last_poll_at"] = _safe_isoformat()
            cycles = _fetch_remote_scanner_feed_cycles()
            ingested_total = 0
            latest_created_at = str(_remote_scanner_feed_state.get("last_created_at") or "")
            recent_signal_ids = list(_remote_scanner_feed_state.get("recent_signal_ids") or [])
            for cycle in cycles:
                created_at = str(cycle.get("created_at") or "")
                metadata = cycle.get("metadata") if isinstance(cycle.get("metadata"), dict) else {}
                feed_id = str(metadata.get("feed_id") or created_at or "")
                signals = metadata.get("signals") if isinstance(metadata.get("signals"), list) else []
                summary = metadata.get("summary") if isinstance(metadata.get("summary"), dict) else {}
                if created_at and created_at > latest_created_at:
                    latest_created_at = created_at
                ingested_this_cycle = 0
                for signal in signals[:REMOTE_SCANNER_FEED_MAX_SIGNALS]:
                    normalized = _normalize_remote_scanner_signal(signal)
                    if not normalized:
                        continue
                    signal_uid = str(normalized.get("signal_uid") or "")
                    if signal_uid in recent_signal_ids:
                        continue
                    signal_age_sec = time.time() - _iso_to_epoch(str(normalized.get("timestamp") or ""))
                    if signal_age_sec > REMOTE_SCANNER_FEED_MAX_AGE_SEC:
                        continue
                    normalized["transport"] = "supabase_feed"
                    normalized["feed_id"] = feed_id
                    _msc_engine.process_and_relay(normalized, _relay_to_KiBot)
                    recent_signal_ids.append(signal_uid)
                    ingested_total += 1
                    ingested_this_cycle += 1
                if ingested_this_cycle > 0 or signals:
                    print(
                        f"[KIBOT][REMOTE_SCANNER_FEED] feed={feed_id or '?'} "
                        f"signals={len(signals)} ingested={ingested_this_cycle} "
                        f"sent={summary.get('total_sent', 0)} scanned={summary.get('total_scanned', 0)}",
                        flush=True,
                    )
                    _remote_scanner_feed_state["last_feed_id"] = feed_id
                    _remote_scanner_feed_state["cycles_seen"] = int(_remote_scanner_feed_state.get("cycles_seen") or 0) + 1
            if cycles:
                _remote_scanner_feed_state["last_created_at"] = latest_created_at
                _remote_scanner_feed_state["last_success_at"] = _safe_isoformat()
                _remote_scanner_feed_state["last_error"] = ""
                _remote_scanner_feed_state["signals_ingested"] = int(_remote_scanner_feed_state.get("signals_ingested") or 0) + ingested_total
                _remote_scanner_feed_state["recent_signal_ids"] = recent_signal_ids[-256:]
                _save_remote_scanner_feed_state()
                _write_runtime_note()
        except Exception as error:
            _remote_scanner_feed_state["last_error"] = str(error)
            _save_remote_scanner_feed_state()
            print(f"[KIBOT][REMOTE_SCANNER_FEED][WARN] {error}", flush=True)
        if _shutdown_event.wait(timeout=max(5, REMOTE_SCANNER_FEED_POLL_SEC)):
            break

def _maintenance_loop():
    """Periodic cleanup of internal caches to prevent memory growth."""
    while not _shutdown_event.is_set():
        try:
            now = time.time()
            # 1. Cleanup AI Veto Cache (TTL: 1 hour)
            with _ai_veto_lock:
                expired_vetoes = [p for p, d in _ai_veto_cache.items() if now - d.get("ts", 0) > 3600]
                for p in expired_vetoes:
                    del _ai_veto_cache[p]
            
            # 2. Cleanup Pair Cooldowns
            with _state_lock:
                expired_cooldowns = [p for p, d in _pair_cooldowns.items() if now > d.get("until", 0)]
                for p in expired_cooldowns:
                    del _pair_cooldowns[p]
                    
            # 3. Cleanup Old Prices (Only keep active pairs)
            if len(_price_history) > 500:
                pass

            # 4. Sovereign Intelligence: Sync Dynamic Config based on performance
            try:
                metrics = _get_trade_metrics_today()
                if metrics.get("total_trades", 0) >= 3: # Need some sample size
                    dynamic_config.sync_from_performance(metrics)
                    
                    # 5. Crisis Healing: If performance is poor, force brain refresh
                    if metrics.get("win_rate", 1.0) < 0.4 or metrics.get("profit_factor", 1.0) < 0.8:
                        print("[v7][MAINTENANCE][CRISIS] Performance degraded. Forcing AI Brain refresh...", flush=True)
                        _brain.refresh()
            except Exception as de:
                print(f"[v7][MAINTENANCE][INTEL] Performance sync failed: {de}")

        except Exception as e:
            print(f"[v7][MAINTENANCE][ERROR] {e}", flush=True)
            
        time.sleep(600) # Every 10 minutes

def main() -> None:
    global _main_socket, _last_dashboard_export, _last_btc_upd, _last_screen, _last_review
    print("[BOOT] KiBot Manager Starting...", flush=True)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    _ensure_env()
    try:
        from ki_vault import load_sovereign_env
        load_sovereign_env()
    except Exception as ve:
        print(f"[BOOT][VAULT][WARN] Could not load vaulted env: {ve}")
    
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    _load_daily_state()
    _reconcile_daily_guard_day_rollover()

    # Sync state guard to daily state
    _ensure_hard_stop_consistency()
    _write_json_file(PROVIDER_STATE_PATH, _provider_runtime_state)
    _save_pair_cooldown_state()
    _save_gate_state()
    _save_daily_guard_state()
    _daily_cycle_state["active_wib_date"] = str(_daily_cycle_state.get("active_wib_date") or _wib_today_str())
    _save_daily_cycle_state()
    _bootstrap_daily_guard_from_KiBot()
    _set_conservative_mode("fresh_start")
    if DAILY_SUMMARY_ENABLED:
        _write_json_file(DAILY_SUMMARY_PATH, _load_daily_summary())
    _append_runtime_event(
        "manager_start",
        {
            "KiBot_target": f"{KiBot_UDP_HOST}:{KiBot_UDP_PORT}" if KiBot_UDP_HOST else "",
        },
    )
    _write_runtime_note(force=True)
    force_evaluate_recent_loss()
    scanner_thread = threading.Thread(target=_news_scanner_loop, name="kibot-news-scanner", daemon=True)
    scanner_thread.start()
    corr_thread = threading.Thread(target=_correlation_loop, name="kibot-correlation-loop", daemon=True)
    corr_thread.start()
    gecko_thread = threading.Thread(target=_coingecko_trending_loop, name="kibot-coingecko-loop", daemon=True)
    gecko_thread.start()
    screen_thread = threading.Thread(target=_pair_screen_loop, name="kibot-pair-screen-loop", daemon=True)
    screen_thread.start()
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, name="kibot-heartbeat-loop", daemon=True)
    heartbeat_thread.start()
    threading.Thread(target=_maintenance_loop, daemon=True).start()
    health_gate_thread = threading.Thread(target=_health_gate_loop, name="kibot-health-gate-loop", daemon=True)
    health_gate_thread.start()
    ai_review_thread = threading.Thread(target=_ai_batch_review_loop, name="kibot-ai-review-loop", daemon=True)
    ai_review_thread.start()
    math_review_thread = threading.Thread(target=_math_review_loop, name="kibot-math-review-loop", daemon=True)
    math_review_thread.start()
    
    # === START RESOURCE GOVERNOR (THE BRAIN) ===
    governor_thread = threading.Thread(target=run_resource_governor, name="kibot-resource-governor", daemon=True)
    governor_thread.start()

    # === START AI SCOUT LOOP ===
    try:
        if "kibot_ai_scout" in sys.modules:
            scout_thread = threading.Thread(target=sys.modules["kibot_ai_scout"].run_scout_loop, name="kibot-ai-scout-loop", daemon=True)
            scout_thread.start()
    except Exception as e:
        print(f"[KIBOT][ERROR] Failed to start AI Scout Loop: {e}", flush=True)
    
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        _shutdown_event.set()
        print("[KIBOT] Shutdown signal received.")

async def main_async():
    """Restored v9.0 Async Event Loop."""
    loop = asyncio.get_running_loop()
    
    # 1. Start high-performance UDP listener
    print(f"[BOOT][ASYNC] Initializing Sovereign UDP Pipeline on port {LOCAL_SIGNAL_PORT}...", flush=True)
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: AsyncUDPProtocol(),
        local_addr=('0.0.0.0', LOCAL_SIGNAL_PORT)
    )
    
    # 2. Start maintenance and health tasks
    asyncio.create_task(_scanner_registry.monitor_health())
    
    # 3. Handle signal handler (async version if needed)
    # Already handled in main() via signal.signal

    # Keep loop alive until shutdown
    while not _shutdown_event.is_set():
        await asyncio.sleep(1)
    
    transport.close()
    print("[BOOT][ASYNC] UDP Pipeline closed.", flush=True)

def _load_daily_state():
    """Restores daily capital metrics with WIB context."""
    global _initial_capital_idr, _entry_loss_count
    try:
        path = STATE_ROOT / "daily_state.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        _hard_stop.initial_capital = float(data.get("initial_capital_idr") or 0.0)
        _hard_stop.daily_pnl = float(data.get("daily_pnl") or 0.0)
        _entry_loss_count = data.get("entry_loss_count") or {}
    except Exception as e:
        print(f"[BOOT][ERROR] Failed to load daily state: {e}", flush=True)
    _daily_reset_state()

def _daily_reset_state():
    """Daily reset at midnight WIB."""
    global _initial_capital_idr
    balance = _get_total_equity_estimate()
    today = datetime.now(timezone.utc).date().isoformat() # Minimal fallback
    state = {
        "date": today,
        "initial_capital_idr": balance,
        "reset_at": time.time()
    }
    Path("state").mkdir(exist_ok=True)
    Path("state/daily_state.json").write_text(json.dumps(state))
    _initial_capital_idr = balance
    _hard_stop.initial_capital = balance
    _entry_loss_count.clear()

def _get_daily_loss_pct() -> float:
    if _initial_capital_idr <= 0: return 0.0
    current = _get_current_balance()
    return max(0.0, (_initial_capital_idr - current) / _initial_capital_idr * 100)

if __name__ == "__main__":
    _load_daily_state()
    main()
