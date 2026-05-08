import os
import json
import httpx
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - GHOST - %(message)s')

ROOT_DIR = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parents[2]))
try:
    from SERVER_BATAM.Intelligence.kibot_rag import get_rag_context
except Exception:
    get_rag_context = None

OLLAMA_GENERATE_URL = os.getenv(
    "KIBOT_GHOST_AGENT_OLLAMA_URL",
    os.getenv("KIBOT_OLLAMA_GENERATE_URL", "http://127.0.0.1:11435/api/chat"),
).strip()
OLLAMA_FALLBACK_URL = os.getenv(
    "KIBOT_GHOST_AGENT_OLLAMA_FALLBACK_URL",
    "http://127.0.0.1:11434/api/chat",
).strip()
OLLAMA_AUTH_TOKEN = os.getenv("KIBOT_OLLAMA_GATEWAY_TOKEN", os.getenv("OLLAMA_API_KEY", "")).strip()

class GhostAgent:
    def __init__(self, model=None):
        self.model = model or os.getenv("KIBOT_GHOST_AGENT_MODEL", "qwen2.5-coder:7b")
        self.knowledge_base = self._load_knowledge()

    def _load_knowledge(self):
        """Membaca semua file penting Batam untuk dipelajari."""
        knowledge = ""
        critical_files = [
            ROOT_DIR / "SERVER_BATAM" / "Core" / "kibot_manager.py",
            ROOT_DIR / "SERVER_BATAM" / "Core" / "sovereign_arbitrator.py",
            ROOT_DIR / "SERVER_BATAM" / "Support" / "ki_config.py",
        ]
        for f in critical_files:
            if f.exists():
                with open(f, "r", encoding="utf-8") as content:
                    knowledge += f"\nFILE: {os.path.basename(f)}\n{content.read()[:2000]}\n"
        return knowledge

    async def chat(self, user_input):
        rag_context = ""
        if get_rag_context:
            try:
                rag_context = get_rag_context(user_input, top_k=2).strip()
            except Exception as e:
                logging.info(f"[GHOST][RAG] {e}")
        prompt = (
            f"KNOWLEDGE BASE:\n{self.knowledge_base}\n\n"
            f"RAG CONTEXT:\n{rag_context or '(none)'}\n\n"
            f"PERTANYAAN USER: {user_input}\n\n"
            "Kamu adalah Ghost Agent Batam. Gunakan knowledge di atas untuk menjawab. "
            "Jawab dengan gaya 'Cyberpunk Agent', dingin tapi cerdas."
        )
        urls = [OLLAMA_GENERATE_URL]
        if OLLAMA_FALLBACK_URL and OLLAMA_FALLBACK_URL not in urls:
            urls.append(OLLAMA_FALLBACK_URL)
        headers = {"Content-Type": "application/json"}
        if OLLAMA_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {OLLAMA_AUTH_TOKEN}"
        last_error = None
        async with httpx.AsyncClient() as client:
            for url in urls:
                try:
                    res = None
                    res = await client.post(
                        url,
                        json={"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False},
                        headers=headers if url == OLLAMA_GENERATE_URL else {"Content-Type": "application/json"},
                        timeout=300.0,
                    )
                    data = res.json()
                    if isinstance(data, dict) and "message" in data:
                        return data["message"]["content"]
                    elif isinstance(data, dict) and "response" in data:
                        return data["response"]
                    last_error = f"empty_response_from_{url}"
                except Exception as e:
                    last_error = f"{url}: {e}"
                    if res is not None:
                        last_error += f" (Status: {res.status_code})"
                    continue
        return f"Error: {last_error or 'unknown'}"

# Uji Coba Agent
if __name__ == "__main__":
    import asyncio
    agent = GhostAgent()
    response = asyncio.run(agent.chat("Siapa kamu dan apa tugasmu di Batam?"))
    print(f"Ghost Agent: {response}")
