import requests, time, json, socket, math

BATAM_HOST = "168.110.201.228"
BATAM_PORT = 9998
GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_API   = "https://clob.polymarket.com"

class PolymarketFullScanner:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seen_markets = {}  # market_id → last_prob untuk deteksi pergeseran

    def fetch_all_markets(self, limit=500):
        """Ambil semua market aktif dari Gamma API."""
        try:
            r = requests.get(
                f"{GAMMA_API}/markets",
                params={"active": True, "closed": False, "limit": limit,
                        "order": "volume24hr", "ascending": False},
                timeout=12
            )
            return r.json() if r.status_code == 200 else []
        except:
            return []

    def get_market_spread(self, condition_id: str) -> float:
        """Ambil spread dari CLOB (best ask - best bid)."""
        try:
            r = requests.get(f"{CLOB_API}/book?token_id={condition_id}", timeout=4)
            data = r.json()
            best_bid = float(data["bids"][0]["price"]) if data.get("bids") else 0
            best_ask = float(data["asks"][0]["price"]) if data.get("asks") else 1
            return round(best_ask - best_bid, 4)
        except:
            return 1.0  # Spread max = tidak tradeable

    def confidence_score(self, market: dict) -> float:
        """
        Score 0-1. Faktor:
        - Volume (lebih tinggi = lebih liquid)  
        - Spread (lebih kecil = lebih tradeable)
        - Time to resolution (terlalu dekat = decay, terlalu jauh = discount)
        - Probability extremes (dekat 0 atau 1 = kurang peluang)
        - Probability shift dari terakhir kita lihat (momentum)
        """
        now = time.time()

        vol = float(market.get("volumeNum", 0) or market.get("volume", 0) or 0)
        liquidity = float(market.get("liquidityNum", 0) or market.get("liquidity", 0) or 0)
        outcomes = market.get("outcomes", [])

        # Ambil best outcome probability
        best_prob = 0.5
        if outcomes and isinstance(outcomes, list):
            try:
                probs = [float(o.get("price", 0.5)) for o in outcomes if isinstance(o, dict)]
                best_prob = max(probs) if probs else 0.5
            except:
                pass

        # Time to resolution
        end_date = market.get("endDate") or market.get("endDateIso")
        hours_to_end = 999.0
        if end_date:
            try:
                import datetime
                end_ts = datetime.datetime.fromisoformat(end_date.replace("Z", "+00:00")).timestamp()
                hours_to_end = max(0.0, (end_ts - now) / 3600)
            except:
                pass

        # Volume score (log scale)
        vol_score = min(1.0, math.log10(max(vol, 1)) / 7)  # 10M volume = 1.0

        # Liquidity score
        liq_score = min(1.0, math.log10(max(liquidity, 1)) / 6)

        # Time window score — optimum 1 jam sampai 7 hari
        if hours_to_end < 0.5:
            time_score = 0.0   # Hampir expired
        elif hours_to_end < 2:
            time_score = 0.4   # Terlalu mepet
        elif hours_to_end < 168:  # 1 minggu
            time_score = 1.0
        elif hours_to_end < 720:  # 1 bulan
            time_score = 0.7
        else:
            time_score = 0.4   # Terlalu jauh

        # Probability edge score — kita cari yang masih ada value (20-80%)
        prob_edge = 1.0 - abs(best_prob - 0.5) * 2  # 0 di 0% atau 100%, 1 di 50%
        prob_score = max(0.1, prob_edge)

        # Momentum: apakah probabilitas bergerak signifikan?
        market_id = market.get("conditionId") or market.get("id", "")
        prev_prob  = self.seen_markets.get(market_id, best_prob)
        prob_shift = abs(best_prob - prev_prob)
        momentum_score = min(1.0, prob_shift * 20)  # shift 5% = momentum 1.0
        self.seen_markets[market_id] = best_prob

        # Weighted composite
        score = (
            vol_score * 0.30 +
            liq_score * 0.25 +
            time_score * 0.20 +
            prob_score * 0.15 +
            momentum_score * 0.10
        )
        return round(min(1.0, score), 4)

    def scan(self):
        markets = self.fetch_all_markets()
        if not markets:
            return

        signals = []
        for m in markets:
            score = self.confidence_score(m)
            if score < 0.35:
                continue  # Filter pasar yang tidak menarik

            market_id = m.get("conditionId") or m.get("id", "")
            question  = m.get("question", "Unknown")[:80]
            best_yes  = 0.5
            outcomes  = m.get("outcomes", [])
            if outcomes and isinstance(outcomes, list):
                try:
                    probs = [(float(o.get("price", 0.5)), o.get("outcome", "")) for o in outcomes if isinstance(o, dict)]
                    best_yes = max(probs, key=lambda x: x[0])[0]
                except:
                    pass

            sig = {
                "type": "POLYMARKET_OPPORTUNITY",
                "s": f"POLY:{market_id[:12]}",
                "symbol": f"POLY:{market_id[:12]}",
                "base_symbol": "POLY",
                "exchange": "POLYMARKET",
                "meta": {
                    "market_id": market_id,
                    "question": question,
                    "best_prob": best_yes,
                    "confidence_score": score,
                    "volume": m.get("volumeNum", 0),
                    "liquidity": m.get("liquidityNum", 0),
                    "end_date": m.get("endDate", ""),
                    "category": m.get("category", "other"),
                    "outcome_index": 0,
                },
                "price": best_yes,
                "obi": score,   # Gunakan confidence score sebagai proxy OBI
                "regime": "POLYMARKET_SIGNAL",
                "ts": int(time.time() * 1000),
                "sentAtEpochMs": int(time.time() * 1000),
            }
            signals.append(sig)

        # Sort by confidence, kirim top 20
        signals.sort(key=lambda x: x["obi"], reverse=True)
        top_signals = signals[:20]

        if top_signals:
            payload = json.dumps({
                "seq_id": int(time.time()),
                "ts": int(time.time() * 1000),
                "signals": top_signals
            }).encode()
            for _ in range(2):
                self.sock.sendto(payload, (BATAM_HOST, BATAM_PORT))
            print(f"[POLY-SCANNER] Sent {len(top_signals)} opportunities (of {len(signals)} scored)")

    def run(self):
        print("[POLYMARKET-FULL] Full market scanner started")
        while True:
            try:
                self.scan()
            except Exception as e:
                print(f"[POLY-SCANNER] Error: {e}")
            time.sleep(120)  # Scan tiap 2 menit

if __name__ == "__main__":
    PolymarketFullScanner().run()
