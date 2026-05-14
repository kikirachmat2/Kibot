"""
KiBot What-If Simulation Engine v2.0
======================================
Upgraded per PUMP_LIFECYCLE_STRATEGY.md §15.3, §16.3, §16.6

v2 adds:
- Exit simulation (§17.3): sellability, spread risk, slippage, deadline risk
- Missed Opportunity Tracker (§16.3): track rejected signals for learning
- Opportunity Ranking (§16.6): compare multiple candidates
- EV now uses exit_plan awareness

Old simulate_pair() preserved for backward compat with /api/state.whatIfSimulation
"""

import json, time, math, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from Core.Intelligence.kibot_learning_engine import get_engine, ROUND_TRIP_MAKER, ROUND_TRIP_TAKER

WHATIF_PATH    = "state/whatif_results.json"
MISSED_OPP_PATH = "state/missed_opportunities.json"
WIB_TZ = timezone(timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))))
STATE_DIR = Path("state")

# §14: Indodax minimum order (IDR)
MIN_ORDER_IDR = float(os.getenv("KIBOT_MIN_ORDER_IDR", "10000"))


def _now_wib() -> datetime:
    return datetime.now(WIB_TZ)


def _atomic_write(path: str, payload: dict) -> None:
    p   = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(f"{path}.tmp.{os.getpid()}")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(p)


# ─────────────────────────────────────────────
# §17.3 Exit Simulation
# ─────────────────────────────────────────────

def simulate_exit(
    pair: str,
    entry_price: float,
    budget_idr: float,
    spread_pct: Optional[float],
    obi: Optional[float],
    daily_context: Optional[Dict] = None,
) -> Dict:
    """
    §17.3: 'Can KiBot exit cleanly?'
    Must answer: sellability, spread risk, slippage, deadline risk.

    Returns:
      {
        "sellable": bool,
        "min_sellable_size": float,
        "expected_slippage_pct": float,
        "spread_risk": "LOW|MEDIUM|HIGH",
        "deadline_risk": "SAFE|TIGHT|CRITICAL",
        "verdict": "EXIT_OK|EXIT_RISKY|DO_NOT_ENTER"
      }
    """
    result = {
        "sellable":             True,
        "min_sellable_size":    0.0,
        "expected_slippage_pct": 0.0,
        "spread_risk":          "LOW",
        "deadline_risk":        "SAFE",
        "verdict":              "EXIT_OK",
    }

    # Minimum order sellability check
    if entry_price > 0:
        coin_amount = (budget_idr * (1 - ROUND_TRIP_MAKER)) / entry_price
        min_sell_idr = coin_amount * entry_price
        result["min_sellable_size"] = round(coin_amount, 8)
        if min_sell_idr < MIN_ORDER_IDR:
            result["sellable"] = False
            result["verdict"]  = "DO_NOT_ENTER"
            result["spread_risk"] = "HIGH"
            return result

    # Spread risk
    s = spread_pct or 0.0
    if s < 0.4:
        result["spread_risk"] = "LOW"
        result["expected_slippage_pct"] = s * 0.5
    elif s < 0.9:
        result["spread_risk"] = "MEDIUM"
        result["expected_slippage_pct"] = s * 0.8
    else:
        result["spread_risk"] = "HIGH"
        result["expected_slippage_pct"] = s * 1.5

    # OBI exit risk
    if obi is not None and obi < -0.15:
        result["spread_risk"] = "HIGH"
        result["expected_slippage_pct"] += 0.5

    # Deadline risk from daily context
    if daily_context:
        minutes = daily_context.get("minutes_to_midnight", 480)
        if minutes < 30:
            result["deadline_risk"] = "CRITICAL"
        elif minutes < 90:
            result["deadline_risk"] = "TIGHT"
        else:
            result["deadline_risk"] = "SAFE"

    # Verdict
    if result["spread_risk"] == "HIGH" or result["deadline_risk"] == "CRITICAL":
        result["verdict"] = "EXIT_RISKY" if result["sellable"] else "DO_NOT_ENTER"
    elif result["spread_risk"] == "MEDIUM":
        result["verdict"] = "EXIT_RISKY"
    else:
        result["verdict"] = "EXIT_OK"

    result["expected_slippage_pct"] = round(result["expected_slippage_pct"], 4)
    return result


