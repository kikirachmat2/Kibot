import os
from pathlib import Path
import pytz

def _load_dotenv_early():
    """Load .env or .env.kiv files early before constants are assigned."""
    import os
    from ki_vault import get_vault
    vault = get_vault()
    
    candidates = [
        Path(".env.kiv"), Path(".env"), 
        Path("scripts/.env"), Path("../.env"), 
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent / ".env.kiv"
    ]
    if os.getenv("KIBOT_MANAGER_ENV_FILE"):
        candidates.insert(0, Path(os.getenv("KIBOT_MANAGER_ENV_FILE")))
    
    for p in candidates:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'").strip('"')
                    
                    # Decrypt if encrypted
                    if v.startswith("ENC(") and v.endswith(")"):
                        try:
                            v = vault.decrypt(v[4:-1])
                        except Exception as e:
                            print(f"[KIBOT][VAULT][ERROR] Failed to decrypt {k}: {e}", flush=True)
                            continue
                            
                    if k and k not in os.environ:
                        os.environ[k] = v

_load_dotenv_early()

# --- PATHS ---
BASE_PATH = Path(__file__).resolve().parent.parent
REPO_PATH = BASE_PATH.parent if (BASE_PATH / ".env").exists() else BASE_PATH

# --- TIMEZONE ---
WIB = pytz.timezone('Asia/Jakarta')
UTC_OFFSET = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))

# --- NETWORKING ---
KIBOT_UDP_HOST = os.getenv("KIBOT_UDP_HOST", "100.122.1.109")
KIBOT_UDP_HOST_BACKUP = os.getenv("KIBOT_UDP_HOST_BACKUP", "100.122.1.110") # Singapore/Batam backup
KIBOT_UDP_PORT = int(os.getenv("KIBOT_UDP_PORT", "9999"))

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
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11435/api/chat")
AI_REQUEST_TIMEOUT_SEC = float(os.getenv("KIBOT_AI_TIMEOUT", "10.0"))
AI_ROUTER_ENABLED = os.getenv("KIBOT_AI_ROUTER_ENABLED", "true").lower() == "true"

# --- NOTIFICATIONS ---
TELEGRAM_BOT_TOKEN = os.getenv("KIBOT_TELEGRAM_TOKEN", "REDACTED_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("KIBOT_TELEGRAM_CHAT_ID", "1346696386")

# --- TRADING LIMITS ---
STALE_SIGNAL_ABORT_MS = int(os.getenv("KIBOT_STALE_SIGNAL_MS", "3000"))
KIBOT_SIGNAL_DEDUP_S = int(os.getenv("KIBOT_SIGNAL_DEDUP_S", "90"))
KIBOT_QUARANTINE_SECONDS = int(os.getenv("KIBOT_QUARANTINE_SECONDS", "2700"))
KIBOT_MAX_PAIR_LOSS = int(os.getenv("KIBOT_MAX_PAIR_LOSS", "2"))
KIBOT_Z_SCORE_THRESHOLD = float(os.getenv("KIBOT_Z_SCORE_THRESHOLD", "2.2"))

# --- REDIS ---
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
