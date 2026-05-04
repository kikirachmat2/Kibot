"""
KiBot Trinity — Telegram Monitor & Command Handler
===================================================
Script ini berjalan sebagai daemon terpisah di server lu.
Tugasnya:
  1. Poll status bot (PnL, posisi, risk mode) tiap interval
  2. Kirim alert proaktif ke Telegram jika ada anomali
  3. Terima command dari Telegram buat kontrol bot

Cara pakai:
  python3 ki_telegram_monitor.py

Env vars yang dibutuhkan (taruh di .env):
  TELEGRAM_BOT_TOKEN    — token bot Telegram lu
  TELEGRAM_CHAT_ID      — chat ID lu (bisa dapat dari @userinfobot)
  KIBOT_STATE_FILE      — path ke file state JSON bot (default: state/daily_state.json)
  KIBOT_LOG_FILE        — path ke file log trade (default: logs/trades.jsonl)
  KIBOT_MANAGER_PID_FILE — path ke PID file manager (default: state/manager.pid)
"""

import os
import json
import time
import signal
import logging
import threading
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import requests

# ── Timezone WIB ───────────────────────────────────────────────────────────────
WIB = timezone(timedelta(hours=7))
ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_early() -> None:
    candidates = [
        ROOT_DIR / ".env.kibot_manager",
        ROOT_DIR / ".env.kibot",
        ROOT_DIR / ".env.server",
        ROOT_DIR / ".env",
        Path(".env.kibot_manager"),
        Path(".env.kibot"),
        Path(".env.server"),
        Path(".env"),
        Path("../.env"),
    ]
    explicit = os.getenv("KIBOT_MANAGER_ENV_FILE")
    if explicit:
        candidates.insert(0, Path(explicit))
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv_early()

def now_wib() -> datetime:
    return datetime.now(WIB)

def ts_wib() -> str:
    return now_wib().strftime("%H:%M:%S WIB")

# ── Config dari env ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("KIBOT_TELEGRAM_BOT_TOKEN")
    or os.getenv("KICRYP_TELEGRAM_BOT_TOKEN")
    or ""
).strip()
TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("TELEGRAM_USER_ID")
    or os.getenv("KIBOT_TELEGRAM_CHAT_ID")
    or ""
).strip()

BASE_DIR         = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))
try:
    from kibot_ai_coordinator import query_ai
except Exception:
    query_ai = None

STATE_FILE       = Path(os.getenv("KIBOT_STATE_FILE",  str(BASE_DIR / "state" / "daily_state.json")))
LOG_FILE         = Path(os.getenv("KIBOT_LOG_FILE",    str(BASE_DIR / "logs"  / "trades.jsonl")))
PID_FILE         = Path(os.getenv("KIBOT_MANAGER_PID_FILE", str(BASE_DIR / "state" / "manager.pid")))
OPS_LOG          = BASE_DIR / "logs" / "OPS_UPDATE_LOG.md"
MANAGER_STATE_URL = os.getenv("KIBOT_MANAGER_STATE_URL", "http://127.0.0.1:9998/api/state")
POLYMARKET_STATE_URL = os.getenv("KIBOT_POLYMARKET_STATE_URL", "http://127.0.0.1:11600/api/state")


def _canonical_ollama_chat_url(raw_url: str) -> str:
    fallback = "http://127.0.0.1:11435/api/chat"
    url = str(raw_url or "").strip() or fallback
    allow_direct = os.getenv("KIBOT_ALLOW_DIRECT_OLLAMA", "").strip().lower() in {"1", "true", "yes", "on"}
    if allow_direct:
        return url
    try:
        parsed = urlsplit(url)
    except Exception:
        return fallback
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 11434:
        log.warning("Direct Ollama upstream disabled; using gateway http://127.0.0.1:11435/api/chat")
        return fallback
    return url


OLLAMA_CHAT_URL = _canonical_ollama_chat_url(os.getenv("KIBOT_OLLAMA_BASE_URL", ""))
OLLAMA_CHAT_TOKEN = (
    os.getenv("OLLAMA_API_KEY")
    or os.getenv("KIBOT_OLLAMA_GATEWAY_TOKEN")
    or ""
).strip()
OLLAMA_CHAT_MODEL = os.getenv("KIBOT_OLLAMA_FAST_MODEL", "qwen3:0.6b")
OLLAMA_CHAT_TIMEOUT_SEC = float(os.getenv("KIBOT_OLLAMA_TELEGRAM_TIMEOUT_SEC", "45"))

