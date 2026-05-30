#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
OUT_FILE = STATE_DIR / "ai_system_inventory.json"


@dataclass(frozen=True)
class Component:
    name: str
    path: str
    category: str
    runtime_role: str
    status: str
    evidence: str
    notes: str = ""


COMPONENTS: List[Component] = [
    Component("RuntimeModeGuard", "Core/Support/runtime_mode_guard.py", "runtime_contract", "policy", "ACTIVE", "LIVE_ONLY enforcement and legacy mode normalization"),
    Component("LiveTruthManager", "Core/Treasury/live_truth_manager.py", "truth", "source_of_truth", "ACTIVE", "writes canonical live_truth.json"),
    Component("DeterministicDecisionGate", "Core/Decision/deterministic_decision_gate.py", "decision_gate", "hot_path_gate", "ACTIVE", "hard gate before live entry"),
    Component("PairQuarantine", "Core/Intelligence/pair_quarantine.py", "risk_memory", "pair_memory", "ACTIVE", "quarantines repeated losers"),
    Component("TelegramExceptionNotifier", "Core/Notifications/telegram_exception_notifier.py", "notification", "exception_only", "ACTIVE", "deduped exception/trade summaries only"),
    Component("JupiterGateway", "Core/Exchange/jupiter_gateway.py", "execution", "phantom_route", "LOCKED_OR_CONDITIONAL", "quote/swap gateway; execution depends on env/RPC/signing"),
    Component("IndodaxExecutor", "Core/Executors/Indodax/indodax_executor.py", "execution", "indodax_route", "ACTIVE", "calls deterministic gate before real buy"),
    Component("ExpectedValue", "Core/Intelligence/expected_value.py", "analytics", "edge_estimator", "ACTIVE", "requires real historical sample size"),
    Component("StrategyScorecard", "Core/Intelligence/strategy_scorecard.py", "analytics", "approval_layer", "ACTIVE", "cannot override EV reject"),
    Component("AutonomousSizing", "Core/Trading/autonomous_sizing.py", "sizing", "risk_sizing", "ACTIVE", "conservative defaults and EV guardrails"),
    Component("RiskGate", "Core/risk_gate.py", "risk", "global_gate", "ACTIVE", "runtime-mode and risk check"),
    Component("AccountingTruth", "Core/Treasury/accounting_truth.py", "truth", "capital_truth", "ACTIVE", "prefers live_truth canonical balances"),
    Component("PhantomCapitalMover", "Core/Treasury/phantom_capital_mover.py", "treasury", "phantom_venue", "ACTIVE", "bridge/withdrawal off by policy"),
    Component("KibotDashboard", "Core/Intelligence/kibot_dashboard.py", "dashboard", "control_plane", "ACTIVE", "reads live_truth and legacy state"),
    Component("AICoordinator", "Core/Intelligence/kibot_ai_coordinator.py", "ai_orchestration", "advisory_router", "ACTIVE", "multi-provider router for non-trading subsystems"),
    Component("AIScout", "Core/Intelligence/kibot_ai_scout.py", "ai_orchestration", "advisor", "ACTIVE", "advisory only"),
    Component("AISearchService", "Core/Intelligence/kibot_ai_search.py", "ai_orchestration", "search", "ACTIVE", "context/research/search support"),
    Component("AIDirector", "Core/Intelligence/autonomous_director.py", "ai_orchestration", "orchestrator", "ACTIVE", "decision support and routing"),
    Component("SovereignCouncil", "Core/sovereign_council.py", "governance", "advisor", "ACTIVE", "advisory; not allowed to override hot path"),
    Component("OllamaGateway", "Core/Intelligence/kibot_ollama_gateway.py", "provider", "model_backend", "ACTIVE", "local model gateway"),
    Component("RAG", "Core/Intelligence/kibot_rag.py", "retrieval", "context", "ACTIVE", "retrieval support"),
    Component("LearningEngine", "Core/Intelligence/kibot_learning_engine.py", "learning", "analysis", "ACTIVE", "feedback loop support"),
    Component("WhatIfEngine", "Core/Intelligence/kibot_whatif_engine.py", "scenario", "analysis", "ACTIVE", "scenario analysis"),
    Component("LeadLagAlpha", "Core/Intelligence/leadlag_alpha.py", "signal_model", "lead_lag", "ACTIVE", "Binance -> Indodax lead-lag signal"),
    Component("PhantomOpportunityScout", "Core/Intelligence/phantom_opportunity_scout.py", "signal_model", "phantom_scanner", "ACTIVE", "phantom opportunity discovery"),
    Component("SystemCommander", "Core/Support/system_commander.py", "runtime_health", "inventory", "ACTIVE", "writes inventory_matrix and runtime health"),
    Component("LiveTruthWriter", "scripts/run_live_truth_writer.py", "runtime_writer", "state_writer", "ACTIVE", "service writer"),
]


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_inventory() -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    for candidate in [
        STATE_DIR / "live_truth.json",
        STATE_DIR / "system_commander.json",
        STATE_DIR / "inventory_matrix.json",
        STATE_DIR / "ai_strategy_review.json",
        STATE_DIR / "ai_decision_trace.json",
        STATE_DIR / "provider_health.json",
        STATE_DIR / "source_health.json",
    ]:
        if candidate.exists():
            state[candidate.name] = _load_json(candidate)

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for component in COMPONENTS:
        groups.setdefault(component.category, []).append(
            {
                "name": component.name,
                "path": component.path,
                "runtime_role": component.runtime_role,
                "status": component.status,
                "evidence": component.evidence,
                "notes": component.notes,
            }
        )

    inventory = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_mode": str(_load_json(STATE_DIR / "live_truth.json").get("runtime_mode") or "LIVE_ONLY"),
        "summary": {
            "total_components": len(COMPONENTS),
            "active_components": sum(1 for c in COMPONENTS if c.status == "ACTIVE"),
            "locked_or_conditional_components": sum(1 for c in COMPONENTS if c.status != "ACTIVE"),
            "source_truth_files": sorted(state.keys()),
        },
        "categories": groups,
        "live_only_policy": {
            "trading_hot_path": "deterministic",
            "ai_role": "advisory_only",
            "telegram_role": "exception_only",
            "bridge": "OFF",
            "withdrawal": "OFF",
            "paper_mock_canary_shadow": "DISABLED",
        },
        "state_snapshots": state,
    }
    return inventory


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory()
    OUT_FILE.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK:AI_SYSTEM_INVENTORY_WRITTEN {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
