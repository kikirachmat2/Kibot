#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from Core.Support.growth_audit import audit_daily_controls, audit_fill_quality, audit_net_growth, audit_strategy_symbol_normalization, build_critical_operator_questions
from Core.Support.money_movement_audit import load_state_bundle


def main() -> None:
    bundle = load_state_bundle()
    net = audit_net_growth(bundle)
    fill = audit_fill_quality(bundle)
    strat = audit_strategy_symbol_normalization(bundle)
    daily = audit_daily_controls(bundle)
    crit = build_critical_operator_questions(bundle)
    critique = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "menurut_agent_salah_terbesar_sistem_ini": "Fill banyak tapi belum terbukti closed round-trip accounting bersih; edge EDEN/XRP negatif dan symbol/source mapping masih tercemar.",
        "bukti_server": [
            f"net_growth={net.get('status')}",
            f"fill_quality={fill.get('status')}",
            f"strategy={strat.get('eden', {}).get('recommendation')}",
            f"daily_controls={daily.get('recommendation')}",
        ],
        "apakah_sistem_cuma_bergerak_tapi_tidak_tumbuh": net.get("status") not in {"GROWING"},
        "apakah_indodax_overtrade": fill.get("status") in {"CHURN", "DUPLICATE_COUNTING"},
        "apakah_strategy_edge_valid": strat.get("eden", {}).get("reliable", False) and strat.get("eden", {}).get("recommendation") != "DISABLE",
        "apakah_daily_controls_menghambat": daily.get("recommendation") == "TIGHTEN",
        "apakah_modal_minimum_order_jadi_masalah": "below_min_trade" in str((bundle.get("autonomous_sizing", {}) or {}).get("reason") or ""),
        "apakah_fill_accounting_bersih": fill.get("status") == "CLEAN",
        "apa_yang_harus_dilakukan_pertama": "Rapikan closed round trip accounting lalu cabut scale-up dari source unknown dan pair negatif.",
        "apa_yang_tidak_boleh_dilakukan": "Jangan scale-up, jangan longgarkan loss cap, jangan anggap fill sebagai profit.",
        "keputusan_final": "FIX_ACCOUNTING" if net.get("status") in {"INSUFFICIENT_DATA", "NO_CLOSED_ROUND_TRIPS", "ACCOUNTING_UNCLEAR"} else "REDUCE_CHURN",
        "critical_questions": crit,
    }
    path = Path("state/agent_self_critique.json")
    path.write_text(json.dumps(critique, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(critique, indent=2, ensure_ascii=False))
    print("status_marker=OK:AGENT_SELF_CRITIQUE_WRITTEN")


if __name__ == "__main__":
    main()
