from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from Core.Scanner.ki_indodax_smallcap_scanner import IndodaxSmallCapScanner
from Core.Scanner.source_proof import SourceProof

logger = logging.getLogger("IndodaxBinanceLeadLagScanner")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "indodax_binance_leadlag_scanner.json"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        if isinstance(value, str) and not value.strip():
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class IndodaxBinanceLeadLagScanner:
    """
    Lead-lag scanner for Indodax that compares short-window Binance momentum
    against the matching Indodax IDR pair. This is intentionally route-specific
    so the Indodax runtime can react to Binance moves that still have seconds of
    lag locally.
    """

    def __init__(self) -> None:
        self.exchange = "INDODAX"
        self.leader_exchange = "BINANCE"
        self.indodax = IndodaxSmallCapScanner()
        self.aggressive_mode = os.getenv("KIBOT_INDO_BINANCE_LEADLAG_AGGRESSIVE_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.bootstrap_mode = os.getenv("KIBOT_INDO_BINANCE_LEADLAG_BOOTSTRAP_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
        if self.aggressive_mode:
            self.bootstrap_mode = True
        self.lookback_sec = int(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_LOOKBACK_SEC", "6" if self.aggressive_mode else "12"))
        self.min_leader_move_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_MIN_LEADER_MOVE_PCT", "0.18" if self.aggressive_mode else "0.45"))
        self.max_follower_move_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_MAX_FOLLOWER_MOVE_PCT", "0.45" if self.aggressive_mode else "0.25"))
        self.min_gap_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_MIN_GAP_PCT", "0.08" if self.aggressive_mode else "0.25"))
        self.min_volume_idr = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_MIN_VOLUME_IDR", "25000000" if self.aggressive_mode else "50000000"))
        self.min_leader_quote_volume = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_MIN_LEADER_QUOTE_VOL", "750000" if self.aggressive_mode else "1500000"))
        self.max_spread_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_MAX_SPREAD_PCT", "1.20" if self.aggressive_mode else "0.80"))
        self.fee_roundtrip_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_FEE_ROUNDTRIP_PCT", "0.45" if self.aggressive_mode else "0.51"))
        self.min_expected_net_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_MIN_EXPECTED_NET_PCT", "0.00" if self.aggressive_mode else "0.10"))
        self.bootstrap_min_gap_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_BOOTSTRAP_MIN_GAP_PCT", "0.15" if self.aggressive_mode else "0.25"))
        self.bootstrap_min_leader_move_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_BOOTSTRAP_MIN_LEADER_MOVE_PCT", "0.25" if self.aggressive_mode else "0.45"))
        self.bootstrap_min_lag_sec = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_BOOTSTRAP_MIN_LAG_SEC", "0.50" if self.aggressive_mode else "1.00"))
        self.cache_ttl_sec = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_CACHE_TTL_SEC", "2.0"))

        self._history: Dict[str, List[Dict[str, Any]]] = {}
        self._signal_state: Dict[str, Dict[str, Any]] = {}
        self._binance_cache: Dict[str, Dict[str, Any]] = {}
        self._binance_cache_ts = 0.0
        self._indodax_cache: Dict[str, Dict[str, Any]] = {}
        self._indodax_cache_ts = 0.0

    def _pair_to_binance_symbol(self, pair: str) -> str:
        base = str(pair or "").split("_")[0].upper().strip()
        return f"{base}USDT" if base else ""

    def _prune_history(self, key: str) -> None:
        now = time.time()
        history = self._history.get(key, [])
        cutoff = now - max(5.0, float(self.lookback_sec))
        self._history[key] = [row for row in history if _safe_float(row.get("ts")) >= cutoff]

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str) -> Any:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"http_{resp.status}")
            return await resp.json()

    async def _fetch_binance_tickers(self, session: aiohttp.ClientSession) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        if self._binance_cache and (now - self._binance_cache_ts) < self.cache_ttl_sec:
            return dict(self._binance_cache)
        try:
            raw = await self._fetch_json(session, "https://api.binance.com/api/v3/ticker/24hr")
            parsed: Dict[str, Dict[str, Any]] = {}
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    symbol = str(item.get("symbol") or "").upper().strip()
                    if not symbol.endswith("USDT"):
                        continue
                    last_price = _safe_float(item.get("lastPrice") or item.get("price"))
                    if last_price <= 0:
                        continue
                    parsed[symbol] = {
                        "symbol": symbol,
                        "lastPrice": last_price,
                        "quoteVolume": _safe_float(item.get("quoteVolume")),
                        "priceChangePercent": _safe_float(item.get("priceChangePercent")),
                        "highPrice": _safe_float(item.get("highPrice")),
                        "lowPrice": _safe_float(item.get("lowPrice")),
                    }
            if parsed:
                self._binance_cache = parsed
                self._binance_cache_ts = now
            return dict(parsed or self._binance_cache)
        except Exception as exc:
            logger.debug("Binance fetch failed: %s", exc)
            return dict(self._binance_cache)

    async def _fetch_indodax_tickers(self, session: aiohttp.ClientSession) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        if self._indodax_cache and (now - self._indodax_cache_ts) < self.cache_ttl_sec:
            return dict(self._indodax_cache)
        try:
            raw = await self._fetch_json(session, "https://indodax.com/api/summaries")
            tickers = raw.get("tickers", {}) if isinstance(raw, dict) else {}
            parsed: Dict[str, Dict[str, Any]] = {}
            if isinstance(tickers, dict):
                for pair, item in tickers.items():
                    if not isinstance(item, dict):
                        continue
                    pair_key = str(pair).lower().strip()
                    if not pair_key.endswith("_idr"):
                        continue
                    parsed[pair_key] = {
                        "pair": pair_key,
                        "symbol": pair_key.upper().replace("_", "/"),
                        "last": _safe_float(item.get("last")),
                        "buy": _safe_float(item.get("buy")),
                        "sell": _safe_float(item.get("sell")),
                        "high": _safe_float(item.get("high")),
                        "low": _safe_float(item.get("low")),
                        "vol_idr": _safe_float(item.get("vol_idr") or item.get("volume_idr")),
                    }
            if parsed:
                self._indodax_cache = parsed
                self._indodax_cache_ts = now
            return dict(parsed or self._indodax_cache)
        except Exception as exc:
            logger.debug("Indodax fetch failed: %s", exc)
            return dict(self._indodax_cache)

    def _update_leadlag_state(
        self,
        pair: str,
        leader_change_pct: float,
        follower_change_pct: float,
        now_ts: float,
    ) -> Dict[str, Any]:
        state = self._signal_state.setdefault(
            pair,
            {
                "leader_cross_ts": None,
                "follower_cross_ts": None,
                "last_reset_ts": now_ts,
            },
        )
        leader_floor = max(self.min_leader_move_pct, 0.10)
        follower_floor = max(self.max_follower_move_pct, 0.05)

        if leader_change_pct >= leader_floor and state.get("leader_cross_ts") is None:
            state["leader_cross_ts"] = now_ts
        if follower_change_pct >= follower_floor and state.get("follower_cross_ts") is None:
            state["follower_cross_ts"] = now_ts

        if leader_change_pct < leader_floor * 0.4 and follower_change_pct < follower_floor * 0.4:
            state["leader_cross_ts"] = None
            state["follower_cross_ts"] = None
            state["last_reset_ts"] = now_ts

        leader_cross_ts = _safe_float(state.get("leader_cross_ts"), 0.0)
        follower_cross_ts = _safe_float(state.get("follower_cross_ts"), 0.0)
        if leader_cross_ts <= 0:
            lag_seconds = 0.0
        elif follower_cross_ts > 0:
            lag_seconds = max(0.0, follower_cross_ts - leader_cross_ts)
        else:
            lag_seconds = max(0.0, now_ts - leader_cross_ts)

        return {
            "leader_cross_ts": leader_cross_ts or None,
            "follower_cross_ts": follower_cross_ts or None,
            "lag_seconds": round(lag_seconds, 3),
        }

    def _build_snapshot_candidate(
        self,
        pair: str,
        indodax_item: Dict[str, Any],
        binance_item: Dict[str, Any],
        now_ts: float,
    ) -> Dict[str, Any] | None:
        follower_price = _safe_float(indodax_item.get("last"))
        leader_price = _safe_float(binance_item.get("lastPrice"))
        if follower_price <= 0 or leader_price <= 0:
            return None

        leader_change_pct = _safe_float(binance_item.get("priceChangePercent"))
        follower_low = _safe_float(indodax_item.get("low"))
        follower_high = _safe_float(indodax_item.get("high"))
        if follower_low > 0 and follower_high >= follower_low:
            follower_change_pct = ((follower_price - follower_low) / follower_low) * 100.0
            follower_range_position = ((follower_price - follower_low) / max(follower_high - follower_low, 1e-9)) * 100.0 if follower_high > follower_low else 0.0
            follower_distance_to_high = ((follower_high - follower_price) / follower_high) * 100.0 if follower_high > 0 else 0.0
        else:
            follower_change_pct = 0.0
            follower_range_position = 0.0
            follower_distance_to_high = 0.0

        leadlag_gap_pct = leader_change_pct - follower_change_pct
        spread_pct = 0.0
        buy = _safe_float(indodax_item.get("buy"))
        sell = _safe_float(indodax_item.get("sell"))
        if buy > 0 and sell > 0:
            spread_pct = max(0.0, ((sell - buy) / buy) * 100.0)

        leader_quote_volume = _safe_float(binance_item.get("quoteVolume"))
        volume_idr = _safe_float(indodax_item.get("vol_idr"))
        vol_score = min(1.0, max(0.0, (volume_idr / max(self.min_volume_idr, 1.0)))) if self.min_volume_idr > 0 else 0.0
        quote_vol_score = min(1.0, leader_quote_volume / max(self.min_leader_quote_volume, 1.0)) if self.min_leader_quote_volume > 0 else 0.0
        expected_net_pct = leadlag_gap_pct - self.fee_roundtrip_pct - (spread_pct / 2.0)
        stage = "SNAPSHOT_BOOTSTRAP"

        leader_symbol = self._pair_to_binance_symbol(pair)
        symbol = pair.upper().replace("_", "/")
        indodax_proof = SourceProof.create(
            source_type="REAL_EXCHANGE",
            source_name="Indodax",
            source_url_or_endpoint="https://indodax.com/api/summaries",
            raw_id=pair,
            symbol=symbol,
            address_or_mint=pair,
            chain="idr",
            proof_ok=True,
        )
        binance_proof = SourceProof.create(
            source_type="REAL_API",
            source_name="Binance",
            source_url_or_endpoint="https://api.binance.com/api/v3/ticker/24hr",
            raw_id=leader_symbol,
            symbol=leader_symbol,
            address_or_mint=leader_symbol,
            chain="usdt",
            proof_ok=True,
        )
        source_proof_ok = SourceProof.validate(indodax_proof) and SourceProof.validate(binance_proof)
        if not source_proof_ok:
            return {
                "rank": 0,
                "symbol": symbol,
                "pair": pair.upper(),
                "binance_symbol": leader_symbol,
                "leader_symbol": leader_symbol,
                "price": follower_price,
                "last_price": follower_price,
                "leader_price": leader_price,
                "follower_price": follower_price,
                "leader_change_pct": round(leader_change_pct, 4),
                "follower_change_pct": round(follower_change_pct, 4),
                "leadlag_gap_pct": round(leadlag_gap_pct, 4),
                "leadlag_lag_seconds": 0.0,
                "leadlag_window_sec": float(self.lookback_sec),
                "leadlag_score": 0.0,
                "entry_score": 0.0,
                "confidence": 0.0,
                "expected_net_pct": round(expected_net_pct, 4),
                "volume_24h_idr": volume_idr,
                "leader_quote_volume": leader_quote_volume,
                "spread_pct": round(spread_pct, 4),
                "route_status": "BLOCKED_WITH_REASON",
                "recommended_action": "REJECT",
                "reason": "invalid_source_proof",
                "source_proof": indodax_proof,
                "leader_source_proof": binance_proof,
                "leadlag_signal": True,
                "leadlag_stage": "INVALID",
                "leadlag_pass": False,
            }

        leader_move_ok = abs(leader_change_pct) >= self.bootstrap_min_leader_move_pct
        gap_ok = leadlag_gap_pct >= self.bootstrap_min_gap_pct
        spread_ok = spread_pct <= self.max_spread_pct
        volume_ok = volume_idr >= self.min_volume_idr or leader_quote_volume >= self.min_leader_quote_volume
        expected_ok = expected_net_pct >= self.min_expected_net_pct
        follower_still_lagging = leadlag_gap_pct >= self.bootstrap_min_gap_pct
        bootstrap_lag_sec = max(self.bootstrap_min_lag_sec, min(3.0, max(0.0, leader_change_pct) * 0.5))
        lag_bonus = min(8.0, bootstrap_lag_sec * 0.75)
        confidence = _clamp(
            0.30
            + min(0.34, max(0.0, leader_change_pct) / 5.0)
            + min(0.26, max(0.0, leadlag_gap_pct) / 3.0)
            + min(0.16, vol_score * 0.16)
            + min(0.10, quote_vol_score * 0.10)
            + min(0.08, lag_bonus / 10.0),
            0.0,
            0.99,
        )
        leadlag_score = max(0.0, (leadlag_gap_pct * 4.0) + (max(0.0, leader_change_pct) * 1.8) + (confidence * 10.0) + lag_bonus)
        entry_score = leadlag_score + (12.0 if gap_ok and follower_still_lagging and expected_ok else 0.0)

        reasons: List[str] = []
        if not leader_move_ok:
            reasons.append(f"leader_move_too_small({leader_change_pct:.2f}<{self.bootstrap_min_leader_move_pct:.2f})")
        if not spread_ok:
            reasons.append(f"spread_too_wide({spread_pct:.2f}>{self.max_spread_pct:.2f})")
        if not volume_ok:
            reasons.append(f"volume_too_low({volume_idr:,.0f}<{self.min_volume_idr:,.0f})")
        if not gap_ok:
            reasons.append(f"leadlag_gap_small({leadlag_gap_pct:.2f}<{self.bootstrap_min_gap_pct:.2f})")
        if not expected_ok:
            reasons.append(f"negative_expected_net({expected_net_pct:.2f})")

        if self.aggressive_mode and leader_move_ok and gap_ok and spread_ok and volume_ok and follower_still_lagging and expected_ok:
            action = "ENTER"
            route_status = "EXECUTABLE"
        elif leader_move_ok and gap_ok and spread_ok and volume_ok and follower_still_lagging:
            action = "WATCH"
            route_status = "EXECUTABLE"
        else:
            action = "REJECT"
            route_status = "BLOCKED_WITH_REASON"
        if action == "REJECT" and not reasons:
            reasons.append("leadlag_bootstrap_filters_not_met")

        return {
            "rank": 0,
            "symbol": symbol,
            "pair": pair.upper(),
            "binance_symbol": leader_symbol,
            "leader_symbol": leader_symbol,
            "price": follower_price,
            "last_price": follower_price,
            "leader_price": leader_price,
            "follower_price": follower_price,
            "leader_change_pct": round(leader_change_pct, 4),
            "follower_change_pct": round(follower_change_pct, 4),
            "leadlag_gap_pct": round(leadlag_gap_pct, 4),
            "leadlag_lag_seconds": round(bootstrap_lag_sec, 3),
            "leadlag_window_sec": float(self.lookback_sec),
            "leadlag_score": round(leadlag_score, 4),
            "entry_score": round(entry_score, 2),
            "confidence": round(confidence, 4),
            "expected_net_pct": round(expected_net_pct, 4),
            "volume_24h_idr": volume_idr,
            "leader_quote_volume": leader_quote_volume,
            "spread_pct": round(spread_pct, 4),
            "route_status": route_status,
            "recommended_action": action,
            "reason": "; ".join(reasons),
            "source_proof": indodax_proof,
            "leader_source_proof": binance_proof,
            "leadlag_signal": True,
            "leadlag_stage": stage,
            "leadlag_pass": action == "ENTER",
            "leadlag_source": "BINANCE_TO_INDODAX",
            "source_pool": "leadlag_candidates",
        }

    def _build_candidate(
        self,
        pair: str,
        indodax_item: Dict[str, Any],
        binance_item: Dict[str, Any],
        now_ts: float,
    ) -> Dict[str, Any] | None:
        follower_price = _safe_float(indodax_item.get("last"))
        leader_price = _safe_float(binance_item.get("lastPrice"))
        if follower_price <= 0 or leader_price <= 0:
            return None

        history = self._history.setdefault(pair, [])
        history.append(
            {
                "ts": now_ts,
                "leader_price": leader_price,
                "follower_price": follower_price,
                "leader_volume": _safe_float(binance_item.get("quoteVolume")),
                "follower_volume": _safe_float(indodax_item.get("vol_idr")),
            }
        )
        self._prune_history(pair)
        history = self._history.get(pair, [])
        if len(history) < 2:
            if self.bootstrap_mode:
                return self._build_snapshot_candidate(pair, indodax_item, binance_item, now_ts)
            return None

        oldest = history[0]
        leader_old = _safe_float(oldest.get("leader_price"))
        follower_old = _safe_float(oldest.get("follower_price"))
        if leader_old <= 0 or follower_old <= 0:
            return None

        leader_change_pct = ((leader_price - leader_old) / leader_old) * 100.0
        follower_change_pct = ((follower_price - follower_old) / follower_old) * 100.0
        leadlag_gap_pct = leader_change_pct - follower_change_pct
        spread_pct = 0.0
        buy = _safe_float(indodax_item.get("buy"))
        sell = _safe_float(indodax_item.get("sell"))
        if buy > 0 and sell > 0:
            spread_pct = max(0.0, ((sell - buy) / buy) * 100.0)

        leader_quote_volume = _safe_float(binance_item.get("quoteVolume"))
        volume_idr = _safe_float(indodax_item.get("vol_idr"))
        vol_score = min(1.0, max(0.0, (volume_idr / max(self.min_volume_idr, 1.0)))) if self.min_volume_idr > 0 else 0.0
        quote_vol_score = min(1.0, leader_quote_volume / max(self.min_leader_quote_volume, 1.0)) if self.min_leader_quote_volume > 0 else 0.0
        lag_state = self._update_leadlag_state(pair, leader_change_pct, follower_change_pct, now_ts)
        lag_seconds = _safe_float(lag_state.get("lag_seconds"), 0.0)
        expected_net_pct = leadlag_gap_pct - self.fee_roundtrip_pct - (spread_pct / 2.0)

        leader_symbol = self._pair_to_binance_symbol(pair)
        symbol = pair.upper().replace("_", "/")
        indodax_proof = SourceProof.create(
            source_type="REAL_EXCHANGE",
            source_name="Indodax",
            source_url_or_endpoint="https://indodax.com/api/summaries",
            raw_id=pair,
            symbol=symbol,
            address_or_mint=pair,
            chain="idr",
            proof_ok=True,
        )
        binance_proof = SourceProof.create(
            source_type="REAL_API",
            source_name="Binance",
            source_url_or_endpoint="https://api.binance.com/api/v3/ticker/24hr",
            raw_id=leader_symbol,
            symbol=leader_symbol,
            address_or_mint=leader_symbol,
            chain="usdt",
            proof_ok=True,
        )

        source_proof_ok = SourceProof.validate(indodax_proof) and SourceProof.validate(binance_proof)
        if not source_proof_ok:
            return {
                "rank": 0,
                "symbol": symbol,
                "pair": pair.upper(),
                "binance_symbol": leader_symbol,
                "leader_symbol": leader_symbol,
                "price": follower_price,
                "last_price": follower_price,
                "leader_price": leader_price,
                "follower_price": follower_price,
                "leader_change_pct": round(leader_change_pct, 4),
                "follower_change_pct": round(follower_change_pct, 4),
                "leadlag_gap_pct": round(leadlag_gap_pct, 4),
                "leadlag_lag_seconds": round(lag_seconds, 3),
                "leadlag_window_sec": float(self.lookback_sec),
                "leadlag_score": 0.0,
                "entry_score": 0.0,
                "confidence": 0.0,
                "expected_net_pct": round(expected_net_pct, 4),
                "volume_24h_idr": volume_idr,
                "leader_quote_volume": leader_quote_volume,
                "spread_pct": round(spread_pct, 4),
                "route_status": "BLOCKED_WITH_REASON",
                "recommended_action": "REJECT",
                "reason": "invalid_source_proof",
                "source_proof": indodax_proof,
                "leader_source_proof": binance_proof,
                "leadlag_signal": True,
                "leadlag_stage": "INVALID",
                "leadlag_pass": False,
            }

        leader_move_ok = abs(leader_change_pct) >= self.min_leader_move_pct
        follower_still_lagging = follower_change_pct <= self.max_follower_move_pct
        spread_ok = spread_pct <= self.max_spread_pct
        volume_ok = volume_idr >= self.min_volume_idr or leader_quote_volume >= self.min_leader_quote_volume
        gap_ok = leadlag_gap_pct >= self.min_gap_pct
        expected_ok = expected_net_pct >= self.min_expected_net_pct

        reasons: List[str] = []
        if not leader_move_ok:
            reasons.append(f"leader_move_too_small({leader_change_pct:.2f}<{self.min_leader_move_pct:.2f})")
        if not spread_ok:
            reasons.append(f"spread_too_wide({spread_pct:.2f}>{self.max_spread_pct:.2f})")
        if not volume_ok:
            reasons.append(
                f"volume_too_low({volume_idr:,.0f}<{self.min_volume_idr:,.0f})"
            )
        if not gap_ok:
            reasons.append(f"leadlag_gap_small({leadlag_gap_pct:.2f}<{self.min_gap_pct:.2f})")
        if not expected_ok:
            reasons.append(f"negative_expected_net({expected_net_pct:.2f})")

        leadership_strength = max(0.0, leader_change_pct)
        lag_bonus = min(10.0, lag_seconds * 0.75)
        confidence = _clamp(
            0.24
            + min(0.36, leadership_strength / 5.0)
            + min(0.28, max(0.0, leadlag_gap_pct) / 3.0)
            + min(0.16, vol_score * 0.16)
            + min(0.10, quote_vol_score * 0.10)
            + min(0.08, lag_bonus / 10.0),
            0.0,
            0.99,
        )
        leadlag_score = max(0.0, (leadlag_gap_pct * 3.5) + (leadership_strength * 1.5) + (confidence * 10.0) + lag_bonus)
        entry_score = leadlag_score + (10.0 if gap_ok and follower_still_lagging and expected_ok else 0.0)
        stage = "EARLY_LAG" if gap_ok and follower_still_lagging else "LEADER_AHEAD" if leader_move_ok else "LATE"
        aggressive_enter_ok = (
            self.aggressive_mode
            and leader_move_ok
            and spread_ok
            and volume_ok
            and gap_ok
            and follower_still_lagging
            and expected_net_pct >= max(-0.05, self.min_expected_net_pct)
            and leadlag_gap_pct >= max(self.min_gap_pct, self.bootstrap_min_gap_pct)
        )

        if not leader_move_ok or not spread_ok or not volume_ok or not gap_ok or not expected_ok:
            action = "REJECT"
            route_status = "BLOCKED_WITH_REASON"
        elif aggressive_enter_ok or (gap_ok and follower_still_lagging and expected_ok):
            action = "ENTER"
            route_status = "EXECUTABLE"
        elif leader_move_ok and follower_still_lagging and spread_ok and volume_ok:
            action = "WATCH"
            route_status = "EXECUTABLE"
        else:
            action = "REJECT"
            route_status = "BLOCKED_WITH_REASON"

        if action == "REJECT" and not reasons:
            reasons.append("leadlag_filters_not_met")

        return {
            "rank": 0,
            "symbol": symbol,
            "pair": pair.upper(),
            "binance_symbol": leader_symbol,
            "leader_symbol": leader_symbol,
            "price": follower_price,
            "last_price": follower_price,
            "leader_price": leader_price,
            "follower_price": follower_price,
            "leader_change_pct": round(leader_change_pct, 4),
            "follower_change_pct": round(follower_change_pct, 4),
            "leadlag_gap_pct": round(leadlag_gap_pct, 4),
            "leadlag_lag_seconds": round(lag_seconds, 3),
            "leadlag_window_sec": float(self.lookback_sec),
            "leadlag_score": round(leadlag_score, 4),
            "entry_score": round(entry_score, 2),
            "confidence": round(confidence, 4),
            "expected_net_pct": round(expected_net_pct, 4),
            "volume_24h_idr": volume_idr,
            "leader_quote_volume": leader_quote_volume,
            "spread_pct": round(spread_pct, 4),
            "route_status": route_status,
            "recommended_action": action,
            "reason": "; ".join(reasons),
            "source_proof": indodax_proof,
            "leader_source_proof": binance_proof,
            "leadlag_signal": True,
            "leadlag_stage": stage,
            "leadlag_pass": action == "ENTER",
            "leadlag_source": "BINANCE_TO_INDODAX",
            "source_pool": "leadlag_candidates",
        }

    async def scan(
        self,
        indodax_tickers: Optional[Dict[str, Dict[str, Any]]] = None,
        binance_tickers: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        now_str = datetime.now(timezone.utc).isoformat()
        started = time.time()
        STATE_DIR.mkdir(parents=True, exist_ok=True)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.0)) as session:
            if indodax_tickers is None:
                indodax_tickers = await self._fetch_indodax_tickers(session)
            else:
                indodax_tickers = {
                    str(pair).lower().strip(): dict(item)
                    for pair, item in (indodax_tickers or {}).items()
                    if isinstance(item, dict)
                }

            if binance_tickers is None:
                binance_tickers = await self._fetch_binance_tickers(session)
            else:
                binance_tickers = {
                    str(symbol).upper().strip(): dict(item)
                    for symbol, item in (binance_tickers or {}).items()
                    if isinstance(item, dict)
                }

        pair_candidates: List[Dict[str, Any]] = []
        rejected_candidates: List[Dict[str, Any]] = []
        seen_pairs = 0

        for pair, indodax_item in indodax_tickers.items():
            if not str(pair).endswith("_idr"):
                continue
            seen_pairs += 1
            leader_symbol = self._pair_to_binance_symbol(pair)
            if not leader_symbol or leader_symbol not in binance_tickers:
                continue
            binance_item = binance_tickers.get(leader_symbol, {})
            candidate = self._build_candidate(pair, indodax_item, binance_item, time.time())
            if not candidate:
                continue
            if candidate.get("recommended_action") == "REJECT":
                rejected_candidates.append(candidate)
            else:
                pair_candidates.append(candidate)

        pair_candidates.sort(key=lambda x: (x.get("entry_score", 0.0), x.get("leadlag_gap_pct", 0.0), x.get("confidence", 0.0)), reverse=True)
        rejected_candidates.sort(key=lambda x: (x.get("leadlag_gap_pct", 0.0), x.get("confidence", 0.0)), reverse=True)

        top_candidate = pair_candidates[0] if pair_candidates else {}
        top_candidate = dict(top_candidate) if isinstance(top_candidate, dict) else {}
        if top_candidate:
            top_candidate["rank"] = 1

        watchlist = [c for c in pair_candidates if c.get("recommended_action") == "WATCH"][:20]
        actionable = [c for c in pair_candidates if c.get("recommended_action") in {"ENTER", "WATCH"}]
        source_status = "OK" if actionable else ("NO_DATA" if indodax_tickers and binance_tickers else "SOURCE_FAILED")
        why_empty = ""
        if not actionable:
            if not indodax_tickers:
                why_empty = "indodax_summaries_missing"
            elif not binance_tickers:
                why_empty = "binance_24hr_missing"
            else:
                why_empty = "no_pair_passed_leadlag_filters"
                source_status = "DEGRADED"

        state = {
            "updated_at": now_str,
            "scan_mode": "BINANCE_TO_INDODAX_LEADLAG",
            "source_status": source_status,
            "lookback_sec": self.lookback_sec,
            "pairs_checked": seen_pairs,
            "binance_pairs_checked": len(binance_tickers),
            "candidate_universe": len(actionable),
            "leadlag_candidates": actionable[:20],
            "leadlag_watchlist": watchlist,
            "rejected_candidates": rejected_candidates[:20],
            "top_candidate": top_candidate,
            "why_empty": why_empty,
            "scan_latency_ms": round((time.time() - started) * 1000.0, 2),
        }
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return state

    async def collect_signals(self) -> Dict[str, Any]:
        state = await self.scan()
        signals: List[Dict[str, Any]] = []
        for candidate in state.get("leadlag_candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("recommended_action") or "").upper() != "ENTER":
                continue
            signals.append(
                {
                    "exchange": "INDODAX",
                    "source": "BINANCE_TO_INDODAX_LEADLAG",
                    "symbol": candidate.get("symbol"),
                    "base_symbol": str(candidate.get("symbol") or "").split("/")[0],
                    "price": candidate.get("price"),
                    "price_idr": candidate.get("price"),
                    "change_pct": candidate.get("follower_change_pct"),
                    "change_5m_pct": candidate.get("follower_change_pct"),
                    "leader_symbol": candidate.get("leader_symbol"),
                    "leader_change_pct": candidate.get("leader_change_pct"),
                    "follower_change_pct": candidate.get("follower_change_pct"),
                    "leadlag_gap_pct": candidate.get("leadlag_gap_pct"),
                    "leadlag_lag_seconds": candidate.get("leadlag_lag_seconds"),
                    "leadlag_score": candidate.get("leadlag_score"),
                    "expected_net_pct": candidate.get("expected_net_pct"),
                    "opportunity_score": candidate.get("entry_score"),
                    "confidence": candidate.get("confidence"),
                    "trade_grade": "A" if float(candidate.get("confidence") or 0.0) >= 0.75 else "B",
                    "leadlag_pass": True,
                    "ts": int(time.time() * 1000),
                    "source_proof": candidate.get("source_proof"),
                    "leader_source_proof": candidate.get("leader_source_proof"),
                }
            )
        return {"signals": signals, "state": state}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = IndodaxBinanceLeadLagScanner()

    async def _main() -> None:
        state = await scanner.scan()
        print(json.dumps(state, indent=2, ensure_ascii=False, default=str))

    asyncio.run(_main())
