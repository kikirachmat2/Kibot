# ═══════════════════════════════════════════════════════════
# MULTI-SCANNER CONFIDENCE SCORE (MSC) ENGINE
# ═══════════════════════════════════════════════════════════

import time, json, os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCANNER_WEIGHTS = {
    "BINANCE": 0.15, "BYBIT": 0.10, "KUCOIN": 0.10, "OKX": 0.10,
    "BITHUMB": 0.08, "UPBIT": 0.08, "MEXC": 0.07, "GATE": 0.06,
    "BITBANK": 0.05, "BITGET": 0.04, "PHEMEX": 0.04, "BITMART": 0.04,
    "CRYPTOCOM": 0.04, "HTX": 0.03, "LBANK": 0.02
}
ALL_WEIGHT_SUM = sum(SCANNER_WEIGHTS.values())  # = 1.00

SIGNAL_WINDOW_S  = float(os.environ.get("KIBOT_MSC_SIGNAL_WINDOW_S",  "5.0"))
MSC_MIN          = float(os.environ.get("KIBOT_MSC_MIN_THRESHOLD",     "0.60"))
MSC_MEDIUM       = 0.70
MSC_HIGH         = 0.80
MSC_MAX          = 0.90
MEXC_ONLY_BLOCK  = os.environ.get("KIBOT_MEXC_ONLY_BLOCK", "true").lower() == "true"

DIRECTIVES_FILE = Path(os.environ.get("KIBOT_GOVERNOR_FILE", "state/governor_directives.json"))


