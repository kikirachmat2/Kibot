import logging
from typing import Dict, Any, List

logger = logging.getLogger("KiBotMicrostructure")

class IndodaxMicrostructureAnalyzer:
    def __init__(self, taker_fee_pct: float = 0.51):
        """
        Initialize the Microstructure Analyzer.
        
        Args:
            taker_fee_pct: The taker fee percentage for Indodax (default 0.51%).
        """
        self.taker_fee_pct = taker_fee_pct / 100.0  # e.g., 0.0051

    def analyze_liquidity(self, orderbook: Dict[str, Any], target_size_idr: float = 10000000.0) -> Dict[str, Any]:
        """
        Analyze order book to calculate spread, slippage, fill price, depth scores, and exit liquidity.
        
        Args:
            orderbook: dict containing "buy"/"bids" and "sell"/"asks" as lists of [price, amount] or similar.
            target_size_idr: target size in IDR to estimate average fill price and slippage.
            
        Returns:
            dict with microstructure telemetry.
        """
        telemetry = {
            "spread_bid_ask": 0.0,
            "spread_pct": 0.0,
            "bid_price": 0.0,
            "ask_price": 0.0,
            "avg_fill_price": 0.0,
            "slippage_pct": 0.0,
            "depth_score": 0.0,
            "net_yield_pct": 0.0,
            "pass_liquidity": False,
            "reason": ""
        }
        
        # Get bids and asks lists. Indodax orderbook keys can be "bids"/"asks" or "buy"/"sell"
        bids = orderbook.get("bids", orderbook.get("buy", []))
        asks = orderbook.get("asks", orderbook.get("sell", []))
        
        if not bids or not asks:
            telemetry["reason"] = "Empty order book bids or asks."
            return telemetry
            
        try:
            # bids and asks are list of [price, amount] or [price, amount, ...]
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            
            telemetry["bid_price"] = best_bid
            telemetry["ask_price"] = best_ask
            
            spread = best_ask - best_bid
            telemetry["spread_bid_ask"] = spread
            mid_price = (best_bid + best_ask) / 2.0
            if mid_price > 0:
                telemetry["spread_pct"] = (spread / mid_price) * 100.0
                
            # Estimate slippage for buying with target_size_idr (taking from asks)
            total_idr_filled = 0.0
            total_coin_filled = 0.0
            
            for ask in asks:
                ask_price = float(ask[0])
                ask_amount = float(ask[1])
                ask_volume_idr = ask_price * ask_amount
                
                remaining_idr = target_size_idr - total_idr_filled
                if remaining_idr <= 0:
                    break
                    
                fill_idr = min(remaining_idr, ask_volume_idr)
                fill_coin = fill_idr / ask_price
                
                total_idr_filled += fill_idr
                total_coin_filled += fill_coin
                
            if total_coin_filled > 0:
                avg_fill_price = total_idr_filled / total_coin_filled
                telemetry["avg_fill_price"] = avg_fill_price
                
                # Slippage relative to best ask
                if best_ask > 0:
                    telemetry["slippage_pct"] = ((avg_fill_price - best_ask) / best_ask) * 100.0
            else:
                telemetry["reason"] = "Insufficient liquidity to fill target size."
                return telemetry
                
            # Calculate Depth Score (cumulative volume in top 10 price levels)
            depth_volume_idr = 0.0
            for ask in asks[:10]:
                depth_volume_idr += float(ask[0]) * float(ask[1])
            for bid in bids[:10]:
                depth_volume_idr += float(bid[0]) * float(bid[1])
            telemetry["depth_score"] = depth_volume_idr
            
            # exit liquidity check (e.g. if slippage is less than 1.5% and depth score is sufficient)
            max_allowed_slippage = 1.5
            if telemetry["slippage_pct"] <= max_allowed_slippage and depth_volume_idr >= target_size_idr * 1.5:
                telemetry["pass_liquidity"] = True
            else:
                telemetry["reason"] = f"High slippage ({telemetry['slippage_pct']:.2f}%) or low depth score ({depth_volume_idr:.2f} IDR)."
                
        except Exception as e:
            telemetry["reason"] = f"Microstructure calculations failed: {e}"
            
        return telemetry

    def calculate_net_yield(self, gross_yield_pct: float, slippage_pct: float) -> float:
        """
        Calculate net yield after slippage and taking fees into account.
        
        Args:
            gross_yield_pct: The gross yield percentage of the opportunity.
            slippage_pct: Estimated fill slippage percentage.
            
        Returns:
            float: Net yield percentage.
        """
        # Indodax fee is 0.51% for taker orders.
        # Net Yield = Gross Yield - Slippage - (Taker Fee * 2 for enter and exit)
        total_fees = self.taker_fee_pct * 2 * 100.0
        return gross_yield_pct - slippage_pct - total_fees
