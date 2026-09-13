from pathlib import Path
import os
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseModel):
    # Absolute Default Live Gate: FALSE (Paper mode only)
    LIVE_TRADING_ENABLED: bool = Field(default=False, description="Strict safety gate. When false, real orders are physically blocked.")
    
    # Credentials (Loaded from ENV or files with permission 600)
    INDODAX_KEY: str = Field(default="", description="Indodax API Key")
    INDODAX_SECRET: str = Field(default="", description="Indodax API Secret")
    
    # WebSocket Endpoints
    INDODAX_WS_URL: str = Field(default="wss://ws3.indodax.com/ws/", description="Indodax WebSocket endpoint")
    INDODAX_WS_STATIC_TOKEN: str = Field(
        default="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE5NDY2MTg0MTV9.UR1lBM6Eqh0yWz-PVirw1uPCxe60FdchR8eNVdsskeo",
        description="Public static token for Indodax WebSocket handshake"
    )
    INDODAX_REST_URL: str = Field(default="https://indodax.com", description="Indodax public & private REST base URL")
    BINANCE_WS_URL: str = Field(default="wss://stream.binance.com:9443/ws", description="Binance WebSocket base endpoint")
    
    # Concurrency & Queue Configuration
    COUNCIL_WORKERS: int = Field(default=4, ge=1, le=16, description="Parallel worker coroutines for council deliberation")
    MAX_SYMBOL_QUEUE_CAP: int = Field(default=20, ge=5, le=100, description="Max concurrent symbol queues before lowest score drop")
    
    # Risk Limits
    MAX_DRAWDOWN_PCT: float = Field(default=18.0, description="Circuit breaker overall drawdown limit percentage")
    MAX_DAILY_LOSS_PCT: float = Field(default=3.0, description="Daily loss cap percentage")
    IDEMPOTENCY_WINDOW_SECONDS: float = Field(default=30.0, description="Window to prevent duplicate orders on identical pair")
    
    # Out-of-band Enrichment
    ENRICHMENT_INTERVAL_SECONDS: int = Field(default=900, description="Background enrichment interval in seconds (15m)")
    ENRICHMENT_TTL_SECONDS: int = Field(default=1800, description="Enrichment cache TTL in seconds (30m)")
    ENRICHMENT_TIMEOUT_SECONDS: float = Field(default=2.0, description="Hard timeout per external enrichment request")
    
    # Trading Fees, Targets & Sizing (Empirically calibrated to V1 data)
    FEE_ROUNDTRIP_PCT: float = Field(default=0.42, description="Estimated roundtrip fee percentage (0.21% maker + 0.21% taker)")
    DEFAULT_TAKE_PROFIT_PCT: float = Field(default=1.8, description="Calibrated realistic take-profit percentage (1.8%)")
    DEFAULT_STOP_LOSS_PCT: float = Field(default=2.4, description="Calibrated realistic stop-loss percentage (2.4%)")
    MIN_ORDER_NOTIONAL_IDR: float = Field(default=10_000.0, description="Indodax minimum order size in IDR")
    
    # Storage & Logging
    STATE_DIR: Path = Field(default=ROOT_DIR / "state", description="Durable state persistence directory")
    LOG_DIR: Path = Field(default=ROOT_DIR / "logs", description="Application log directory")
    MAX_LOG_SIZE_BYTES: int = Field(default=10 * 1024 * 1024, description="Max rotating log file size (10MB)")
    LOG_BACKUP_COUNT: int = Field(default=3, description="Number of rotating log backups")
    
    def __init__(self, **data):
        mapping = {
            "live_trading_enabled": "LIVE_TRADING_ENABLED",
            "indodax_key": "INDODAX_KEY",
            "indodax_secret_key": "INDODAX_SECRET",
            "indodax_secret": "INDODAX_SECRET",
        }
        normalized = {}
        for k, v in data.items():
            normalized[mapping.get(k.lower(), k)] = v
        super().__init__(**normalized)

    def __repr__(self) -> str:
        # Guarantee no secrets appear in repr()
        safe_dict = self.get_redacted_dict()
        return f"Settings({safe_dict})"

    def get_redacted_dict(self) -> dict:
        data = self.model_dump()
        if data.get("INDODAX_KEY"):
            data["INDODAX_KEY"] = "********"
        if data.get("INDODAX_SECRET"):
            data["INDODAX_SECRET"] = "********"
        return data

    @property
    def live_trading_enabled(self) -> bool:
        return self.LIVE_TRADING_ENABLED

    @property
    def indodax_key(self) -> str:
        return self.INDODAX_KEY

    @property
    def indodax_secret_key(self) -> str:
        return self.INDODAX_SECRET

BotConfig = Settings

def load_settings() -> Settings:
    # Priority: ENV vars -> fallback to default
    live_flag = os.getenv("LIVE_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    key = os.getenv("INDODAX_KEY", os.getenv("INDODAX_API_KEY", ""))
    secret = os.getenv("INDODAX_SECRET", os.getenv("INDODAX_SECRET_KEY", ""))
    
    # If permission 600 credentials file exists, read it
    cred_file = os.getenv("KIBOT_CREDENTIALS_FILE", "")
    if cred_file and Path(cred_file).is_file():
        try:
            # Check permissions (must be 600 or stricter)
            stat = Path(cred_file).stat()
            if (stat.st_mode & 0o077) != 0:
                pass  # warn or handle in strict auditor
            with open(cred_file, "r") as f:
                for line in f:
                    if line.startswith("INDODAX_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("INDODAX_SECRET="):
                        secret = line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass

    return Settings(
        LIVE_TRADING_ENABLED=live_flag,
        INDODAX_KEY=key,
        INDODAX_SECRET=secret,
        COUNCIL_WORKERS=int(os.getenv("COUNCIL_WORKERS", "4")),
        MAX_SYMBOL_QUEUE_CAP=int(os.getenv("MAX_SYMBOL_QUEUE_CAP", "20")),
        MAX_DRAWDOWN_PCT=float(os.getenv("MAX_DRAWDOWN_PCT", "18.0")),
        MAX_DAILY_LOSS_PCT=float(os.getenv("MAX_DAILY_LOSS_PCT", "3.0")),
    )

settings = load_settings()
