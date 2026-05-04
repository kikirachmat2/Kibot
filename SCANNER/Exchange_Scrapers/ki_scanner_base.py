"""
KiBot Trinity — Base Scanner Class
Semua scanner global extend class ini.
Filosofi: scan SEMUA koin, filter berdasarkan kualitas signal, bukan whitelist static.
"""
import json, time, socket, os, requests, asyncio, aiohttp
from typing import Optional, Any
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

MANAGER_HOST = os.environ.get("KIBOT_MANAGER_HOST", "168.110.201.228")
MANAGER_UDP_PORT = int(os.environ.get("KIBOT_UDP_PORT", "9999"))
SCAN_INTERVAL_S = int(os.environ.get("SCAN_INTERVAL_S", "30"))
RUNTIME_ROOT = Path(os.environ.get("KIBOT_RUNTIME_ROOT", str(Path(__file__).resolve().parent.parent)))
SCANNER_STATE_ROOT = Path(
    os.environ.get(
        "KIBOT_SCANNER_STATE_DIR",
        str(RUNTIME_ROOT / "state" / "scanners"),
    )
)

# Semua pair yang terdaftar di Indodax (di-update tiap startup dari API)
_indodax_pairs_cache: dict[str, str] = {}  # base_symbol → pair_id (e.g. "BTC" → "btc_idr")
_indodax_cache_ttl = 0

def fetch_indodax_pairs() -> dict[str, str]:
    """
    Ambil semua pair dari Indodax API secara dinamis.
    Ini memastikan koin baru langsung masuk radar tanpa hardcode.
    Cache 1 jam.
    """
    global _indodax_pairs_cache, _indodax_cache_ttl
    if time.time() < _indodax_cache_ttl and _indodax_pairs_cache:
        return _indodax_pairs_cache

    try:
        r = requests.get("https://indodax.com/api/pairs", timeout=10)
        pairs = r.json()
        result = {}
        for p in pairs:
            pair_id = p.get("ticker_id") or p.get("id") or ""
            base = p.get("traded_currency") or p.get("base_currency") or ""
            quote = p.get("base_currency") or p.get("quote_currency") or p.get("quote") or ""
            if pair_id and base and str(quote).lower() == "idr":
                if "_" not in pair_id and pair_id.lower().endswith("idr"):
                    pair_id = f"{str(base).lower()}_idr"
                result[str(base).upper()] = pair_id
        _indodax_pairs_cache = result
        _indodax_cache_ttl = time.time() + 3600  # cache 1 jam
        print(f"[INDODAX_PAIRS] Loaded {len(result)} pairs from Indodax API")
        return result
    except Exception as e:
        print(f"[INDODAX_PAIRS] Fetch failed: {e}, using cached {len(_indodax_pairs_cache)}")
        return _indodax_pairs_cache


SCANNER_WEIGHTS = {
    "BINANCE":    0.16,
    "BYBIT":      0.14,
    "KUCOIN":     0.10,
    "CRYPTOCOM":   0.08,
    "MEXC":        0.08,
    "GATE":        0.05,
    "HTX":         0.05,
    "OKX":         0.05,
    "BITGET":      0.05,
    "BITBANK":     0.03,
    "BITMART":     0.03,
    "COINBASE":    0.03,
    "LBANK":       0.03,
    "UPBIT":       0.03,
    "PHEMEX":      0.03,
    "BITHUMB":     0.03,
    "WHALE":       0.01,
    "INDODAX":     0.10,
    "POLYMARKET":  0.08,
    "KRAKEN":      0.05,
}


