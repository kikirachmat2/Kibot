# ==============================================================================
# KiBot Guardian: The Strategic Risk Gate
# Motto: "Tekan Kerugian, Maksimalkan Probabilitas Keuntungan"
# ==============================================================================

import time
import sys
import os

# Add paths to imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Support.ki_config import KiConfig

class KiGuardian:
    def __init__(self):
        self.philosophy = KiConfig.PHILOSOPHY
        self.max_loss = KiConfig.MAX_DAILY_LOSS_PERCENT
        self.min_prob = KiConfig.MIN_SIGNAL_PROBABILITY
        print(f"🛡️ [GUARDIAN] System Activated. Philosophy: {self.philosophy}")

    def validate_signal(self, signal_data):
        """Motto: Maksimalkan Probabilitas Keuntungan"""
        prob = signal_data.get('probability', 0)
        if prob >= self.min_prob:
            print(f"✅ [GUARDIAN] High Probability Signal ({prob*100}%). Validating Risk...")
            return True
        else:
            print(f"❌ [GUARDIAN] Signal Rejected. Probability {prob*100}% below threshold {self.min_prob*100}%.")
            return False

    def check_daily_drawdown(self, current_pnl_percent):
        """Motto: Tekan Kerugian"""
        if current_pnl_percent <= -self.max_loss:
            print(f"⚠️ [CRITICAL] Daily Drawdown Limit Reached ({current_pnl_percent}%). KILL SWITCH ACTIVATED.")
            self.emergency_stop()
            return False
        return True

    def emergency_stop(self):
        print("🛑 [GUARDIAN] Sending STOP command to all nodes...")
        # Logic to send stop signal to Executor via Command Plane
        pass

if __name__ == "__main__":
    guardian = KiGuardian()
    # Mock loop for background monitoring
    while True:
        # Actual implementation will hook into the state engine
        time.sleep(60)
