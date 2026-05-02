"""KiPolymarket — Polymarket crypto scanner for SCANNER."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ki_scanner_base import KiScannerBase
from kibot_polymarket import ENGINE as POLYMARKET_ENGINE


class KiPolymarketScanner(KiScannerBase):
    def __init__(self):
        super().__init__("POLYMARKET", 8794)

    def collect_signals(self) -> dict:
        state = POLYMARKET_ENGINE.refresh_state()
        alpha_candidates = state.get("alpha_candidates") if isinstance(state.get("alpha_candidates"), list) else []
        signals = []

        for item in alpha_candidates:
            mapped_pair = str(item.get("mapped_pair") or "").strip().lower()
            asset = str(item.get("asset") or "").strip().upper()
            direction = str(item.get("direction") or "").strip().upper()
            if not mapped_pair or not asset:
                continue

            score = float(item.get("alpha_score") or item.get("signal_score") or 0.0)
            signal_score = float(item.get("signal_score") or 0.0)
            if score <= 0:
                continue

            weight = self.weights.get(self.exchange, 0.10)
            signals.append(
                {
                    "exchange": self.exchange,
                    "base_symbol": asset,
                    "pair_indodax": mapped_pair,
                    "price": float(item.get("implied_prob_yes") or 0.0),
                    "vol_usdt_24h": float(item.get("liquidity") or item.get("volume24hr") or 0.0),
                    "change_24h": round(min(49.0, score * 49.0), 3),
                    "change_1h": round(min(15.0, max(1.0, signal_score * 15.0)), 3),
                    "detection_score": round(score, 4),
                    "weight": weight,
                    "weighted_contrib": round(weight * score, 4),
                    "direction": direction or "LONG",
                    "market_question": str(item.get("question") or ""),
                    "condition_id": str(item.get("condition_id") or ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        return {"scanned": len(alpha_candidates), "signals": signals, "ready": bool(state.get("analysis_ready"))}

    def run(self):
        while True:
            started = time.time()
            result = self.collect_signals()
            signals = result.get("signals") if isinstance(result, dict) else []
            if isinstance(signals, list) and signals:
                print(f"[POLYMARKET] {len(signals)} signals | scanned={result.get('scanned', 0)}", flush=True)
                for signal in signals:
                    self.send_signal(signal)
            elapsed = time.time() - started
            time.sleep(max(1, self.scan_interval - elapsed))


if __name__ == "__main__":
    KiPolymarketScanner().run()
