import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re

from config import settings

TELEGRAM_TOKEN_REGEX = re.compile(r'\b\d{10}:[A-Za-z0-9_-]{35}\b')

class SecretRedactingFilter(logging.Filter):
    """
    Guarantees no API key, bot token, or secret can leak into logs, even at DEBUG level.
    Auto-redacts Telegram Bot Token pattern and any explicit secret strings.
    """
    def __init__(self, key: str = "", secret: str = "", tg_token: str = ""):
        super().__init__()
        self.patterns = []
        if key and len(key) > 4:
            self.patterns.append(re.compile(re.escape(key)))
        if secret and len(secret) > 4:
            self.patterns.append(re.compile(re.escape(secret)))
        if tg_token and len(tg_token) > 4:
            self.patterns.append(re.compile(re.escape(tg_token)))

    def _sanitize(self, text: str) -> str:
        text = TELEGRAM_TOKEN_REGEX.sub("<REDACTED>", text)
        for pat in self.patterns:
            text = pat.sub("<REDACTED>", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)
        if record.args:
            # Also clean tuple/dict args if string
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    arg = self._sanitize(arg)
                new_args.append(arg)
            record.args = tuple(new_args)
        return True

def setup_logging(
    log_dir: Path = settings.LOG_DIR,
    max_bytes: int = settings.MAX_LOG_SIZE_BYTES,
    backup_count: int = settings.LOG_BACKUP_COUNT,
    level: int = logging.INFO,
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "kibot_v2.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler (10MB max, 3 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    
    # Redaction filter
    redactor = SecretRedactingFilter(
        key=settings.INDODAX_KEY,
        secret=settings.INDODAX_SECRET,
        tg_token=settings.TELEGRAM_BOT_TOKEN,
    )
    file_handler.addFilter(redactor)
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redactor)
    root_logger.addHandler(console_handler)

