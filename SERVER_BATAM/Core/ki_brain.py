from __future__ import annotations

import importlib.util
import calendar
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import requests


logger = logging.getLogger("KiBrain")
ROOT_DIR = Path(__file__).resolve().parent.parent

POSITIVE_HEADLINE_KEYWORDS = {
    "approval",
    "breakout",
    "bull",
    "gain",
    "greenlight",
    "growth",
    "inflow",
    "launch",
    "listing",
    "partnership",
    "rally",
    "record",
    "recovery",
    "surge",
    "upgrade",
}

NEGATIVE_HEADLINE_KEYWORDS = {
    "attack",
    "ban",
    "breach",
    "crackdown",
    "delist",
    "downtime",
    "dump",
    "exploit",
    "fraud",
    "hack",
    "halt",
    "investigation",
    "lawsuit",
    "liquidation",
    "loss",
    "outage",
    "risk",
    "scam",
    "selloff",
}

KNOWN_CRYPTO_ASSETS = {
    "ADA",
    "ARB",
    "AVAX",
    "BNB",
    "BTC",
    "DOGE",
    "ETH",
    "LTC",
    "MATIC",
    "ONDO",
    "REQ",
    "SOL",
    "SUI",
    "TRX",
    "XLM",
    "XRP",
}


def _load_dotenv_early() -> None:
    candidates = [
        ROOT_DIR / ".env.kibot_manager",
        ROOT_DIR / ".env.kibot",
        ROOT_DIR / ".env.server",
        ROOT_DIR / ".env",
        Path(".env.kibot_manager"),
        Path(".env.kibot"),
        Path(".env.server"),
        Path(".env"),
        Path("../.env"),
    ]
    explicit = os.getenv("KIBOT_MANAGER_ENV_FILE")
    if explicit:
        candidates.insert(0, Path(explicit))
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv_early()

try:
    from SERVER_BATAM.Intelligence.kibot_ai_coordinator import (
        get_provider_status as _coordinator_provider_status_fn,
        query_ai as _coordinator_query_ai_fn,
        query_ai_consensus as _coordinator_query_ai_consensus_fn,
        query_ai_debate as _coordinator_query_ai_debate_fn,
    )
except Exception:
    _coordinator_provider_status_fn = None
    _coordinator_query_ai_fn = None
    _coordinator_query_ai_consensus_fn = None
    _coordinator_query_ai_debate_fn = None


