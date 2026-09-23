"""
Module: config.settings
Author: KiBot V3 Team
Date: 2026-10-01

References:
[1] SlowMist (2025). "Security Audit Guidelines: Deterministic Boundary Protection for Automated Agents."
[2] Binance Academy (2026). "API Security Best Practices: Principle of Least Privilege and Narrow Scoping."
"""

import os
from typing import Dict
from pydantic import BaseModel, Field

# Load .env file automatically if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Settings(BaseModel):
    # Operating Mode
    PAPER_MODE: bool = Field(default=True, description="Run in paper trading simulation mode")
    
    # Storage
    DB_PATH: str = Field(default="data/kibot_v3.db", description="Path to SQLite database")
    
    # Core Strategy Allocation Targets (70% BTC / 30% ETH)
    TARGET_ALLOCATION: Dict[str, float] = Field(
        default={
            "BTC": 0.70,
            "ETH": 0.30,
        },
        description="Target portfolio allocation percentages (70% BTC / 30% ETH)"
    )
    
    # Polling & Cycle Intervals (in seconds)
    EVENT_POLLING_INTERVAL: int = Field(
        default=180,
        description="Polling interval in seconds for balance delta inspection"
    )
    
    # Guardrails (Loaded from environment variables if set)
    MAX_SINGLE_TRADE_IDR: float = Field(
        default_factory=lambda: float(os.getenv("MAX_SINGLE_TRADE_IDR", "1000000.0")),
        description="Maximum IDR amount per single trade execution"
    )
    MAX_MONTHLY_TOPUP_IDR: float = Field(
        default_factory=lambda: float(os.getenv("MAX_MONTHLY_TOPUP_IDR", "5000000.0")),
        description="Maximum cumulative IDR topup permitted per calendar month"
    )
    MIN_TOPUP_IDR: float = Field(
        default_factory=lambda: float(os.getenv("MIN_TOPUP_IDR", "100000.0")),
        description="Minimum IDR topup amount"
    )


settings = Settings()
