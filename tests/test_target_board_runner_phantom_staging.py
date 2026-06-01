from __future__ import annotations

import json
from pathlib import Path

from Core.Decision import target_board_runner


def test_target_board_runner_stages_phantom_candidates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(target_board_runner, "STATE_DIR", tmp_path)
    candidate_path = tmp_path / "candidate_decisions.jsonl"
    candidate_path.write_text(
        json.dumps({"venue": "indodax", "pair": "EDEN_IDR", "status": "APPROVED"}) + "\n",
        encoding="utf-8",
    )

    phantom_board = {
        "top_targets": [
            {
                "route": "solana_jupiter",
                "symbol": "PHA",
                "recommended_action": "ENTER",
                "reason": "staged_candidate",
                "confidence": 0.82,
                "expected_net_edge_pct": 2.4,
                "historical_sample_size": 24,
                "source_proof_ok": True,
                "exit_route_ok": True,
            }
        ]
    }

    target_board_runner._write_candidate_decisions(phantom_board)

    rows = [
        json.loads(line)
        for line in candidate_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    phantom_rows = [row for row in rows if str(row.get("venue") or "").lower() == "phantom"]
    assert len(rows) == 2
    assert len(phantom_rows) == 1
    assert phantom_rows[0]["status"] == "STAGED"
    assert phantom_rows[0]["approved"] is True
    assert phantom_rows[0]["simulation_verdict"] == "PASS"

