import sys
import os
from pathlib import Path

# Setup path
ROOT_DIR = Path.cwd()
sys.path.insert(0, str(ROOT_DIR))

try:
    from SERVER_BATAM.Core.ki_brain import BrainManager
    brain = BrainManager()
    print("✅ BrainManager loaded successfully")
    print(f"Snapshot status: {'Available' if brain.snapshot() else 'Empty'}")
except Exception as e:
    print(f"❌ BrainManager failed: {e}")
    import traceback
    traceback.print_exc()

try:
    from SERVER_BATAM.Support.ki_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    print(f"✅ Config loaded: Token prefix {TELEGRAM_BOT_TOKEN[:10]}...")
except Exception as e:
    print(f"❌ Config failed: {e}")
