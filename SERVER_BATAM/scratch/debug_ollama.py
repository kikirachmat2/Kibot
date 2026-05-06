import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(_root / "SERVER_BATAM" / "AI_Orchestration"))

import kibot_ai_coordinator
print("OLLAMA URL:", kibot_ai_coordinator.PROVIDERS["ollama"]["base_url"])
