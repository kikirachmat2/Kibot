import sys
import requests
from pathlib import Path
_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(_root / "SERVER_BATAM" / "AI_Orchestration"))

import kibot_ai_coordinator

context = {"user_message": "Hello KiBot, are you operational?", "governor_profile": "test", "runtime": "test"}
prompt = kibot_ai_coordinator._render_prompt(kibot_ai_coordinator.PROMPT_TEMPLATES.get("OPS_CHAT"), context)

print("PROMPT:")
print(prompt)

api_key = kibot_ai_coordinator._provider_api_key("ollama")
model = kibot_ai_coordinator._provider_model("ollama", "OPS_CHAT")
url = kibot_ai_coordinator.PROVIDERS["ollama"]["base_url"]
payload = {
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
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

req = requests.post(url, json=payload, headers=headers, timeout=30.0)
print("STATUS CODE:", req.status_code)
print("TEXT:", req.text)
