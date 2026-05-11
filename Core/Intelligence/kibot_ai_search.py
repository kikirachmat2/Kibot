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
import httpx
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import hashlib
import urllib.parse

from Core.Support.ki_config import PROJECT_ROOT as ROOT_DIR

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

    async def _get_json_async(self, url: str, params: Dict = None, headers: Dict = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return {}

    def _get_json(self, url: str, params: Dict = None, headers: Dict = None) -> Any:
        # Keep for backward compatibility if needed, but internally it's now blocking call to async
        return asyncio.run(self._get_json_async(url, params, headers))

    async def _cached_async(self, key: str, ttl: int, loader) -> Any:
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
        
        # Only execute loader if cache miss
        if asyncio.iscoroutinefunction(loader):
            data = await loader()
        elif callable(loader):
            data = loader()
        else:
            # If it's already a coroutine (legacy support), await it
            data = await loader
            
        if data:
            cache[key] = {"at": now, "data": data}
            try:
                self.cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")
            except: pass
        return data

    def _cached(self, key: str, ttl: int, fn) -> Any:
        return asyncio.run(self._cached_async(key, ttl, asyncio.to_thread(fn)))

    async def tavily_search_async(self, query: str, search_depth: str = "basic") -> Dict:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key: return {}
        
        async def loader():
            data = {
                "api_key": api_key,
                "query": query,
                "search_depth": search_depth,
                "include_answer": True
            }
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post("https://api.tavily.com/search", json=data)
                    if resp.status_code == 200:
                        return resp.json()
            except: pass
            return {}
            
        return await self._cached_async(f"tavily:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def tavily_search(self, query: str, search_depth: str = "basic") -> Dict:
        return asyncio.run(self.tavily_search_async(query, search_depth))

    async def serper_search_async(self, query: str) -> Dict:
        api_key = os.getenv("SERPER_API_KEY")
        if not api_key: return {}
        
        async def loader():
            headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
            data = {"q": query, "gl": "id", "hl": "id"}
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post("https://google.serper.dev/search", json=data, headers=headers)
                    if resp.status_code == 200:
                        return resp.json()
            except: pass
            return {}
            
        return await self._cached_async(f"serper:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def serper_search(self, query: str) -> Dict:
        return asyncio.run(self.serper_search_async(query))

    async def ddg_search_async(self, query: str, max_results: int = 5) -> List[Dict]:
        try:
            from duckduckgo_search import DDGS
            async def loader():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results))
            return await self._cached_async(f"ddg:{hashlib.md5(query.encode()).hexdigest()}", 1800, loader)
        except ImportError:
            return []

    def ddg_search(self, query: str, max_results: int = 5) -> List[Dict]:
        return asyncio.run(self.ddg_search_async(query, max_results))

    async def jina_search_async(self, query: str) -> str:
        api_key = os.getenv("JINA_API_KEY")
        if not api_key: return ""
        
        async def loader():
            search_url = f"https://r.jina.ai/{urllib.parse.quote(query)}"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "X-No-Cache": "true",
                "X-With-Links-Summary": "true",
                "User-Agent": "KiBot-Sovereign-Council/1.0"
            }
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(search_url, headers=headers)
                    if resp.status_code != 200:
                        return ""
                    data = resp.json()
                    results = data.get("data", []) if isinstance(data, dict) else []
                    if not results and "content" in data:
                        return data["content"]
                    
                    content = ""
                    for res in results[:5]:
                        content += f"Source: {res.get('url')}\nContent: {res.get('content', '')[:1000]}\n\n"
                    return content
            except: return ""
            
        return await self._cached_async(f"jina:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def jina_search(self, query: str) -> str:
        return asyncio.run(self.jina_search_async(query))

    async def brave_search_async(self, query: str) -> Dict:
        """Async version of Brave search."""
        api_key = os.getenv("BRAVE_API_KEY")
        if not api_key: return {}
        
        async def loader():
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                "X-Subscription-Token": api_key,
                "Accept": "application/json"
            }
            params = {"q": query}
            try:
                return await self._get_json_async(url, params=params, headers=headers)
            except: return {}
            
        return await self._cached_async(f"brave:{hashlib.md5(query.encode()).hexdigest()}", 3600, loader)

    def brave_search(self, query: str) -> Dict:
        return asyncio.run(self.brave_search_async(query))

    async def cryptopanic_news_async(self, filter: str = "hot") -> List[Dict]:
        """Async version of CryptoPanic news."""
        api_key = os.getenv("CRYPTOPANIC_API_KEY")
        if not api_key: return []
        
        async def loader():
            url = "https://cryptopanic.com/api/v1/posts/"
            params = {
                "auth_token": api_key,
                "public": "true",
                "filter": filter,
                "kind": "news"
            }
            try:
                res = await self._get_json_async(url, params=params)
                return res.get("results", [])
            except: return []
            
        return await self._cached_async(f"cryptopanic:{filter}", 600, loader)

    def cryptopanic_news(self, filter: str = "hot") -> List[Dict]:
        return asyncio.run(self.cryptopanic_news_async(filter))

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
        if isinstance(panic, list):
            for p in panic[:5]:
                panic_snippet += f"- [{p.get('votes', {}).get('positive', 0)}+] {p.get('title')}\n"
        else:
            panic_snippet = "- No data available (CryptoPanic)\n"

        # Format Finnhub results
        finnhub_snippet = ""
        if isinstance(finnhub, list):
            for n in finnhub[:3]:
                finnhub_snippet += f"- {n.get('headline')} ({n.get('source')})\n"
        else:
            finnhub_snippet = "- No data available (Finnhub)\n"
            
        return (
            f"### Market Consensus for: {topic}\n\n"
            f"**Institutional (Finnhub):**\n{finnhub_snippet}\n"
            f"**Brave Web Results:**\n{brave_snippet}\n"
            f"**CryptoPanic Hot News:**\n{panic_snippet}\n"
            f"**Deep Jina Context:**\n{jina[:2000]}\n"
        )

    async def get_market_consensus_async(self, topic: str) -> str:
        """Combines multiple search signals into a single consensus string (Async)."""
        # Run independent queries in parallel
        is_crypto = "crypto" in topic.lower()
        tasks = [
            self.jina_search_async(topic),
            self.brave_search_async(topic),
            self.cryptopanic_news_async() if is_crypto else asyncio.sleep(0),
            self.finnhub_news_async() if is_crypto else asyncio.sleep(0)
        ]
        
        results = await asyncio.gather(*tasks)
        jina = results[0]
        brave = results[1]
        panic = results[2] if is_crypto else []
        finnhub = results[3] if is_crypto else []
        
        # Format Brave results
        brave_snippet = ""
        if isinstance(brave, dict) and brave.get("web", {}).get("results"):
            for res in brave["web"]["results"][:3]:
                brave_snippet += f"- {res.get('title')}: {res.get('description')}\n"
        
        # Format CryptoPanic
        panic_snippet = ""
        if isinstance(panic, list):
            for p in panic[:5]:
                panic_snippet += f"- [{p.get('votes', {}).get('positive', 0)}+] {p.get('title')}\n"
        else:
            panic_snippet = "- No data available (CryptoPanic)\n"

        # Format Finnhub results
        finnhub_snippet = ""
        if isinstance(finnhub, list):
            for n in finnhub[:3]:
                finnhub_snippet += f"- {n.get('headline')} ({n.get('source')})\n"
        else:
            finnhub_snippet = "- No data available (Finnhub)\n"
            
        return (
            f"### Market Consensus for: {topic}\n\n"
            f"**Institutional (Finnhub):**\n{finnhub_snippet}\n"
            f"**Brave Web Results:**\n{brave_snippet}\n"
            f"**CryptoPanic Hot News:**\n{panic_snippet}\n"
            f"**Deep Jina Context:**\n{str(jina)[:2000]}\n"
        )

    async def finnhub_news_async(self, category: str = "crypto") -> List[Dict]:
        api_key = os.getenv("FINNHUB_API_KEY")
        if not api_key: return []
        
        async def loader():
            return await self._get_json_async(
                "https://finnhub.io/api/v1/news",
                params={"category": category, "token": api_key}
            )
        return await self._cached_async(f"finnhub:{category}", 900, loader)

    def finnhub_news(self, category: str = "crypto") -> List[Dict]:
        return asyncio.run(self.finnhub_news_async(category))

    async def gdelt_news_async(self, query: str = "crypto") -> List[Dict]:
        async def loader():
            payload = await self._get_json_async(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": 10
                }
            )
            return payload.get("articles", []) if isinstance(payload, dict) else []
        return await self._cached_async(f"gdelt:{hashlib.md5(query.encode()).hexdigest()}", 1800, loader)

    def gdelt_news(self, query: str = "crypto") -> List[Dict]:
        return asyncio.run(self.gdelt_news_async(query))

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