class KiScannerBase(ABC):
    def __init__(self, exchange_name: str, port: int):
        self.exchange = exchange_name.upper()
        self.port = port
        self.weights = SCANNER_WEIGHTS.copy()
        self.msc_min = 0.40
        self.scan_interval = SCAN_INTERVAL_S
        self._vol_history: dict[str, list] = {}
        self._price_history: dict[str, list] = {}
        self._state_file = SCANNER_STATE_ROOT / f"scanner_{self.exchange.lower()}_state.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
        # Load Indodax pairs on startup
        self._indodax_pairs = fetch_indodax_pairs()
        self._refresh_directives()
        print(f"[{self.exchange}] Scanner init — {len(self._indodax_pairs)} Indodax pairs tracked")

    def _refresh_directives(self):
        """Load dynamic weights and thresholds from the Governor."""
        directives_file = RUNTIME_ROOT / "state" / "governor_directives.json"
        if directives_file.exists():
            try:
                with open(directives_file, "r") as f:
                    cfg = json.load(f)
                scanner_cfg = cfg.get("scanner", {})
                if "weights" in scanner_cfg:
                    self.weights.update(scanner_cfg["weights"])
                if "msc_min" in scanner_cfg:
                    self.msc_min = float(scanner_cfg["msc_min"])
                
                # Adaptive Interval: opportunistic mode scans faster
                if cfg.get("strategy_mode") == "OPPORTUNISTIC":
                    self.scan_interval = max(5, SCAN_INTERVAL_S // 3)
                else:
                    self.scan_interval = SCAN_INTERVAL_S
            except Exception as e:
                print(f"[{self.exchange}][WARN] Failed to load directives: {e}")

    @abstractmethod
    def fetch_tickers(self) -> dict:
        """
        Ambil SEMUA ticker dari exchange (bukan hanya pair tertentu).
        Return: {symbol: {price, vol_usdt_24h, change_24h, change_1h}}
        """
        pass

    def symbol_to_indodax(self, base_symbol: str) -> str | None:
        """
        Cross-reference dengan pair Indodax yang di-fetch dynamically.
        Support koin baru tanpa hardcode.
        """
        # Refresh pair list tiap jam
        if time.time() >= _indodax_cache_ttl:
            self._indodax_pairs = fetch_indodax_pairs()
        return self._indodax_pairs.get(base_symbol.upper())

    # ── Volume spike ─────────────────────────────────────────
    def _update_vol(self, pair: str, vol: float):
        h = self._vol_history.setdefault(pair, [])
        h.append(vol); self._vol_history[pair] = h[-10:]

    def _vol_spike_score(self, pair: str, current: float) -> float:
        h = self._vol_history.get(pair, [])
        if not h: return 0.0
        avg = (sum(h[:-1]) / len(h[:-1])) if len(h) > 1 else current
        return min(1.0, (current / avg) / 5.0) if avg > 0 else 0.0

    # ── Signal detection ──────────────────────────────────────
    def detect_signal(self, base_symbol: str, price: float,
                      vol_usdt: float, change_24h: float,
                      change_1h: float = 0.0) -> dict | None:
        pair = self.symbol_to_indodax(base_symbol)
        if not pair:
            return None  # Koin tidak listing di Indodax

        # Universal hard blocks
        if change_24h > 50:
            return None  # Sudah terlambat, pump sudah selesai
        if self.exchange == "MEXC" and change_24h > 30:
            return None  # MEXC: threshold ketat, banyak fake pump
        if self.exchange == "MEXC" and vol_usdt < 2_000_000:
            return None  # MEXC: min $2M volume

        self._update_vol(pair, vol_usdt)
        vol_spike = self._vol_spike_score(pair, vol_usdt)

        # Pump momentum score — optimal range 2-15% 1h change
        if change_1h > 0:
            import math
            mom = math.exp(-((change_1h - 5.0) ** 2) / (2 * 4.0 ** 2))
        else:
            mom = max(0.0, min(0.3, change_24h / 20.0))

        detection_score = vol_spike * 0.60 + mom * 0.40
        if detection_score < 0.30:
            return None

        weight = self.weights.get(self.exchange, 0.10)
        return {
            "exchange":        self.exchange,
            "base_symbol":     base_symbol.upper(),
            "pair_indodax":    pair,
            "price_usdt":      price,
            "vol_usdt_24h":    vol_usdt,
            "change_24h":      round(change_24h, 3),
            "change_1h":       round(change_1h, 3),
            "detection_score": round(detection_score, 3),
            "weight":          weight,
            "weighted_contrib":round(weight * detection_score, 3),
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }

    # ── UDP send ──────────────────────────────────────────────
    def send_signal(self, signal: dict):
        """
        Sends a cryptographically signed signal to the Manager.
        v8.2: Includes HMAC-SHA256 and TTL timestamp.
        """
        try:
            # 1. Prepare base payload
            if not hasattr(self, "_seq_num"): self._seq_num = 0
            self._seq_num += 1
            msg = {
                "type": "MULTI_SCANNER_SIGNAL", 
                "sequence_num": self._seq_num,
                **signal
            }
            
            # 2. Add TTL (Time-To-Live) timestamp
            msg["sentAtEpochMs"] = int(time.time() * 1000)
            
            # 3. HMAC Signing (Paranoid v8.2)
            key = os.environ.get("KIBOT_SIGNAL_KEY", "SOVEREIGN_DEFAULT_SIGNAL_SECRET").encode()
            
            # Reconstruct canonical payload for signing (excluding signature itself)
            # v8.2: Use sort_keys=True to ensure consistency with the Manager's verification logic.
            canonical_payload = json.dumps(msg, separators=(',', ':'), sort_keys=True)
            import hmac, hashlib, base64
            signature = hmac.new(key, canonical_payload.encode(), hashlib.sha256).digest()
            msg["signature"] = base64.b64encode(signature).decode()
            
            payload = json.dumps(msg).encode()
            
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(2.0)
                s.sendto(payload, (MANAGER_HOST, MANAGER_UDP_PORT))
                
        except Exception as e:
            print(f"[{self.exchange}] UDP sign/send err: {e}")

    # ── State persistence ─────────────────────────────────────
    def _load_state(self):
        try:
            if self._state_file.exists():
                s = json.loads(self._state_file.read_text())
                self._vol_history = s.get("vol_history", {})
        except: pass

    def _save_state(self):
        try:
            tmp = str(self._state_file) + ".tmp"
            Path(tmp).write_text(json.dumps({"vol_history": self._vol_history}))
            os.replace(tmp, self._state_file)
        except: pass

    # ── Main loop ─────────────────────────────────────────────
    def run(self):
        print(f"[{self.exchange}] Scanner started "
              f"tracking {len(self._indodax_pairs)} pairs")
        errors = 0
        while True:
            try:
                self._refresh_directives()
                t0 = time.time()
                tickers = self.fetch_tickers()
                sent = 0

                for base_sym, data in tickers.items():
                    sig = self.detect_signal(
                        base_symbol=base_sym,
                        price=data.get("price", 0),
                        vol_usdt=data.get("vol_usdt_24h", 0),
                        change_24h=data.get("change_24h", 0),
                        change_1h=data.get("change_1h", 0),
                    )
                    if sig:
                        self.send_signal(sig); sent += 1

                elapsed = time.time() - t0
                if sent > 0:
                    print(f"[{self.exchange}] {sent} signals | "
                          f"{len(tickers)} scanned | {elapsed:.1f}s")
                errors = 0
                self._save_state()
                time.sleep(max(1, self.scan_interval - elapsed))

            except Exception as e:
                errors += 1
                wait = min(120, 15 * errors)
                print(f"[{self.exchange}] Error #{errors}: {e} — retry in {wait}s")
                time.sleep(wait)

class KiScannerBaseAsync(KiScannerBase):
    """
    v9.0 Sovereign Perfection Upgrade:
    Asynchronous version of the base scanner for high-frequency WebSockets.
    """
    def __init__(self, exchange_name: str, port: int):
        super().__init__(exchange_name, port)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    async def send_signal_async(self, signal: dict):
        """Async version of UDP signal transmission."""
        try:
            msg = {"type": "MULTI_SCANNER_SIGNAL", **signal}
            msg["sentAtEpochMs"] = int(time.time() * 1000)
            
            key = os.environ.get("KIBOT_SIGNAL_KEY", "SOVEREIGN_DEFAULT_SIGNAL_SECRET").encode()
            canonical_payload = json.dumps(msg, separators=(',', ':'), sort_keys=True)
            import hmac, hashlib, base64
            signature = hmac.new(key, canonical_payload.encode(), hashlib.sha256).digest()
            msg["signature"] = base64.b64encode(signature).decode()
            
            payload = json.dumps(msg).encode()
            
            # Non-blocking UDP send
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            try:
                sock.sendto(payload, (MANAGER_HOST, MANAGER_UDP_PORT))
            finally:
                sock.close()
                
        except Exception as e:
            print(f"[{self.exchange}] UDP async send err: {e}")

    async def run_async(self):
        """Main async loop for WebSocket or High-Frequency Polling."""
        print(f"[{self.exchange}] Async Scanner v9.0 active.")
        while True:
            try:
                # Subclasses should implement their own infinite loop or WS handler here
                await self.handle_async_logic()
            except Exception as e:
                print(f"[{self.exchange}] Async Runtime Err: {e}")
                await asyncio.sleep(10)

    @abstractmethod
    async def handle_async_logic(self):
        pass
