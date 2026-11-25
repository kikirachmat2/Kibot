"""Module: core.allocator — Dynamic target buy allocation from env / Zura."""
import json
import os
from pathlib import Path
from typing import Dict, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _normalize_weights(btc: float, eth: float) -> Tuple[float, float]:
    if btc > 1.0 or eth > 1.0:
        btc /= 100.0
        eth /= 100.0
    total = btc + eth
    if btc < 0 or eth < 0 or total <= 0:
        return 0.70, 0.30
    return round(btc / total, 4), round(eth / total, 4)


def get_target_weights() -> Tuple[float, float]:
    env_btc = os.getenv("TARGET_BTC_PCT")
    env_eth = os.getenv("TARGET_ETH_PCT")
    if env_btc is not None or env_eth is not None:
        try:
            btc = float(env_btc) if env_btc is not None else (1.0 - float(env_eth))
            eth = float(env_eth) if env_eth is not None else (1.0 - btc)
            return _normalize_weights(btc, eth)
        except (TypeError, ValueError):
            pass

    gate_candidates = [
        os.getenv("KIBOT_GATE_PATH"),
        "/home/ubuntu/zura-core/gates/kibot_gate.json",
        os.path.expanduser("~/Documents/Web Develop/Personal AI/gates/kibot_gate.json"),
    ]
    for gp in gate_candidates:
        if gp and Path(gp).exists():
            try:
                gate_data = json.loads(Path(gp).read_text(encoding="utf-8"))
                intel = gate_data.get("indodax_intel") or {}
                alloc = intel.get("target_allocation") or {}
                if "BTC" in alloc and "ETH" in alloc:
                    return _normalize_weights(float(alloc["BTC"]), float(alloc["ETH"]))
            except Exception:
                pass

    return 0.70, 0.30


def allocate(topup_amount_idr: float) -> Dict[str, float]:
    if topup_amount_idr <= 0:
        return {"BTC": 0.0, "ETH": 0.0}
    btc_w, eth_w = get_target_weights()
    return {
        "BTC": round(btc_w * topup_amount_idr, 2),
        "ETH": round(eth_w * topup_amount_idr, 2),
    }