POLL_INTERVAL    = int(os.getenv("KIBOT_MONITOR_POLL_SEC",  "60"))   # cek status tiap N detik
ALERT_LOSS_PCT   = float(os.getenv("KIBOT_ALERT_LOSS_PCT",  "-1.0")) # alert kalau rugi > ini
ALERT_WIN_PCT    = float(os.getenv("KIBOT_ALERT_WIN_PCT",   "1.5"))  # alert kalau untung > ini

# ── Logger ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MONITOR] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ki_monitor")

# ── State internal monitor ──────────────────────────────────────────────────────
_last_pnl_pct:      float = 0.0
_last_risk_mode:    str   = ""
_last_alert_ts:     float = 0.0
_alert_cooldown:    float = 300.0   # jangan spam alert, min 5 menit antar alert sejenis
_last_update_id:    int   = 0
_running:           bool  = True

# ── Telegram helper ─────────────────────────────────────────────────────────────
def _tg(method: str, **kwargs) -> Optional[dict]:
    if not TELEGRAM_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN tidak diset — notif dimatiin")
        return None
    try:
        request_timeout: float | tuple[float, float]
        if method == "getUpdates":
            poll_timeout = float(kwargs.get("timeout") or 30)
            request_timeout = (5.0, max(15.0, poll_timeout + 10.0))
        else:
            request_timeout = 10.0
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}",
            json=kwargs,
            timeout=request_timeout,
        )
        return r.json()
    except Exception as e:
        log.error(f"Telegram {method} gagal: {e}")
        return None

def send(text: str, parse_mode: str = "HTML") -> None:
    if not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_CHAT_ID tidak diset")
        return
    _tg("sendMessage", chat_id=TELEGRAM_CHAT_ID, text=text,
        parse_mode=parse_mode, disable_web_page_preview=True)

def get_updates(offset: int = 0) -> list:
    resp = _tg("getUpdates", offset=offset, timeout=30, allowed_updates=["message"])
    if resp and resp.get("ok"):
        return resp.get("result", [])
    return []

# ── Baca state bot ──────────────────────────────────────────────────────────────
def _fetch_json(url: str) -> dict:
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

def read_state() -> dict:
    live = _fetch_json(MANAGER_STATE_URL)
    if live:
        return live
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception as e:
        log.error(f"Gagal baca state: {e}")
    return {}

def read_polymarket_state() -> dict:
    return _fetch_json(POLYMARKET_STATE_URL)

def read_recent_trades(n: int = 5) -> list:
    trades = []
    try:
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text().strip().splitlines()
            for line in reversed(lines[-50:]):
                try:
                    trades.append(json.loads(line))
                    if len(trades) >= n:
                        break
                except Exception:
                    pass
    except Exception as e:
        log.error(f"Gagal baca log trade: {e}")
    return trades

def get_manager_pid() -> Optional[int]:
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except Exception:
        pass
    return None

def is_manager_alive() -> bool:
    pid = get_manager_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False

