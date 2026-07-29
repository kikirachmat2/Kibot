import logging
import os
from pathlib import Path
import pytz
from Core.Support.runtime_mode_guard import LIVE_ONLY, normalize_runtime_mode

def _load_sovereign_env():
    """Load and decrypt vaulted environment variables."""
    try:
        from Core.Support.ki_vault import load_sovereign_env
    except ImportError:
        try:
            from ki_vault import load_sovereign_env
        except ImportError:
            return
            
    # Load from vault (looks for .env.kiv by default)
    load_sovereign_env()

# Load everything before constants are assigned
_load_sovereign_env()

for noisy_logger in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(noisy_logger).setLevel(logging.ERROR)


def _normalize_ollama_root_url(raw_url: str, default_root: str = "http://127.0.0.1:11434") -> str:
    """Return the Ollama host root without any /api/... suffix."""
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        return default_root.rstrip("/")

    for suffix in ("/api/chat", "/api/generate", "/api/embed", "/api/tags", "/api/ps"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break

    return url or default_root.rstrip("/")


def _normalize_ollama_chat_url(raw_url: str, default_root: str = "http://127.0.0.1:11434") -> str:
    """Return a usable Ollama chat endpoint from root or already-qualified URLs."""
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        return f"{default_root.rstrip('/')}/api/chat"

    if url.endswith("/api/chat"):
        return url

    for suffix in ("/api/generate", "/api/embed", "/api/tags", "/api/ps"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break

    if "/api/" in url:
        return url

    return f"{url}/api/chat"


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on", "live", "production"}

# --- PATHS ---
BASE_PATH = Path(__file__).resolve().parent.parent  # Points to Core/
PROJECT_ROOT = BASE_PATH.parent                     # Points to KiBot root
STATE_DIR = PROJECT_ROOT / "state"
LOGS_DIR = PROJECT_ROOT / "logs"
RAW_DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"

# --- CLUSTER NODES ---
# ==============================================================================
# KiBot: The Agentic Sovereign Framework
# Philosophy: "Sedikit Demi Sedikit, Lama-Lama Jadi Bukit"
# Protocol: "Tekan Kerugian, Maksimalkan Probabilitas Keuntungan"
# ==============================================================================

class KiConfig:
    # --- PHILOSOPHY & RISK GATE ---
    PHILOSOPHY = "Sedikit Demi Sedikit, Lama-Lama Jadi Bukit"
    MOTTO = "Tekan Kerugian, Maksimalkan Probabilitas Keuntungan"
    
    # Strict Risk Parameters (Sovereign Level - Aggressive V3.1)
    MAX_DAILY_LOSS_PERCENT = 3.0       # Manifesto max daily loss cap (updated to 3.0%)
    MIN_SIGNAL_PROBABILITY = 0.65     # Lowered to 65% for high-aggression
    SCALPING_TP_PERCENT = 1.0         # Increased for more room
    SCALPING_SL_PERCENT = 2.0         # Matches RiskGate SL
    _RAW_TRADING_MODE = os.getenv("KIBOT_RUNTIME_MODE", os.getenv("KIBOT_TRADING_MODE", LIVE_ONLY)).strip().lower()
    TRADING_MODE = normalize_runtime_mode(_RAW_TRADING_MODE)
    INDODAX_ONLY = _env_flag("KIBOT_INDODAX_ONLY", "true")
    LIVE_TRADING_ENABLED = _env_flag("KIBOT_LIVE_TRADING_ENABLED", "true" if TRADING_MODE == LIVE_ONLY else "false")
    LIVE_OPPORTUNITY_EXPANSION = _env_flag("KIBOT_LIVE_OPPORTUNITY_EXPANSION", "true" if TRADING_MODE == LIVE_ONLY else "false")
    FORCE_DAILY_PROFIT = _env_flag("KIBOT_FORCE_DAILY_PROFIT", "false")
    DAILY_PROFIT_DEADLINE = _env_flag("KIBOT_DAILY_PROFIT_DEADLINE", "false")
    MAX_DAILY_LOSS_IDR = float(os.getenv("KIBOT_MAX_DAILY_LOSS_IDR", "0") or 0)
    MAX_CONSECUTIVE_LOSSES = int(os.getenv("KIBOT_MAX_CONSECUTIVE_LOSSES", "1") or 1)
    MAX_TRADES_PER_DAY = int(os.getenv("KIBOT_MAX_TRADES_PER_DAY", "4") or 4)
    
    # --- LIVE CANARY GATE & CONTROLS ---
    CANARY_LIVE_ENABLED = False
    CANARY_EXCHANGE = os.getenv("KIBOT_CANARY_EXCHANGE", "INDODAX").strip().upper()
    CANARY_MAX_TRADE_IDR = float(os.getenv("KIBOT_CANARY_MAX_TRADE_IDR", "25000"))
    CANARY_MAX_DAILY_LOSS_IDR = float(os.getenv("KIBOT_CANARY_MAX_DAILY_LOSS_IDR", "25000"))
    CANARY_MAX_DAILY_TRADES = int(os.getenv("KIBOT_CANARY_MAX_DAILY_TRADES", "3"))
    CANARY_MAX_OPEN_POSITIONS = int(os.getenv("KIBOT_CANARY_MAX_OPEN_POSITIONS", "1"))
    CANARY_REQUIRE_MICROSTRUCTURE_PASS = _env_flag("KIBOT_CANARY_REQUIRE_MICROSTRUCTURE_PASS", "true")
    CANARY_REQUIRE_COUNCIL_APPROVAL = _env_flag("KIBOT_CANARY_REQUIRE_COUNCIL_APPROVAL", "true")
    CANARY_REQUIRE_POSITIVE_EV = _env_flag("KIBOT_CANARY_REQUIRE_POSITIVE_EV", "true")
    CANARY_AUTO_ROLLBACK = _env_flag("KIBOT_CANARY_AUTO_ROLLBACK", "true")
    LEGACY_TRADING_MODES_DISABLED = TRADING_MODE == LIVE_ONLY

    # --- REMOVED CROSS-CHAIN SAFETY GATES ---
    ENABLE_REAL_SWAP = False
    ENABLE_REAL_BRIDGE = False
    ENABLE_REAL_WITHDRAWAL = False
    ENABLE_POLYMARKET_LIVE = False
    SCANNER_ENABLE_POLYMARKET = False
    SCANNER_ENABLE_WEB3 = False
    SCANNER_ENABLE_UNIVERSAL = False
    
    # --- AI & OLLAMA GUARDRAILS ---
    LLM_ENABLED = _env_flag("KIBOT_LLM_ENABLED", "true")
    LLM_ADVISORY_ONLY = _env_flag("KIBOT_LLM_ADVISORY_ONLY", "true")
    LLM_MAX_CONCURRENT = int(os.getenv("KIBOT_LLM_MAX_CONCURRENT", "1"))
    LLM_TIMEOUT_S = float(os.getenv("KIBOT_LLM_TIMEOUT_S", "4"))
    LLM_HEAVY_MODEL_TIMEOUT_S = float(os.getenv("KIBOT_LLM_HEAVY_MODEL_TIMEOUT_S", "8"))
    LLM_FAIL_OPEN_TO_DETERMINISTIC = _env_flag("KIBOT_LLM_FAIL_OPEN_TO_DETERMINISTIC", "true")
    LLM_BLOCK_EXECUTOR = _env_flag("KIBOT_LLM_BLOCK_EXECUTOR", "false")
    LLM_ALLOWED_TO_PLACE_ORDER = _env_flag("KIBOT_LLM_ALLOWED_TO_PLACE_ORDER", "false")
    
    
    TELEGRAM_GLOBAL_MIN_INTERVAL_SEC = int(os.getenv("KIBOT_TELEGRAM_MIN_INTERVAL_SEC", "30"))
    TELEGRAM_DEDUPE_WINDOW_SEC = int(os.getenv("KIBOT_TELEGRAM_DEDUPE_WINDOW_SEC", "900"))
    TELEGRAM_INCIDENT_COOLDOWN_SEC = int(os.getenv("KIBOT_TELEGRAM_INCIDENT_COOLDOWN_SEC", "3600"))
    TELEGRAM_CLAIM_TTL_SEC = int(os.getenv("KIBOT_TELEGRAM_CLAIM_TTL_SEC", "30"))
    TELEGRAM_MAX_CHARS = int(os.getenv("KIBOT_TELEGRAM_MAX_CHARS", "3800"))
    
    # --- EXCHANGE RATES ---
    KRW_USD_RATE = 1350.0             # Default conversion, can be updated via env
    
    # --- MESH TOPOLOGY ---
    BATAM_MASTER = "127.0.0.1"
    SCANNER_NODE = "127.0.0.1"
    EXECUTOR_NODE = "127.0.0.1"
    
    # --- PORTS ---
    UDP_SIGNAL_PORT = 9999      # Default signal port
    INDO_SIGNAL_PORT = 9998     # Indodax specific
    COMMAND_PLANE_PORT = 9991
    
    # --- SECURITY ---
    VAULT_SALT = os.getenv("KIBOT_VAULT_SALT", "SOVEREIGN_SALT_2026")
    SECRET_KEY = os.getenv("KIBOT_SECRET")

    @classmethod
    def get_node_name(cls):
        # Auto-detect node based on environment or hostname
        return os.getenv("KIBOT_NODE_NAME", "UNKNOWN_NODE")

# --- CLUSTER NODES (Mesh-First) ---
BATAM_HOST = os.getenv("KIBOT_BATAM_HOST", "127.0.0.1")
EXECUTOR_HOST = os.getenv("KIBOT_EXECUTOR_HOST", "127.0.0.1")
SCANNER_HOST = os.getenv("KIBOT_SCANNER_HOST", "127.0.0.1")
SCANNER_MESH_HOST = os.getenv("KIBOT_SCANNER_MESH_HOST", SCANNER_HOST)

# --- TIMEZONE ---
WIB = pytz.timezone('Asia/Jakarta')
UTC_OFFSET = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))

