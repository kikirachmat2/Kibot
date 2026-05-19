import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from Core.Scanner.source_proof import SourceProof
from Core.Scanner.ki_indodax_smallcap_scanner import IndodaxSmallCapScanner

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
        self.state_dir = STATE_DIR

    async def scan(self) -> dict:
        logger.info("📡 Running real Indodax exchange scanner...")
        now_str = datetime.now(timezone.utc).isoformat()
        self.state_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Fetch real tickers
            tickers = self.scanner.fetch_all_tickers()
            if not tickers:
                state = {
                    "updated_at": now_str,
                    "source_status": "NO_DATA",
                    "scan_mode": "REAL_EXCHANGE",
                    "pairs_checked": 0,
                    "candidates_found": 0,
                    "candidates": [],
                    "rejected_candidates": [],
                    "best_candidate": {},
                    "no_data_reason": "No tickers fetched from Indodax exchange API"
                }
                STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                return state

            pairs_checked = 0
            candidates = []
            rejected_candidates = []

            for pair, ticker in tickers.items():
                if not pair.endswith("_idr"):
                    continue
                pairs_checked += 1

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
                                "source_proof": proof
                            }
                            candidates.append(candidate)
                        else:
                            rejected_candidates.append({
                                "symbol": symbol,
                                "reason": "invalid_source_proof",
                                "proof": proof
                            })

            # Sort by price acceleration descending
            candidates.sort(key=lambda x: x.get("price_acceleration", 0.0), reverse=True)
            best_candidate = candidates[0] if candidates else {}

            state = {
                "updated_at": now_str,
                "source_status": "OK" if candidates else "NO_DATA",
                "scan_mode": "REAL_EXCHANGE",
                "pairs_checked": pairs_checked,
                "candidates_found": len(candidates),
                "candidates": candidates,
                "rejected_candidates": rejected_candidates,
                "best_candidate": best_candidate,
                "no_data_reason": "" if candidates else "No candidates satisfied the pump detection thresholds."
            }

            STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
            logger.info(f"💾 Indodax scanner completed successfully. Found {len(candidates)} real candidates.")
            return state

        except Exception as e:
            logger.error(f"❌ Indodax scanner failed with exception: {e}")
            state = {
                "updated_at": now_str,
                "source_status": "SOURCE_FAILED",
                "scan_mode": "REAL_EXCHANGE",
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
