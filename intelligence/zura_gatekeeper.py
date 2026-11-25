"""KiBot Pre-Trade & Emergency Gatekeeper Client for Zura Integration.

STRICT FAIL-CLOSED: Any missing/corrupt/expired gate or unreachable Zura => VETO.
"""

import os
import sys
import json
import time
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

CANDIDATE_CONFIG_PATHS = [
    os.getenv("ZURA_ADAPTIVE_CONFIG_PATH"),
    "/home/ubuntu/zura-core/data/zura_adaptive_config.json",
    os.path.expanduser("~/Documents/Web Develop/Personal AI/data/zura_adaptive_config.json"),
]

CANDIDATE_GATE_PATHS = [
    os.getenv("KIBOT_GATE_PATH"),
    "/home/ubuntu/zura-core/gates/kibot_gate.json",
    os.path.expanduser("~/Documents/Web Develop/Personal AI/gates/kibot_gate.json"),
]

CANDIDATE_ZURA_DB_PATHS = [
    os.getenv("ZURA_DB_PATH"),
    "/home/ubuntu/zura-core/data/zura.db",
    os.path.expanduser("~/Documents/Web Develop/Personal AI/data/zura.db"),
]

CANDIDATE_ADVISORY_SCRIPTS = [
    os.getenv("ZURA_ADVISORY_SCRIPT"),
    "/home/ubuntu/zura-core/scripts/zura_advisory.py",
    os.path.expanduser("~/Documents/Web Develop/Personal AI/scripts/zura_advisory.py"),
]

DEFAULT_GATE_MAX_AGE_SEC = float(os.getenv("KIBOT_GATE_MAX_AGE_SEC", "900.0"))


def _first_existing(paths) -> Optional[Path]:
    for p in paths:
        if p:
            path_obj = Path(p)
            if path_obj.exists():
                return path_obj
    return None


def is_system_paused() -> bool:
    verified_clean = False

    gate_path = _first_existing(CANDIDATE_GATE_PATHS)
    if gate_path:
        try:
            gate_data = json.loads(gate_path.read_text(encoding="utf-8"))
            if gate_data.get("system_paused") is True:
                return True
        except Exception:
            return True

    db_path = _first_existing(CANDIDATE_ZURA_DB_PATHS)
    if db_path:
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0) as conn:
                cur = conn.cursor()
                cur.execute("SELECT value FROM system_state WHERE key = 'system_paused'")
                row = cur.fetchone()
                if row and row[0] is not None:
                    val = str(row[0]).strip().lower()
                    if val in ("1", "true", "yes", "paused"):
                        return True
                verified_clean = True
        except Exception:
            return True

    cfg_path = _first_existing(CANDIDATE_CONFIG_PATHS)
    if cfg_path:
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if data.get("system_paused"):
                return True
            verified_clean = True
        except Exception:
            return True

    return not verified_clean


def check_kibot_gate(max_age_sec: float = DEFAULT_GATE_MAX_AGE_SEC) -> Dict[str, Any]:
    gate_path = _first_existing(CANDIDATE_GATE_PATHS)
    if not gate_path:
        return {
            "allowed": False,
            "reason_code": "GATE_FILE_MISSING",
            "reason": "gates/kibot_gate.json tidak ditemukan. Trading diblokir (Fail-Closed).",
        }

    try:
        data = json.loads(gate_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Gate payload is not a JSON object")
    except Exception as e:
        return {
            "allowed": False,
            "reason_code": "GATE_FILE_CORRUPT",
            "reason": f"gates/kibot_gate.json tidak terbaca/corrupt: {e}",
        }

    now = time.time()
    updated_at = float(data.get("updated_at", 0.0) or 0.0)
    age = now - updated_at
    if updated_at <= 0.0 or age > max_age_sec:
        return {
            "allowed": False,
            "reason_code": "GATE_FILE_EXPIRED",
            "reason": f"Gate Zura kedaluwarsa (usia {age:.1f}s > batas {max_age_sec:.0f}s). Trading ditahan.",
            "gate": data,
        }

    if data.get("system_paused") or is_system_paused():
        return {
            "allowed": False,
            "reason_code": "SYSTEM_PAUSED",
            "reason": "Zura Kill-Switch Aktif (system_paused = true). Seluruh transaksi dibekukan.",
            "gate": data,
        }

    if data.get("macro_circuit_breaker", False):
        macro_reason = data.get("macro_reason") or "Macro Circuit Breaker aktif"
        return {
            "allowed": False,
            "reason_code": "MACRO_CIRCUIT_BREAKER",
            "reason": f"Macro Circuit Breaker Aktif: {macro_reason}",
            "gate": data,
        }

    paused_until = float(data.get("trading_paused_until", 0.0) or 0.0)
    if now < paused_until:
        remaining_min = round((paused_until - now) / 60.0, 1)
        return {
            "allowed": False,
            "reason_code": "TRADING_PAUSED",
            "reason": f"Trading dijeda oleh Zura selama {remaining_min} menit lagi.",
            "gate": data,
        }

    return {"allowed": True, "reason_code": "ALLOWED", "reason": "Gate OK", "gate": data}


def consult_zura_for_trade(
    pair: str,
    action: str,
    amount_idr: float,
    price_idr: float,
    fear_greed_score: Optional[int] = None,
) -> Dict[str, Any]:
    gate_res = check_kibot_gate()
    if not gate_res.get("allowed"):
        return {
            "is_approved": False,
            "action": "VETO",
            "reason_code": gate_res.get("reason_code", "GATE_BLOCKED"),
            "reason": gate_res.get("reason", "Ditolak oleh Zura Gate."),
        }

    script_path = _first_existing(CANDIDATE_ADVISORY_SCRIPTS)
    if not script_path:
        return {
            "is_approved": False,
            "action": "VETO",
            "reason_code": "ZURA_UNREACHABLE",
            "reason": "Zura advisory script tidak ditemukan/tidak dapat diakses (Fail-Closed).",
        }

    zura_root = script_path.parent.parent
    venv_python = zura_root / "venv" / "bin" / "python3"
    python_bin = str(venv_python) if venv_python.exists() else (sys.executable or "python3")

    payload = {
        "pair": pair,
        "action": action,
        "amount_idr": float(amount_idr),
        "price_idr": float(price_idr),
        "fear_greed_score": fear_greed_score,
    }

    try:
        res = subprocess.run(
            [python_bin, str(script_path), "--trade", json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(zura_root),
        )
        if res.returncode == 0 and res.stdout.strip():
            verdict = json.loads(res.stdout.strip())
            if not isinstance(verdict, dict) or "is_approved" not in verdict:
                return {
                    "is_approved": False,
                    "action": "VETO",
                    "reason_code": "ZURA_INVALID_RESPONSE",
                    "reason": "Respons Zura advisory tidak valid (Fail-Closed).",
                }
            verdict["is_approved"] = bool(verdict.get("is_approved"))
            return verdict
        return {
            "is_approved": False,
            "action": "VETO",
            "reason_code": "ZURA_EXEC_ERROR",
            "reason": f"Zura advisory execution error: {res.stderr.strip() or 'Non-zero exit'}",
        }
    except Exception as e:
        return {
            "is_approved": False,
            "action": "VETO",
            "reason_code": "ZURA_EXCEPTION",
            "reason": f"Gagal menghubungi Zura Pre-Trade Gatekeeper: {e}",
        }
