"""KiIndodax — Indodax Conviction Scanner | SCANNER source scanner."""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone

from ki_scanner_base import KiScannerBase


class KiIndodaxScanner(KiScannerBase):
    API = "https://indodax.com/api/tickers"

    def __init__(self):
        super().__init__("INDODAX", 8793)

    def _fetch_tickers(self) -> dict:
        try:
            req = urllib.request.Request(self.API, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            tickers = payload.get("tickers", payload)
            return tickers if isinstance(tickers, dict) else {}
        except Exception as error:
            print(f"[INDODAX] ticker fetch error: {error}")
            return {}

    def collect_signals(self) -> dict:
        tickers = self._fetch_tickers()
        signals = []

        for pair, data in tickers.items():
            pair_id = str(pair).lower()
            if not pair_id.endswith("_idr"):
                continue

            try:
                last = float(data.get("last", 0) or 0)
                buy = float(data.get("buy", 0) or 0)
                sell = float(data.get("sell", 0) or 0)
                high = float(data.get("high", last) or last)
                low = float(data.get("low", last) or last)
                vol_idr = float(data.get("vol_idr", 0) or 0)
            except Exception:
                continue

            if last <= 0 or vol_idr < 50_000_000:
                continue

            spread = ((sell - buy) / last) if last > 0 and buy > 0 else 1.0
            price_range = max(high - low, 1e-9)
            range_score = max(0.0, min(1.0, (last - low) / price_range))
            vol_score = max(0.0, min(1.0, vol_idr / 1_000_000_000))
            spread_score = max(0.0, 1.0 - min(spread / 0.02, 1.0))
            conviction = round((range_score * 0.45) + (vol_score * 0.40) + (spread_score * 0.15), 4)

            if conviction < 0.85:
                continue

            base_symbol = pair_id.replace("_idr", "").upper()
            change_24h = round(min(49.0, range_score * 49.0), 3)
            change_1h = round(min(15.0, max(1.0, conviction * 10.0)), 3)
            weight = self.weights.get(self.exchange, 0.10)

            signals.append(
                {
                    "exchange": self.exchange,
                    "base_symbol": base_symbol,
                    "pair_indodax": pair_id,
                    "price": last,
                    "vol_usdt_24h": vol_idr,
                    "change_24h": change_24h,
                    "change_1h": change_1h,
                    "detection_score": conviction,
                    "weight": weight,
                    "weighted_contrib": round(weight * conviction, 4),
                    "conviction": conviction,
                    "spread_pct": round(spread * 100.0, 3),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        return {"scanned": len(tickers), "signals": signals}

    def run(self):
        while True:
            started = time.time()
            result = self.collect_signals()
            signals = result.get("signals") if isinstance(result, dict) else []
            if isinstance(signals, list) and signals:
                print(f"[INDODAX] {len(signals)} signals | scanned={result.get('scanned', 0)}", flush=True)
                for signal in signals:
                    self.send_signal(signal)
            elapsed = time.time() - started
            time.sleep(max(1, self.scan_interval - elapsed))


if __name__ == "__main__":
    KiIndodaxScanner().run()