# --- NETWORKING ---
KIBOT_UDP_HOST = os.getenv("KIBOT_UDP_HOST", EXECUTOR_HOST)
KIBOT_UDP_HOST_BACKUP = os.getenv("KIBOT_UDP_HOST_BACKUP", SCANNER_HOST)
KIBOT_UDP_PORT = int(os.getenv("KIBOT_UDP_PORT", "9999"))
KIBOT_SIGNAL_KEY = os.getenv("KIBOT_SIGNAL_KEY", "SOVEREIGN_DEFAULT_SIGNAL_SECRET")
# comma-separated list of allowed scanner IPs. If empty, all are allowed (not recommended for production)
KIBOT_ALLOWED_SCANNER_IPS = [ip.strip() for ip in os.getenv("KIBOT_ALLOWED_SCANNER_IPS", "").split(",") if ip.strip()]

def verify_egress_health() -> bool:
    """Hardening check: Verify we can reach the sovereign egress hosts."""
    import socket
    for host in [KIBOT_UDP_HOST, KIBOT_UDP_HOST_BACKUP]:
        if not host: continue
        try:
            with socket.create_connection((host, KIBOT_UDP_PORT), timeout=2):
                return True
        except:
            continue
    return False

# Computed Egress List
KIBOT_EGRESS_HOSTS = [h for h in [KIBOT_UDP_HOST, KIBOT_UDP_HOST_BACKUP] if h]

