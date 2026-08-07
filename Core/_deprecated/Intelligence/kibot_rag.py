import json
import os
import re
from pathlib import Path
from typing import List, Dict, Any

class KiBotRAG:
    """
    Lightweight Sovereign RAG Engine for KiBot Trinity.
    Replaces Dify with a fast, local, keyword-based context retriever.
    """
    def __init__(self, bundle_path: str = "/home/ubuntu/KiBot/Batam/data/intelligence_bundle.json"):
        self.bundle_path = Path(bundle_path)
        self.knowledge = {}
        self.chunks = []
        self.load_knowledge()

    def load_knowledge(self):
        """Load aggregated knowledge from the intelligence bundle."""
        if not self.bundle_path.exists():
            print(f"[RAG] Warning: Intelligence bundle not found at {self.bundle_path}")
            return

        try:
            with open(self.bundle_path, "r") as f:
                self.knowledge = json.load(f)
            self._create_chunks()
            print(f"[RAG] Loaded {len(self.chunks)} knowledge chunks.")
        except Exception as e:
            print(f"[RAG] Error loading knowledge: {e}")

    def _create_chunks(self):
        """Split rules and maps into searchable chunks."""
        self.chunks = []

        # 1. Rules
        rules = self.knowledge.get("rules", {})
        for source, content in rules.items():
            sections = re.split(r'\n(?=##|#|\d+\.)', content)
            for sec in sections:
                if sec.strip():
                    self.chunks.append({"source": f"RULE_{source}", "content": sec.strip()})

        # 2. System Map
        system_map = self.knowledge.get("system_map", "")
        if system_map:
            sections = re.split(r'\n(?=##|#)', system_map)
            for sec in sections:
                if sec.strip():
                    self.chunks.append({"source": "SYSTEM_MAP", "content": sec.strip()})

        # 3. Learning Experience (Condensed)
        learning = self.knowledge.get("learning_experience", {})
        for pair, data in learning.items():
            if isinstance(data, dict):
                summary = f"Pair {pair}: Realized PnL {data.get('total_pnl', 0)}, Success Rate {data.get('success_rate', 0)}%"
                self.chunks.append({"source": "LEARNING", "content": summary})

    def search(self, query: str, top_k: int = 3) -> str:
        """Simple keyword-based search to find relevant context."""
        if not self.chunks:
            return ""

        query_terms = set(re.findall(r'\w+', query.lower()))
        scores = []

        for chunk in self.chunks:
            content_lower = chunk["content"].lower()
            score = sum(2 for term in query_terms if term in content_lower) # Match
            # Bonus for exact phrase match
            if query.lower() in content_lower:
                score += 5

            if score > 0:
                scores.append((score, chunk))

        # Sort by score descending
        scores.sort(key=lambda x: x[0], reverse=True)

        results = [s[1]["content"] for s in scores[:top_k]]
        return "\n---\n".join(results)

# Singleton instance
_rag_engine = None

def get_rag_context(query: str, top_k: int = 2) -> str:
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = KiBotRAG()
    return _rag_engine.search(query, top_k=top_k)

if __name__ == "__main__":
    # Test
    print("Testing RAG...")
    context = get_rag_context("filosofi trading")
    print(f"Context found:\n{context}")
