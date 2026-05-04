import math
from typing import Iterable, List, Optional, Tuple

# --- Fast Math Utilities ---

def fast_mean(data: List[float]) -> float:
    if not data: return 0.0
    return sum(data) / len(data)

def fast_std(data: List[float], mu: Optional[float] = None) -> float:
    if len(data) < 2: return 0.0
    if mu is None: mu = fast_mean(data)
    variance = sum((x - mu) ** 2 for x in data) / len(data)
    return math.sqrt(variance)

# --- Technical Indicators ---

def calculate_z_score(prices: List[float], period: int = 20) -> float:
    """Calculates Z-Score (Price - SMA) / STD."""
    if len(prices) < period: return 0.0
    window = prices[-period:]
    mu = fast_mean(window)
    sigma = fast_std(window, mu)
    if sigma == 0: return 0.0
    return (prices[-1] - mu) / sigma

def calculate_ema(prices: List[float], period: int = 14) -> float:
    """Exponential Moving Average (EMA)."""
    if len(prices) < period: return fast_mean(prices)
    alpha = 2 / (period + 1)
    ema = fast_mean(prices[:period])
    for price in prices[period:]:
        ema = (price * alpha) + (ema * (1 - alpha))
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Relative Strength Index (RSI) using Wilder's Smoothing."""
    if len(prices) < period + 1: return 50.0
    
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0: return 100.0
    
    # Smoothing
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Average True Range (ATR)."""
    if len(closes) < period + 1: return 0.0
    
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
        
    # Wilders smoothing for ATR
    atr = sum(tr_list[:period]) / period
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
    return atr

def is_anomaly(prices: List[float], threshold: float = 3.0) -> bool:
    """Returns True if Z-Score exceeds threshold (Statistical Anomaly)."""
    return abs(calculate_z_score(prices)) >= threshold

def calculate_obi(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> float:
    """
    Calculates Order Book Imbalance (OBI).
    Formula: (BidVol - AskVol) / (BidVol + AskVol)
    Returns: -1.0 (Heavy Sell Pressure) to 1.0 (Heavy Buy Pressure)
    """
    if not bids or not asks: return 0.0
    bid_vol = sum(vol for price, vol in bids[:5]) # Top 5 levels
    ask_vol = sum(vol for price, vol in asks[:5])
    total_vol = bid_vol + ask_vol
    if total_vol == 0: return 0.0
    return (bid_vol - ask_vol) / total_vol

def detect_regime(prices: List[float], period: int = 50) -> str:
    """
    Classifies Market Regime based on Volatility and Trend.
    - TRENDING_BULL / TRENDING_BEAR
    - SIDEWAYS_VOLATILE (Chop)
    - SIDEWAYS_STABLE (Low Liquidity)
    """
    if len(prices) < 14: return "UNKNOWN"
    period = min(period, len(prices))
    
    window = prices[-period:]
    mu = fast_mean(window)
    std = fast_std(window, mu)
    
    # 1. Volatility Context
    volatility_ratio = (std / mu) * 100 # Coefficient of Variation
    
    # 2. Trend Context (Price vs EMA)
    ema_val = calculate_ema(prices, period=period)
    price_dist = (prices[-1] - ema_val) / ema_val
    
    # Heuristic Thresholds
    is_volatile = volatility_ratio > 0.5
    is_stable = volatility_ratio < 0.15
    
    if is_stable:
        return "SIDEWAYS_STABLE"
        
    if abs(price_dist) > 0.02: # 2% deviation from EMA
        return "TRENDING_BULL" if price_dist > 0 else "TRENDING_BEAR"
        
    if is_volatile:
        return "SIDEWAYS_VOLATILE"
        
    return "SIDEWAYS_NORMAL"

def get_market_session() -> str:
    """Returns the current trading session based on WIB (Asia/Jakarta)."""
    import datetime
    now = datetime.datetime.now()
    hour = now.hour
    
    if 7 <= hour < 14:
        return "ASIA_SESSION"
    elif 14 <= hour < 20:
        return "LONDON_OPEN"
    elif 20 <= hour <= 23 or 0 <= hour < 3:
        return "NY_OPEN"
    else:
        return "QUIET_HOURS"
