import os
import json
import time
import socket
from datetime import datetime, timezone
from typing import List, Dict, Any, Sequence
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

class GlobalScannerMesh:
    def __init__(self, scanners: Sequence[Any] | None = None, interval_s: int | None = None):
        self.interval_s = int(interval_s or os.getenv("SCAN_INTERVAL_S", "5")) # Faster scan (5s)
        self.scanners: List[Any] = list(scanners or self._build_scanners())
        
        self.batam_host = "168.110.201.228"
        self.batam_port = 9998
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.last_prices = {} # For Delta Filtering
        self.seq_id = 0

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
        except: pass
        return {"signals": signals}

    def run_once(self) -> None:
        self.seq_id += 1
        started_at = time.time()
        all_signals = []

        with ThreadPoolExecutor(max_workers=15) as executor:
            results = list(executor.map(self._scan_one, self.scanners))
        for res in results:
            all_signals.extend(res["signals"])

        if not all_signals: return

        payload = json.dumps({
            "seq_id": self.seq_id,
            "ts": int(started_at * 1000),
            "signals": all_signals
        }).encode("utf-8")
        
        # UDP REDUNDANCY: Send twice to prevent packet loss
        for _ in range(2):
            self.udp_sock.sendto(payload, (self.batam_host, self.batam_port))
        
        print(f"[SCANNER] Seq:{self.seq_id} | Sent {len(all_signals)} changed signals to Batam.")

    def _heartbeat_worker(self):
        """Send health heartbeat to Batam every 10s."""
        while True:
            try:
                payload = json.dumps({
                    "type": "HEARTBEAT",
                    "node": "SCANNER_TOKYO",
                    "ts": int(time.time() * 1000),
                    "status": "ONLINE"
                }).encode("utf-8")
                self.udp_sock.sendto(payload, (self.batam_host, self.batam_port))
            except: pass
            time.sleep(10)

    def run(self) -> None:
        import threading
        # Start heartbeat in background
        threading.Thread(target=self._heartbeat_worker, daemon=True).start()
        
        while True:
            t0 = time.time()
            self.run_once()
            time.sleep(max(0.1, float(self.interval_s) - (time.time() - t0)))

if __name__ == "__main__":
    scanner = GlobalScannerMesh()
    scanner.run()