# ─────────────────────────────────────────────
# §16.3 Missed Opportunity Tracker
# ─────────────────────────────────────────────

def record_rejected_signal(
    signal: Dict,
    reject_reason: str,
    reject_confidence: float,
    review_after_minutes: int = 60,
) -> None:
    """
    Record a rejected signal for post-hoc learning.
    The missed opportunity will be reviewed after review_after_minutes.
    """
    entry = {
        "pair":                    signal.get("symbol", "UNKNOWN"),
        "rejected_at":             time.time(),
        "reject_reason":           reject_reason,
        "reject_confidence":       round(reject_confidence, 4),
        "lifecycle":               signal.get("lifecycle", "UNKNOWN"),
        "trade_grade":             signal.get("trade_grade", "UNKNOWN"),
        "price_at_reject":         float(signal.get("price_idr", signal.get("price", 0))),
        "opportunity_score":       signal.get("opportunity_score", 0.0),
        "review_after_ts":         time.time() + review_after_minutes * 60,
        "max_gain_after_reject_pct":  None,
        "max_drawdown_after_reject_pct": None,
        "verdict":                 "PENDING",
        "review_after_minutes":    review_after_minutes,
    }

    # Load existing
    missed = _load_missed_opportunities()
    missed["pending"].append(entry)

    # Keep only last 500 entries total
    if len(missed["pending"]) > 250:
        missed["pending"] = missed["pending"][-250:]
    if len(missed.get("reviewed", [])) > 250:
        missed["reviewed"] = missed["reviewed"][-250:]

    _atomic_write(MISSED_OPP_PATH, missed)


def review_missed_opportunities(current_prices: Dict[str, float]) -> int:
    """
    Check pending missed opportunities against current prices.
    Update verdict for those past their review_after_ts.

    Returns number of opportunities reviewed in this call.
    """
    missed = _load_missed_opportunities()
    now    = time.time()
    reviewed_count = 0

    still_pending = []
    for entry in missed.get("pending", []):
        if now < entry.get("review_after_ts", 0):
            still_pending.append(entry)
            continue

        pair_key = entry["pair"].lower().replace("/", "_")
        current  = current_prices.get(pair_key, 0)
        reject_price = float(entry.get("price_at_reject", 0))

        if current > 0 and reject_price > 0:
            gain_pct     = (current - reject_price) / reject_price * 100
            max_gain_pct = max(0.0, gain_pct)   # simplified (no OHLC post-reject)
            max_dd_pct   = abs(min(0.0, gain_pct))

            entry["max_gain_after_reject_pct"]     = round(max_gain_pct, 2)
            entry["max_drawdown_after_reject_pct"] = round(max_dd_pct, 2)

            # §16.3 verdict
            if max_gain_pct >= 3.0:
                entry["verdict"] = "FALSE_NEGATIVE"
            elif max_dd_pct >= 2.0 and max_gain_pct < 1.0:
                entry["verdict"] = "GOOD_REJECT"
            elif max_gain_pct >= 1.0:
                entry["verdict"] = "STILL_RISKY"
            else:
                entry["verdict"] = "UNKNOWN"
        else:
            entry["verdict"] = "UNKNOWN"

        entry["reviewed_at"] = now
        missed.setdefault("reviewed", []).append(entry)
        reviewed_count += 1

    missed["pending"] = still_pending
    _atomic_write(MISSED_OPP_PATH, missed)
    return reviewed_count


def _load_missed_opportunities() -> Dict:
    try:
        p = Path(MISSED_OPP_PATH)
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return {"pending": [], "reviewed": []}


