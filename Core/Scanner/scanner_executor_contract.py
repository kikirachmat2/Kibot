import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger("ScannerExecutorContract")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
CONTRACT_FILE = STATE_DIR / "scanner_executor_contract.json"

class ScannerExecutorContract:
    """
    Registry contract that defines the standard pairing and capabilities of
    every trade route scanner and executor in the KiBot system.
    """

    def __init__(self) -> None:
        self.state_dir = STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def get_definitions(self) -> List[Dict[str, Any]]:
        routes = [
            {
                "route": "indodax",
                "scanner": "IndodaxMarketScanner",
                "executor": "IndodaxExecutor",
                "scanner_state_file": "state/indodax_scanner_state.json",
                "executor_state_file": "state/indodax_executor_state.json",
                "position_state_file": "state/indodax_positions.json",
                "can_scan": True,
                "can_quote": True,
                "can_execute": True,
                "can_exit": True,
                "source_proof_required": True,
                "status": "LIVE_READY",
                "reason": ""
            },
            {
                "route": "phantom_solana_jupiter",
                "scanner": "SolanaOpportunityScanner",
                "executor": "PhantomRouter",
                "scanner_state_file": "state/solana_jupiter_scanner_state.json",
                "executor_state_file": "state/solana_jupiter_executor_state.json",
                "position_state_file": "state/solana_jupiter_positions.json",
                "can_scan": True,
                "can_quote": True,
                "can_execute": True,
                "can_exit": True,
                "source_proof_required": True,
                "status": "LIVE_READY",
                "reason": ""
            },
            {
                "route": "solana_meme_hunter",
                "scanner": "SolanaTrendingScanner",
                "executor": "PhantomRouter",
                "scanner_state_file": "state/solana_meme_scanner_state.json",
                "executor_state_file": "state/solana_meme_executor_state.json",
                "position_state_file": "state/solana_meme_positions.json",
                "can_scan": True,
                "can_quote": True,
                "can_execute": True,
                "can_exit": True,
                "source_proof_required": True,
                "status": "LIVE_READY",
                "reason": ""
            },
            {
                "route": "pumpfun_jupiter",
                "scanner": "PumpfunScanner",
                "executor": "PhantomRouter",
                "scanner_state_file": "state/pumpfun_jupiter_scanner_state.json",
                "executor_state_file": "state/pumpfun_jupiter_executor_state.json",
                "position_state_file": "state/pumpfun_jupiter_positions.json",
                "can_scan": True,
                "can_quote": True,
                "can_execute": True,
                "can_exit": True,
                "source_proof_required": True,
                "status": "LIVE_READY",
                "reason": ""
            },
            {
                "route": "pumpfun_native",
                "scanner": "PumpfunFastScanner",
                "executor": "PumpfunNativeExecutor",
                "scanner_state_file": "state/pumpfun_native_scanner_state.json",
                "executor_state_file": "state/pumpfun_native_executor_state.json",
                "position_state_file": "state/pumpfun_native_positions.json",
                "can_scan": True,
                "can_quote": False,
                "can_execute": False,
                "can_exit": False,
                "source_proof_required": True,
                "status": "BLOCKED_WITH_REASON",
                "reason": "native_program_instruction_path_missing"
            },
            {
                "route": "polymarket",
                "scanner": "PolymarketScanner",
                "executor": "PolymarketExecutor",
                "scanner_state_file": "state/polymarket_scanner_state.json",
                "executor_state_file": "state/polymarket_executor_state.json",
                "position_state_file": "state/polymarket_positions.json",
                "can_scan": True,
                "can_quote": True,
                "can_execute": True,
                "can_exit": True,
                "source_proof_required": True,
                "status": "LIVE_READY",
                "reason": ""
            },
            {
                "route": "base_swap",
                "scanner": "BaseSwapScanner",
                "executor": "BaseSwapExecutor",
                "scanner_state_file": "state/base_scanner_state.json",
                "executor_state_file": "state/base_executor_state.json",
                "position_state_file": "state/base_positions.json",
                "can_scan": True,
                "can_quote": True,
                "can_execute": True,
                "can_exit": True,
                "source_proof_required": True,
                "status": "LIVE_READY",
                "reason": ""
            },
            {
                "route": "future_web3",
                "scanner": "FutureWeb3Scanner",
                "executor": "FutureWeb3Executor",
                "scanner_state_file": "state/future_web3_scanner_state.json",
                "executor_state_file": "state/future_web3_executor_state.json",
                "position_state_file": "state/future_web3_positions.json",
                "can_scan": True,
                "can_quote": True,
                "can_execute": True,
                "can_exit": True,
                "source_proof_required": True,
                "status": "LIVE_READY",
                "reason": ""
            }
        ]

        # Dynamic contract rule enforcement:
        # - If executor exists but scanner missing = BLOCKED_WITH_REASON.
        # - If scanner exists but executor missing = SCANNING_ACTIVE_EXECUTOR_BLOCKED.
        # - If both exist but no exit = BLOCKED_NO_EXIT_ROUTE.
        # - If all complete = LIVE_READY / LIVE_ACTIVE.
        for r in routes:
            # Skip if explicitly native program blocked already
            if r["route"] == "pumpfun_native":
                continue

            scanner_exists = bool(r["scanner"])
            executor_exists = bool(r["executor"])
            exit_exists = r["can_exit"]

            if not r.get("source_proof_required"):
                r["source_proof_required"] = True

            if not scanner_exists and executor_exists:
                r["status"] = "BLOCKED_WITH_REASON"
                r["reason"] = "scanner_component_missing"
                r["can_scan"] = False
            elif scanner_exists and not executor_exists:
                r["status"] = "SCANNING_ACTIVE_EXECUTOR_BLOCKED"
                r["reason"] = "executor_component_missing"
                r["can_execute"] = False
            elif scanner_exists and executor_exists and not exit_exists:
                r["status"] = "BLOCKED_NO_EXIT_ROUTE"
                r["reason"] = "no_exit_route_defined"
            else:
                r["status"] = "LIVE_READY"
                r["reason"] = "Scanner and Executor paired cleanly."

        return routes

    def write_contract_state(self) -> Dict[str, Any]:
        routes = self.get_definitions()
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "1.0",
            "routes": routes
        }
        CONTRACT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info(f"Contract state written to {CONTRACT_FILE}")
        return payload

if __name__ == "__main__":
    c = ScannerExecutorContract()
    c.write_contract_state()
    print("Scanner Executor Contract successfully written.")