# ── Format pesan ────────────────────────────────────────────────────────────────
def fmt_status(state: dict) -> str:
    ts       = ts_wib()
    pnl_pct  = float(state.get("daily_pnl_pct", 0.0) or 0.0)
    equity   = float(
        state.get("equity_idr")
        or state.get("capital_health", {}).get("total_equity_est_idr")
        or 0.0
    )
    risk     = state.get("trading_mode") or state.get("risk_mode", "UNKNOWN")
    governor = state.get("strategy_governor") if isinstance(state.get("strategy_governor"), dict) else {}
    trade_metrics = state.get("trade_metrics") if isinstance(state.get("trade_metrics"), dict) else {}
    trades   = int(state.get("total_trades_today") or trade_metrics.get("total_trades") or 0)
    wins     = int(state.get("wins_today") or trade_metrics.get("wins") or 0)
    losses   = int(state.get("losses_today") or trade_metrics.get("losses") or 0)
    wr       = (wins / trades * 100) if trades > 0 else 0.0
    alive    = "✅ Running" if is_manager_alive() else "🔴 <b>MATI!</b>"
    system_state = str(state.get("system_state") or "UNKNOWN")
    status_msg = str(state.get("degradedReason") or state.get("statusMessage") or "").strip()
    brain_mode = str(governor.get("brain_mode") or governor.get("strategy_mode") or "UNKNOWN")
    plan_state = str(governor.get("plan_state") or "UNKNOWN")
    refresh_profile = str(governor.get("refresh_profile") or (governor.get("refresh") or {}).get("last_profile") or "").strip()
    confidence = float(governor.get("effective_confidence") or governor.get("confidence") or 0.0)
    focus_pairs = ", ".join(str(item).upper() for item in list((governor.get("indodax") or {}).get("focus_pairs") or [])[:3])
    ops_alerts = list(governor.get("ops_alerts") or [])[:2]

    pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
    risk_emoji = {"GROWTH": "🚀", "CAUTION": "⚠️", "DEFENSIVE": "🛡️",
                  "RESTRICTED": "🔒", "HARD_STOP": "🛑"}.get(risk, "❓")

    message = (
        f"📊 <b>KiBot Status</b> — {ts}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot       : {alive}\n"
        f"{pnl_emoji} PnL Hari  : {pnl_pct:+.2f}%\n"
        f"💰 Equity  : Rp{equity:,.0f}\n"
        f"{risk_emoji} Risk Mode : {risk}\n"
        f"🧭 State   : {system_state}\n"
        f"📈 Trades  : {trades} ({wins}W/{losses}L | WR {wr:.0f}%)\n"
        + (f"📝 Note    : {status_msg}\n" if status_msg else "")
    )
    profile_text = f" | {refresh_profile}" if refresh_profile else ""
    message += f"🧠 Brain   : {brain_mode} | {plan_state}{profile_text} | conf {confidence*100:.0f}%\n"
    if focus_pairs:
        message += f"🎯 Focus   : {focus_pairs}\n"
    for item in ops_alerts:
        message += f"⚠️ Alert   : {item}\n"
    return message

def fmt_trade(t: dict) -> str:
    pair     = t.get("pair_id", "?").upper()
    side     = t.get("side", "?")
    profit   = t.get("net_profit_idr", 0.0)
    pct      = t.get("profit_pct", 0.0)
    bucket   = t.get("bucket_type", "?")
    emoji    = "🟢" if profit >= 0 else "🔴"
    return f"{emoji} <b>{pair}</b> {side} | {pct:+.2f}% | Rp{profit:+,.0f} [{bucket}]"

def fmt_polymarket(state: dict) -> str:
    if not state:
        return "🎯 <b>Polymarket</b>\nState belum tersedia."
    geoblock = state.get("geoblock") if isinstance(state.get("geoblock"), dict) else {}
    opportunities = list(state.get("top_opportunities") or [])[:3]
    maker_candidates = list(state.get("maker_candidates") or [])[:2]
    alpha_candidates = list(state.get("alpha_candidates") or [])[:2]
    cross_market_bias = state.get("cross_market_bias") if isinstance(state.get("cross_market_bias"), dict) else {}
    lines = [
        "🎯 <b>Polymarket</b>",
        f"Ready      : {'✅' if state.get('ready') else '⚠️'} | analysis={'✅' if state.get('analysis_ready') else '⚠️'}",
        f"Region     : {geoblock.get('country') or '?'} blocked={geoblock.get('blocked')}",
        f"Wallet     : <code>{str(state.get('wallet_address') or '')[:16]}...</code>" if state.get("wallet_address") else "Wallet     : unavailable",
    ]
    if cross_market_bias:
        lines.append("")
        lines.append("<b>Cross-market bias</b>")
        for asset, detail in list(cross_market_bias.items())[:3]:
            if not isinstance(detail, dict):
                continue
            lines.append(
                f"• {asset.upper()} {detail.get('direction') or '?'} "
                f"score={float(detail.get('score') or 0.0):.2f}"
            )
    if opportunities:
        lines.append("")
        lines.append("<b>Top markets</b>")
        for item in opportunities:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"• {str(item.get('slug') or item.get('question') or '?')[:64]} | "
                f"liq={float(item.get('liquidity') or 0.0):,.0f} | "
                f"spr={float(item.get('spread') or 0.0):.3f}"
            )
    if maker_candidates:
        lines.append("")
        lines.append("<b>Maker/rebate</b>")
        for item in maker_candidates:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"• {str(item.get('slug') or item.get('question') or '?')[:52]} | "
                f"maker={float(item.get('maker_score') or 0.0):.2f} | "
                f"{str(item.get('execution_style') or 'OBSERVE')}"
            )
    if alpha_candidates:
        lines.append("")
        lines.append("<b>Alpha to Indodax</b>")
        for item in alpha_candidates:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"• {str(item.get('mapped_pair') or item.get('asset') or '?').upper()} "
                f"{str(item.get('direction') or '?')} score={float(item.get('alpha_score') or 0.0):.2f}"
            )
    return "\n".join(lines)


