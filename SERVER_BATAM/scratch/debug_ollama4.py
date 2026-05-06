import sys
import requests
from pathlib import Path
_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(_root / "SERVER_BATAM" / "AI_Orchestration"))

import kibot_ai_coordinator

api_key = kibot_ai_coordinator._provider_api_key("ollama")
model = kibot_ai_coordinator._provider_model("ollama", "OPS_CHAT")
url = kibot_ai_coordinator.PROVIDERS["ollama"]["base_url"]
payload = {
    "model": model,
    "messages": [{"role": "user", "content": "hello"}],
    "stream": False,
    "format": "json",
    "keep_alive": kibot_ai_coordinator._ollama_keep_alive("OPS_CHAT"),
    "options": kibot_ai_coordinator._ollama_options("OPS_CHAT"),
}
payload["think"] = kibot_ai_coordinator._ollama_think_value()

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
}

print(f"URL: {url}")
print(f"Payload: {payload}")
print(f"Headers: {headers}")

req = requests.post(url, json=payload, headers=headers, timeout=20.0)
print("STATUS CODE:", req.status_code)
print("TEXT:", req.text)
