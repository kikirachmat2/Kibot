import json
import logging
import os
import pathlib
from typing import Dict, Any

logger = logging.getLogger("KiBot.ScriptAdaptationEngine")

DEFAULT_STATE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "state"

class ScriptAdaptationEngine:
    """
    Script Adaptation Engine.
    Processes strategic, out-of-band AI reviews from state/ai_strategy_review.json
    and applies bounded parameter adjustments to state/script_adaptation.json.
    Ensures human/script rule parameters cannot be pushed into unsafe bounds.
    """

    def __init__(self, state_dir: pathlib.Path = DEFAULT_STATE_DIR):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.adaptation_path = self.state_dir / "script_adaptation.json"
        self.review_path = self.state_dir / "ai_strategy_review.json"
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        """Sets up default script_adaptation configuration if missing."""
        if not self.adaptation_path.exists():
            defaults = {
                "confidence_floor": 0.70,
                "min_score": 0.58,
                "max_spread_pct": 1.20,
                "max_risk_penalty": 0.60,
                "last_adjusted_at": 0.0,
                "last_reason": "Default parameters initialized"
            }
            try:
                self.adaptation_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
                logger.info(f"Initialized default script adaptation at {self.adaptation_path}")
            except Exception as e:
                logger.error(f"Failed to write default script adaptation file: {e}")

    def run_adaptation_cycle(self) -> Dict[str, Any]:
        """
        Loads the latest AI review, bounds recommendations to safe limits,
        and saves the adjustments to state/script_adaptation.json.
        """
        # Ensure files are initialized
        self._ensure_defaults()
        
        if not self.review_path.exists():
            logger.debug("No out-of-band AI strategy review file found. Skipping adaptation cycle.")
            return self.load_adaptation()

        # Load active parameters
        active = self.load_adaptation()
        
        try:
            review = json.loads(self.review_path.read_text(encoding="utf-8"))
            if not isinstance(review, dict) or review.get("status") != "COMPLETED":
                return active
            
            # Check if this review was already processed
            review_ts = float(review.get("timestamp", 0.0))
            if review_ts <= active.get("last_adjusted_at", 0.0):
                return active
            
            proposed = review.get("proposed_adjustments", {})
            floor_delta = float(proposed.get("confidence_floor_delta", 0.0))
            reason = str(proposed.get("reasoning", "Adaptive review adjustment"))
            
            # Calculate new parameters
            new_floor = active.get("confidence_floor", 0.70) + floor_delta
            
            # Strict Hard Boundaries Guardrails
            # We never let AI push parameters into unsafe levels
            new_floor = max(0.65, min(0.85, new_floor))
            
            # AI could also suggest min_score adjustments, let's bound it too
            new_score = active.get("min_score", 0.58)
            if "min_score_delta" in proposed:
                new_score += float(proposed["min_score_delta"])
            new_score = max(0.50, min(0.75, new_score))
            
            # Update the configuration
            active.update({
                "confidence_floor": round(new_floor, 3),
                "min_score": round(new_score, 3),
                "last_adjusted_at": review_ts,
                "last_reason": f"AI review applied: {reason}"
            })
            
            self.adaptation_path.write_text(json.dumps(active, indent=2), encoding="utf-8")
            logger.info(f"🚀 Bounded script adaptation applied successfully: floor={new_floor:.3f}, min_score={new_score:.3f}")
            
        except Exception as e:
            logger.error(f"Failed to process script adaptation cycle: {e}")
            
        return active

    def load_adaptation(self) -> Dict[str, Any]:
        """Loads and returns current script adaptation values."""
        try:
            if self.adaptation_path.exists():
                return json.loads(self.adaptation_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load script adaptation file: {e}")
        
        return {
            "confidence_floor": 0.70,
            "min_score": 0.58,
            "max_spread_pct": 1.20,
            "max_risk_penalty": 0.60,
            "last_adjusted_at": 0.0,
            "last_reason": "Fallback default parameters loaded"
        }
