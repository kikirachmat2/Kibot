import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(_root / "SERVER_BATAM" / "AI_Orchestration"))

import kibot_ai_coordinator
print(kibot_ai_coordinator._call_provider("ollama", "hello", "OPS_CHAT"))