# --- AI & OLLAMA ---
OLLAMA_URL = _normalize_ollama_root_url(os.getenv("OLLAMA_URL", os.getenv("KIBOT_OLLAMA_BASE_URL", "")))
OLLAMA_CHAT_URL = _normalize_ollama_chat_url(os.getenv("KIBOT_OLLAMA_BASE_URL", OLLAMA_URL))
OLLAMA_TAGS_URL = f"{OLLAMA_URL}/api/tags"
OLLAMA_PS_URL = f"{OLLAMA_URL}/api/ps"
AI_REQUEST_TIMEOUT_SEC = float(os.getenv("KIBOT_AI_TIMEOUT", "10.0"))
AI_ROUTER_ENABLED = os.getenv("KIBOT_AI_ROUTER_ENABLED", "true").lower() == "true"

# --- NOTIFICATIONS ---
TELEGRAM_BOT_TOKEN = os.getenv("KIBOT_TELEGRAM_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    # We raise an error in production but allow a warning in dev if needed
    print("⚠️ WARNING: KIBOT_TELEGRAM_TOKEN is missing!")

TELEGRAM_CHAT_ID = os.getenv("KIBOT_TELEGRAM_CHAT_ID")
if not TELEGRAM_CHAT_ID:
    print("⚠️ WARNING: KIBOT_TELEGRAM_CHAT_ID is missing!")

# --- TRADING LIMITS ---
STALE_SIGNAL_ABORT_MS = int(os.getenv("KIBOT_STALE_SIGNAL_MS", "3000"))
KIBOT_SIGNAL_DEDUP_S = int(os.getenv("KIBOT_SIGNAL_DEDUP_S", "300"))
KIBOT_QUARANTINE_SECONDS = int(os.getenv("KIBOT_QUARANTINE_SECONDS", "3600"))
KIBOT_MAX_PAIR_LOSS = int(os.getenv("KIBOT_MAX_PAIR_LOSS", "2"))
KIBOT_Z_SCORE_THRESHOLD = float(os.getenv("KIBOT_Z_SCORE_THRESHOLD", "2.2"))

# --- REDIS ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