# ─────────────────────────────────────────────
# Core EV simulation (upgraded)
# ─────────────────────────────────────────────

def simulate_pair(
    pair: str,
    current_price: float,
    win_prob: float = 0.55,
    spread_pct: Optional[float] = None,
    budget_idr: float = 50000,
    daily_context: Optional[Dict] = None,
) -> dict:
    """
    Hitung expected value untuk entry di harga sekarang.
    v2: now includes exit simulation verdict.
    """
    engine = get_engine()
    stats  = engine.get(pair)

    if stats.trade_count >= 3:
        win_prob = stats.win_probability

    bear_prob  = 1 - win_prob
    bull_gross = stats.avg_win  if stats.win_count  > 0 else 0.015
    bear_gross = -abs(stats.avg_loss) if stats.loss_count > 0 else -0.008
    base_gross = 0.003

    fee      = ROUND_TRIP_MAKER
    bull_net = bull_gross - fee
    bear_net = bear_gross - fee
    base_net = base_gross - fee

    ev = win_prob * bull_net + 0.15 * base_net + bear_prob * bear_net
    rr = abs(bull_net / bear_net) if bear_net != 0 else 1.0
    kelly = stats.kelly_fraction() if ev > 0 else 0.0

    # Exit simulation
    exit_sim = simulate_exit(pair, current_price, budget_idr, spread_pct, None, daily_context)

    # Downgrade EV if exit is risky
    if exit_sim["verdict"] == "DO_NOT_ENTER":
        ev = min(ev, -0.001)  # Force non-entry
    elif exit_sim["verdict"] == "EXIT_RISKY":
        ev *= 0.7  # Discount EV for risky exit

    verdict = "ENTRY_OK" if ev > 0.003 else ("MARGINAL" if ev > 0 else "SKIP")
    if exit_sim["verdict"] == "DO_NOT_ENTER":
        verdict = "SKIP"

    return {
        "pair":             pair,
        "currentPrice":     current_price,
        "winProbability":   round(win_prob, 3),
        "expectedValue":    round(ev, 5),
        "riskRewardRatio":  round(rr, 2),
        "kellySizeRecommended": round(kelly, 3),
        "scenarios": {
            "bull": {"gross": bull_gross, "net": round(bull_net, 4), "prob": win_prob},
            "base": {"gross": base_gross, "net": round(base_net, 4), "prob": 0.15},
            "bear": {"gross": bear_gross, "net": round(bear_net, 4), "prob": bear_prob}
        },
        "exit_simulation":  exit_sim,
        "historian_verdict": stats.historian_verdict,
        "verdict":          verdict,
        "timestamp":        _now_wib().isoformat()
    }


def run_simulation(
    market_prices: dict,
    daily_context: Optional[Dict] = None,
) -> dict:
    """
    Jalankan simulasi untuk semua pair yang punya harga.
    market_prices: {"btc_idr": 1282178000, "fartcoin_idr": 3568, ...}
    """
    results = {}
    for pair, price in market_prices.items():
        if price > 0:
            results[pair] = simulate_pair(pair, price, daily_context=daily_context)

    # Sort by expected value, descending (§16.6: best candidate wins)
    sorted_results = dict(sorted(
        results.items(),
        key=lambda x: x[1]["expectedValue"],
        reverse=True
    ))

    # Filter: only show EXIT_OK candidates in top opportunities
    top_ok = [
        p for p, v in sorted_results.items()
        if v.get("exit_simulation", {}).get("verdict") == "EXIT_OK"
        and v["verdict"] == "ENTRY_OK"
    ]

    output = {
        "runAt":              _now_wib().isoformat(),
        "pairsSimulated":     len(sorted_results),
        "topOpportunities":   top_ok[:5],
        "results":            sorted_results
    }

    os.makedirs("state", exist_ok=True)
    _atomic_write(WHATIF_PATH, output)

    return output
