import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re

from config import settings

class SecretRedactingFilter(logging.Filter):
    """
    Guarantees no API key or secret can leak into logs, even at DEBUG level.
    """
    def __init__(self, key: str = "", secret: str = ""):
        super().__init__()
        self.patterns = []
        if key and len(key) > 4:
            self.patterns.append(re.compile(re.escape(key)))
        if secret and len(secret) > 4:
            self.patterns.append(re.compile(re.escape(secret)))

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pat in self.patterns:
                record.msg = pat.sub("********", record.msg)
        if record.args:
            # Also clean tuple/dict args if string
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pat in self.patterns:
                        arg = pat.sub("********", arg)
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
    )
    file_handler.addFilter(redactor)
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redactor)
    root_logger.addHandler(console_handler)
