"""Unit tests for configuration security, default values, and credential masking."""
import os
import logging
from config.settings import BotConfig
from storage.async_logger import SecretRedactingFilter

def test_live_trading_default_is_false():
    """Ensure LIVE_TRADING_ENABLED is strictly False by default."""
    config = BotConfig()
    assert config.live_trading_enabled is False

def test_credential_masking_in_repr():
    """Ensure API secret is never exposed in string representation."""
    config = BotConfig(indodax_secret_key="SUPER_SECRET_KEY_12345")
    repr_str = repr(config)
    assert "SUPER_SECRET_KEY_12345" not in repr_str
    assert "********" in repr_str

def test_credential_masking_in_redacted_dict():
    """Ensure get_redacted_dict masks sensitive keys."""
    config = BotConfig(
        indodax_key="MY_KEY_ABC",
        indodax_secret_key="SUPER_SECRET_XYZ"
    )
    redacted = config.get_redacted_dict()
    assert redacted["INDODAX_KEY"] == "********"
    assert redacted["INDODAX_SECRET"] == "********"

def test_secret_redacting_logging_filter():
    """Ensure SecretRedactingFilter strips configured secrets from logs."""
    redactor = SecretRedactingFilter(key="KEY_999_SECRET_ABC", secret="TOP_SECRET_PHRASE_XYZ")
    
    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="Connecting with key: KEY_999_SECRET_ABC and secret TOP_SECRET_PHRASE_XYZ now",
        args=(),
        exc_info=None
    )
    redactor.filter(record)
    assert "TOP_SECRET_PHRASE_XYZ" not in record.msg
    assert "KEY_999_SECRET_ABC" not in record.msg
    assert "********" in record.msg
