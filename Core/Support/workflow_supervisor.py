from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from Core.Support.ki_config import PROJECT_ROOT, STATE_DIR

ROOT = Path(PROJECT_ROOT)
STATE = Path(STATE_DIR)
STATE_FILE = STATE / "workflow_automation.json"

CRITICAL_SERVICES = [
    "kibot-capital-governor",
    "kibot-scanner",
    "kibot-executor",
    "kibot-indodax-director",
    "kibot-phantom-brain",
    "kibot-target-board",
    "kibot-telemetry",
    "kibot-ai-scout",
    "kibot-dashboard",
]


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _age_s(path: Path) -> float:
    try:
        return round(time.time() - path.stat().st_mtime, 1)
    except Exception:
        return -1.0


def _run(args: list[str], timeout: int = 6) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "returncode": proc.returncode,
        }
    except Exception as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "returncode": -1}


def _service_statuses() -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for service in CRITICAL_SERVICES:
        res = _run(["systemctl", "is-active", service], timeout=4)
        raw = res.get("stdout") or res.get("stderr") or "unknown"
        statuses[service] = {
            "active": bool(res.get("ok")) and str(raw).strip() == "active",
            "raw": raw,
        }
    return statuses


def _target_count(board: dict[str, Any]) -> int:
    targets = board.get("top_targets")
    return len(targets) if isinstance(targets, list) else 0


def _enter_count(board: dict[str, Any]) -> int:
    count = 0
    targets = board.get("top_targets")
    if not isinstance(targets, list):
        return 0
    for target in targets:
        if isinstance(target, dict) and str(target.get("recommended_action") or "").upper() == "ENTER":
            count += 1
    return count


def _dispatcher_reason(dispatcher: dict[str, Any]) -> str:
    reason = str(dispatcher.get("reason") or "").strip()
    if reason:
        return reason
    child_reasons = []
    for key in ("indodax", "phantom"):
        child = dispatcher.get(key)
        if isinstance(child, dict) and child.get("reason"):
            child_reasons.append(f"{key}:{child.get('reason')}")
    return "; ".join(child_reasons)


def _env_or_dotenv(name: str) -> str:
    val = os.getenv(name, "").strip()
    if val:
        return val
    env_file = ROOT / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            if key.strip() == name:
                return raw.strip().strip("\"'")
    except Exception:
        pass
    return ""


def _telegram_status() -> dict[str, Any]:
    token = _env_or_dotenv("KIBOT_TELEGRAM_TOKEN") or _env_or_dotenv("TELEGRAM_BOT_TOKEN")
    chat_id = _env_or_dotenv("KIBOT_TELEGRAM_CHAT_ID") or _env_or_dotenv("TELEGRAM_CHAT_ID")
    status = {
        "configured": bool(token and chat_id),
        "token_present": bool(token),
        "chat_id_present": bool(chat_id),
        "bot_api_ok": None,
        "throttle_age_s": _age_s(STATE / "telegram_throttle.json"),
        "reason": "",
    }
    if not token or not chat_id:
        status["reason"] = "telegram_env_missing"
        return status
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=6)
        status["bot_api_ok"] = bool(resp.ok and resp.json().get("ok"))
        if not status["bot_api_ok"]:
            status["reason"] = f"telegram_getme_failed_http_{resp.status_code}"
    except Exception as exc:
        status["bot_api_ok"] = False
        status["reason"] = f"telegram_getme_error:{exc}"
    return status


def _support_tools() -> dict[str, Any]:
    return {
        "gh": bool(shutil.which("gh")),
        "copilot": bool(shutil.which("copilot")) or bool(shutil.which("gh")),
        "aider": bool(shutil.which("aider")) or (Path.home() / ".local/bin/aider").exists(),
        "crush": bool(shutil.which("crush")),
        "openhands": bool(shutil.which("openhands")),
        "selected_policy": "use_crush_copilot_gh_for_patrol; keep_openhands_optional_not_runtime_dependency",
    }


