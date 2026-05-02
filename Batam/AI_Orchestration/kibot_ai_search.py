#!/usr/bin/env python3
"""
KiBot AI Search Service
=======================
Consolidated web search and news retrieval service for autonomous research.
Provides unified access to Tavily, Serper, DuckDuckGo, Finnhub, and GDELT.
"""

import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import hashlib

# Path resolution for .env
ROOT_DIR = Path(__file__).resolve().parent.parent

def _load_dotenv() -> None:
    """Search for .env in current and parent directories."""
    candidates = [
        ROOT_DIR / ".env",
        ROOT_DIR.parent / ".env",
        Path(".env"),
        Path("../.env"),
    ]
    for p in candidates:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                try:
                    k, v = line.split("=", 1)
                    if k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip("'").strip('"')
                except: continue
            break

_load_dotenv()

class AISearchService:
    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        # Root state for persistence
        self.state_dir = ROOT_DIR / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.state_dir / "ai_search_cache.json"

    def _get_json(self, url: str, params: Dict = None, headers: Dict = None) -> Any:
        try:
            if params:
                url += "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return {}

    def _cached(self, key: str, ttl: int, fn) -> Any:
        now = time.time()
        cache = {}
        if self.cache_file.exists():
            try:
                cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except: pass
        
        if key in cache:
            entry = cache[key]
            if now - entry.get("at", 0) < ttl:
                return entry.get("data")
        
        data = fn()
        if data:
            cache[key] = {"at": now, "data": data}
            try:
                self.cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")
            except: pass
        return data

    def tavily_search(self, query: str, search_depth: str = "basic") -> Dict:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key: return {}
        
        def loader():
            # Tavily API v1
            data = json.dumps({
                "api_key": api_key,
                "query": query,
                "search_depth": search_depth,
                "include_answer": True
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=data,
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except: return {}
            
        return self._cached(f"tavily:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def serper_search(self, query: str) -> Dict:
        api_key = os.getenv("SERPER_API_KEY")
        if not api_key: return {}
        
        def loader():
            req = urllib.request.Request(
                "https://google.serper.dev/search",
                data=json.dumps({"q": query, "gl": "id", "hl": "id"}).encode("utf-8"),
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except: return {}
            
        return self._cached(f"serper:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def ddg_search(self, query: str, max_results: int = 5) -> List[Dict]:
        try:
            from duckduckgo_search import DDGS
            def loader():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results))
            return self._cached(f"ddg:{hashlib.md5(query.encode()).hexdigest()}", 1800, loader)
        except ImportError:
            return []

    def finnhub_news(self, category: str = "crypto") -> List[Dict]:
        api_key = os.getenv("FINNHUB_API_KEY")
        if not api_key: return []
        
        def loader():
            return self._get_json(
                "https://finnhub.io/api/v1/news",
                params={"category": category, "token": api_key}
            )
        return self._cached(f"finnhub:{category}", 900, loader)

    def gdelt_news(self, query: str = "crypto") -> List[Dict]:
        def loader():
            payload = self._get_json(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": 10
                }
            )
            return payload.get("articles", []) if isinstance(payload, dict) else []
        return self._cached(f"gdelt:{hashlib.md5(query.encode()).hexdigest()}", 1800, loader)

if __name__ == "__main__":
    service = AISearchService()
    print("--- AI Search Service Test ---")
    # Small test
    news = service.finnhub_news()
    print(f"Finnhub News found: {len(news)}")
    if news: print(f"Top: {news[0].get('headline')}")
