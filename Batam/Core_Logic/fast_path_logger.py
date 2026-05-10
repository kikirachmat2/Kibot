import json
import os
from datetime import datetime
from pathlib import Path

class FastPathLogger:
    """
    Sovereign Fast Path Logger
    Captures every signal decision (Executed, Vetoed, or Skipped) with full context.
    This log serves as the primary data source for the Trading Council's auditing.
    """
    def __init__(self, log_path=None):
        if log_path is None:
            # Default to Batam/Logs/fast_path_signals.jsonl
            base_dir = Path(__file__).resolve().parent.parent
            self.log_path = base_dir / "Logs" / "fast_path_signals.jsonl"
        else:
            self.log_path = Path(log_path)
            
        # Ensure directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_decision(self, signal_data, status, reason, metadata=None):
        """
        Logs a decision entry to the jsonl file.
        
        Args:
            signal_data (dict): The original signal payload.
            status (str): The decision outcome (e.g., 'APPROVED', 'VETOED', 'MATH_SKIP').
            reason (str): Human-readable reason for the decision.
            metadata (dict, optional): Additional context (portfolio state, etc.)
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": signal_data.get('s') or signal_data.get('symbol'),
            "price": float(signal_data.get('p') or signal_data.get('price_idr') or signal_data.get('price_usdt', 0)),
            "status": status,
            "reason": reason,
            "raw_signal": signal_data,
            "metadata": metadata or {}
        }
        
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            # Fallback to stdout if file logging fails
            print(f"ERROR [FastPathLogger]: Failed to log decision for {entry.get('symbol')}: {e}")

if __name__ == "__main__":
    # Test logic
    logger = FastPathLogger()
    logger.log_decision({"s": "BTC-IDR", "p": 1000000000}, "APPROVED", "High Momentum")
    print(f"Test entry logged to {logger.log_path}")