def _compact_system_state(state: dict) -> dict:
    capital = state.get("capital_health") if isinstance(state.get("capital_health"), dict) else {}
    adaptive = capital.get("adaptive_profile") if isinstance(capital.get("adaptive_profile"), dict) else {}
    brain = state.get("brain_assist") if isinstance(state.get("brain_assist"), dict) else {}
    governor = state.get("strategy_governor") if isinstance(state.get("strategy_governor"), dict) else {}
    return {
        "system_state": state.get("system_state"),
        "effective_state": state.get("effectiveState"),
        "trading_allowed": state.get("tradingAllowed"),
        "daily_pnl_pct": state.get("daily_pnl_pct"),
        "node_status": state.get("nodeStatus"),
        "reason": state.get("degradedReason") or state.get("healthDecision"),
        "capital_mode": adaptive.get("mode"),
        "capital_reason": adaptive.get("reason"),
        "ai_legion_count": ((brain.get("ai_legion") or {}).get("configured_count")),
        "ai_critic": brain.get("ai_critic"),
        "governor": {
            "plan_id": governor.get("plan_id"),
            "plan_state": governor.get("plan_state"),
            "refresh_profile": governor.get("refresh_profile") or (governor.get("refresh") or {}).get("last_profile"),
            "brain_mode": governor.get("brain_mode"),
            "market_regime": governor.get("market_regime"),
            "capital_posture": governor.get("capital_posture"),
            "confidence": governor.get("effective_confidence") or governor.get("confidence"),
            "focus_pairs": list((governor.get("indodax") or {}).get("focus_pairs") or [])[:4],
            "ops_alerts": list(governor.get("ops_alerts") or [])[:3],
        },
    }


def _compact_polymarket_state(state: dict) -> dict:
    opportunities = []
    for item in list(state.get("top_opportunities") or [])[:3]:
        if not isinstance(item, dict):
            continue
        opportunities.append(
            {
                "slug": item.get("slug"),
                "spread": item.get("spread"),
                "liquidity": item.get("liquidity"),
            }
        )
    return {
        "ready": state.get("ready"),
        "blocked": (state.get("geoblock") or {}).get("blocked") if isinstance(state.get("geoblock"), dict) else None,
        "wallet": state.get("wallet_address"),
        "top": opportunities,
    }


def _chat_context() -> dict:
    state = read_state()
    polymarket = read_polymarket_state()
    return {
        "system_state": _compact_system_state(state),
        "polymarket": _compact_polymarket_state(polymarket),
    }


def _chat_reply(user_message: str, *, local_only: bool = False) -> str:
    if query_ai is None:
        return "⚠️ AI coordinator belum aktif di host ini."
    prompt_type = "OPS_CHAT_LOCAL" if local_only else "OPS_CHAT"
    reply = query_ai(
        prompt_type,
        {
            **_chat_context(),
            "user_message": str(user_message or "").strip()[:1200],
        },
        cache_ttl_minutes=1,
        force_refresh=True,
    )
    if isinstance(reply, dict):
        answer = str(reply.get("answer") or reply.get("raw") or "").strip()
        if answer:
            return answer
    return "⚠️ AI belum memberi jawaban yang valid."


def _local_ollama_chat(user_message: str) -> str:
    payload = {
        "model": OLLAMA_CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are KiBot's Telegram copilot. "
                    "Answer briefly in Indonesian, operationally, and truthfully."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        **_chat_context(),
                        "user_message": str(user_message or "").strip()[:800],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "stream": False,
        "think": False,
        "keep_alive": "30s",
        "options": {
            "temperature": 0.2,
            "num_ctx": 1536,
            "num_predict": 160,
        },
    }
    headers = {"Content-Type": "application/json"}
    if OLLAMA_CHAT_TOKEN:
        headers["Authorization"] = f"Bearer {OLLAMA_CHAT_TOKEN}"
    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            json=payload,
            headers=headers,
            timeout=OLLAMA_CHAT_TIMEOUT_SEC,
        )
        response.raise_for_status()
        data = response.json()
        text = str((data.get("message") or {}).get("content") or "").strip()
        return text or "⚠️ Ollama tidak mengembalikan jawaban."
    except Exception as error:
        return f"⚠️ Ollama tidak siap: {type(error).__name__}"


