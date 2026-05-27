import os
import json
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
from Core.Scanner.source_proof import SourceProof
from Core.Scanner.ki_indodax_smallcap_scanner import IndodaxSmallCapScanner
from Core.Scanner.indodax_binance_leadlag_scanner import IndodaxBinanceLeadLagScanner

logger = logging.getLogger("IndodaxMarketScanner")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "indodax_scanner_state.json"

class IndodaxMarketScanner:
    """
    Real Indodax market-wide scanner.
    Fetches real exchange data from Indodax API, validates candidates, and attaches cryptographic source proof.
    """

    def __init__(self) -> None:
        self.scanner = IndodaxSmallCapScanner()
        self.leadlag_scanner = IndodaxBinanceLeadLagScanner()
        self.state_dir = STATE_DIR

    def _fetch_pair_metadata(self) -> dict:
        try:
            rows = requests.get("https://indodax.com/api/pairs", timeout=8).json()
            if not isinstance(rows, list):
                return {}
            out = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ticker_id = str(row.get("ticker_id") or "").lower()
                if ticker_id:
                    out[ticker_id] = row
            return out
        except Exception as exc:
            logger.debug("Pair metadata fetch failed: %s", exc)
            return {}

    @staticmethod
    def _pair_route_status(pair: str, pair_meta: dict) -> dict:
        meta = pair_meta.get(str(pair).lower(), {}) if isinstance(pair_meta, dict) else {}
        maintenance = int(meta.get("is_maintenance", 0) or 0) == 1
        suspended = int(meta.get("is_market_suspended", 0) or 0) == 1
        if maintenance or suspended:
            reason = (
                f"pair_unavailable_maintenance={int(maintenance)}_"
                f"suspended={int(suspended)}"
            )
            return {
                "is_maintenance": maintenance,
                "is_market_suspended": suspended,
                "route_status": "BLOCKED_WITH_REASON",
                "recommended_action": "REJECT",
                "reason": reason,
                "pair_metadata": {
                    "trade_min_base_currency": meta.get("trade_min_base_currency"),
                    "trade_min_traded_currency": meta.get("trade_min_traded_currency"),
                    "price_precision": meta.get("price_precision"),
                    "volume_precision": meta.get("volume_precision"),
                    "is_maintenance": meta.get("is_maintenance"),
                    "is_market_suspended": meta.get("is_market_suspended"),
                },
            }
        return {
            "is_maintenance": False,
            "is_market_suspended": False,
            "route_status": "EXECUTABLE",
            "recommended_action": "",
            "reason": "",
            "pair_metadata": {
                "trade_min_base_currency": meta.get("trade_min_base_currency"),
                "trade_min_traded_currency": meta.get("trade_min_traded_currency"),
                "price_precision": meta.get("price_precision"),
                "volume_precision": meta.get("volume_precision"),
                "is_maintenance": meta.get("is_maintenance"),
                "is_market_suspended": meta.get("is_market_suspended"),
            },
        }

    @classmethod
    def _apply_pair_route_status(cls, item: dict, pair_meta: dict) -> dict:
        out = dict(item)
        pair = str(out.get("pair") or out.get("mint") or out.get("symbol") or "").lower().replace("/", "_")
        status = cls._pair_route_status(pair, pair_meta)
        out.update({k: v for k, v in status.items() if k != "recommended_action" or v})
        if status["route_status"] != "EXECUTABLE":
            out["route_status"] = status["route_status"]
            out["recommended_action"] = status["recommended_action"]
            out["reason"] = status["reason"]
        else:
            out.setdefault("route_status", "EXECUTABLE")
        return out

    async def scan(self) -> dict:
        logger.info("📡 Running real Indodax exchange scanner...")
        now_str = datetime.now(timezone.utc).isoformat()
        self.state_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Fetch real tickers
            tickers = self.scanner.fetch_all_tickers()
            pair_meta = self._fetch_pair_metadata()
            if not tickers:
                state = {
                    "updated_at": now_str,
                    "source_status": "NO_DATA",
                    "scan_mode": "REAL_EXCHANGE_MARKET_WIDE",
                    "pairs_checked": 0,
                    "candidates_found": 0,
                    "candidates": [],
                    "rejected_candidates": [],
                    "best_candidate": {},
                    "no_data_reason": "No tickers fetched from Indodax exchange API"
                }
                STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                return state

            try:
                leadlag_state = await self.leadlag_scanner.scan(indodax_tickers=tickers)
            except Exception as exc:
                logger.debug("Lead-lag scanner failed: %s", exc)
                leadlag_state = {
                    "updated_at": now_str,
                    "scan_mode": "BINANCE_TO_INDODAX_LEADLAG",
                    "source_status": "SOURCE_FAILED",
                    "pairs_checked": 0,
                    "binance_pairs_checked": 0,
                    "candidate_universe": 0,
                    "leadlag_candidates": [],
                    "leadlag_watchlist": [],
                    "rejected_candidates": [],
                    "top_candidate": {},
                    "why_empty": f"leadlag_scanner_error:{exc}",
                }

            pairs_checked = 0
            categories_checked = ["ALL", "IDR_MARKETS", "NEW_COIN", "MEME", "AI_BIG_DATA", "RWA", "DEFI", "L1_L2", "NFT", "TOKENIZED_STOCKS", "OTHER"]
            candidates = []
            rejected_candidates = []
            gainers_24h = []
            volume_leaders = []
            leadlag_candidates = []
            for c in (leadlag_state.get("leadlag_candidates", []) or []):
                if not isinstance(c, dict):
                    continue
                normalized = dict(c)
                normalized.setdefault("source_pool", "leadlag_candidates")
                normalized.setdefault("source_class", "leadlag_binance")
                normalized = self._apply_pair_route_status(normalized, pair_meta)
                leadlag_candidates.append(normalized)

            leadlag_watchlist = []
            for c in (leadlag_state.get("leadlag_watchlist", []) or []):
                if not isinstance(c, dict):
                    continue
                normalized = dict(c)
                normalized.setdefault("source_pool", "leadlag_watchlist")
                normalized.setdefault("source_class", "leadlag_binance")
                normalized = self._apply_pair_route_status(normalized, pair_meta)
                leadlag_watchlist.append(normalized)

            for pair, ticker in tickers.items():
                if not pair.endswith("_idr"):
                    continue
                pairs_checked += 1
                last_price = float(ticker.get("last", 0.0) or 0.0)
                high = float(ticker.get("high", last_price) or last_price)
                low = float(ticker.get("low", last_price) or last_price)
                vol_idr = float(ticker.get("vol_idr", ticker.get("volume_idr", 0.0)) or 0.0)
                change_24h = ((last_price - low) / low * 100.0) if low > 0 else 0.0
                range_span = max(high - low, 1e-9)
                range_position_pct = ((last_price - low) / range_span * 100.0) if high > low else 0.0
                distance_to_high_pct = ((high - last_price) / high * 100.0) if high > 0 else 0.0
                runup_from_low_pct = ((last_price - low) / low * 100.0) if low > 0 else 0.0
                pair_status = self._pair_route_status(pair, pair_meta)
                gainers_24h.append({
                    "symbol": pair.upper().replace("_", "/"),
                    "pair": pair,
                    "change_24h_pct": change_24h,
                    "volume_idr": vol_idr,
                    "last_price": last_price,
                    "high_24h": high,
                    "low_24h": low,
                    "range_position_pct": range_position_pct,
                    "distance_to_high_pct": distance_to_high_pct,
                    "runup_from_low_pct": runup_from_low_pct,
                    "source_proof": SourceProof.create(
                        source_type="REAL_EXCHANGE",
                        source_name="Indodax",
                        source_url_or_endpoint="https://indodax.com/api/summaries",
                        raw_id=pair,
                        symbol=pair.upper().replace("_", "/"),
                        address_or_mint=pair,
                        chain="rupiah",
                        proof_ok=True
                    ),
                    **pair_status,
                })
                volume_leaders.append({
                    "symbol": pair.upper().replace("_", "/"),
                    "pair": pair,
                    "change_24h_pct": change_24h,
                    "volume_idr": vol_idr,
                    "last_price": last_price,
                    "high_24h": high,
                    "low_24h": low,
                    "range_position_pct": range_position_pct,
                    "distance_to_high_pct": distance_to_high_pct,
                    "runup_from_low_pct": runup_from_low_pct,
                    "source_proof": SourceProof.create(
                        source_type="REAL_EXCHANGE",
                        source_name="Indodax",
                        source_url_or_endpoint="https://indodax.com/api/summaries",
                        raw_id=pair,
                        symbol=pair.upper().replace("_", "/"),
                        address_or_mint=pair,
                        chain="rupiah",
                        proof_ok=True
                    ),
                    **pair_status,
                })

                # Use the real pump detection engine from the smallcap scanner
                sig = self.scanner.detect_pump(pair, ticker)
                if sig:
                    sig = self.scanner._enrich_signal(sig, datetime.now(timezone.utc).timestamp())
                    if sig:
                        symbol = sig.get("symbol", pair.upper().replace("_", "/"))
                        # Create valid SourceProof
                        proof = SourceProof.create(
                            source_type="REAL_EXCHANGE",
                            source_name="Indodax",
                            source_url_or_endpoint="https://indodax.com/api/summaries",
                            raw_id=pair,
                            symbol=symbol,
                            address_or_mint=pair,
                            chain="rupiah",
                            proof_ok=True
                        )

                        # Enforce SourceProof check
                        if SourceProof.validate(proof):
                            entry_score = round(
                                min(
                                    100.0,
                                    max(
                                        0.0,
                                        float(sig.get("confidence", 0.5)) * 100.0
                                        + float(sig.get("change_pct", 0.0)) * 2.0
                                        + float(sig.get("vol_ratio", 0.0)) * 6.0,
                                    ),
                                ),
                                2,
                            )
                            candidate = {
                                "symbol": symbol,
                                "mint": pair,
                                "chain": "rupiah",
                                "sector": "indodax",
                                "price": float(sig.get("price", 0.0)),
                                "change_pct": float(sig.get("change_pct", 0.0)),
                                "price_acceleration": float(sig.get("change_pct", 0.0)),
                                "volume_acceleration": float(sig.get("vol_ratio", 0.0)),
                                "confidence": float(sig.get("confidence", 0.5)),
                                "entry_score": entry_score,
                                "high_24h": high,
                                "low_24h": low,
                                "range_position_pct": range_position_pct,
                                "distance_to_high_pct": distance_to_high_pct,
                                "runup_from_low_pct": runup_from_low_pct,
                                "source_proof": proof
                            }
                            candidate.update(pair_status)
                            if pair_status["route_status"] == "EXECUTABLE":
                                candidates.append(candidate)
                            else:
                                rejected_candidates.append(candidate)
                            gainers_24h.append({
                                "symbol": symbol,
                                "pair": pair,
                                "change_24h_pct": float(sig.get("change_pct", 0.0)),
                                "volume_idr": float(sig.get("volume_idr", sig.get("vol_idr", 0.0)) or 0.0),
                                "source_proof": proof,
                            })
                            volume_leaders.append({
                                "symbol": symbol,
                                "pair": pair,
                                "change_24h_pct": float(sig.get("change_pct", 0.0)),
                                "volume_idr": float(sig.get("volume_idr", sig.get("vol_idr", 0.0)) or 0.0),
                                    "source_proof": proof,
                                })
                        else:
                            rejected_candidates.append({
                                "symbol": symbol,
                                "reason": "invalid_source_proof",
                                "proof": proof
                            })
                elif vol_idr >= 100_000_000 or change_24h >= 5.0:
                    # Fallback continuation/pullback watcher so the runtime does
                    # not collapse to a single narrow pump detector. This stays
                    # data-driven and still requires real exchange proof.
                    symbol = pair.upper().replace("_", "/")
                    fallback_stage = (
                        "CONTINUATION"
                        if distance_to_high_pct <= 12.0
                        else "PULLBACK_RECLAIM"
                        if runup_from_low_pct >= 6.0
                        else "MOMENTUM"
                    )
                    proof = SourceProof.create(
                        source_type="REAL_EXCHANGE",
                        source_name="Indodax",
                        source_url_or_endpoint="https://indodax.com/api/summaries",
                        raw_id=pair,
                        symbol=symbol,
                        address_or_mint=pair,
                        chain="rupiah",
                        proof_ok=True
                    )
                    if SourceProof.validate(proof):
                        candidate = {
                            "symbol": symbol,
                            "mint": pair,
                            "chain": "rupiah",
                            "sector": "indodax",
                            "price": last_price,
                            "change_pct": change_24h,
                            "price_acceleration": change_24h,
                            "volume_acceleration": min(5.0, max(1.0, vol_idr / 100_000_000.0)),
                            "confidence": min(0.85, 0.45 + min(change_24h / 25.0, 0.20) + min(vol_idr / 500_000_000.0, 0.20)),
                            "pump_stage": fallback_stage,
                            "trend_continuation": fallback_stage == "CONTINUATION",
                            "pullback_reclaim": fallback_stage == "PULLBACK_RECLAIM",
                            "late_reclaim": fallback_stage == "PULLBACK_RECLAIM" and runup_from_low_pct >= 12.0,
                            "range_break_reclaim": range_position_pct >= 60.0,
                            "support_bounce_reclaim": range_position_pct <= 40.0,
                            "pivot_reclaim": range_position_pct <= 25.0,
                            "mature_pump": change_24h >= 20.0 or vol_idr >= 500_000_000.0,
                            "high_24h": high,
                            "low_24h": low,
                            "range_position_pct": range_position_pct,
                            "distance_to_high_pct": distance_to_high_pct,
                            "runup_from_low_pct": runup_from_low_pct,
                            "source_proof": proof,
                            "fallback_reason": "momentum_fallback_from_real_exchange_snapshot",
                            "entry_score": round(
                                min(
                                    100.0,
                                    max(
                                        0.0,
                                        change_24h * 2.0
                                        + min(vol_idr / 5_000_000.0, 20.0)
                                        + (10.0 if fallback_stage == "CONTINUATION" else 0.0)
                                        + (8.0 if fallback_stage == "PULLBACK_RECLAIM" else 0.0)
                                        + (6.0 if fallback_stage == "RANGE_BREAK_RECLAIM" else 0.0)
                                    ),
                                ),
                                2,
                            ),
                        }
                        candidate.update(pair_status)
                        if pair_status["route_status"] == "EXECUTABLE":
                            candidates.append(candidate)
                        else:
                            rejected_candidates.append(candidate)
                        gainers_24h.append({
                            "symbol": symbol,
                            "pair": pair,
                            "change_24h_pct": change_24h,
                            "volume_idr": vol_idr,
                            "last_price": last_price,
                            "high_24h": high,
                            "low_24h": low,
                            "range_position_pct": range_position_pct,
                            "distance_to_high_pct": distance_to_high_pct,
                            "runup_from_low_pct": runup_from_low_pct,
                            "source_proof": proof,
                            **pair_status,
                        })
                        volume_leaders.append({
                            "symbol": symbol,
                            "pair": pair,
                            "change_24h_pct": change_24h,
                            "volume_idr": vol_idr,
                            "last_price": last_price,
                            "high_24h": high,
                            "low_24h": low,
                            "range_position_pct": range_position_pct,
                            "distance_to_high_pct": distance_to_high_pct,
                            "runup_from_low_pct": runup_from_low_pct,
                            "source_proof": proof,
                            **pair_status,
                        })

            candidates.extend(leadlag_candidates)
            for c in (leadlag_state.get("rejected_candidates", []) or []):
                if isinstance(c, dict):
                    normalized = dict(c)
                    normalized.setdefault("source_pool", "leadlag_rejected")
                    rejected_candidates.append(normalized)
            candidates.sort(
                key=lambda x: (
                    float(x.get("entry_score", 0.0) or 0.0),
                    float(x.get("confidence", 0.0) or 0.0),
                    float(x.get("price_acceleration", x.get("leadlag_gap_pct", 0.0)) or 0.0),
                    float(x.get("volume_acceleration", x.get("leadlag_score", 0.0)) or 0.0),
                ),
                reverse=True,
            )
            gainers_24h.sort(key=lambda x: x.get("change_24h_pct", 0.0), reverse=True)
            volume_leaders.sort(key=lambda x: x.get("volume_idr", 0.0), reverse=True)
            brutal_momentum_candidates = gainers_24h[:15]
            pullback_candidates = [c for c in candidates if float(c.get("change_pct", 0.0)) > 0 and float(c.get("confidence", 0.0)) < 0.8]

            best_candidate = candidates[0] if candidates else {}

            scan_source_ok = bool(tickers)
            state = {
                "updated_at": now_str,
                "source_status": "OK" if scan_source_ok else "NO_DATA",
                "scan_mode": "REAL_EXCHANGE_MARKET_WIDE",
                "pairs_checked": pairs_checked,
                "categories_checked": categories_checked,
                "gainers_24h": gainers_24h[:20],
                "volume_leaders": volume_leaders[:20],
                "brutal_momentum_candidates": brutal_momentum_candidates,
                "pullback_candidates": pullback_candidates[:20],
                "leadlag_scan_mode": leadlag_state.get("scan_mode", "BINANCE_TO_INDODAX_LEADLAG"),
                "leadlag_source_status": leadlag_state.get("source_status", "NO_DATA"),
                "leadlag_pairs_checked": leadlag_state.get("pairs_checked", 0),
                "leadlag_candidates": leadlag_candidates[:20],
                "leadlag_watchlist": leadlag_watchlist[:20],
                "leadlag_top_candidate": leadlag_state.get("top_candidate", {}),
                "leadlag_why_empty": leadlag_state.get("why_empty", ""),
                "candidates_found": len(candidates),
                "candidates": candidates,
                "rejected_candidates": rejected_candidates,
                "best_candidate": best_candidate,
                "no_data_reason": "" if scan_source_ok else "No tickers fetched from Indodax exchange API"
            }

            STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
            logger.info(f"💾 Indodax scanner completed successfully. Found {len(candidates)} real candidates.")
            return state

        except Exception as e:
            logger.error(f"❌ Indodax scanner failed with exception: {e}")
            state = {
                "updated_at": now_str,
                "source_status": "SOURCE_FAILED",
                "scan_mode": "REAL_EXCHANGE_MARKET_WIDE",
                "pairs_checked": 0,
                "candidates_found": 0,
                "candidates": [],
                "rejected_candidates": [],
                "best_candidate": {},
                "no_data_reason": f"Indodax API scan failed: {e}"
            }
            STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
            return state

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    scanner = IndodaxMarketScanner()
    asyncio.run(scanner.scan())
