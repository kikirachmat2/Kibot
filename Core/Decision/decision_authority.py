import json
import logging
import os
import pathlib
import time
from typing import Dict, Any, List

logger = logging.getLogger("KiBot.DecisionAuthority")

DEFAULT_STATE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "state"

class DecisionAuthority:
    """
    Sovereign Decision Authority Contract (§11.1).
    Performs 100% deterministic, high-speed, script-based evaluations
    of incoming signals. Completely bypasses the online AI deliberation hot path.
    """

    def __init__(self, state_dir: pathlib.Path = DEFAULT_STATE_DIR):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.state_dir / "decision_authority.json"
        self._ensure_config()

    def _ensure_config(self) -> None:
        """Ensures the state configuration file exists with robust, safe default values."""
        if not self.config_path.exists():
            defaults = {
                "enabled": True,
                "confidence_floor": 0.70,
                "min_score": 0.58,
                "max_spread_pct": 1.20,
                "max_risk_penalty": 0.60,
                "allow_buying": True,
                "allow_selling": True,
                "emergency_halt": False,
                "lock_green_pnl_pct": 1.5,
                "probe_confidence_floor": 0.72,
                "min_coverage_score": 0.35
            }
            try:
                self.config_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
                logger.info(f"Initialized default DecisionAuthority config at {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to write default DecisionAuthority config: {e}")

    def load_config(self) -> Dict[str, Any]:
        """Loads the current configuration from JSON, falling back to defaults if corrupted."""
        try:
            if self.config_path.exists():
                return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load DecisionAuthority config: {e}. Reverting to defaults.")
        
        return {
            "enabled": True,
            "confidence_floor": 0.70,
            "min_score": 0.58,
            "max_spread_pct": 1.20,
            "max_risk_penalty": 0.60,
            "allow_buying": True,
            "allow_selling": True,
            "emergency_halt": False,
            "lock_green_pnl_pct": 1.5,
            "probe_confidence_floor": 0.72,
            "min_coverage_score": 0.35
        }

    def evaluate(self, signals_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main deterministic evaluation entry point.
        Evaluates signals context purely through script-based rules.
        """
        cfg = self.load_config()
        
        # 1. Immediate Safety Blocks
        if cfg.get("emergency_halt", False):
            return {
                "status": "WAIT",
                "action": "NONE",
                "ticker": "",
                "confidence": 0.0,
                "logic": "EMERGENCY_HALT is active in DecisionAuthority config.",
                "wait_reason": "EMERGENCY_HALT active",
                "source": "DECISION_AUTHORITY"
            }

        if not cfg.get("enabled", True):
            return {
                "status": "WAIT",
                "action": "NONE",
                "ticker": "",
                "confidence": 0.0,
                "logic": "DecisionAuthority engine is disabled.",
                "wait_reason": "Engine disabled",
                "source": "DECISION_AUTHORITY"
            }

        # 2. Extract context items
        signals = [sig for sig in list(signals_context.get("signals") or []) if isinstance(sig, dict)]
        evidence_bundle = signals_context.get("evidence_bundle") or {}
        whatif_snapshot = signals_context.get("whatif_snapshot") or {}
        today_trade_activity = signals_context.get("today_trade_activity") or {}
        daily_context = signals_context.get("daily_context") or {}
        minutes_to_midnight = signals_context.get("minutes_to_midnight", 1440)
        
        # 3. Dynamic adaptation of thresholds based on script adaptation engine (if exists)
        adaptation_path = self.state_dir / "script_adaptation.json"
        adaptive_cfg = {}
        if adaptation_path.exists():
            try:
                adaptive_cfg = json.loads(adaptation_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        confidence_floor = adaptive_cfg.get("confidence_floor", cfg.get("confidence_floor", 0.70))
        min_score = adaptive_cfg.get("min_score", cfg.get("min_score", 0.58))
        max_spread = adaptive_cfg.get("max_spread_pct", cfg.get("max_spread_pct", 1.20))
        max_risk = adaptive_cfg.get("max_risk_penalty", cfg.get("max_risk_penalty", 0.60))

        # 4. Check Deadline Profit Enforcer (LOCK_GREEN or MIDNIGHT protocol)
        enforcer_path = self.state_dir / "deadline_profit_enforcer.json"
        if enforcer_path.exists():
            try:
                enforcer_state = json.loads(enforcer_path.read_text(encoding="utf-8"))
                if enforcer_state.get("locked_for_day", False):
                    return {
                        "status": "WAIT",
                        "action": "NONE",
                        "ticker": "",
                        "confidence": 0.0,
                        "logic": f"Locked by DeadlineProfitEnforcer: {enforcer_state.get('lock_reason', 'target reached')}",
                        "wait_reason": "LOCK_GREEN active",
                        "source": "DECISION_AUTHORITY"
                    }
            except Exception:
                pass

        # 5. Evaluate and Rank Candidates
        ranked = []
        for signal in signals:
            ticker = str(signal.get("symbol") or signal.get("ticker") or "").upper()
            if not ticker:
                continue

            # Deterministic Score & Vetoes
            score = float(signal.get("opportunity_score") or signal.get("confidence") or 0.0)
            conf = float(signal.get("confidence", 0.0) or 0.0)
            spread_pct = float(signal.get("spread_pct") or 0.0)
            lifecycle = str(signal.get("lifecycle") or signal.get("pump_stage") or "IGNITION").upper()

            reject_reason = ""
            is_valid = True

            # Check spread
            if spread_pct > max_spread:
                is_valid = False
                reject_reason = f"Spread {spread_pct:.2f}% exceeds limit of {max_spread}%"

            # Check trap lifecycles
            elif lifecycle in ("TRAP", "LOCAL_TRAP", "DISTRIBUTION"):
                is_valid = False
                reject_reason = f"Prohibited lifecycle: {lifecycle}"

            # Check liquidity score if present
            elif float(signal.get("liquidity_score", 1.0) or 1.0) < 0.25:
                is_valid = False
                reject_reason = f"Liquidity score {signal.get('liquidity_score')} below floor 0.25"

            if is_valid:
                ranked.append({
                    "ticker": ticker,
                    "signal": signal,
                    "score": score,
                    "confidence": conf,
                    "is_valid": True
                })
            else:
                ranked.append({
                    "ticker": ticker,
                    "signal": signal,
                    "score": score,
                    "confidence": conf,
                    "is_valid": False,
                    "reject_reason": reject_reason
                })

        # Sort valid first, then by score descending
        valid_candidates = [r for r in ranked if r["is_valid"]]
        valid_candidates.sort(key=lambda x: x["score"], reverse=True)

        best = valid_candidates[0] if valid_candidates else {}
        
        # Apply entry gate controls
        if best:
            best_sig = best["signal"]
            best_conf = best["confidence"]
            best_score = best["score"]
            risk_penalty = float(evidence_bundle.get("risk_penalty", 0.0) or 0.0)
            
            # Additional safety gates
            if not cfg.get("allow_buying", True):
                return {
                    "status": "WAIT",
                    "action": "NONE",
                    "ticker": best["ticker"],
                    "confidence": best_conf,
                    "logic": "DecisionAuthority: allow_buying is turned off.",
                    "wait_reason": "Buying disabled",
                    "source": "DECISION_AUTHORITY",
                    "ranked_candidates": ranked[:5]
                }

            if risk_penalty > max_risk:
                return {
                    "status": "WAIT",
                    "action": "NONE",
                    "ticker": best["ticker"],
                    "confidence": best_conf,
                    "logic": f"DecisionAuthority: High risk penalty ({risk_penalty:.2f} > {max_risk:.2f})",
                    "wait_reason": "Risk penalty too high",
                    "source": "DECISION_AUTHORITY",
                    "ranked_candidates": ranked[:5]
                }

            # Check entry floors
            if best_score >= min_score and best_conf >= confidence_floor:
                # Deterministic Entry mandate!
                return {
                    "status": "EXECUTING",
                    "action": "BUY",
                    "ticker": best["ticker"],
                    "confidence": round(max(best_conf, min(0.95, best_score)), 4),
                    "logic": f"Deterministic execution: Candidate cleared score ({best_score:.2f} >= {min_score:.2f}) and confidence ({best_conf:.2f} >= {confidence_floor:.2f})",
                    "source": "DECISION_AUTHORITY",
                    "source_signal": best_sig,
                    "ranked_candidates": ranked[:5]
                }
            else:
                return {
                    "status": "WAIT",
                    "action": "NONE",
                    "ticker": best["ticker"],
                    "confidence": best_conf,
                    "logic": f"Deterministic wait: Best candidate failed score/confidence floor (score={best_score:.2f}, conf={best_conf:.2f}; floors: score={min_score:.2f}, conf={confidence_floor:.2f})",
                    "wait_reason": f"Under threshold: score={best_score:.2f}, conf={best_conf:.2f}",
                    "source": "DECISION_AUTHORITY",
                    "ranked_candidates": ranked[:5]
                }

        # No valid candidates
        best_invalid = [r for r in ranked if not r["is_valid"]]
        best_invalid.sort(key=lambda x: x["score"], reverse=True)
        
        wait_reason = "No candidates found"
        if best_invalid:
            wait_reason = f"Best invalid candidate {best_invalid[0]['ticker']}: {best_invalid[0].get('reject_reason', 'unknown veto')}"

        return {
            "status": "WAIT",
            "action": "NONE",
            "ticker": "",
            "confidence": 0.0,
            "logic": "No candidate passed the deterministic filters.",
            "wait_reason": wait_reason,
            "source": "DECISION_AUTHORITY",
            "ranked_candidates": ranked[:5]
        }