class BrainManager:
    """
    World-aware research helper for sovereign planning.

    Design principles:
    - Never block the live entry hot path on external network calls.
    - Keep search/news usage bounded with short timeouts and long TTLs.
    - Prefer lightweight REST calls over heavy SDK dependencies on small servers.
    - Provide a compact, operator-readable snapshot of market context, world
      state, and progress toward the daily green target.
    """

    def __init__(self) -> None:
        state_root = Path(os.getenv("KIBOT_MANAGER_STATE_DIR", "state"))
        state_root.mkdir(parents=True, exist_ok=True)
        self.state_file = state_root / "brain_status.json"
        self.request_timeout = (
            float(os.getenv("KIBOT_BRAIN_CONNECT_TIMEOUT_SEC", "5.0")),
            float(os.getenv("KIBOT_BRAIN_READ_TIMEOUT_SEC", "30.0")),
        )
        self.review_ttl_sec = int(os.getenv("KIBOT_BRAIN_REVIEW_TTL_SEC", "900"))
        self.market_pulse_ttl_sec = int(os.getenv("KIBOT_BRAIN_MARKET_PULSE_TTL_SEC", "900"))
        self.tavily_ttl_sec = int(os.getenv("KIBOT_BRAIN_TAVILY_TTL_SEC", "7200"))
        self.serper_ttl_sec = int(os.getenv("KIBOT_BRAIN_SERPER_TTL_SEC", "5400"))
        self.ddg_ttl_sec = int(os.getenv("KIBOT_BRAIN_DDG_TTL_SEC", "3600"))
        self.finnhub_ttl_sec = int(os.getenv("KIBOT_BRAIN_FINNHUB_TTL_SEC", "900"))
        self.gemini_ttl_sec = int(os.getenv("KIBOT_BRAIN_GEMINI_TTL_SEC", "7200"))
        self.polymarket_ttl_sec = int(os.getenv("KIBOT_BRAIN_POLYMARKET_TTL_SEC", "90"))
        self.world_model_ttl_sec = int(os.getenv("KIBOT_BRAIN_WORLD_MODEL_TTL_SEC", "600"))
        self.coingecko_ttl_sec = int(os.getenv("KIBOT_BRAIN_COINGECKO_TTL_SEC", "900"))
        self.gdelt_ttl_sec = int(os.getenv("KIBOT_BRAIN_GDELT_TTL_SEC", "1800"))
        self.x_ttl_sec = int(os.getenv("KIBOT_BRAIN_X_TTL_SEC", "600"))
        self.fear_greed_ttl_sec = int(os.getenv("KIBOT_BRAIN_FEAR_GREED_TTL_SEC", "900"))
        self.funding_rate_ttl_sec = int(os.getenv("KIBOT_BRAIN_FUNDING_RATE_TTL_SEC", "300"))
        self.stablecoin_flow_ttl_sec = int(os.getenv("KIBOT_BRAIN_STABLECOIN_FLOW_TTL_SEC", "1800"))
        self.binance_symbol_allowlist = self._parse_binance_symbol_allowlist()
        self.max_watch_symbols = max(1, int(os.getenv("KIBOT_BRAIN_MAX_WATCH_SYMBOLS", "5")))
        self.max_external_symbols = max(1, int(os.getenv("KIBOT_BRAIN_NEWS_MAX_SYMBOLS", "2")))
        self.max_world_events = max(1, int(os.getenv("KIBOT_BRAIN_MAX_WORLD_EVENTS", "6")))
        self.max_world_opportunities = max(1, int(os.getenv("KIBOT_BRAIN_MAX_WORLD_OPPORTUNITIES", "5")))
        self.green_target_daily_pct = float(os.getenv("KIBOT_GREEN_TARGET_DAILY_PCT", "0.003"))
        self.external_research_enabled = os.getenv("KIBOT_BRAIN_ENABLE_EXTERNAL_RESEARCH", "true").lower() == "true"
        self.ai_coordinator_enabled = os.getenv("KIBOT_BRAIN_ENABLE_AI_COORDINATOR", "true").lower() == "true"
        self.world_model_enabled = os.getenv("KIBOT_BRAIN_ENABLE_WORLD_MODEL", "true").lower() == "true"
        self.gdelt_enabled = os.getenv("KIBOT_BRAIN_ENABLE_GDELT", "true").lower() == "true"
        self.search_country = os.getenv("KIBOT_BRAIN_SEARCH_COUNTRY", "indonesia")
        self.search_lang = os.getenv("KIBOT_BRAIN_SEARCH_LANG", "id")
        self.x_lang = os.getenv("KIBOT_BRAIN_X_LANG", "en")
        self.gemini_model = os.getenv("KIBOT_BRAIN_GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite"))
        self.polymarket_state_url = os.getenv("KIBOT_POLYMARKET_STATE_URL", "").strip()
        self._pair_cache: Dict[str, Dict[str, Any]] = {}
        self._provider_cache: Dict[str, Dict[str, Any]] = {}
        self._indodax_pairs_cache: Dict[str, str] = {}
        self._indodax_pairs_cache_at: float = 0.0
        self._indodax_pairs_cooldown_until: float = 0.0
        self._indodax_pairs_cache_file = state_root / "brain_indodax_pairs.json"
        self._indodax_pairs_cache = self._load_indodax_pairs_cache()
        self._last_snapshot: Dict[str, Any] = self._load_snapshot()
        self._refresh_lock = threading.Lock()
        self._refresh_in_flight = False
        self.ai_search = None

    def veto_signal(self, pair: str, msg_type: str = "SIGNAL", regime: str = "UNKNOWN", obi: float = 0.0, session: str = "UNKNOWN") -> Tuple[str, str]:
        """
        Sovereign Veto Logic v2.
        Decides if a signal should be approved based on world model intelligence,
        market regime, and liquidity pressure.
        """
        snapshot = self.snapshot()
        ai_critic = snapshot.get("ai_critic", {})
        market_pulse = snapshot.get("market_pulse", {})
        
        # 1. Rule-Based Pre-Veto (Enhanced with Regime/OBI)
        risk_bias = str(market_pulse.get("risk_bias") or ai_critic.get("risk_bias") or "MIXED").upper()
        posture = str(ai_critic.get("capital_posture") or "NEUTRAL").upper()
        
        # [v7.5] Regime-Aware Blocking
        if regime in ("TRENDING_BEAR", "SIDEWAYS_VOLATILE") and msg_type == "ANOMALY":
            return "REJECTED", f"Regime is {regime}; high-risk anomalies blocked."
            
        # [v7.5] Liquidity Guard (OBI)
        if obi < -0.6 and msg_type in ("SIGNAL", "ANOMALY"):
            return "REJECTED", f"Heavy Sell Pressure (OBI={obi:.2f}); entry rejected."

        if risk_bias == "RISK_OFF" and msg_type in ("ANOMALY", "PUMP"):
            return "REJECTED", "Global risk bias is RISK_OFF; speculative signals blocked."
            
        if posture == "DEFENSIVE" and msg_type not in ("SMART_ENTRY", "SIGNAL"):
            return "REJECTED", "Defensive posture active; only high-conviction signals allowed."

        # 2. Headline Sentiment Overlap
        top_headlines = market_pulse.get("top_headlines", [])
        neg_hits = sum(1 for h in top_headlines if any(w in h.lower() for w in NEGATIVE_HEADLINE_KEYWORDS))
        if neg_hits >= 3:
            return "REJECTED", f"High headline negativity detected ({neg_hits} major alerts)."

        # 3. AI Critic specific symbols
        focus_symbols = [str(s).upper() for s in ai_critic.get("focus_symbols", [])]
        base_symbol = str(pair).upper().split('_')[0] if '_' in pair else str(pair).upper().replace('IDR', '')
        
        if focus_symbols and base_symbol not in focus_symbols:
            # If the critic is opportunistic, we allow it. Otherwise, we stick to focus list.
            if posture != "OPPORTUNISTIC":
                return "REJECTED", f"Asset {base_symbol} not in focus list ({focus_symbols})."

        # 4. Multi-Agent AI Consensus
        decision, reason = self._get_ai_consensus(pair, msg_type, regime, obi, session)
        if decision == "REJECT":
            return "REJECTED", reason
            
        # 5. Lead-lag check (v9.2): Verify against Binance for Indodax signals
        if "idr" in pair.lower() or "idx" in session.lower():
            ll_ok, ll_reason = self._check_lead_lag(pair, {"change_5m_pct": 0}) # Placeholder change
            if not ll_ok:
                return "REJECTED", f"Lead-Lag Veto: {ll_reason}"

        return "APPROVED", f"Passed all Sovereign checks ({regime}/{session})."

    def _check_lead_lag(self, pair: str, signal: dict) -> tuple[bool, str]:
        """
        Cek apakah sinyal Indodax masih dalam window lead-lag Binance.
        Jika Binance sudah naik 5%+ 5 menit lalu, Indodax kemungkinan terlambat.
        """
        # Extract base symbol
        base = pair.split('_')[0].upper() if '_' in pair else pair.upper().replace('IDR', '').replace('/', '')
        binance_pair = f"{base}USDT"
        
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": binance_pair, "interval": "1m", "limit": 10},
                timeout=3
            )
            klines = r.json()
            if not klines or len(klines) < 7:
                return True, "lead_lag_skip"

            # Perubahan harga 5 menit lalu di Binance
            price_5m_ago = float(klines[-6][4])  # close 5 candle lalu
            price_now    = float(klines[-1][4])  # close terakhir
            binance_change = (price_now - price_5m_ago) / price_5m_ago * 100

            indodax_change = float(signal.get("change_5m_pct", 0))

            # Kalau Binance sudah naik >3% dan Indodax baru mulai, ini lead-lag valid
            if binance_change > 3.0 and indodax_change < binance_change * 0.5:
                return True, f"lead_lag_valid: BNB+{binance_change:.1f}% IDX+{indodax_change:.1f}%"

            # Kalau Binance sudah naik >5% dan Indodax sudah naik sebanding, terlambat
            if binance_change > 5.0 and indodax_change > 3.0:
                return False, f"lead_lag_late: BNB already +{binance_change:.1f}%"

        except Exception as e:
            logger.debug(f"Lead-lag error: {e}")
            pass
        return True, "lead_lag_ok"

    def _get_ai_consensus(self, pair: str, msg_type: str, regime: str, obi: float, session: str) -> Tuple[str, str]:
        """
        Multi-Agent Reasoning: Debate between analysts to reach a sovereign decision.
        Uses a tiered architecture:
        1. Sniper (1.5b) - Fast Filter (Instant)
        2. AI Coordinator - High-IQ Consensus (Strategic)
        """
        # --- TIER 1: SNIPER FAST FILTER ---
        try:
            sniper_decision, sniper_reason = self._fast_filter_sniper(pair, msg_type, regime, obi)
            if sniper_decision == "REJECT":
                logger.info(f"[Brain] Sniper REJECTED {pair}: {sniper_reason}")
                return "REJECT", f"Sniper: {sniper_reason}"
        except Exception as e:
            logger.warning(f"[Brain] Sniper bypass due to error: {e}")

        # --- TIER 2: COORDINATOR CONSENSUS ---
        if not self.ai_coordinator_enabled or _coordinator_query_ai_consensus_fn is None:
            return "APPROVE", "AI Coordinator disabled; passing through Sniper check."

        context = {
            "pair": pair,
            "msg_type": msg_type,
            "regime": regime,
            "obi": obi,
            "session": session,
            "market_pulse": self.snapshot().get("market_pulse", {}),
            "world_model": self.snapshot().get("world_model", {}),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        
        try:
            # Use the 7-agent consensus for critical decisions
            symbol = pair.split('_')[0] if '_' in pair else pair
            result = _coordinator_query_ai_consensus_fn(context, symbol=symbol)
            
            if not result:
                return "APPROVE", "Consensus returned empty; default approval."
                
            decision = str(result.get("decision") or "APPROVE").upper()
            reason = str(result.get("reason") or "No reason provided by arbitrator.")
            plan = str(result.get("action_plan") or "")
            
            final_reason = f"{reason} | Plan: {plan}"[:280]
            return decision, final_reason
        except Exception as e:
            logger.error(f"[Brain] Consensus error: {e}")
            return "APPROVE", f"Consensus failed: {e}"
            return "APPROVE", "Fallback to default approval (AI offline)"

        
    def _fast_filter_sniper(self, pair: str, msg_type: str, regime: str, obi: float) -> Tuple[str, str]:
        """
        Calls the Always-On Qwen 1.5b model for near-instant signal validation.
        """
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        prompt = (
            f"As a high-frequency trading sniper, filter this signal.\n"
            f"Asset: {pair}, Type: {msg_type}, Regime: {regime}, OBI: {obi}\n"
            f"Strictly output JSON: {{\"decision\": \"APPROVE\" or \"REJECT\", \"reason\": \"short reason\"}}"
        )
        try:
            payload = {
                "model": "qwen2.5:1.5b",
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "top_p": 0.9}
            }
            response = self._post_json(f"{ollama_url}/api/generate", body=payload, timeout=30.0)
            res_json = json.loads(response.get("response", "{}"))
            return str(res_json.get("decision", "APPROVE")).upper(), str(res_json.get("reason", ""))
        except Exception as e:
            raise RuntimeError(f"Sniper call failed: {e}")

        # AI Search Service (Dynamic Integration)
        self.ai_search = None
        try:
            from SERVER_BATAM.Intelligence.kibot_ai_search import AISearchService
            self.ai_search = AISearchService()
        except Exception as e:
            logger.debug(f"[KiBrain] AI Search Service integration deferred: {e}")

    def _gemini_api_key(self) -> str:
        return (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_SUPPORT_API_KEY")
            or ""
        )

    def _load_indodax_pairs_cache(self) -> Dict[str, str]:
        try:
            if self._indodax_pairs_cache_file.exists():
                payload = json.loads(self._indodax_pairs_cache_file.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    pairs = payload.get("pairs")
                    if isinstance(pairs, dict):
                        clean: Dict[str, str] = {}
                        for base, pair_id in pairs.items():
                            base_key = str(base or "").strip().upper()
                            pair_key = str(pair_id or "").strip().lower()
                            if base_key and pair_key:
                                clean[base_key] = pair_key
                        if clean:
                            self._indodax_pairs_cache = clean
                            self._indodax_pairs_cache_at = float(payload.get("updated_at_epoch") or time.time())
                            return dict(self._indodax_pairs_cache)
        except Exception:
            pass
        return dict(self._indodax_pairs_cache)

    def _get_indodax_pairs(self) -> List[Dict[str, Any]]:
        now = time.time()
        if now < self._indodax_pairs_cooldown_until:
            if self._indodax_pairs_cache:
                return [{"base_currency": base, "ticker_id": pair_id} for base, pair_id in self._indodax_pairs_cache.items()]
            return self._load_indodax_pairs_cache()
        if self._indodax_pairs_cache and (now - self._indodax_pairs_cache_at) < max(900, self.review_ttl_sec):
            return [{"base_currency": base, "ticker_id": pair_id} for base, pair_id in self._indodax_pairs_cache.items()]
        try:
            indodax_pairs = self._get_json("https://indodax.com/api/pairs")
        except Exception as error:
            self._indodax_pairs_cooldown_until = now + 900
            if self._indodax_pairs_cache:
                return [{"base_currency": base, "ticker_id": pair_id} for base, pair_id in self._indodax_pairs_cache.items()]
            logger.debug("[KiBrain] indodax pairs fetch failed: %s", error)
            return []
        if isinstance(indodax_pairs, list) and indodax_pairs:
            cleaned: Dict[str, str] = {}
            for item in indodax_pairs:
                if not isinstance(item, dict):
                    continue
                pair_id = item.get("ticker_id") or item.get("id") or ""
                base = item.get("traded_currency") or item.get("base_currency") or ""
                quote = item.get("base_currency") or item.get("quote_currency") or item.get("quote") or ""
                if pair_id and base and str(quote).lower() == "idr":
                    if "_" not in str(pair_id) and str(pair_id).lower().endswith("idr"):
                        pair_id = f"{str(base).lower()}_idr"
                    cleaned[str(base).upper()] = str(pair_id).lower()
            if cleaned:
                self._indodax_pairs_cache = cleaned
                self._indodax_pairs_cache_at = now
                self._indodax_pairs_cooldown_until = 0.0
                try:
                    self._indodax_pairs_cache_file.write_text(
                        json.dumps({"updated_at_epoch": now, "pairs": cleaned}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                return [{"base_currency": base, "ticker_id": pair_id} for base, pair_id in cleaned.items()]
        self._indodax_pairs_cooldown_until = now + 900
        if self._indodax_pairs_cache:
            return [{"base_currency": base, "ticker_id": pair_id} for base, pair_id in self._indodax_pairs_cache.items()]
        return []

    def get_market_intel(self, symbol: str) -> Dict[str, Any]:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"symbol": "", "ok": False, "reason": "empty_symbol"}

        now = time.time()
        cached = self._pair_cache.get(symbol)
        if cached and (now - float(cached.get("ts") or 0.0)) < self.review_ttl_sec:
            return dict(cached)

        pair = f"{symbol}USDT"
        errors: List[str] = []
        indodax_pairs = self._get_indodax_pairs()
        if not indodax_pairs:
            errors.append("indodax:empty")
        binance: Dict[str, Any] = {}
        if symbol in self.binance_symbol_allowlist:
            try:
                binance = self._get_json(
                    "https://api.binance.com/api/v3/ticker/24hr",
                    params={"symbol": pair},
                )
            except Exception as error:
                binance = {}
                errors.append(f"binance:{type(error).__name__}")
        try:
            coingecko = self._get_json(
                "https://api.coingecko.com/api/v3/search",
                params={"query": symbol},
            )
        except Exception as error:
            coingecko = {}
            errors.append(f"coingecko:{type(error).__name__}")
        listed_on_indodax = self._listed_on_indodax(symbol, indodax_pairs)
        quote_volume = self._safe_float(binance.get("quoteVolume"))
        external_research = self._symbol_external_intel(symbol)
        intel = {
            "symbol": symbol,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "binance": binance,
            "indodax_pairs": indodax_pairs,
            "coingecko_search": coingecko,
            "listed_on_indodax": listed_on_indodax,
            "quote_volume_usdt": quote_volume,
            "external_research": external_research,
            "ok": not errors,
            "errors": errors,
            "ts": now,
        }
        self._pair_cache[symbol] = intel
        return dict(intel)

    def vet_signal(self, symbol: str, tech_score: float) -> Tuple[bool, str]:
        """
        Advisory signal review for tests/manual audits.
        This must not be used as a blocking network call in the live hot path.
        """
        if tech_score < 0.60:
            return False, "technical_score_too_weak"

        intel = self.get_market_intel(symbol)
        if not intel.get("listed_on_indodax"):
            return False, "symbol_not_listed_on_indodax"

        quote_volume = self._safe_float(intel.get("quote_volume_usdt"))
        if quote_volume <= 0:
            return False, "missing_or_zero_quote_volume"

        research = intel.get("external_research") if isinstance(intel.get("external_research"), dict) else {}
        risk_bias = str(research.get("risk_bias") or "UNKNOWN")
        if risk_bias == "RISK_OFF" and tech_score < 0.75:
            return False, "external_research_risk_off"

        return True, "brain_advisory_ok"

    def think(
        self,
        watch_symbols: Optional[Iterable[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Background connectivity / research pulse.
        Safe to run in a background thread with short network timeouts.
        """
        context = context or {}
        symbols = self._normalize_symbols(watch_symbols or self._default_watch_symbols())[: self.max_watch_symbols]
        market_pulse = self._get_market_pulse(symbols)
        polymarket_snapshot = self._get_polymarket_snapshot()
        world_model = self._build_world_model(symbols, market_pulse, polymarket_snapshot, context)
        snapshot = {
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mode": "sovereign_support",
            "provider_status": self._provider_status(),
            "ai_legion": self._ai_legion_status(),
            "optional_modules": self._optional_modules(),
            "brain_capabilities": {
                "world_model_active": bool(world_model),
                "external_research_enabled": self.external_research_enabled,
                "ai_coordinator_enabled": self.ai_coordinator_enabled,
            },
            "internet_checks": {
                "binance": self._status_code("https://api.binance.com/api/v3/ping"),
                "bybit": self._status_code("https://api.bybit.com/v5/market/tickers?category=spot"),
                "kucoin": self._status_code("https://api.kucoin.com/api/v1/market/allTickers"),
                "mexc": self._status_code("https://api.mexc.com/api/v3/ticker/24hr"),
                "indodax": self._status_code("https://indodax.com/api/pairs"),
            },
            "daily_target": self._daily_target_snapshot(context),
            "market_pulse": market_pulse,
            "polymarket": polymarket_snapshot,
            "fear_greed": self._get_fear_greed_index(),
            "funding_rate": self._get_binance_funding_rate(),
            "stablecoin_flow": self._get_stablecoin_flow(),
            "world_model": world_model,
            "watch_symbols": symbols,
            "watch_reviews": [],
        }
        snapshot["ai_critic"] = self._get_ai_critic(symbols, market_pulse, world_model, context)
        for symbol in symbols[: self.max_external_symbols]:
            intel = self.get_market_intel(symbol)
            approved, reason = self.vet_signal(symbol, 0.70)
            research = intel.get("external_research") if isinstance(intel.get("external_research"), dict) else {}
            watch_review = {
                "symbol": symbol,
                "approved": approved,
                "reason": reason,
                "listed_on_indodax": bool(intel.get("listed_on_indodax")),
                "quote_volume_usdt": round(self._safe_float(intel.get("quote_volume_usdt")), 2),
                "risk_bias": str(research.get("risk_bias") or "UNKNOWN"),
                "research_provider": str(research.get("provider") or "none"),
                "research_summary": str(research.get("summary") or "")[:280],
                "headline_count": len(list(research.get("headlines") or [])),
                "top_headlines": list(research.get("headlines") or [])[:3],
            }
            snapshot["watch_reviews"].append(watch_review)

        self._last_snapshot = snapshot
        self._write_snapshot(snapshot)
        return dict(snapshot)

    def snapshot(self) -> Dict[str, Any]:
        if getattr(self, "_last_snapshot", None):
            return dict(self._last_snapshot)
        self._last_snapshot = self._load_snapshot()
        return dict(self._last_snapshot)

    def refresh(self) -> Dict[str, Any]:
        """Force a deep refresh of all world intelligence models."""
        # This normally runs in its own thread in kibot_manager or via maintenance
        symbols = list(self.binance_symbol_allowlist)[:self.max_watch_symbols]
        market_pulse = self._get_market_pulse(symbols)
        polymarket_snapshot = self._get_polymarket_snapshot()
        world_model = self._build_world_model(symbols, market_pulse, polymarket_snapshot, "FORCED_REFRESH")
        ai_critic = self._get_ai_critic(symbols, market_pulse, world_model, "FORCED_REFRESH")
        
        snapshot = {
            "at_epoch": time.time(),
            "market_pulse": market_pulse,
            "polymarket": polymarket_snapshot,
            "world_model": world_model,
            "ai_critic": ai_critic
        }
        self._last_snapshot = snapshot
        self._save_snapshot(snapshot)
        return snapshot

    def snapshot_age_sec(self) -> Optional[float]:
        snapshot = self.snapshot()
        checked_at = str(snapshot.get("checked_at") or "").strip()
        if not checked_at:
            return None
        try:
            ts = time.strptime(checked_at, "%Y-%m-%dT%H:%M:%SZ")
            return max(0.0, time.time() - calendar.timegm(ts))
        except Exception:
            return None

    def ensure_warm(
        self,
        watch_symbols: Optional[Iterable[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        age = self.snapshot_age_sec()
        stale_after = max(60, int(self.market_pulse_ttl_sec))
        if age is not None and age < stale_after:
            return False
        with self._refresh_lock:
            if self._refresh_in_flight:
                return False
            self._refresh_in_flight = True

        def worker() -> None:
            try:
                self.think(watch_symbols=watch_symbols, context=context)
            except Exception as error:
                logger.warning("Brain async warm failed: %s", error)
            finally:
                with self._refresh_lock:
                    self._refresh_in_flight = False

        threading.Thread(target=worker, name="kibot-brain-warm", daemon=True).start()
        return True

    def _get_market_pulse(self, symbols: Sequence[str]) -> Dict[str, Any]:
        def loader() -> Dict[str, Any]:
            finnhub_news = self._get_finnhub_crypto_news()
            tavily_brief = self._get_tavily_market_brief()
            serper_brief = self._get_serper_market_brief() if not tavily_brief else {}
            ddg_brief = self._get_ddg_market_brief()

            top_headlines: List[str] = []
            for row in finnhub_news[:6]:
                if isinstance(row, dict):
                    headline = str(row.get("headline") or "").strip()
                    if headline:
                        top_headlines.append(headline)
            if tavily_brief.get("answer"):
                top_headlines.append(str(tavily_brief.get("answer")).strip())
            for item in list(tavily_brief.get("results") or [])[:2]:
                if isinstance(item, dict):
                    headline = str(item.get("title") or "").strip()
                    if headline:
                        top_headlines.append(headline)
            for item in list(serper_brief.get("organic") or [])[:2]:
                if isinstance(item, dict):
                    headline = str(item.get("title") or "").strip()
                    if headline:
                        top_headlines.append(headline)
            for item in list(ddg_brief.get("results") or [])[:2]:
                if isinstance(item, dict):
                    headline = str(item.get("title") or item.get("content") or "").strip()
                    if headline:
                        top_headlines.append(headline)

            deduped_headlines = self._dedupe_texts(top_headlines)[:5]
            positive_hits, negative_hits = self._sentiment_counts(deduped_headlines)
            if negative_hits > positive_hits + 1:
                risk_bias = "RISK_OFF"
            elif positive_hits > negative_hits + 1:
                risk_bias = "RISK_ON"
            else:
                risk_bias = "MIXED"

            summary = ""
            if tavily_brief.get("answer"):
                summary = str(tavily_brief.get("answer")).strip()
            elif serper_brief.get("organic"):
                first = serper_brief.get("organic")[0]
                if isinstance(first, dict):
                    summary = str(first.get("snippet") or first.get("title") or "").strip()
            if deduped_headlines:
                summary = deduped_headlines[0]

            # --- Sovereign Integration: Pulse Override ---
            sentiment_file = ROOT_DIR /  "Data/State/sentiment_pulse.json"
            sentiment_score = 0.5
            if sentiment_file.exists():
                try:
                    pulse = json.loads(sentiment_file.read_text())
                    risk_bias = pulse.get("global_bias", risk_bias)
                    sentiment_score = pulse.get("fear_greed_index", 0.5)
                except:
                    pass

            return {
                "risk_bias": risk_bias,
                "sentiment_score": sentiment_score,
                "headline_count": len(finnhub_news),
                "top_headlines": deduped_headlines,
                "summary": summary[:320],
                "providers_used": [name for name, used in {
                    "finnhub": bool(finnhub_news),
                    "tavily": bool(tavily_brief),
                    "serper": bool(serper_brief),
                    "ddg": bool(ddg_brief),
                }.items() if used],
                "watch_symbols": list(symbols)[: self.max_external_symbols],
            }

        return self._cached_payload("market_pulse", self.market_pulse_ttl_sec, loader)

    def _extract_text_from_gemini_response(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first.get("content"), dict) else {}
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            return ""
        first_part = parts[0] if isinstance(parts[0], dict) else {}
        text = first_part.get("text")
        return str(text or "").strip()

    def _safe_json_from_text(self, text: str) -> Dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
            raw = raw[:-3].strip() if raw.endswith("```") else raw
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _get_ai_critic(
        self,
        symbols: Sequence[str],
        market_pulse: Dict[str, Any],
        world_model: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.external_research_enabled:
            return {}
        risk_bias = str(market_pulse.get("risk_bias") or "UNKNOWN").upper()
        daily_pnl = f"{self._safe_float(context.get('daily_pnl_pct')):.4f}"
        cache_key = f"ai_critic:{risk_bias}:{daily_pnl}:{'-'.join(list(symbols)[:3])}"
        daily_target = self._daily_target_snapshot(context)
        polymarket = self._get_polymarket_snapshot()
        critic_context = {
            "watch_symbols": list(symbols)[:3],
            "market_pulse": {
                "risk_bias": market_pulse.get("risk_bias"),
                "headline_count": int(market_pulse.get("headline_count") or 0),
                "top_headlines": list(market_pulse.get("top_headlines") or [])[:3],
                "summary": str(market_pulse.get("summary") or "")[:240],
                "watch_symbols": list(market_pulse.get("watch_symbols") or [])[:3],
            },
            "daily_target": {
                "status": daily_target.get("status"),
                "gap_pct": daily_target.get("gap_pct"),
                "strategy_next": daily_target.get("strategy_next"),
                "capital_profile": (
                    {
                        "mode": (daily_target.get("capital_profile") or {}).get("mode"),
                        "reason": (daily_target.get("capital_profile") or {}).get("reason"),
                        "trading_allowed": (daily_target.get("capital_profile") or {}).get("trading_allowed"),
                        "max_position_idr": (daily_target.get("capital_profile") or {}).get("max_position_idr"),
                        "daily_loss_limit_pct": (daily_target.get("capital_profile") or {}).get("daily_loss_limit_pct"),
                    }
                    if isinstance(daily_target.get("capital_profile"), dict)
                    else {}
                ),
            },
            "capital_profile": {
                "mode": (context.get("capital_profile") or {}).get("mode"),
                "reason": (context.get("capital_profile") or {}).get("reason"),
                "trading_allowed": (context.get("capital_profile") or {}).get("trading_allowed"),
                "max_position_idr": (context.get("capital_profile") or {}).get("max_position_idr"),
                "daily_loss_limit_pct": (context.get("capital_profile") or {}).get("daily_loss_limit_pct"),
            },
            "polymarket": {
                "ready": polymarket.get("ready"),
                "analysis_ready": polymarket.get("analysis_ready"),
                "execution_enabled": polymarket.get("execution_enabled"),
                "blocked": (polymarket.get("geoblock") or {}).get("blocked") if isinstance(polymarket.get("geoblock"), dict) else None,
                "country": (polymarket.get("geoblock") or {}).get("country") if isinstance(polymarket.get("geoblock"), dict) else None,
                "top_opportunities": [
                    {
                        "slug": item.get("slug"),
                        "spread": item.get("spread"),
                        "liquidity": item.get("liquidity"),
                    }
                    for item in list(polymarket.get("top_opportunities") or [])[:3]
                    if isinstance(item, dict)
                ],
                "maker_candidates": [
                    {
                        "slug": item.get("slug"),
                        "maker_score": item.get("maker_score"),
                        "execution_style": item.get("execution_style"),
                    }
                    for item in list(polymarket.get("maker_candidates") or [])[:2]
                    if isinstance(item, dict)
                ],
                "cross_market_bias": polymarket.get("cross_market_bias") if isinstance(polymarket.get("cross_market_bias"), dict) else {},
                "ops_alerts": list(polymarket.get("ops_alerts") or [])[:3],
            },
            "world_model": self._world_model_for_prompt(world_model),
        }

        def loader() -> Dict[str, Any]:
            if self.ai_coordinator_enabled and _coordinator_query_ai_debate_fn is not None:
                critic = _coordinator_query_ai_debate_fn(
                    "BRAIN_CRITIC",
                    critic_context,
                    cache_ttl_minutes=max(1, int(self.gemini_ttl_sec / 60)),
                )
                if isinstance(critic, dict) and critic:
                    return critic

            if not self._gemini_api_key():
                return {}
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    "You are a Trading Committee consisting of three expert personas:\n"
                                    "1. **Macro Analyst**: Evaluates global sentiment, headline risk, and risk-on/off bias.\n"
                                    "2. **Chart Technician**: Evaluates local price action, market regimes (trends vs chop), and liquidity.\n"
                                    "3. **Sovereign Arbitrator**: Reviews reports from both analysts to provide a final decision.\n\n"
                                    "Your goal is to provide a unified posture. Return compact JSON only with keys:\n"
                                    "{\"capital_posture\":\"DEFENSIVE|NEUTRAL|OPPORTUNISTIC\","
                                    "\"risk_bias\":\"RISK_OFF|MIXED|RISK_ON\","
                                    "\"confidence\":0.0,"
                                    "\"reasoning\":\"[Arbitrator Summary]: <Analyst findings> + <Technician findings> = <Final Verdict>\","
                                    "\"strategy_next\":\"One sentence action plan\","
                                    "\"focus_symbols\":[...],"
                                    "\"do_not_do\":[...]}"
                                    "\n\nContext:\n"
                                    f"- watch_symbols: {json.dumps(critic_context.get('watch_symbols'), ensure_ascii=False)}\n"
                                    f"- market_pulse: {json.dumps(critic_context.get('market_pulse'), ensure_ascii=False)}\n"
                                    f"- daily_target: {json.dumps(critic_context.get('daily_target'), ensure_ascii=False)}\n"
                                    f"- capital_profile: {json.dumps(critic_context.get('capital_profile'), ensure_ascii=False)}\n"
                                    f"- polymarket: {json.dumps(critic_context.get('polymarket'), ensure_ascii=False)}\n"
                                    f"- world_model: {json.dumps(critic_context.get('world_model'), ensure_ascii=False)}\n"
                                    "Rules:\n"
                                    "- Be extremely strict. Reject signals if Analyst and Technician disagree.\n"
                                    "- If news is negative but chart is bullish, prioritize news (Analyst Veto).\n"
                                    "- strategy_next must be actionable for a bot.\n"
                                )
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 450,
                    "responseMimeType": "application/json",
                },
            }
            base = os.getenv("GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
            api_key = self._gemini_api_key()
            url = f"{base}/models/{self.gemini_model}:generateContent"
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                    "User-Agent": "KiBot-Brain/1.0",
                },
            )
            with urlopen(request, timeout=max(self.request_timeout)) as response:
                raw = json.loads(response.read().decode("utf-8"))
            text = self._extract_text_from_gemini_response(raw)
            critic = self._safe_json_from_text(text)
            if critic:
                critic["provider"] = "gemini"
                critic["model"] = self.gemini_model
            return critic

        return self._cached_payload(cache_key, self.gemini_ttl_sec, loader)

    def _symbol_external_intel(self, symbol: str) -> Dict[str, Any]:
        def loader() -> Dict[str, Any]:
            news_hits = self._filter_news_for_symbol(symbol, self._get_finnhub_crypto_news())
            tavily_brief = self._get_tavily_symbol_brief(symbol)
            serper_brief = self._get_serper_symbol_brief(symbol) if not tavily_brief else {}
            ddg_brief = self._get_ddg_symbol_brief(symbol)

            texts: List[str] = []
            headlines = []
            for row in news_hits[:4]:
                headline = str(row.get("headline") or "").strip()
                if headline:
                    headlines.append(headline)
                    texts.append(headline)
                summary = str(row.get("summary") or "").strip()
                if summary:
                    texts.append(summary)
            if tavily_brief.get("answer"):
                texts.append(str(tavily_brief.get("answer")).strip())
            for item in list(tavily_brief.get("results") or [])[:2]:
                if isinstance(item, dict):
                    title = str(item.get("title") or "").strip()
                    content = str(item.get("content") or "").strip()
                    if title:
                        headlines.append(title)
                        texts.append(title)
                    if content:
                        texts.append(content)
            for item in list(serper_brief.get("organic") or [])[:2]:
                if isinstance(item, dict):
                    title = str(item.get("title") or "").strip()
                    snippet = str(item.get("snippet") or "").strip()
                    if title:
                        headlines.append(title)
                        texts.append(title)
                    if snippet:
                        texts.append(snippet)
            for item in list(ddg_brief.get("results") or [])[:2]:
                if isinstance(item, dict):
                    title = str(item.get("title") or "").strip()
                    snippet = str(item.get("content") or "").strip()
                    if title:
                        headlines.append(title)
                        texts.append(title)
                    if snippet:
                        texts.append(snippet)

            positive_hits, negative_hits = self._sentiment_counts(texts)
            if negative_hits > positive_hits + 1:
                risk_bias = "RISK_OFF"
            elif positive_hits > negative_hits + 1:
                risk_bias = "RISK_ON"
            else:
                risk_bias = "MIXED"

            summary = ""
            provider = "finnhub"
            if tavily_brief.get("answer"):
                summary = str(tavily_brief.get("answer")).strip()
                provider = "tavily"
            elif serper_brief.get("organic"):
                first = serper_brief.get("organic")[0]
                if isinstance(first, dict):
                    summary = str(first.get("snippet") or first.get("title") or "").strip()
                    provider = "serper"
            elif ddg_brief.get("results"):
                first = ddg_brief.get("results")[0]
                if isinstance(first, dict):
                    summary = str(first.get("content") or first.get("title") or "").strip()
                    provider = "ddg"
            elif headlines:
                summary = headlines[0]

            return {
                "provider": provider,
                "risk_bias": risk_bias,
                "headlines": self._dedupe_texts(headlines)[:3],
                "summary": summary[:320],
                "news_hit_count": len(news_hits),
            }

        return self._cached_payload(f"symbol_external:{symbol}", self.review_ttl_sec, loader)

    def _x_bearer_token(self) -> str:
        return (
            os.getenv("KIBOT_X_BEARER_TOKEN")
            or os.getenv("X_BEARER_TOKEN")
            or os.getenv("TWITTER_BEARER_TOKEN")
            or ""
        ).strip()

    def _coingecko_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        api_key = (
            os.getenv("KIBOT_COINGECKO_API_KEY")
            or os.getenv("COINGECKO_PRO_API_KEY")
            or os.getenv("COINGECKO_API_KEY")
            or ""
        ).strip()
        demo_key = os.getenv("COINGECKO_DEMO_API_KEY", "").strip()
        if api_key:
            headers["x-cg-pro-api-key"] = api_key
        elif demo_key:
            headers["x-cg-demo-api-key"] = demo_key
        return headers

    def _get_x_market_brief(self) -> Dict[str, Any]:
        if not self.external_research_enabled or not self._x_bearer_token():
            return {}

        def loader() -> Dict[str, Any]:
            query = os.getenv(
                "KIBOT_BRAIN_X_QUERY",
                "(bitcoin OR btc OR ethereum OR eth OR solana OR sol OR xrp OR doge OR altcoin OR memecoin) "
                "(etf OR inflow OR outflow OR listing OR launch OR exploit OR hack OR regulation) "
                "-is:retweet -is:reply",
            )
            payload = self._get_json(
                "https://api.x.com/2/tweets/search/recent",
                params={
                    "query": query,
                    "max_results": 10,
                    "tweet.fields": "created_at,public_metrics,author_id",
                },
                headers={"Authorization": f"Bearer {self._x_bearer_token()}"},
            )
            rows = []
            for item in list(payload.get("data") or [])[:10]:
                if not isinstance(item, dict):
                    continue
                metrics = item.get("public_metrics") if isinstance(item.get("public_metrics"), dict) else {}
                engagement = sum(
                    int(metrics.get(name) or 0)
                    for name in ("like_count", "retweet_count", "reply_count", "quote_count")
                )
                rows.append(
                    {
                        "text": str(item.get("text") or "").strip(),
                        "created_at": str(item.get("created_at") or ""),
                        "engagement": engagement,
                    }
                )
            return {
                "query": query,
                "meta": payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
                "results": rows,
            }

        return self._cached_payload("x_market", self.x_ttl_sec, loader)

    def _get_gdelt_market_brief(self) -> Dict[str, Any]:
        if not self.external_research_enabled or not self.gdelt_enabled:
            return {}

        def loader() -> Dict[str, Any]:
            payload = self._get_json(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": os.getenv(
                        "KIBOT_BRAIN_GDELT_QUERY",
                        '("bitcoin" OR "ethereum" OR "solana" OR "altcoin" OR "crypto") '
                        '("etf" OR "listing" OR "regulation" OR "exploit" OR "hack" OR "treasury")',
                    ),
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": 5,
                    "sort": "datedesc",
                    "timespan": os.getenv("KIBOT_BRAIN_GDELT_TIMESPAN", "3days"),
                },
                timeout=float(os.getenv("KIBOT_BRAIN_GDELT_TIMEOUT_SEC", "4")),
            )
            articles = payload.get("articles") if isinstance(payload, dict) else []
            normalized = []
            for item in list(articles or [])[:8]:
                if not isinstance(item, dict):
                    continue
                normalized.append(
                    {
                        "title": str(item.get("title") or "").strip(),
                        "domain": str(item.get("domain") or "").strip(),
                        "language": str(item.get("language") or "").strip(),
                        "sourcecountry": str(item.get("sourcecountry") or "").strip(),
                        "seendate": str(item.get("seendate") or "").strip(),
                    }
                )
            return {"articles": normalized}

        return self._cached_payload("gdelt_market", self.gdelt_ttl_sec, loader)

    def _get_coingecko_trending(self) -> Dict[str, Any]:
        if not self.external_research_enabled:
            return {}

        def loader() -> Dict[str, Any]:
            payload = self._get_json(
                "https://api.coingecko.com/api/v3/search/trending",
                headers=self._coingecko_headers(),
                timeout=float(os.getenv("KIBOT_BRAIN_COINGECKO_TIMEOUT_SEC", "5")),
            )
            return payload if isinstance(payload, dict) else {}

        return self._cached_payload("coingecko_trending", self.coingecko_ttl_sec, loader)

    def _world_model_for_prompt(self, world_model: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(world_model, dict):
            return {}
        return {
            "market_regime": str(world_model.get("market_regime") or ""),
            "confidence": round(self._safe_float(world_model.get("confidence")), 4),
            "summary": str(world_model.get("summary") or "")[:240],
            "narratives": list(world_model.get("global_narratives") or [])[:3],
            "opportunities": [
                {
                    "pair": item.get("pair"),
                    "kind": item.get("kind"),
                    "score": round(self._safe_float(item.get("score")), 4),
                    "thesis": str(item.get("thesis") or "")[:120],
                }
                for item in list(world_model.get("opportunity_register") or [])[:3]
                if isinstance(item, dict)
            ],
            "risks": [
                {
                    "severity": str(item.get("severity") or ""),
                    "summary": str(item.get("summary") or "")[:120],
                }
                for item in list(world_model.get("risk_register") or [])[:3]
                if isinstance(item, dict)
            ],
            "micro_capital_plan": world_model.get("micro_capital_plan") if isinstance(world_model.get("micro_capital_plan"), dict) else {},
            "fear_greed": world_model.get("fear_greed") if isinstance(world_model.get("fear_greed"), dict) else {},
            "funding_rate": {
                "aggregate_signal": (world_model.get("funding_rate") or {}).get("aggregate_signal"),
                "overleveraged_long_count": (world_model.get("funding_rate") or {}).get("overleveraged_long_count"),
            } if isinstance(world_model.get("funding_rate"), dict) else {},
            "stablecoin_flow": {
                "flow_signal": (world_model.get("stablecoin_flow") or {}).get("flow_signal"),
                "market_cap_change_24h_pct": (world_model.get("stablecoin_flow") or {}).get("market_cap_change_24h_pct"),
            } if isinstance(world_model.get("stablecoin_flow"), dict) else {},
            "source_status": world_model.get("source_status") if isinstance(world_model.get("source_status"), dict) else {},
            "source_weighting": world_model.get("source_weighting") if isinstance(world_model.get("source_weighting"), dict) else {},
        }

    def _extract_assets_from_text(
        self,
        text: str,
        *,
        extra_candidates: Optional[Iterable[str]] = None,
    ) -> List[str]:
        upper = str(text or "").upper()
        if not upper:
            return []
        candidates = set(KNOWN_CRYPTO_ASSETS)
        if extra_candidates:
            candidates.update(str(item).upper().strip() for item in extra_candidates if str(item).strip())
        out: List[str] = []
        for asset in sorted(candidates, key=len, reverse=True):
            if re.search(rf"\b{re.escape(asset)}\b", upper):
                out.append(asset)
        return out[:4]

    def _asset_to_pair(self, asset: str) -> str:
        cleaned = str(asset or "").strip().lower()
        return f"{cleaned}_idr" if cleaned else ""

    def _build_world_model(
        self,
        symbols: Sequence[str],
        market_pulse: Dict[str, Any],
        polymarket: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.world_model_enabled:
            return {}
        daily_target = self._daily_target_snapshot(context)
        capital_profile = context.get("capital_profile") if isinstance(context.get("capital_profile"), dict) else {}
        risk_bias = str(market_pulse.get("risk_bias") or "UNKNOWN").upper()
        cache_key = (
            f"world_model:{risk_bias}:{str(capital_profile.get('mode') or 'UNKNOWN').upper()}:"
            f"{'-'.join(list(symbols)[:3])}"
        )

        def loader() -> Dict[str, Any]:
            x_brief = self._get_x_market_brief()
            gdelt_brief = self._get_gdelt_market_brief()
            coingecko_trending = self._get_coingecko_trending()
            fear_greed = self._get_fear_greed_index()
            funding_rate = self._get_binance_funding_rate()
            stablecoin_flow = self._get_stablecoin_flow()
            provider_status = self._provider_status()
            external_world = self._load_external_world_model()

            source_names = set(str(item) for item in list(market_pulse.get("providers_used") or []) if str(item).strip())
            if x_brief:
                source_names.add("x")
            if gdelt_brief:
                source_names.add("gdelt")
            if coingecko_trending:
                source_names.add("coingecko")
            if fear_greed:
                source_names.add("fear_greed")
            if funding_rate:
                source_names.add("funding_rate")
            if stablecoin_flow:
                source_names.add("stablecoin_flow")

            source_weight_map = {
                "polymarket": 0.24,
                "finnhub": 0.18,
                "coingecko": 0.14,
                "funding_rate": 0.12,
                "fear_greed": 0.10,
                "x": 0.10,
                "stablecoin_flow": 0.06,
                "gdelt": 0.06,
                "tavily": 0.05,
                "serper": 0.04,
                "ddg": 0.03,
            }
            source_weights = {
                name: round(float(source_weight_map.get(name, 0.03)), 4)
                for name in sorted(source_names)
            }
            source_weight_score = round(min(1.0, sum(source_weights.values())), 4)
            source_category_scores = {
                "market_execution": round(
                    sum(source_weights.get(name, 0.0) for name in ("polymarket", "coingecko", "finnhub")),
                    4,
                ),
                "news_research": round(
                    sum(source_weights.get(name, 0.0) for name in ("x", "gdelt", "tavily", "serper", "ddg")),
                    4,
                ),
            }

            narratives = self._dedupe_texts(
                list(market_pulse.get("top_headlines") or [])
                + [str(item.get("text") or "") for item in list(x_brief.get("results") or [])[:2] if isinstance(item, dict)]
                + [str(item.get("title") or "") for item in list(gdelt_brief.get("articles") or [])[:2] if isinstance(item, dict)]
                + ([str(external_world.get("intelligence", {}).get("summary", ""))] if external_world.get("intelligence") else [])
            )[:4]

            event_rows: List[Dict[str, Any]] = []
            for headline in list(market_pulse.get("top_headlines") or [])[:2]:
                assets = self._extract_assets_from_text(headline, extra_candidates=symbols)
                event_rows.append(
                    {
                        "source": "market_pulse",
                        "headline": str(headline)[:160],
                        "impact": "BULLISH" if risk_bias == "RISK_ON" else "MIXED" if risk_bias == "MIXED" else "BEARISH",
                        "assets": assets,
                    }
                )
            for item in list(x_brief.get("results") or [])[:2]:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                assets = self._extract_assets_from_text(text, extra_candidates=symbols)
                pos_hits, neg_hits = self._sentiment_counts([text])
                impact = "BULLISH" if pos_hits > neg_hits else "BEARISH" if neg_hits > pos_hits else "MIXED"
                event_rows.append(
                    {
                        "source": "x",
                        "headline": text[:160],
                        "impact": impact,
                        "assets": assets,
                        "engagement": int(item.get("engagement") or 0),
                    }
                )
            for item in list(gdelt_brief.get("articles") or [])[:2]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                pos_hits, neg_hits = self._sentiment_counts([title])
                impact = "BULLISH" if pos_hits > neg_hits else "BEARISH" if neg_hits > pos_hits else "MIXED"
                event_rows.append(
                    {
                        "source": "gdelt",
                        "headline": title[:160],
                        "impact": impact,
                        "assets": self._extract_assets_from_text(title, extra_candidates=symbols),
                    }
                )
            event_rows = event_rows[: self.max_world_events]

            opportunity_map: Dict[str, Dict[str, Any]] = {}

            def register_opportunity(item: Dict[str, Any]) -> None:
                pair = str(item.get("pair") or "").lower().strip()
                if not pair:
                    return
                existing = opportunity_map.get(pair)
                if existing is None or self._safe_float(item.get("score")) > self._safe_float(existing.get("score")):
                    opportunity_map[pair] = item

            for symbol in list(symbols)[: self.max_external_symbols]:
                intel = self.get_market_intel(symbol)
                research = intel.get("external_research") if isinstance(intel.get("external_research"), dict) else {}
                if not bool(intel.get("listed_on_indodax")):
                    continue
                opportunity_score = 0.52
                if risk_bias == "RISK_ON":
                    opportunity_score += 0.10
                if str(research.get("risk_bias") or "").upper() == "RISK_ON":
                    opportunity_score += 0.08
                if self._safe_float(intel.get("quote_volume_usdt")) >= 5_000_000:
                    opportunity_score += 0.06
                register_opportunity(
                    {
                        "pair": self._asset_to_pair(symbol),
                        "symbol": symbol,
                        "kind": "watch_symbol",
                        "score": min(0.88, round(opportunity_score, 4)),
                        "thesis": str(research.get("summary") or market_pulse.get("summary") or "watch symbol aligned")[:140],
                        "budget_hint_idr": float(capital_profile.get("max_position_idr") or 0.0),
                    }
                )

            trending_coins = []
            for row in list(coingecko_trending.get("coins") or [])[:3]:
                item = row.get("item") if isinstance(row, dict) and isinstance(row.get("item"), dict) else {}
                if item:
                    trending_coins.append(item)
            for item in trending_coins:
                symbol = str(item.get("symbol") or "").upper().strip()
                if not symbol:
                    continue
                intel = self.get_market_intel(symbol)
                if not bool(intel.get("listed_on_indodax")):
                    continue
                price_change = self._safe_float((((item.get("data") or {}).get("price_change_percentage_24h") or {}).get("usd")))
                score = 0.55
                if price_change > 0:
                    score += 0.05
                if risk_bias == "RISK_ON":
                    score += 0.06
                register_opportunity(
                    {
                        "pair": self._asset_to_pair(symbol),
                        "symbol": symbol,
                        "kind": "coingecko_trending",
                        "score": min(0.87, round(score, 4)),
                        "thesis": f"{symbol} trending on CoinGecko search with live interest",
                        "budget_hint_idr": float(capital_profile.get("max_position_idr") or 0.0),
                    }
                )

            for item in list(polymarket.get("alpha_candidates") or [])[:3]:
                if not isinstance(item, dict):
                    continue
                pair = str(item.get("mapped_pair") or "").lower().strip()
                if not pair:
                    continue
                score = 0.56 + (self._safe_float(item.get("alpha_score")) * 0.28) + (self._safe_float(item.get("signal_score")) * 0.12)
                register_opportunity(
                    {
                        "pair": pair,
                        "symbol": str(item.get("asset") or "").upper().strip(),
                        "kind": "polymarket_alpha",
                        "score": min(0.92, round(score, 4)),
                        "thesis": f"Polymarket bias {str(item.get('direction') or 'mixed').lower()} feeding cross-market signal",
                        "budget_hint_idr": float(capital_profile.get("max_position_idr") or 0.0),
                    }
                )

            opportunities = sorted(
                opportunity_map.values(),
                key=lambda item: self._safe_float(item.get("score")),
                reverse=True,
            )[: self.max_world_opportunities]

            # Merge external possibilities from WorldScout
            if external_world.get("possibility_matrix"):
                for item in list(external_world["possibility_matrix"])[:2]:
                    if not isinstance(item, dict): continue
                    opportunities.append({
                        "pair": item.get("pair") or "UNKNOWN",
                        "kind": "world_scout_possibility",
                        "score": round(self._safe_float(item.get("confidence", 0.75)), 4),
                        "thesis": str(item.get("reasoning") or "WorldScout identified catalyst")[:140]
                    })

            risk_register: List[Dict[str, Any]] = []
            if risk_bias == "RISK_OFF":
                risk_register.append(
                    {
                        "severity": "HIGH",
                        "summary": "world model sees external risk-off conditions",
                        "assets": [],
                    }
                )
            # Fear & Greed risk signals
            fg_value = int(fear_greed.get("value") or 50)
            if fg_value >= 80:
                risk_register.append(
                    {
                        "severity": "HIGH",
                        "summary": f"extreme greed ({fg_value}) — market overheated, reduce exposure",
                        "assets": [],
                    }
                )
            elif fg_value <= 20:
                risk_register.append(
                    {
                        "severity": "INFO",
                        "summary": f"extreme fear ({fg_value}) — contrarian opportunity window",
                        "assets": [],
                    }
                )
            # Funding rate risk signals
            fr_aggregate = str(funding_rate.get("aggregate_signal") or "")
            if fr_aggregate == "LIQUIDATION_RISK_LONG":
                risk_register.append(
                    {
                        "severity": "HIGH",
                        "summary": "overleveraged longs detected — liquidation cascade risk",
                        "assets": ["BTC", "ETH"],
                    }
                )
            elif fr_aggregate == "SHORT_SQUEEZE_POTENTIAL":
                risk_register.append(
                    {
                        "severity": "INFO",
                        "summary": "overleveraged shorts — short squeeze potential",
                        "assets": ["BTC", "ETH"],
                    }
                )
            # Stablecoin flow risk signals
            sc_flow = str(stablecoin_flow.get("flow_signal") or "")
            if sc_flow == "STRONG_OUTFLOW":
                risk_register.append(
                    {
                        "severity": "WARNING",
                        "summary": f"strong capital outflow ({stablecoin_flow.get('market_cap_change_24h_pct', 0):.1f}% 24h) — macro bearish",
                        "assets": [],
                    }
                )
            if not source_names:
                risk_register.append(
                    {
                        "severity": "HIGH",
                        "summary": "no external online source returned a usable payload",
                        "assets": [],
                    }
                )
            for alert in list(polymarket.get("ops_alerts") or [])[:3]:
                text = str(alert or "").strip()
                if not text:
                    continue
                risk_register.append(
                    {
                        "severity": "WARNING" if "low" in text.lower() else "INFO",
                        "summary": text[:160],
                        "assets": [],
                    }
                )
            ollama_status = provider_status.get("ollama") if isinstance(provider_status.get("ollama"), dict) else {}
            if ollama_status and not bool(ollama_status.get("available", True)):
                risk_register.append(
                    {
                        "severity": "WARNING",
                        "summary": f"ollama unavailable: {str(ollama_status.get('last_failure_reason') or 'cooldown')[:120]}",
                        "assets": [],
                    }
                )
            if not bool(capital_profile.get("trading_allowed", True)):
                risk_register.append(
                    {
                        "severity": "CRITICAL",
                        "summary": "capital profile currently blocks new entries",
                        "assets": [],
                    }
                )
            risk_register = risk_register[: self.max_world_events]

            free_cash_idr = self._safe_float(context.get("free_cash_idr") or daily_target.get("free_cash_idr"))
            max_position_idr = self._safe_float(capital_profile.get("max_position_idr"))
            min_position_idr = max(
                self._safe_float(capital_profile.get("min_position_idr")),
                10_000.0,
            )
            small_account = str(capital_profile.get("mode") or "").upper() in {"MICRO", "BUILDUP"}
            exploration_budget = max(
                min_position_idr,
                min(
                    max_position_idr if max_position_idr > 0 else free_cash_idr,
                    free_cash_idr * (0.22 if small_account else 0.28),
                ),
            ) if free_cash_idr > 0 else min_position_idr
            allow_exploration = (
                bool(capital_profile.get("trading_allowed", True))
                and risk_bias != "RISK_OFF"
                and free_cash_idr >= min_position_idr
                and bool(opportunities)
            )

            confidence = min(
                0.95,
                0.34
                + (0.05 * min(5, len(source_names)))
                + (0.12 * source_weight_score)
                + (0.03 * min(3, len(opportunities))),
            )
            summary_parts = []
            if narratives:
                summary_parts.append(narratives[0][:120])
            if opportunities:
                summary_parts.append(f"{len(opportunities)} opportunity lane(s) active")
            if risk_register:
                summary_parts.append(f"{len(risk_register)} active risk(s)")

            return {
                "version": 1,
                "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "market_regime": risk_bias if risk_bias in {"RISK_ON", "MIXED", "RISK_OFF"} else "UNKNOWN",
                "confidence": round(confidence, 4),
                "summary": " | ".join(summary_parts)[:320],
                "global_narratives": narratives,
                "external_events": event_rows,
                "opportunity_register": opportunities,
                "risk_register": risk_register,
                "internal_state": {
                    "capital_mode": str(capital_profile.get("mode") or "UNKNOWN"),
                    "trading_allowed": bool(capital_profile.get("trading_allowed", True)),
                    "free_cash_idr": round(free_cash_idr, 2),
                    "provider_count": len(source_names),
                    "polymarket_ready": bool(polymarket.get("ready")),
                    "analysis_ready": bool(polymarket.get("analysis_ready")),
                },
                "micro_capital_plan": {
                    "allow_exploration": allow_exploration,
                    "exploration_budget_idr": round(exploration_budget, 2),
                    "preferred_pairs": [str(item.get("pair") or "") for item in opportunities[:2]],
                    "max_concurrent_explorations": 1 if small_account else 2,
                    "notes": [
                        "stay selective and keep position sizing small",
                        "prefer liquid pairs with converging external and local signals",
                    ][: (2 if allow_exploration else 1)],
                },
                "fear_greed": fear_greed,
                "funding_rate": funding_rate,
                "stablecoin_flow": stablecoin_flow,
                "source_status": {
                    "providers_used": sorted(source_names),
                    "provider_count": len(source_names),
                    "x_hits": len(list(x_brief.get("results") or [])),
                    "gdelt_hits": len(list(gdelt_brief.get("articles") or [])),
                    "coingecko_trending_hits": len(list(coingecko_trending.get("coins") or [])),
                    "fear_greed_value": int(fear_greed.get("value") or 0),
                    "funding_rate_signal": str(funding_rate.get("aggregate_signal") or ""),
                    "stablecoin_flow_signal": str(stablecoin_flow.get("flow_signal") or ""),
                },
                "source_weighting": {
                    "weights": source_weights,
                    "score": source_weight_score,
                    "category_scores": source_category_scores,
                    "priority": sorted(source_weights.keys(), key=lambda name: source_weights.get(name, 0.0), reverse=True),
                },
            }

        return self._cached_payload(cache_key, self.world_model_ttl_sec, loader)

    def _get_tavily_market_brief(self) -> Dict[str, Any]:
        if not self.external_research_enabled or not self.ai_search:
            return {}
        return self.ai_search.tavily_search("crypto market today bitcoin altcoin risk catalysts regulation exploit exchange")

    def _get_tavily_symbol_brief(self, symbol: str) -> Dict[str, Any]:
        if not self.external_research_enabled or not self.ai_search:
            return {}
        return self.ai_search.tavily_search(f"{symbol} crypto latest news catalyst risk")

    def _get_serper_market_brief(self) -> Dict[str, Any]:
        if not self.external_research_enabled or not self.ai_search:
            return {}
        return self.ai_search.serper_search("crypto market today bitcoin altcoin risk catalysts")

    def _get_serper_symbol_brief(self, symbol: str) -> Dict[str, Any]:
        if not self.external_research_enabled or not self.ai_search:
            return {}
        return self.ai_search.serper_search(f"{symbol} crypto latest news catalyst risk")

    def _get_ddg_market_brief(self) -> Dict[str, Any]:
        if not self.external_research_enabled or not self.ai_search:
            return {}
        return {"results": self.ai_search.ddg_search("crypto market today bitcoin altcoin risk catalysts exchange exploit")}

    def _get_ddg_symbol_brief(self, symbol: str) -> Dict[str, Any]:
        if not self.external_research_enabled or not self.ai_search:
            return {}
        return {"results": self.ai_search.ddg_search(f"{symbol} crypto latest news catalyst risk")}

    def _get_finnhub_crypto_news(self) -> List[Dict[str, Any]]:
        if not self.external_research_enabled or not self.ai_search:
            return []
        return self.ai_search.finnhub_news("crypto")

    def _get_fear_greed_index(self) -> Dict[str, Any]:
        """Alternative.me Fear & Greed Index — free, no key needed."""
        if not self.external_research_enabled:
            return {}

        def loader() -> Dict[str, Any]:
            payload = self._get_json(
                "https://api.alternative.me/fng/",
                params={"limit": "1", "format": "json"},
                timeout=4.0,
            )
            if not isinstance(payload, dict):
                return {}
            data = list(payload.get("data") or [])
            if not data or not isinstance(data[0], dict):
                return {}
            entry = data[0]
            value = int(entry.get("value") or 0)
            classification = str(entry.get("value_classification") or "")
            # Map to capital posture hint
            if value <= 25:
                posture_hint = "OPPORTUNISTIC_BUY"
            elif value <= 40:
                posture_hint = "CAUTIOUS"
            elif value <= 60:
                posture_hint = "NEUTRAL"
            elif value <= 75:
                posture_hint = "TAKE_PROFIT"
            else:
                posture_hint = "EXTREME_GREED_DEFENSIVE"
            return {
                "value": value,
                "classification": classification,
                "posture_hint": posture_hint,
                "timestamp": str(entry.get("timestamp") or ""),
            }

        return self._cached_payload("fear_greed", self.fear_greed_ttl_sec, loader)

    def _get_binance_funding_rate(self) -> Dict[str, Any]:
        """Binance Futures funding rate + OI for BTC/ETH — free public API."""
        if not self.external_research_enabled:
            return {}

        def loader() -> Dict[str, Any]:
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            results: Dict[str, Any] = {}
            for symbol in symbols:
                try:
                    fr_data = self._get_json(
                        "https://fapi.binance.com/fapi/v1/fundingRate",
                        params={"symbol": symbol, "limit": "1"},
                        timeout=4.0,
                    )
                    oi_data = self._get_json(
                        "https://fapi.binance.com/fapi/v1/openInterest",
                        params={"symbol": symbol},
                        timeout=4.0,
                    )
                    funding_rate = 0.0
                    if isinstance(fr_data, list) and fr_data:
                        funding_rate = self._safe_float(fr_data[0].get("fundingRate"))
                    open_interest = self._safe_float(
                        oi_data.get("openInterest") if isinstance(oi_data, dict) else 0.0
                    )
                    # Interpretation
                    if funding_rate > 0.001:  # > 0.1% per 8h
                        leverage_bias = "OVERLEVERAGED_LONG"
                    elif funding_rate < -0.001:
                        leverage_bias = "OVERLEVERAGED_SHORT"
                    else:
                        leverage_bias = "NEUTRAL"
                    results[symbol] = {
                        "funding_rate": round(funding_rate, 6),
                        "funding_rate_pct_8h": round(funding_rate * 100, 4),
                        "open_interest": round(open_interest, 2),
                        "leverage_bias": leverage_bias,
                    }
                except Exception:
                    pass
            # Aggregate signal
            overleveraged_long = sum(
                1 for item in results.values()
                if item.get("leverage_bias") == "OVERLEVERAGED_LONG"
            )
            overleveraged_short = sum(
                1 for item in results.values()
                if item.get("leverage_bias") == "OVERLEVERAGED_SHORT"
            )
            if overleveraged_long >= 2:
                aggregate = "LIQUIDATION_RISK_LONG"
            elif overleveraged_short >= 2:
                aggregate = "SHORT_SQUEEZE_POTENTIAL"
            else:
                aggregate = "BALANCED"
            return {
                "symbols": results,
                "aggregate_signal": aggregate,
                "overleveraged_long_count": overleveraged_long,
                "overleveraged_short_count": overleveraged_short,
            }

        return self._cached_payload("funding_rate", self.funding_rate_ttl_sec, loader)

    def _get_stablecoin_flow(self) -> Dict[str, Any]:
        """Stablecoin market cap delta via CoinGecko — uses existing key."""
        if not self.external_research_enabled:
            return {}

        def loader() -> Dict[str, Any]:
            payload = self._get_json(
                "https://api.coingecko.com/api/v3/global",
                headers=self._coingecko_headers(),
                timeout=5.0,
            )
            if not isinstance(payload, dict):
                return {}
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            total_mcap = self._safe_float(data.get("total_market_cap", {}).get("usd"))
            total_volume = self._safe_float(data.get("total_volume", {}).get("usd"))
            mcap_change_24h = self._safe_float(data.get("market_cap_change_percentage_24h_usd"))
            # Liquidity signal interpretation
            if mcap_change_24h > 2.0:
                flow_signal = "STRONG_INFLOW"
            elif mcap_change_24h > 0.5:
                flow_signal = "MILD_INFLOW"
            elif mcap_change_24h > -0.5:
                flow_signal = "STABLE"
            elif mcap_change_24h > -2.0:
                flow_signal = "MILD_OUTFLOW"
            else:
                flow_signal = "STRONG_OUTFLOW"
            return {
                "total_market_cap_usd": round(total_mcap, 0),
                "total_volume_24h_usd": round(total_volume, 0),
                "market_cap_change_24h_pct": round(mcap_change_24h, 2),
                "flow_signal": flow_signal,
                "active_cryptocurrencies": int(data.get("active_cryptocurrencies") or 0),
            }

        return self._cached_payload("stablecoin_flow", self.stablecoin_flow_ttl_sec, loader)

    def _get_polymarket_snapshot(self) -> Dict[str, Any]:
        if not self.polymarket_state_url:
            return {}

        def loader() -> Dict[str, Any]:
            payload = self._request_json(self.polymarket_state_url)
            return payload if isinstance(payload, dict) else {}

        return self._cached_payload("polymarket_state", self.polymarket_ttl_sec, loader)

    def _provider_status(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for name, env_key in (
            ("tavily", "TAVILY_API_KEY"),
            ("serper", "SERPER_API_KEY"),
            ("finnhub", "FINNHUB_API_KEY"),
        ):
            last = self._provider_cache.get(name) or {}
            out[name] = {
                "configured": bool(os.getenv(env_key)),
                "last_ok": bool(last.get("ok")) if last else None,
                "last_checked_at": last.get("checked_at"),
                "last_error": last.get("error", ""),
            }

        ddg_last = self._provider_cache.get("ddg") or {}
        out["ddg"] = {
            "configured": self._has_ddg_client(),
            "last_ok": bool(ddg_last.get("ok")) if ddg_last else None,
            "last_checked_at": ddg_last.get("checked_at"),
            "last_error": ddg_last.get("error", ""),
        }

        coordinator_status = self._coordinator_provider_status()
        for name, detail in coordinator_status.items():
            if not isinstance(detail, dict):
                continue
            out[name] = {
                "configured": bool(detail.get("configured")),
                "model": str(detail.get("model") or ""),
                "priority": detail.get("priority"),
                "used": detail.get("used"),
                "remaining": detail.get("remaining"),
                "pct_used": detail.get("pct_used"),
                "last_ok": out.get(name, {}).get("last_ok"),
                "last_checked_at": out.get(name, {}).get("last_checked_at"),
                "last_error": out.get(name, {}).get("last_error", ""),
            }
        return out

    def _ai_legion_status(self) -> Dict[str, Any]:
        provider_status = self._provider_status()
        configured = [name for name, detail in provider_status.items() if bool(detail.get("configured"))]
        llm_providers = {
            name: detail for name, detail in provider_status.items()
            if name in {"ollama", "groq", "gemini", "openrouter", "cohere", "jina", "nvidia"}
        }
        search_providers = {
            name: detail for name, detail in provider_status.items()
            if name in {"tavily", "serper", "finnhub", "ddg"}
        }
        return {
            "configured_count": len(configured),
            "configured_names": configured,
            "llm_providers": llm_providers,
            "search_providers": search_providers,
            "coordinator_enabled": self.ai_coordinator_enabled,
        }

    def _daily_target_snapshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        daily_pnl_pct = self._safe_float(context.get("daily_pnl_pct"))
        target_gap_pct = max(self.green_target_daily_pct - daily_pnl_pct, 0.0)
        capital_profile = context.get("capital_profile") if isinstance(context.get("capital_profile"), dict) else {}
        if daily_pnl_pct >= self.green_target_daily_pct:
            status = "AHEAD"
        elif daily_pnl_pct >= 0.0:
            status = "CHASING_GREEN"
        else:
            status = "RECOVERY_MODE"
        mode = str(capital_profile.get("mode") or "UNKNOWN")
        if mode in {"MICRO", "BUILDUP"}:
            strategy = "Trade smaller, favor liquid high-trust pairs, and require cleaner scanner confirmation."
        elif mode == "RECOVERY":
            strategy = "Freeze aggressive rotation, demand strong veto alignment, and prioritize capital protection."
        elif mode == "EXPANSION":
            strategy = "Keep discipline, but allow normal rotation when scanner and local flow confirm."
        else:
            strategy = "Stay selective and let market pulse decide whether to press or wait."
        return {
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "target_pct": round(self.green_target_daily_pct, 4),
            "gap_pct": round(target_gap_pct, 4),
            "status": status,
            "equity_idr": self._safe_float(context.get("equity_idr")),
            "free_cash_idr": self._safe_float(context.get("free_cash_idr")),
            "capital_profile": capital_profile,
            "strategy_next": strategy,
            "cascade_mode": str(context.get("cascade_mode") or "UNKNOWN"),
            "cascade_consecutive_losses": int(context.get("cascade_consecutive_losses") or 0),
            "hard_stopped": bool(context.get("hard_stopped")),
            "active_positions_count": int(context.get("active_positions_count") or 0),
        }

    def _get_json(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        request_url = f"{url}?{urlencode(params)}" if params else url
        return self._request_json(request_url, headers=headers, timeout=timeout)

    def _post_json(self, url: str, *, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None) -> Any:
        merged_headers = {
            "Content-Type": "application/json",
            "User-Agent": "KiBot-Brain/1.0",
        }
        if headers:
            merged_headers.update(headers)
        return self._request_json(url, body=body, headers=merged_headers, timeout=timeout)

    def _request_json(
        self,
        url: str,
        *,
        body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        request_headers = {"User-Agent": "KiBot-Brain/1.0"}
        if headers:
            request_headers.update(headers)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            request = Request(url, data=data, headers=request_headers)
            with urlopen(request, timeout=timeout or max(self.request_timeout)) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            logger.warning("Brain fetch failed url=%s reason=%s", url, error)
            raise

    def _failure_backoff_seconds(self, error: Exception) -> int:
        code = int(getattr(error, "code", 0) or 0)
        if code in {401, 403}:
            return 3600
        if code == 432:
            return 3600
        if code == 429:
            return 900
        if code == 400:
            return 300
        if code >= 500:
            return 120
        message = str(error).lower()
        if "timeout" in message or "timed out" in message:
            return 120
        if "connection refused" in message or "temporary failure" in message:
            return 120
        return 60

    def _cached_payload(self, key: str, ttl_sec: int, loader) -> Any:
        now = time.time()
        provider_root = key.split(":", 1)[0].split("_", 1)[0]
        provider_root_cache = self._provider_cache.get(provider_root)
        if provider_root_cache:
            root_retry_after = float(provider_root_cache.get("retry_after") or 0.0)
            if root_retry_after and now < root_retry_after:
                return provider_root_cache.get("data")
        cached = self._provider_cache.get(key)
        if cached:
            retry_after = float(cached.get("retry_after") or 0.0)
            if retry_after and now < retry_after:
                return cached.get("data")
            if (now - float(cached.get("ts") or 0.0)) < ttl_sec:
                return cached.get("data")
        try:
            data = loader()
            self._provider_cache[key] = {
                "ts": now,
                "data": data,
                "ok": True,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "retry_after": 0.0,
            }
            self._provider_cache[provider_root] = {
                "ts": now,
                "data": data,
                "ok": True,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "retry_after": 0.0,
            }
            return data
        except Exception as error:
            cached_data = cached.get("data") if cached else {}
            provider_root = key.split(":", 1)[0].split("_", 1)[0]
            backoff_sec = self._failure_backoff_seconds(error)
            error_payload = {
                "ts": now,
                "data": cached_data,
                "ok": False,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "error": f"{type(error).__name__}: {error}",
                "retry_after": now + float(backoff_sec),
            }
            self._provider_cache[key] = error_payload
            self._provider_cache[provider_root] = dict(error_payload)
            return cached_data

    def _status_code(self, url: str) -> int:
        try:
            request = Request(url, headers={"User-Agent": "KiBot-Brain/1.0"})
            with urlopen(request, timeout=max(self.request_timeout)) as response:
                return int(getattr(response, "status", 200))
        except Exception:
            return 0

    def _listed_on_indodax(self, symbol: str, pairs_payload: Any) -> bool:
        if not isinstance(pairs_payload, list):
            return False
        symbol = symbol.upper()
        for row in pairs_payload:
            if not isinstance(row, dict):
                continue
            quote = str(row.get("quote_currency") or row.get("base_currency") or "").lower()
            base = str(
                row.get("traded_currency")
                or row.get("traded_currency_unit")
                or row.get("base_currency")
                or ""
            ).upper()
            if base == symbol and quote == "idr":
                return True
        return False

    def _default_watch_symbols(self) -> Iterable[str]:
        raw = os.getenv("KIBOT_BRAIN_WATCH_SYMBOLS", "BTC,ETH,SOL")
        return [item.strip() for item in raw.split(",")]

    def _parse_binance_symbol_allowlist(self) -> set[str]:
        raw = os.getenv(
            "KIBOT_BRAIN_BINANCE_SYMBOLS",
            "BTC,ETH,SOL,XRP,ADA,BNB,DOGE,LTC,MATIC,ARB,AVAX,ONDO,REQ,TRX,XLM,SUI",
        )
        out = {
            str(item or "").strip().upper()
            for item in raw.split(",")
            if str(item or "").strip()
        }
        return out or set(KNOWN_CRYPTO_ASSETS)

    def _normalize_symbols(self, watch_symbols: Iterable[str]) -> List[str]:
        out: List[str] = []
        for raw in watch_symbols:
            text = str(raw or "").strip().upper()
            if not text:
                continue
            if "_" in text:
                text = text.split("_", 1)[0]
            if text.endswith("IDR"):
                text = text[:-3]
            if text.endswith("USDT"):
                text = text[:-4]
            if text and text not in out:
                out.append(text)
        return out

    def _filter_news_for_symbol(self, symbol: str, news_items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        symbol = symbol.upper()
        out: List[Dict[str, Any]] = []
        for row in news_items:
            if not isinstance(row, dict):
                continue
            related = str(row.get("related") or "").upper()
            headline = str(row.get("headline") or "").upper()
            summary = str(row.get("summary") or "").upper()
            if symbol in related or symbol in headline or symbol in summary:
                out.append(row)
        return out

    def _sentiment_counts(self, texts: Iterable[str]) -> Tuple[int, int]:
        positive_hits = 0
        negative_hits = 0
        for text in texts:
            lowered = str(text or "").lower()
            positive_hits += sum(1 for word in POSITIVE_HEADLINE_KEYWORDS if word in lowered)
            negative_hits += sum(1 for word in NEGATIVE_HEADLINE_KEYWORDS if word in lowered)
        return positive_hits, negative_hits

    def _dedupe_texts(self, texts: Iterable[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for text in texts:
            cleaned = str(text or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(cleaned)
        return out

    def _safe_float(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if number != number or number in (float("inf"), float("-inf")):
            return 0.0
        return number

    def _optional_modules(self) -> Dict[str, Dict[str, Any]]:
        def has_module(name: str) -> bool:
            try:
                return importlib.util.find_spec(name) is not None
            except ModuleNotFoundError:
                return False

        return {
            "ddgs": {
                "installed": has_module("ddgs"),
                "api_key_present": False,
            },
            "google.genai": {
                "installed": has_module("google.genai"),
                "api_key_present": bool(self._gemini_api_key()),
            },
            "google.generativeai": {
                "installed": has_module("google.generativeai"),
                "api_key_present": bool(self._gemini_api_key()),
                "legacy_sdk": True,
            },
            "tavily": {
                "installed": has_module("tavily"),
                "api_key_present": bool(os.getenv("TAVILY_API_KEY")),
            },
            "duckduckgo_search": {
                "installed": has_module("duckduckgo_search"),
                "api_key_present": False,
            },
            "finnhub": {
                "installed": has_module("finnhub"),
                "api_key_present": bool(os.getenv("FINNHUB_API_KEY")),
            },
            "x_api": {
                "installed": True,
                "api_key_present": bool(self._x_bearer_token()),
            },
            "coingecko": {
                "installed": True,
                "api_key_present": bool(self._coingecko_headers()),
            },
            "numpy": {
                "installed": has_module("numpy"),
                "api_key_present": False,
            },
            "pandas": {
                "installed": has_module("pandas"),
                "api_key_present": False,
            },
            "talib": {
                "installed": has_module("talib"),
                "api_key_present": False,
            },
        }

    def _has_ddg_client(self) -> bool:
        for module_name in ("ddgs", "duckduckgo_search"):
            try:
                if importlib.util.find_spec(module_name) is not None:
                    return True
            except ModuleNotFoundError:
                continue
        return False

    def _ddg_search(self, query: str, max_results: int = 3) -> Dict[str, Any]:
        client_cls = None
        for module_name in ("ddgs", "duckduckgo_search"):
            try:
                module = __import__(module_name, fromlist=["DDGS"])
                client_cls = getattr(module, "DDGS", None)
                if client_cls is not None:
                    break
            except Exception:
                continue
        if client_cls is None:
            return {}

        client = None
        try:
            try:
                client = client_cls(timeout=max(self.request_timeout))
            except TypeError:
                client = client_cls()
            raw_results = client.text(query, max_results=max_results)
            results = []
            for item in list(raw_results or [])[:max_results]:
                if not isinstance(item, dict):
                    continue
                results.append(
                    {
                        "title": str(item.get("title") or "").strip(),
                        "content": str(item.get("body") or item.get("snippet") or "").strip(),
                        "url": str(item.get("href") or item.get("url") or "").strip(),
                    }
                )
            return {"query": query, "results": results}
        finally:
            closer = getattr(client, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass

    def _coordinator_provider_status(self) -> Dict[str, Dict[str, Any]]:
        if not self.ai_coordinator_enabled or _coordinator_provider_status_fn is None:
            return {}
        try:
            payload = _coordinator_provider_status_fn()
            return payload if isinstance(payload, dict) else {}
        except Exception as error:
            logger.warning("Brain coordinator status fetch failed: %s", error)
            return {}

    def _load_snapshot(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_external_world_model(self) -> Dict[str, Any]:
        """Loads the proactive intelligence model from WorldScout."""
        path = ROOT_DIR / "state" / "world_model.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_snapshot(self, snapshot: Dict[str, Any]) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        json_data = json.dumps(snapshot, ensure_ascii=False, indent=2)
        tmp.write_text(json_data, encoding="utf-8")
        tmp.replace(self.state_file)
        
        # Mirror to dashboard runtime_note.json
        mirror_path = os.getenv("KIBOT_RUNTIME_NOTE_PATH")
        if mirror_path:
            try:
                m_path = Path(mirror_path)
                m_path.parent.mkdir(parents=True, exist_ok=True)
                m_path.write_text(json_data, encoding="utf-8")
            except Exception as e:
                logger.debug("Failed to mirror brain snapshot: %s", e)
