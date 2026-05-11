import os
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
import time
import socket
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Sequence
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("KiBotScanner")

class ScannerEngine:
    def __init__(self, scanners: Sequence[Any] | None = None, interval_s: int | None = None):
        self.interval_s = int(interval_s or os.getenv("SCAN_INTERVAL_S", "5"))
        self.scanners: List[Any] = list(scanners or self._build_scanners())
        
        # Now centralized on localhost (Batam Internal)
        self.target_host = "127.0.0.1"
        self.target_port = 9998
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.last_prices = {} # For Delta Filtering
        self.seq_id = 0
        self.is_running = True

    def _build_scanners(self):
        """Builds default scanners if none provided."""
        scanners = []
        try:
            from Core.Scanner.ki_indodax_smallcap_scanner import IndodaxSmallCapScanner
            scanners.append(IndodaxSmallCapScanner())
            logger.info("✅ Indodax SmallCap Scanner integrated.")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Indodax scanner: {e}")
            
        try:
            from Core.Scanner.ki_polymarket_full_scanner import PolymarketFullScanner
            scanners.append(PolymarketFullScanner())
            logger.info("✅ Polymarket Full Scanner integrated.")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Polymarket scanner: {e}")

        try:
            from Core.Scanner.ki_universal_leadlag_scanner import UniversalLeadLagScanner
            scanners.append(UniversalLeadLagScanner())
            logger.info("✅ Universal Lead-Lag Scanner (18+ Sources) integrated.")
        except Exception as e:
            logger.error(f"⚠️ Failed to build Universal scanner: {e}")
            
        return scanners

    def _scan_one(self, scanner: Any) -> Dict[str, Any]:
        exchange = str(getattr(scanner, "exchange", "UNKNOWN")).upper()
        signals = []
        try:
            res = scanner.collect_signals()
            raw_signals = res.get("signals", []) if isinstance(res, dict) else res
            for s in raw_signals:
                s["exchange"] = exchange
                
                # DELTA FILTERING: Only send if price changed
                uid = f"{exchange}:{s.get('base_symbol')}"
                current_price = s.get('price_usdt', 0)
                if uid in self.last_prices and self.last_prices[uid] == current_price:
                    continue 
                
                self.last_prices[uid] = current_price
                signals.append(s)
        except Exception as e:
            logger.debug(f"Scan error for {exchange}: {e}")
        return {"signals": signals}

    def run_once(self) -> None:
        """Single scanning cycle."""
        self.universal_signals = []
        self.seq_id += 1
        started_at = time.time()
        
        from Core.Support.ki_config import KiConfig
        
        with ThreadPoolExecutor(max_workers=15) as executor:
            results = list(executor.map(self._scan_one, self.scanners))
            
        # Group signals by destination
        indo_signals = []
        poly_signals = []
        
        for res in results:
            for s in res["signals"]:
                ex = s.get("exchange")
                if ex == "INDODAX":
                    indo_signals.append(s)
                elif ex == "POLYMARKET":
                    poly_signals.append(s)
                elif ex == "UNIVERSAL_LEAD":
                    if not hasattr(self, 'universal_signals'): self.universal_signals = []
                    self.universal_signals.append(s)

        from Core.Support.ki_utils import sign_payload
        secret = os.environ.get("KIBOT_SECRET", "default_sovereign_secret")

        # Dispatch Indodax
        if indo_signals:
            data = {
                "seq_id": self.seq_id,
                "ts": int(started_at * 1000),
                "signals": indo_signals
            }
            payload = json.dumps({
                "data": data,
                "signature": sign_payload(data, secret)
            }).encode("utf-8")
            self.udp_sock.sendto(payload, (self.target_host, KiConfig.INDO_SIGNAL_PORT))
            logger.debug(f"[SCANNER] Seq:{self.seq_id} | Dispatched {len(indo_signals)} HMAC-signed INDO signals.")

        # Dispatch Polymarket
        if poly_signals:
            data = {
                "seq_id": self.seq_id,
                "ts": int(started_at * 1000),
                "signals": poly_signals
            }
            payload = json.dumps({
                "data": data,
                "signature": sign_payload(data, secret)
            }).encode("utf-8")
            self.udp_sock.sendto(payload, (self.target_host, KiConfig.POLY_SIGNAL_PORT))
            logger.debug(f"[SCANNER] Seq:{self.seq_id} | Dispatched {len(poly_signals)} HMAC-signed POLY signals.")

        # NEW: Dispatch to MasterNode (Council) for high-level deliberation
        all_signals = indo_signals + poly_signals + getattr(self, 'universal_signals', [])
        if all_signals:
            data = {
                "type": "COUNCIL_SIGNAL_DATA",
                "signals": all_signals,
                "ts": int(started_at * 1000)
            }
            payload = json.dumps({
                "data": data,
                "signature": sign_payload(data, secret)
            }).encode("utf-8")
            # Port 9991 is the Command Plane / Council Egress
            self.udp_sock.sendto(payload, ("127.0.0.1", 9991))
            logger.info(f"🧠 Dispatched {len(all_signals)} HMAC-signed signals to Sovereign Council.")

    def run(self) -> None:
        logger.info("🚀 KiBot Centralized Scanner Engine Started.")
        while self.is_running:
            t0 = time.time()
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Scanner Runtime Error: {e}")
            time.sleep(max(0.1, float(self.interval_s) - (time.time() - t0)))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = ScannerEngine()
    scanner.run()
