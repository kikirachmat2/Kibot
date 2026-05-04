# ═══════════════════════════════════════════════════════════
# MULTI-SCANNER CONFIDENCE SCORE (MSC) ENGINE
# ═══════════════════════════════════════════════════════════

import time, json, os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCANNER_WEIGHTS = {
    "BINANCE": 0.16, "BYBIT": 0.14, "KUCOIN": 0.10,
    "CRYPTOCOM": 0.08, "MEXC": 0.08, "GATE": 0.05,
    "HTX": 0.05, "OKX": 0.05, "BITGET": 0.05,
    "BITBANK": 0.03, "BITMART": 0.03, "COINBASE": 0.03,
    "LBANK": 0.03, "UPBIT": 0.03, "PHEMEX": 0.03,
    "BITHUMB": 0.03, "WHALE": 0.01, "INDODAX": 0.10,
    "POLYMARKET": 0.08, "KRAKEN": 0.05
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
    Relay ke KiBot untuk eksekusi nyata.
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
        if "BINANCE" in scanners and "BYBIT" in scanners:
            reason += "+binance_bybit_confirmed"

        # Ambil metadata terbaik dari signal (untuk pass ke KiBot)
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
        Full pipeline: ingest → compute → relay ke KiBot jika ENTRY.
        relay_fn = fungsi yang kirim signal ke KiBot via UDP.
        """
        self.ingest(msg)
        pair = msg.get("pair_indodax", "")
        if not pair: return

        analysis = self.compute_msc(pair)
        if analysis["action"] != "ENTRY": return

        # Relay ke KiBot dengan semua informasi yang dibutuhkan
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


# ── Wrap KiBot (existing) signal ke format baru ──────────
def wrap_KiBot_to_msc(KiBot_signal: dict) -> dict:
    """
    Convert signal lama dari KiBot (Kotlin) ke format MULTI_SCANNER_SIGNAL.
    Backward compatible — KiBot tidak perlu diubah.
    """
    return {
        "type":            "MULTI_SCANNER_SIGNAL",
        "exchange":        "BINANCE",
        "base_symbol":     KiBot_signal.get("pair", "").replace("_idr", "").upper(),
        "pair_indodax":    KiBot_signal.get("pair", ""),
        "change_24h":      KiBot_signal.get("shortTermReturnPct", 0),
        "change_1h":       KiBot_signal.get("shortTermReturnPct", 0),
        "vol_usdt_24h":    KiBot_signal.get("volumeUsdt", 0),
        "detection_score": KiBot_signal.get("confidence", 0.5),
        "weight":          SCANNER_WEIGHTS["BINANCE"],
        "weighted_contrib":SCANNER_WEIGHTS["BINANCE"] * KiBot_signal.get("confidence", 0.5),
        "timestamp":       datetime.now(timezone.utc).isoformat(),
    }