class MultiScannerEngine:
    """
    Aggregates signals dari semua global scanners.
    Hitung MSC. Buat keputusan entry.
    Relay ke KiDax untuk eksekusi nyata.
    """

    def __init__(self):
        self._cache: dict[str, dict] = defaultdict(dict)
        # {pair_indodax: {exchange: {signal_data, received_at}}}
        self.weights = SCANNER_WEIGHTS.copy()
        self.msc_min = MSC_MIN
        self._last_directive_check = 0.0

    def _refresh_directives(self):
        """Load dynamic overrides from the Governor."""
        now = time.time()
        if now - self._last_directive_check < 60: return # throttle check
        self._last_directive_check = now

        if DIRECTIVES_FILE.exists():
            try:
                data = json.loads(DIRECTIVES_FILE.read_text())
                scanner_cfg = data.get("scanner", {})
                if "weights" in scanner_cfg:
                    self.weights.update(scanner_cfg["weights"])
                if "msc_min" in scanner_cfg:
                    self.msc_min = float(scanner_cfg["msc_min"])
            except Exception as e:
                print(f"[MSC][WARN] Failed to load directives: {e}")

    def ingest(self, msg: dict):
        """Terima satu signal dari UDP."""
        exchange = msg.get("exchange", "").upper()
        pair     = msg.get("pair_indodax", "")
        if not exchange or not pair: return

        # --- LATENCY VALIDATION ---
        sent_at = msg.get("sentAtEpochMs") or (msg.get("timestamp", 0) * 1000)
        if sent_at > 0:
            age_sec = (time.time() * 1000 - sent_at) / 1000
            if age_sec > 10.0: # 10s max age for signal ingestion
                print(f"[MSC][REJECT] Stale signal from {exchange}: age={age_sec:.1f}s")
                return

        self._cache[pair][exchange] = {**msg, "received_at": time.time()}
        self._log(f"[MSC_RECV] {exchange} → {pair} "
                  f"score={msg.get('detection_score',0):.2f} "
                  f"chg24h={msg.get('change_24h',0):.1f}%")

    def _purge(self, pair: str):
        now = time.time()
        if pair not in self._cache: return
        self._cache[pair] = {
            exc: sig for exc, sig in self._cache.get(pair, {}).items()
            if now - sig["received_at"] <= SIGNAL_WINDOW_S
        }

    def compute_msc(self, pair: str) -> dict:
        """Hitung Multi-Scanner Confidence Score untuk pair ini."""
        self._purge(pair)
        active = self._cache.get(pair, {})

        if not active:
            return {"msc": 0.0, "action": "IGNORE", "reason": "no_signals",
                    "position_multiplier": 0.0, "scanners": []}

        scanners = list(active.keys())

        # HARD BLOCK: hanya MEXC = fake pump risk
        if MEXC_ONLY_BLOCK and scanners == ["MEXC"]:
            self._log(f"[MSC_BLOCK] {pair}: MEXC-only signal blocked (fake pump risk)")
            return {"msc": 0.0, "action": "IGNORE", "scanners": scanners,
                    "reason": "mexc_only_blocked", "position_multiplier": 0.0,
                    "is_mexc_only": True}

        # Hitung weighted MSC
        self._refresh_directives()
        
        weight_sum = sum(self.weights.get(exc, 0.10) for exc in scanners)
        if weight_sum <= 0: return {"msc": 0.0, "action": "IGNORE", "reason": "no_weight"}

        weighted = sum(
            self.weights.get(exc, 0.10) * active[exc].get("detection_score", 0.5)
            for exc in scanners
        )
        msc = weighted / weight_sum  # normalize
        msc_min = self.msc_min

        # Tentukan action + position multiplier
        if msc < 0.40:
            action, mult, reason = "IGNORE",     0.0, f"msc_weak:{msc:.3f}"
        elif msc < msc_min:
            action, mult, reason = "WATCHLIST",  0.0, f"msc_below_threshold:{msc:.3f}"
        elif msc < MSC_MEDIUM:
            action, mult, reason = "ENTRY", 0.60, f"entry_cautious:msc={msc:.3f}"
        elif msc < MSC_HIGH:
            action, mult, reason = "ENTRY", 0.80, f"entry_normal:msc={msc:.3f}"
        elif msc < MSC_MAX:
            action, mult, reason = "ENTRY", 1.00, f"entry_standard:msc={msc:.3f}"
        else:
            action, mult, reason = "ENTRY", 1.20, f"entry_high_conviction:msc={msc:.3f}"

        # Bonus confirmation flag
        if "BYBIT" in scanners and "KUCOIN" in scanners:
            reason += "+bybit_kucoin_confirmed"

        # Ambil metadata terbaik dari signal (untuk pass ke KiDax)
        best_sig = max(active.values(), key=lambda s: s.get("detection_score", 0))

        result = {
            "msc":                round(msc, 4),
            "scanner_count":      len(scanners),
            "scanners":           scanners,
            "action":             action,
            "position_multiplier":mult,
            "reason":             reason,
            "pair_indodax":       pair,
            "base_symbol":        best_sig.get("base_symbol", ""),
            "change_24h_avg":     round(
                sum(active[e].get("change_24h", 0) for e in scanners) / len(scanners), 2
            ),
            "vol_usdt_total":     sum(
                active[e].get("vol_usdt_24h", 0) for e in scanners
            ),
            "is_mexc_only":       False,
        }

        self._log(
            f"[MSC] {pair}: {msc:.3f} | {len(scanners)} scanners {scanners} | "
            f"action={action} | mult={mult}x | {reason}"
        )
        return result

    def process_and_relay(self, msg: dict, relay_fn):
        """
        Full pipeline: ingest → compute → relay ke KiDax jika ENTRY.
        relay_fn = fungsi yang kirim signal ke KiDax via UDP.
        """
        self.ingest(msg)
        pair = msg.get("pair_indodax", "")
        if not pair: return

        analysis = self.compute_msc(pair)
        if analysis["action"] != "ENTRY": return

        # Relay ke KiDax dengan semua informasi yang dibutuhkan
        relay_fn({
            "type":               "LEAD_LAG_SIGNAL",
            "pair":               pair,
            "source":             "MULTI_SCANNER",
            "bucket":             "LEAD_LAG",          # Global scanner = Bucket A
            "msc":                analysis["msc"],
            "scanners":           analysis["scanners"],
            "scanner_count":      analysis["scanner_count"],
            "position_multiplier":analysis["position_multiplier"],
            "change_24h":         analysis["change_24h_avg"],
            "vol_usdt_total":     analysis["vol_usdt_total"],
            "reason":             analysis["reason"],
            "confidence":         min(0.99, analysis["msc"] * 1.1),
            "timestamp":          time.time(),
        })

    def _log(self, msg: str):
        print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

    def get_active_pairs(self) -> list[str]:
        """Return semua pair yang punya signal aktif dalam window."""
        return [p for p, signals in self._cache.items() if signals]

    def get_active_signals(self) -> list[dict]:
        """Return all active signals with their MSC analysis."""
        results = []
        for pair in self.get_active_pairs():
            results.append(self.compute_msc(pair))
        results.sort(key=lambda x: x.get("msc", 0), reverse=True)
        return results[:30]

    def save_state_to_disk(self, filepath: str = "state/msc_live_state.json"):
        """Save current active signals and analysis for the dashboard."""
        try:
            results = self.get_active_signals()
            
            import psutil
            output = {
                "timestamp": time.time(),
                "active_signals": results,
                "scanners_weights": self.weights,
                "ram": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage('/').percent
            }
            
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w") as f:
                json.dump(output, f, indent=2)
        except Exception as e:
            print(f"[MSC][ERROR] Failed to save state: {e}")
