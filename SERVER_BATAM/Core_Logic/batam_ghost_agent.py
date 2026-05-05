import os
import json
import httpx
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - GHOST - %(message)s')

ROOT_DIR = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parents[2]))
OLLAMA_GENERATE_URL = os.getenv(
    "KIBOT_GHOST_AGENT_OLLAMA_URL",
    os.getenv("KIBOT_OLLAMA_GENERATE_URL", "http://127.0.0.1:11435/api/generate"),
).strip()
OLLAMA_AUTH_TOKEN = os.getenv("KIBOT_OLLAMA_GATEWAY_TOKEN", os.getenv("OLLAMA_API_KEY", "")).strip()

class GhostAgent:
    def __init__(self, model="deepseek-coder-v2:16b"):
        self.model = model
        self.knowledge_base = self._load_knowledge()

    def _load_knowledge(self):
        """Membaca semua file penting Batam untuk dipelajari."""
        knowledge = ""
        critical_files = [
            ROOT_DIR / "SERVER_BATAM" / "Core_Logic" / "kibot_manager.py",
            ROOT_DIR / "SERVER_BATAM" / "Core_Logic" / "sovereign_arbitrator.py",
            ROOT_DIR / "SERVER_BATAM" / "Support" / "ki_config.py",
        ]
        for f in critical_files:
            if f.exists():
                with open(f, "r", encoding="utf-8") as content:
                    knowledge += f"\nFILE: {os.path.basename(f)}\n{content.read()[:2000]}\n"
        return knowledge

    async def chat(self, user_input):
        prompt = (
            f"KNOWLEDGE BASE:\n{self.knowledge_base}\n\n"
            f"PERTANYAAN USER: {user_input}\n\n"
            "Kamu adalah Ghost Agent Batam. Gunakan knowledge di atas untuk menjawab. "
            "Jawab dengan gaya 'Cyberpunk Agent', dingin tapi cerdas."
        )
        try:
            async with httpx.AsyncClient() as client:
                headers = {"Content-Type": "application/json"}
                if OLLAMA_AUTH_TOKEN:
                    headers["Authorization"] = f"Bearer {OLLAMA_AUTH_TOKEN}"
                res = await client.post(
                    OLLAMA_GENERATE_URL,
                    json={"model": self.model, "prompt": prompt, "stream": False},
                    headers=headers,
                    timeout=120.0,
                )
                return res.json()['response']
        except Exception as e:
            return f"Error: {e}"

# Uji Coba Agent
if __name__ == "__main__":
    import asyncio
    agent = GhostAgent()
    response = asyncio.run(agent.chat("Siapa kamu dan apa tugasmu di Batam?"))
    print(f"Ghost Agent: {response}")