def _natural_text_to_command(text: str) -> Optional[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return None
    if raw in {"status", "cek status", "state", "kondisi"}:
        return "/status"
    if raw in {"pnl", "profit", "ringkasan pnl"}:
        return "/pnl"
    if "polymarket" in raw and len(raw.split()) <= 4:
        return "/polymarket"
    if raw.startswith("restart"):
        return "/restart"
    if raw.startswith("stop"):
        return "/stop"
    if raw in {"alive", "hidup?", "masih jalan?"}:
        return "/alive"
    return None

# ── Perintah dari Telegram ───────────────────────────────────────────────────────
HELP_TEXT = """
🤖 <b>KiBot Monitor Commands</b>

/status  — Status bot real-time
/trades  — 5 trade terakhir
/pnl     — Ringkasan PnL hari ini
/polymarket — Status Polymarket executor
/ask ... — Tanya ke otak sistem
/ollama ... — Tanya langsung ke Ollama lokal
/alive   — Cek bot masih jalan ga
/stop    — STOP bot (kirim SIGTERM ke manager)
/restart — Restart manager (jalanin ulang)
/help    — Tampilkan menu ini
"""

def handle_command(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "status":
        state = read_state()
        return fmt_status(state)

    elif cmd == "trades":
        trades = read_recent_trades(5)
        if not trades:
            return "📭 Belum ada trade hari ini."
        lines = ["📋 <b>5 Trade Terakhir:</b>\n"]
        for t in trades:
            lines.append(fmt_trade(t))
        return "\n".join(lines)

    elif cmd == "pnl":
        state = read_state()
        pnl      = state.get("daily_pnl_idr", 0.0)
        pnl_pct  = state.get("daily_pnl_pct", 0.0)
        equity   = state.get("equity_idr", 0.0)
        trades   = state.get("total_trades_today", 0)
        wins     = state.get("wins_today", 0)
        ev       = state.get("expected_value_idr", 0.0)
        emoji    = "🟢" if pnl >= 0 else "🔴"
        return (
            f"{emoji} <b>PnL Hari Ini</b>\n"
            f"Profit    : Rp{pnl:+,.0f} ({pnl_pct:+.2f}%)\n"
            f"Equity    : Rp{equity:,.0f}\n"
            f"Trades    : {trades} ({wins} menang)\n"
            f"EV/trade  : Rp{ev:+,.0f}\n"
            f"📅 Reset tengah malam WIB"
        )

    elif cmd == "polymarket":
        return fmt_polymarket(read_polymarket_state())

    elif cmd == "ask":
        if not arg:
            return "❓ Pakai /ask diikuti pertanyaan. Contoh: /ask kenapa bot lagi defensif?"
        return _chat_reply(arg, local_only=False)

    elif cmd == "ollama":
        if not arg:
            return "❓ Pakai /ollama diikuti pertanyaan."
        return _local_ollama_chat(arg)

    elif cmd == "alive":
        alive = is_manager_alive()
        if alive:
            pid = get_manager_pid()
            return f"✅ Manager hidup (PID {pid})"
        return "🔴 <b>Manager TIDAK berjalan!</b> Gunakan /restart"

    elif cmd == "stop":
        pid = get_manager_pid()
        if pid is None:
            return "⚠️ PID file tidak ditemukan."
        try:
            os.kill(pid, signal.SIGTERM)
            return f"🛑 SIGTERM dikirim ke PID {pid}. Bot akan berhenti."
        except Exception as e:
            return f"❌ Gagal stop: {e}"

    elif cmd == "restart":
        manager_script = BASE_DIR / "core" / "kibot_manager.py"
        if not manager_script.exists():
            return "❌ kibot_manager.py tidak ditemukan."
        # Stop dulu kalau masih jalan
        pid = get_manager_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(3)
            except Exception:
                pass
        try:
            subprocess.Popen(
                ["python3", str(manager_script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return "🔄 Manager di-restart. Cek /alive dalam 10 detik."
        except Exception as e:
            return f"❌ Gagal restart: {e}"

    elif cmd in ("help", "start"):
        return HELP_TEXT

    else:
        return f"❓ Command tidak dikenal: /{cmd}\n{HELP_TEXT}"

# ── Loop terima command ──────────────────────────────────────────────────────────
def command_loop() -> None:
    global _last_update_id
    log.info("Command listener dimulai...")
    while _running:
        try:
            updates = get_updates(offset=_last_update_id + 1)
            for upd in updates:
                _last_update_id = upd["update_id"]
                msg = upd.get("message", {})
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if chat_id != TELEGRAM_CHAT_ID or not text.strip():
                    continue
                normalized = _natural_text_to_command(text)
                if text.startswith("/"):
                    log.info(f"Command diterima: {text}")
                    reply = handle_command(text)
                    send(reply)
                elif normalized:
                    log.info(f"Natural command diterima: {text} -> {normalized}")
                    send(handle_command(normalized))
                else:
                    log.info("Pertanyaan operator diteruskan ke AI chat")
                    send(_chat_reply(text, local_only=False))
        except Exception as e:
            log.error(f"command_loop error: {e}")
        time.sleep(2)

# ── Loop monitoring proaktif ─────────────────────────────────────────────────────
def monitor_loop() -> None:
    global _last_pnl_pct, _last_risk_mode, _last_alert_ts
    log.info("Monitor loop dimulai...")

    # Kirim startup message
    send(
        f"🟢 <b>KiBot Monitor aktif</b> — {ts_wib()}\n"
        f"Ketik /help untuk daftar perintah."
    )

    prev_alive = True

    while _running:
        try:
            state = read_state()
            pnl_pct   = state.get("daily_pnl_pct", 0.0)
            risk_mode = state.get("risk_mode", "")
            alive     = is_manager_alive()
            now_ts    = time.time()

            # ── Alert: bot mati ─────────────────────────────────────────────
            if prev_alive and not alive:
                send(
                    f"🔴 <b>ALERT: KiBot Manager MATI!</b>\n"
                    f"⏰ {ts_wib()}\n"
                    f"Gunakan /restart untuk hidupkan kembali."
                )
            elif not prev_alive and alive:
                send(f"✅ <b>KiBot Manager hidup kembali</b> — {ts_wib()}")
            prev_alive = alive

            cooldown_ok = (now_ts - _last_alert_ts) > _alert_cooldown

            # ── Alert: loss besar ────────────────────────────────────────────
            if pnl_pct <= ALERT_LOSS_PCT and cooldown_ok:
                equity = state.get("equity_idr", 0.0)
                send(
                    f"⚠️ <b>ALERT RUGI!</b> — {ts_wib()}\n"
                    f"PnL hari ini: {pnl_pct:+.2f}%\n"
                    f"Equity: Rp{equity:,.0f}\n"
                    f"Risk Mode: {risk_mode}"
                )
                _last_alert_ts = now_ts

            # ── Alert: profit besar ──────────────────────────────────────────
            if pnl_pct >= ALERT_WIN_PCT and cooldown_ok and pnl_pct > _last_pnl_pct:
                equity = state.get("equity_idr", 0.0)
                send(
                    f"🎯 <b>TARGET PROFIT TERCAPAI!</b> — {ts_wib()}\n"
                    f"PnL hari ini: {pnl_pct:+.2f}%\n"
                    f"Equity: Rp{equity:,.0f}"
                )
                _last_alert_ts = now_ts

            # ── Alert: risk mode berubah ─────────────────────────────────────
            if risk_mode and risk_mode != _last_risk_mode and _last_risk_mode:
                emoji_map = {
                    "GROWTH": "🚀", "CAUTION": "⚠️", "DEFENSIVE": "🛡️",
                    "RESTRICTED": "🔒", "HARD_STOP": "🛑"
                }
                emoji = emoji_map.get(risk_mode, "❓")
                send(
                    f"{emoji} <b>Risk Mode berubah!</b>\n"
                    f"{_last_risk_mode} → <b>{risk_mode}</b>\n"
                    f"⏰ {ts_wib()}"
                )

            _last_pnl_pct  = pnl_pct
            _last_risk_mode = risk_mode

        except Exception as e:
            log.error(f"monitor_loop error: {e}")

        time.sleep(POLL_INTERVAL)

# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    global _running

    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN wajib diisi di .env!")
        return
    if not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_CHAT_ID wajib diisi di .env!")
        return

    log.info(f"KiBot Telegram Monitor v1.0 starting | poll={POLL_INTERVAL}s")

    def _on_signal(sig, frame):
        global _running
        log.info(f"Signal {sig} diterima — shutting down...")
        _running = False
        send(f"🔌 <b>Monitor dimatikan</b> — {ts_wib()}")

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    t_cmd = threading.Thread(target=command_loop, daemon=True, name="cmd-loop")
    t_cmd.start()

    monitor_loop()

if __name__ == "__main__":
    main()
