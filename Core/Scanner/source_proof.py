import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger("SourceProof")

class SourceProof:
    """
    SourceProof Model.
    Ensures every scanned candidate has a valid, real source proof.
    Prevents mock/simulated candidates from being processed in production.
    """

    @staticmethod
    def create(
        source_type: str,  # REAL_API | REAL_RPC | REAL_ONCHAIN | REAL_EXCHANGE | OPERATOR_HINT
        source_name: str,
        source_url_or_endpoint: str,
        raw_id: str,
        symbol: str,
        address_or_mint: str,
        chain: str,
        proof_ok: bool = True
    ) -> Dict[str, Any]:
        
        # Verify address/mint does not contain placeholders
        fake_keywords = ["fake", "dummy", "simulated", "mock", "placeholder", "test", "soulguy", "eliza", "basepepe", "trump_outcome"]
        address_lower = address_or_mint.lower()
        
        if any(kw in address_lower for kw in fake_keywords):
            proof_ok = False
            logger.warning(f"❌ Rejected source proof generation: Placeholder detected in address '{address_or_mint}'")

        # OPERATOR_HINT must be resolved to a real address/mint to be tradable
        if source_type == "OPERATOR_HINT" and not address_or_mint:
            proof_ok = False
            logger.warning("❌ Rejected source proof generation: OPERATOR_HINT is missing a resolved address")

        return {
            "source_type": source_type,
            "source_name": source_name,
            "source_url_or_endpoint": source_url_or_endpoint,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "raw_id": raw_id,
            "symbol": symbol.upper(),
            "address_or_mint": address_or_mint,
            "chain": chain.lower(),
            "proof_ok": proof_ok
        }

    @staticmethod
    def validate(proof: Dict[str, Any]) -> bool:
        """
        Validate source proof dictionary against absolute strictness checks.
        """
        if not isinstance(proof, dict):
            return False
            
        required_keys = [
            "source_type", "source_name", "source_url_or_endpoint", 
            "fetched_at", "raw_id", "symbol", "address_or_mint", 
            "chain", "proof_ok"
        ]
        
        if not all(k in proof for k in required_keys):
            return False

        if not proof.get("proof_ok"):
            return False

        addr = str(proof.get("address_or_mint", "")).lower()
        fake_keywords = ["fake", "dummy", "simulated", "mock", "placeholder", "test", "soulguy", "eliza", "basepepe", "trump_outcome"]
        if any(kw in addr for kw in fake_keywords):
            return False

        # OPERATOR_HINT must not be alone without a real endpoint/address
        if proof.get("source_type") == "OPERATOR_HINT" and not proof.get("address_or_mint"):
            return False

        return True
