import requests, time, json, math
import logging

logger = logging.getLogger("PolymarketScanner")

GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_API   = "https://clob.polymarket.com"

class PolymarketFullScanner:
    def __init__(self):
        self.exchange = "POLYMARKET"
        self.seen_markets = {}  # market_id → last_prob untuk deteksi pergeseran
        self.spread_cache = {}  # market_id -> (spread, ts)
        self.SPREAD_CACHE_TTL = 300 # 5 minutes

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
        except Exception as e:
            logger.error(f"Fetch Gamma markets failed: {e}")
            return []

    def get_market_spread(self, condition_id: str) -> float:
        """Ambil spread dari CLOB (best ask - best bid) dengan caching."""
        now = time.time()
        if condition_id in self.spread_cache:
            spread, ts = self.spread_cache[condition_id]
            if now - ts < self.SPREAD_CACHE_TTL:
                return spread

        try:
            r = requests.get(f"{CLOB_API}/book?token_id={condition_id}", timeout=4)
            data = r.json()
            best_bid = float(data["bids"][0]["price"]) if data.get("bids") else 0
            best_ask = float(data["asks"][0]["price"]) if data.get("asks") else 1
            spread = round(best_ask - best_bid, 4)
            self.spread_cache[condition_id] = (spread, now)
            return spread
        except:
            return 1.0  # Spread max = tidak tradeable

    def confidence_score(self, market: dict) -> float:
        now = time.time()
        vol = float(market.get("volumeNum", 0) or market.get("volume", 0) or 0)
        liquidity = float(market.get("liquidityNum", 0) or market.get("liquidity", 0) or 0)
        outcomes = market.get("outcomes", [])

        # Ambil best outcome probability
        best_prob = 0.5
        # Priority 1: outcomePrices (Usually list of strings)
        outcome_prices = market.get("outcomePrices", [])
        if outcome_prices:
            try:
                probs = [float(p) for p in outcome_prices]
                best_prob = max(probs) if probs else 0.5
            except: pass
        
        # Priority 2: outcomes list (List of dicts)
        if best_prob == 0.5 and outcomes and isinstance(outcomes, list):
            try:
                probs = [float(o.get("price", 0.5)) for o in outcomes if isinstance(o, dict)]
                if probs: best_prob = max(probs)
            except: pass
        
        market["_best_prob"] = best_prob

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

        vol_score = min(1.0, math.log10(max(vol, 1)) / 7)
        liq_score = min(1.0, math.log10(max(liquidity, 1)) / 6)

        if hours_to_end < 0.5:
            time_score = 0.0
        elif hours_to_end < 2:
            time_score = 0.4
        elif hours_to_end < 168:
            time_score = 1.0
        elif hours_to_end < 720:
            time_score = 0.7
        else:
            time_score = 0.4

        prob_edge = 1.0 - abs(best_prob - 0.5) * 2
        prob_score = max(0.1, prob_edge)

        market_id = market.get("conditionId") or market.get("id", "")
        prev_prob  = self.seen_markets.get(market_id, best_prob)
        prob_shift = best_prob - prev_prob
        momentum_score = max(0.0, min(1.0, prob_shift * 20))
        self.seen_markets[market_id] = best_prob

        spread = self.get_market_spread(market_id)
        if spread > 0.25:
            return 0.0
        
        spread_score = max(0.0, 1.0 - (spread / 0.15))
        
        score = (
            (float(vol_score) * 0.25) +
            (float(liq_score) * 0.20) +
            (float(time_score) * 0.18) +
            (float(spread_score) * 0.15) +
            (float(prob_score) * 0.12) +
            (float(momentum_score) * 0.10)
        )
        return round(min(1.0, score), 4)

    def collect_signals(self):
        """Standard interface for ScannerEngine."""
        markets = self.fetch_all_markets()
        if not markets:
            return {"signals": []}

        signals = []
        for m in markets:
            score = self.confidence_score(m)
            if score < 0.35:
                continue

            market_id = m.get("conditionId") or m.get("id", "")
            question  = m.get("question", "Unknown")[:80]
            
            # Use already calculated best_prob if available
            best_yes = m.get("_best_prob", 0.5)
            if best_yes == 0.5:
                prices = m.get("outcomePrices", [])
                try:
                    best_yes = max([float(p) for p in prices]) if prices else 0.5
                except: best_yes = 0.5

            sig = {
                "type": "POLYMARKET_OPPORTUNITY",
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
                "obi": score,
                "regime": "POLYMARKET_SIGNAL",
                "ts": int(time.time() * 1000)
            }
            signals.append(sig)

        signals.sort(key=lambda x: x["obi"], reverse=True)
        return {"signals": signals[:20]}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = PolymarketFullScanner()
    while True:
        res = scanner.collect_signals()
        if res["signals"]:
            print(f"Polymarket Signals: {len(res['signals'])}")
        time.sleep(30)
