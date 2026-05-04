"""KiKraken — Kraken USD market scanner for SCANNER."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from ki_scanner_base import KiScannerBase


class KiKrakenScanner(KiScannerBase):
    ASSET_PAIRS_API = "https://api.kraken.com/0/public/AssetPairs"
    TICKER_API = "https://api.kraken.com/0/public/Ticker"
    TARGET_BASES = [
        "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "DOT", "LINK", "AVAX",
        "LTC", "ATOM", "NEAR", "SUI", "PEPE", "UNI", "TRX", "ARB", "APT", "HBAR",
    ]

    _ASSET_MAP = {
        "XBT": "BTC",
        "XXBT": "BTC",
        "XETH": "ETH",
        "XDG": "DOGE",
        "XXDG": "DOGE",
        "XLTC": "LTC",
        "XREP": "REP",
        "XMR": "XMR",
        "XRP": "XRP",
        "ADA": "ADA",
        "SOL": "SOL",
        "DOT": "DOT",
        "LINK": "LINK",
        "AVAX": "AVAX",
        "ATOM": "ATOM",
        "NEAR": "NEAR",
        "SUI": "SUI",
        "PEPE": "PEPE",
        "UNI": "UNI",
        "TRX": "TRX",
        "ARB": "ARB",
        "APT": "APT",
        "HBAR": "HBAR",
        "BNB": "BNB",
    }

    def __init__(self):
        super().__init__("KRAKEN", 8795)

    @classmethod
    def _normalize_base(cls, raw: str) -> str:
        token = str(raw or "").upper().replace("/", "").replace("Z", "")
        if token in cls._ASSET_MAP:
            return cls._ASSET_MAP[token]
        if token.startswith("XBT"):
            return "BTC"
        if token.startswith("XDG"):
            return "DOGE"
        if token.startswith("XETH"):
            return "ETH"
        if token.startswith("XLTC"):
            return "LTC"
        return token.removeprefix("X").removeprefix("Z")

    def _discover_pairs(self) -> dict[str, str]:
        try:
            payload = requests.get(self.ASSET_PAIRS_API, timeout=15).json()
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            discovered: dict[str, str] = {}
            for pair_name, info in result.items():
                if not isinstance(info, dict):
                    continue
                wsname = str(info.get("wsname") or "")
                if "/USD" not in wsname and "/USDT" not in wsname:
                    continue
                base = self._normalize_base(str(info.get("base") or pair_name))
                if base in self.TARGET_BASES and base not in discovered:
                    discovered[base] = str(info.get("altname") or pair_name)
            return discovered
        except Exception as error:
            print(f"[KRAKEN] pair discovery error: {error}")
            return {}

    def collect_signals(self) -> dict:
        pair_map = self._discover_pairs()
        if not pair_map:
            return {"scanned": 0, "signals": []}

        pair_names = list(pair_map.values())
        signals = []
        scanned = 0
        weight = self.weights.get(self.exchange, 0.10)

        for chunk_start in range(0, len(pair_names), 20):
            batch = pair_names[chunk_start: chunk_start + 20]
            try:
                payload = requests.get(self.TICKER_API, params={"pair": ",".join(batch)}, timeout=15).json()
                ticker_rows = payload.get("result", {}) if isinstance(payload, dict) else {}
            except Exception as error:
                print(f"[KRAKEN] ticker fetch error: {error}")
                continue

            for pair_name, ticker in ticker_rows.items():
                scanned += 1
                base = next((k for k, v in pair_map.items() if v == pair_name), "")
                if not base:
                    continue
                pair_indodax = self.symbol_to_indodax(base)
                if not pair_indodax:
                    continue

                try:
                    last = float((ticker.get("c") or [0, 0])[0] or 0)
                    vol_24h = float((ticker.get("v") or [0, 0])[1] or 0)
                    open_px = float(ticker.get("o") or 0)
                except Exception:
                    continue

                if last <= 0 or vol_24h <= 0:
                    continue

                change_24h = ((last - open_px) / open_px * 100.0) if open_px > 0 else 0.0
                if abs(change_24h) < 0.5 and vol_24h < 10_000_000:
                    continue

                direction = "LONG" if change_24h >= 0 else "SHORT"
                detection_score = round(
                    min(1.0, (abs(change_24h) / 20.0) * 0.6 + min(vol_24h / 100_000_000.0, 1.0) * 0.4),
                    4,
                )
                signals.append(
                    {
                        "exchange": self.exchange,
                        "base_symbol": base,
                        "pair_indodax": pair_indodax,
                        "price": last,
                        "vol_usdt_24h": vol_24h,
                        "change_24h": round(change_24h, 3),
                        "change_1h": round(min(15.0, abs(change_24h) / 2.0), 3),
                        "direction": direction,
                        "detection_score": detection_score,
                        "weight": weight,
                        "weighted_contrib": round(weight * detection_score, 4),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

        return {"scanned": scanned, "signals": signals}

    def run(self):
        while True:
            started = time.time()
            result = self.collect_signals()
            signals = result.get("signals") if isinstance(result, dict) else []
            if isinstance(signals, list) and signals:
                print(f"[KRAKEN] {len(signals)} signals | scanned={result.get('scanned', 0)}", flush=True)
                for signal in signals:
                    self.send_signal(signal)
            elapsed = time.time() - started
            time.sleep(max(1, self.scan_interval - elapsed))


if __name__ == "__main__":
    KiKrakenScanner().run()
