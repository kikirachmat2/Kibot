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
        ROOT_DIR.parent / "Shared" / "Ops" / ".env",
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

    def jina_search(self, query: str) -> str:
        api_key = os.getenv("JINA_API_KEY")
        if not api_key: return ""
        
        def loader():
            # Jina Reader API - using the recommended r.jina.ai prefix
            search_url = f"https://r.jina.ai/{urllib.parse.quote(query)}"
            req = urllib.request.Request(
                search_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "X-No-Cache": "true",
                    "X-With-Links-Summary": "true",
                    "User-Agent": "KiBot-Sovereign-Council/1.0"
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    if resp.status != 200:
                        print(f"[JINA] HTTP Error: {resp.status}")
                        return ""
                    data = json.loads(resp.read().decode("utf-8"))
                    # Jina returns a list of results in 'data' or 'content'
                    results = data.get("data", []) if isinstance(data, dict) else []
                    if not results and "content" in data:
                        return data["content"]
                    
                    content = ""
                    for res in results[:5]: # Top 5
                        content += f"Source: {res.get('url')}\nContent: {res.get('content', '')[:1000]}\n\n"
                    return content
            except Exception as e:
                print(f"[JINA] Connection Error: {e}")
                return ""
            
        return self._cached(f"jina:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def brave_search(self, query: str) -> Dict:
        api_key = os.getenv("BRAVE_API_KEY")
        if not api_key: return {}
        
        def loader():
            req = urllib.request.Request(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json"
                }
            )
            # Add query param
            url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}"
            req.full_url = url
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                print(f"[BRAVE] Error: {e}")
                return {}
            
        return self._cached(f"brave:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def cryptopanic_news(self, filter: str = "hot") -> List[Dict]:
        api_key = os.getenv("CRYPTOPANIC_API_KEY")
        if not api_key: return []
        
        def loader():
            url = "https://cryptopanic.com/api/v1/posts/"
            params = {
                "auth_token": api_key,
                "public": "true",
                "filter": filter,
                "kind": "news"
            }
            try:
                res = self._get_json(url, params=params)
                return res.get("results", [])
            except: return []
            
        return self._cached(f"cryptopanic:{filter}", 600, loader)

    def get_market_consensus(self, topic: str) -> str:
        """Combines multiple search signals into a single consensus string."""
        jina = self.jina_search(topic)
        brave = self.brave_search(topic)
        panic = self.cryptopanic_news() if "crypto" in topic.lower() else []
        finnhub = self.finnhub_news() if "crypto" in topic.lower() else []
        
        # Format Brave results
        brave_snippet = ""
        if brave.get("web", {}).get("results"):
            for res in brave["web"]["results"][:3]:
                brave_snippet += f"- {res.get('title')}: {res.get('description')}\n"
        
        # Format CryptoPanic results
        panic_snippet = ""
        for p in panic[:5]:
            panic_snippet += f"- [{p.get('votes', {}).get('positive', 0)}+] {p.get('title')}\n"

        # Format Finnhub results
        finnhub_snippet = ""
        for n in finnhub[:3]:
            finnhub_snippet += f"- {n.get('headline')} ({n.get('source')})\n"
            
        return (
            f"### Market Consensus for: {topic}\n\n"
            f"**Institutional (Finnhub):**\n{finnhub_snippet}\n"
            f"**Brave Web Results:**\n{brave_snippet}\n"
            f"**CryptoPanic Hot News:**\n{panic_snippet}\n"
            f"**Deep Jina Context:**\n{jina[:2000]}\n"
        )

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

def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """Helper function for quick web search using DDG/Tavily."""
    service = AISearchService()
    # Try Tavily first if key exists, otherwise DDG
    if os.getenv("TAVILY_API_KEY"):
        results = service.tavily_search(query)
        if results.get("results"):
            return results["results"][:max_results]
    return service.ddg_search(query, max_results=max_results)

if __name__ == "__main__":
    print("--- AI Search Service Test ---")
    res = search_web("bitcoin price news")
    print(f"Results: {len(res)}")