def build_workflow_automation_state() -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    governor = _read_json(STATE / "capital_governor.json", {})
    dispatcher = _read_json(STATE / "live_order_dispatcher.json", {})
    indodax_targets = _read_json(STATE / "indodax_top_targets.json", {})
    phantom_targets = _read_json(STATE / "phantom_top_targets.json", {})
    ai_patrol = _read_json(STATE / "ai_patrol.json", {})
    accounting = _read_json(STATE / "accounting_truth.json", {})

    services = _service_statuses()
    inactive_services = [name for name, info in services.items() if not info.get("active")]
    indodax_count = _target_count(indodax_targets)
    phantom_count = _target_count(phantom_targets)
    enter_targets = _enter_count(indodax_targets) + _enter_count(phantom_targets)

    allow_orders = bool(governor.get("allow_new_orders", False))
    governor_reason = str(governor.get("allow_new_orders_reason") or "").strip()
    dispatcher_status = str(dispatcher.get("status") or "MISSING").upper()
    dispatcher_reason = _dispatcher_reason(dispatcher)
    telegram = _telegram_status()
    support_tools = _support_tools()

    blockers: list[dict[str, Any]] = []
    if inactive_services:
        blockers.append({"source": "systemd", "reason": "inactive_services", "details": inactive_services})
    if not allow_orders:
        blockers.append({"source": "capital_governor", "reason": governor_reason or "orders_disabled"})
    if dispatcher_status.startswith("BLOCKED"):
        blockers.append({"source": "live_order_dispatcher", "reason": dispatcher_reason or "dispatcher_blocked"})
    if indodax_count + phantom_count == 0:
        blockers.append({"source": "target_boards", "reason": "no_targets_visible"})
    if not telegram.get("configured") or telegram.get("bot_api_ok") is False:
        blockers.append({"source": "telegram", "reason": telegram.get("reason") or "telegram_not_ready"})
    if isinstance(ai_patrol, dict) and ai_patrol.get("support_action") == "repair_runtime_blocker":
        blockers.append({"source": "ai_patrol", "reason": "; ".join(ai_patrol.get("alerts", [])[:4]) or "runtime_patrol_alert"})

    scanner_fresh = (
        _age_s(STATE / "indodax_top_targets.json") >= 0
        and _age_s(STATE / "indodax_top_targets.json") < 20
        and _age_s(STATE / "phantom_top_targets.json") >= 0
        and _age_s(STATE / "phantom_top_targets.json") < 20
    )

    workflow_steps = [
        {
            "step": "money_truth",
            "status": "ACTIVE" if governor or accounting else "MISSING_WITH_REASON",
            "reason": "capital/accounting state present" if governor or accounting else "capital_governor/accounting_truth missing",
        },
        {
            "step": "scanner_and_targets",
            "status": "ACTIVE" if scanner_fresh and indodax_count + phantom_count > 0 else "BLOCKED_WITH_REASON",
            "reason": f"indodax_targets={indodax_count}, phantom_targets={phantom_count}, fresh={scanner_fresh}",
        },
        {
            "step": "risk_governor",
            "status": "ALLOW" if allow_orders else "BLOCKED_WITH_REASON",
            "reason": governor_reason or "venue-scoped order permission active",
        },
        {
            "step": "dispatcher",
            "status": dispatcher_status,
            "reason": dispatcher_reason or "dispatcher ready/no reason",
        },
        {
            "step": "telegram",
            "status": "OK" if telegram.get("configured") and telegram.get("bot_api_ok") is not False else "BLOCKED_WITH_REASON",
            "reason": telegram.get("reason") or "telegram configured",
        },
        {
            "step": "ai_support",
            "status": "ACTIVE" if ai_patrol else "MISSING_WITH_REASON",
            "reason": str(ai_patrol.get("support_action") or "ai_patrol_missing"),
        },
    ]

    if inactive_services:
        overall_status = "INFRA_BLOCKED"
        next_action = "restart inactive services and rerun workflow supervisor"
    elif dispatcher_status.startswith("BLOCKED"):
        overall_status = "TRADING_FLOW_BLOCKED_WITH_REASON"
        next_action = dispatcher_reason or "inspect live_order_dispatcher"
    elif not allow_orders:
        overall_status = "TRADING_FLOW_BLOCKED_WITH_REASON"
        next_action = governor_reason or "inspect capital governor"
    elif enter_targets > 0:
        overall_status = "TRADING_FLOW_READY"
        next_action = "dispatcher may enter eligible candidate"
    else:
        overall_status = "ACTIVE_SEARCHING"
        next_action = "continue scan and target-board refresh"

    payload = {
        "updated_at": now,
        "mode": "WORKFLOW_AUTOMATION_SUPERVISOR",
        "objective": "make_runtime_truth_clear_and_repairable",
        "overall_status": overall_status,
        "current_best_action": next_action,
        "services": services,
        "workflow_steps": workflow_steps,
        "money_truth": {
            "total_balance_idr": governor.get("total_balance_idr") or governor.get("current_total_equity_idr") or accounting.get("current_total_equity_idr"),
            "reset_total_balance_idr": governor.get("reset_total_balance_idr") or accounting.get("reset_total_balance_idr"),
            "daily_return_idr": governor.get("daily_return_idr") or governor.get("daily_pnl_idr") or accounting.get("daily_pnl_idr"),
            "daily_return_pct": governor.get("daily_return_pct") or governor.get("daily_pnl_pct") or accounting.get("daily_pnl_pct"),
            "allow_new_orders": allow_orders,
            "allow_new_orders_reason": governor_reason,
        },
        "target_summary": {
            "indodax_count": indodax_count,
            "phantom_count": phantom_count,
            "enter_targets": enter_targets,
            "scanner_fresh": scanner_fresh,
        },
        "dispatcher": {
            "status": dispatcher_status,
            "reason": dispatcher_reason,
        },
        "telegram": telegram,
        "support_tools": support_tools,
        "ai_patrol": {
            "support_action": ai_patrol.get("support_action") if isinstance(ai_patrol, dict) else "",
            "alerts": ai_patrol.get("alerts", []) if isinstance(ai_patrol, dict) else [],
            "age_s": _age_s(STATE / "ai_patrol.json"),
        },
        "blockers": blockers,
        "next_check_seconds": int(float(os.getenv("KIBOT_WORKFLOW_SUPERVISOR_INTERVAL_SEC", "30") or 30)),
    }
    return payload


async def notify_if_needed(payload: dict[str, Any]) -> bool:
    blockers = payload.get("blockers")
    if not blockers:
        return False
    try:
        from Core.sovereign_notifier import SovereignNotifier

        reasons = "; ".join(str(item.get("reason") or item.get("source")) for item in blockers[:3] if isinstance(item, dict))
        message = (
            "KiBot workflow supervisor\n"
            f"- status: {payload.get('overall_status')}\n"
            f"- action: {payload.get('current_best_action')}\n"
            f"- blockers: {reasons}\n"
            f"- targets: {payload.get('target_summary', {}).get('enter_targets', 0)} ENTER visible"
        )
        return bool(
            await SovereignNotifier().send_urgent_alert(
                message,
                incident_key="workflow_automation_blocked",
            )
        )
    except Exception:
        return False


async def run_once() -> dict[str, Any]:
    payload = build_workflow_automation_state()
    payload["telegram_alert_sent"] = await notify_if_needed(payload)
    _write_json(STATE_FILE, payload)
    return payload


async def main_loop() -> None:
    interval = int(float(os.getenv("KIBOT_WORKFLOW_SUPERVISOR_INTERVAL_SEC", "30") or 30))
    while True:
        await run_once()
        await asyncio.sleep(max(5, interval))


def main() -> None:
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
