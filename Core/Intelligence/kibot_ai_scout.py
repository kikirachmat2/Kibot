#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

"""
KiBot AI World Scout
====================
Proactive intelligence agent that searches the world every 5 minutes.
Synthesizes market catalysts, security threats, and trending narratives.
"""

import os
import json
import time
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any
import asyncio
from Core.circuit_breaker import CircuitBreaker

from Core.Support.ki_config import STATE_DIR
from Core.Decision.script_adaptation_engine import ScriptAdaptationEngine
from Core.Intelligence.defi_metrics_fetcher import DeFiMetricsFetcher

WORLD_MODEL_FILE = STATE_DIR / "world_model.json"
AI_TRACE_FILE = STATE_DIR / "ai_decision_trace.json"
AI_PATROL_FILE = STATE_DIR / "ai_patrol.json"

# Lazy imports to avoid circular dependency
def get_ai_search():
    from Core.Intelligence.kibot_ai_search import AISearchService
    return AISearchService()

def get_ai_coordinator():
    from Core.Intelligence import kibot_ai_coordinator
    return kibot_ai_coordinator

def _load_daily_state() -> Dict[str, Any]:
    try:
        from Core.sovereign_state import load_strategy
        strategy = load_strategy()
        daily_state = strategy.get("daily_state", {})
        return daily_state if isinstance(daily_state, dict) else {}
    except Exception:
        return {}

class WorldScout:
    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.search_service = get_ai_search()
        self.coordinator = get_ai_coordinator()
        self.defi_fetcher = DeFiMetricsFetcher()
        self.adaptation_engine = ScriptAdaptationEngine()
        self.breaker = CircuitBreaker("WORLD_SCOUT", max_failures=3, reset_after_sec=600)
        self.patrol_services = [
            "kibot-capital-governor",
            "kibot-scanner",
            "kibot-executor",
            "kibot-indodax-director",
            "kibot-phantom-brain",
            "kibot-target-board",
            "kibot-telemetry",
            "kibot-dashboard",
            "kibot-ai-scout",
        ]

    def _log(self, msg: str):
        print(f"[SCOUT][{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

    def _write_ai_trace(self, *, best_action: str = "WAIT", venue: str = "indodax", reason: str = "heartbeat", confidence: float = 0.0, risk_status: str = "UNKNOWN", next_check_seconds: int = 60, market_summary: str = ""):
        try:
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "objective": "maximize_risk_adjusted_profit_for_boss",
                "market_summary": market_summary,
                "best_action": best_action,
                "venue": venue,
                "reason": reason,
                "confidence": float(confidence),
                "risk_status": risk_status,
                "next_check_seconds": int(next_check_seconds),
            }
            AI_TRACE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"[WARN] Failed to write ai_decision_trace heartbeat: {exc}")

    def _run_command(self, args: List[str], timeout: int = 10) -> Dict[str, Any]:
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[-4000:],
                "stderr": (proc.stderr or "")[-4000:],
            }
        except Exception as exc:
            return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}

    def _file_age_s(self, path: Path) -> float:
        try:
            if path.exists():
                return round(time.time() - path.stat().st_mtime, 1)
        except Exception:
            pass
        return -1.0

    def _read_state_json(self, name: str) -> Dict[str, Any]:
        path = STATE_DIR / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _count_targets(self, state: Dict[str, Any]) -> int:
        targets = state.get("top_targets")
        if isinstance(targets, list):
            return len(targets)
        candidates = state.get("approved_candidates") or state.get("candidates")
        if isinstance(candidates, list):
            return len(candidates)
        return 0

    def _telegram_runtime_status(self) -> Dict[str, Any]:
        token = os.getenv("KIBOT_TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("KIBOT_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
        throttle_file = STATE_DIR / "telegram_throttle.json"
        status: Dict[str, Any] = {
            "configured": bool(token and chat_id),
            "token_present": bool(token),
            "chat_id_present": bool(chat_id),
            "throttle_state_file": str(throttle_file),
            "throttle_state_age_s": self._file_age_s(throttle_file),
            "bot_api_ok": None,
            "reason": "",
        }
        if not token or not chat_id:
            status["reason"] = "telegram_env_missing"
            return status

        try:
            import requests

            response = requests.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=8,
            )
            status["bot_api_ok"] = bool(response.ok and response.json().get("ok"))
            if not status["bot_api_ok"]:
                status["reason"] = f"telegram_getme_failed_http_{response.status_code}"
        except Exception as exc:
            status["bot_api_ok"] = False
            status["reason"] = f"telegram_getme_error:{exc}"
        return status

    def _runtime_semantics(self) -> Dict[str, Any]:
        governor = self._read_state_json("capital_governor.json")
        dispatcher = self._read_state_json("live_order_dispatcher.json")
        indodax_targets = self._read_state_json("indodax_top_targets.json")
        phantom_targets = self._read_state_json("phantom_top_targets.json")
        indodax_scanner = self._read_state_json("indodax_scanner_state.json")
        order_tracker = self._read_state_json("order_tracker_state.json")
        active_trades = self._read_state_json("active_trades.json")

        allow_orders = bool(governor.get("allow_new_orders", False))
        allow_reason = str(governor.get("allow_new_orders_reason") or "").strip()
        global_hard_stop = bool(governor.get("global_hard_stop", False))
        daily_reset_pending = bool(governor.get("daily_reset_pending", False))
        dispatcher_status = str(dispatcher.get("status") or "").strip()
        dispatcher_reason = str(dispatcher.get("reason") or "").strip()

        semantic_alerts: List[str] = []
        blockers: List[Dict[str, Any]] = []
        if not allow_orders:
            reason = allow_reason or "capital_governor_orders_disabled"
            semantic_alerts.append(f"orders_blocked:{reason}")
            blockers.append({"source": "capital_governor", "reason": reason})
        if global_hard_stop:
            reason = str(governor.get("global_hard_stop_reason") or allow_reason or "global_hard_stop").strip()
            semantic_alerts.append(f"global_hard_stop:{reason}")
            blockers.append({"source": "capital_governor.global_hard_stop", "reason": reason})
        if daily_reset_pending:
            reason = str(governor.get("daily_reset_reason") or allow_reason or "daily_reset_pending").strip()
            semantic_alerts.append(f"daily_reset_pending:{reason}")
            blockers.append({"source": "capital_governor.daily_reset", "reason": reason})
        if dispatcher_status.upper().startswith("BLOCKED"):
            reason = dispatcher_reason or "dispatcher_blocked"
            semantic_alerts.append(f"dispatcher_blocked:{reason}")
            blockers.append({"source": "live_order_dispatcher", "reason": reason})

        target_count = self._count_targets(indodax_targets) + self._count_targets(phantom_targets)
        enter_targets = 0
        for board in (indodax_targets, phantom_targets):
            for target in board.get("top_targets", []) if isinstance(board.get("top_targets"), list) else []:
                if str(target.get("recommended_action") or "").upper() == "ENTER":
                    enter_targets += 1
        if enter_targets and not allow_orders:
            semantic_alerts.append("opportunities_present_but_orders_blocked")

        scanner_status = str(indodax_scanner.get("source_status") or "").upper()
        pairs_checked = int(float(indodax_scanner.get("pairs_checked", 0) or 0))
        candidates_found = int(float(indodax_scanner.get("candidates_found", 0) or 0))
        if scanner_status in {"NO_DATA", "SOURCE_FAILED"} and pairs_checked > 0:
            semantic_alerts.append(
                f"indodax_scanner_status_inconsistent:{scanner_status}_pairs_{pairs_checked}"
            )

        return {
            "allow_new_orders": allow_orders,
            "allow_new_orders_reason": allow_reason,
            "global_hard_stop": global_hard_stop,
            "daily_reset_pending": daily_reset_pending,
            "dispatcher_status": dispatcher_status,
            "dispatcher_reason": dispatcher_reason,
            "target_count": target_count,
            "enter_targets": enter_targets,
            "indodax_scanner_source_status": scanner_status,
            "indodax_pairs_checked": pairs_checked,
            "indodax_candidates_found": candidates_found,
            "active_trades_count": len(active_trades) if isinstance(active_trades, dict) else 0,
            "order_tracker_open_count": len(order_tracker.get("open_orders", []))
            if isinstance(order_tracker.get("open_orders"), list)
            else 0,
            "blockers": blockers,
            "alerts": semantic_alerts,
        }

    async def _notify_runtime_blockers(self, semantics: Dict[str, Any], telegram: Dict[str, Any]) -> bool:
        alerts = semantics.get("alerts", [])
        if not alerts or not telegram.get("configured"):
            return False
        try:
            from Core.sovereign_notifier import SovereignNotifier

            reason = semantics.get("allow_new_orders_reason") or semantics.get("dispatcher_reason") or alerts[0]
            message = (
                "KiBot runtime blocker detected\n"
                f"- orders: {'ON' if semantics.get('allow_new_orders') else 'OFF'}\n"
                f"- reason: {reason}\n"
                f"- enter targets visible: {semantics.get('enter_targets', 0)}\n"
                f"- next: inspect capital_governor/live_order_dispatcher"
            )
            notifier = SovereignNotifier()
            return bool(
                await notifier.send_urgent_alert(
                    message,
                    incident_key="runtime_orders_blocked_semantic",
                )
            )
        except Exception as exc:
            self._log(f"[WARN] Failed to send runtime blocker Telegram alert: {exc}")
            return False

    async def perform_runtime_patrol(self) -> Dict[str, Any]:
        self._log("Running 5-minute runtime patrol across services, logs, and support tools...")

        state_files = [
            "capital_governor.json",
            "phantom_treasury.json",
            "indodax_scanner_state.json",
            "phantom_top_targets.json",
            "scanner_executor_contract.json",
            "server_telemetry.json",
            "ai_decision_trace.json",
            "ai_strategy_review.json",
            "live_order_dispatcher.json",
            "indodax_top_targets.json",
            "phantom_top_targets.json",
            "telegram_throttle.json",
        ]
        freshness = {}
        stale = []
        for name in state_files:
            path = STATE_DIR / name
            age = self._file_age_s(path)
            freshness[name] = age
            if age < 0:
                stale.append({"file": name, "reason": "missing"})
            elif age > 300:
                stale.append({"file": name, "reason": f"stale_{int(age)}s"})

        services = {}
        for svc in self.patrol_services:
            res = self._run_command(["systemctl", "is-active", svc], timeout=5)
            services[svc] = {
                "active": bool(res.get("ok")) and "active" in str(res.get("stdout", "")).strip().lower(),
                "raw": str(res.get("stdout", "")).strip() or str(res.get("stderr", "")).strip(),
            }

        toolchain = {
            "gh": bool(shutil.which("gh")),
            "aider": bool(shutil.which("aider")),
            "copilot": bool(shutil.which("copilot")),
            "crush": bool(shutil.which("crush")),
        }
        gh_status = self._run_command(["gh", "auth", "status", "-h", "github.com"], timeout=10) if toolchain["gh"] else {"ok": False, "stdout": "", "stderr": "gh_missing"}
        copilot_status = self._run_command(["gh", "copilot", "--help"], timeout=10) if toolchain["gh"] else {"ok": False, "stdout": "", "stderr": "gh_missing"}
        crush_status = self._run_command(["crush", "--help"], timeout=10) if toolchain["crush"] else {"ok": False, "stdout": "", "stderr": "crush_missing"}
        journal_alerts = {}
        for svc in ("kibot-scanner", "kibot-executor", "kibot-dashboard"):
            res = self._run_command(["journalctl", "-u", svc, "-n", "20", "--no-pager"], timeout=12)
            text = f"{res.get('stdout', '')}\n{res.get('stderr', '')}".strip()
            matches = []
            for line in text.splitlines():
                upper = line.upper()
                if any(token in upper for token in ("ERROR", "CRITICAL", "TRACEBACK", "FAILED", "EXCEPTION")):
                    matches.append(line.strip())
            journal_alerts[svc] = matches[:8]

        alerts = []
        for item in stale:
            alerts.append(f"{item['file']}:{item['reason']}")
        for svc, info in services.items():
            if not info.get("active"):
                alerts.append(f"{svc}:inactive")
        if not gh_status.get("ok", False):
            alerts.append("gh_auth_unavailable")

        runtime_semantics = self._runtime_semantics()
        telegram_status = self._telegram_runtime_status()
        for item in runtime_semantics.get("alerts", []):
            alerts.append(str(item))
        if not telegram_status.get("configured"):
            alerts.append("telegram_config_missing")
        elif telegram_status.get("bot_api_ok") is False:
            alerts.append(str(telegram_status.get("reason") or "telegram_bot_api_failed"))

        telegram_alert_sent = await self._notify_runtime_blockers(runtime_semantics, telegram_status)

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "objective": "maximize_risk_adjusted_profit_for_boss",
            "mode": "runtime_patrol",
            "services": services,
            "toolchain": {
                "gh": toolchain["gh"],
                "gh_auth_ok": bool(gh_status.get("ok")),
                "aider": toolchain["aider"],
                "copilot": bool(copilot_status.get("ok")) or toolchain["copilot"],
                "crush": bool(crush_status.get("ok")),
            },
            "state_freshness_s": freshness,
            "stale_files": stale,
            "journal_alerts": journal_alerts,
            "runtime_semantics": runtime_semantics,
            "telegram": telegram_status,
            "telegram_alert_sent": telegram_alert_sent,
            "alerts": alerts[:20],
            "support_action": "continue" if not alerts else "repair_runtime_blocker",
            "next_check_seconds": 300,
        }
        AI_PATROL_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            review_payload = {
                "status": "COMPLETED",
                "timestamp": time.time(),
                "proposed_adjustments": {
                    "confidence_floor_delta": 0.0,
                    "min_score_delta": 0.0,
                    "reasoning": f"runtime_patrol alerts={len(alerts)} support_action={payload['support_action']}",
                },
                "runtime_patrol": payload,
            }
            (STATE_DIR / "ai_strategy_review.json").write_text(json.dumps(review_payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"[WARN] Failed to write ai_strategy_review from patrol: {exc}")
        return payload

    async def perform_scouting(self):
        self._log("Initiating global scouting mission...")
        
        # 1. Gather Raw Data from multiple sources
        scouting_data = {
            "defi_intelligence": await self.defi_fetcher.get_aggregated_defi_intelligence(),
            "security_threats": await self.search_service.ddg_search_async("crypto protocol exploit hack vulnerability latest", max_results=3),
            "market_catalysts": await self.search_service.tavily_search_async("top crypto market catalysts today bitcoin eth regulation", search_depth="advanced") or await self.search_service.jina_search_async("top crypto market catalysts today"),
            "trending_narratives": await self.search_service.gdelt_news_async("crypto trending AI meme RWA layer2"),
            "news_pulse": (await self.search_service.finnhub_news_async("crypto") or [])[:5],
            "indodax_intel": await self.search_service.get_market_consensus_async("Indodax latest listing rumors IDR premium"),
            "polymarket_intel": await self.search_service.get_market_consensus_async("Polymarket trending events crypto prediction odds")
        }

        # 2. Synthesize using Cloud AI (Non-Ollama preferred for global context)
        self._log("Synthesizing global intelligence...")
        daily_state = _load_daily_state()
        
        prompt_context = {
            "raw_data": scouting_data,
            "current_time": time.ctime(),
            "daily_state": daily_state,
        }

        self._write_ai_trace(
            best_action="WAIT",
            venue="indodax",
            reason="scouting_heartbeat",
            confidence=0.05,
            risk_status="SCOUTING",
            next_check_seconds=60,
            market_summary="global scouting in progress",
        )
        
        # We use a specific prompt type for intelligence synthesis
        analysis = await self.coordinator.query_ai(
            prompt_type="INTELLIGENCE_SYNTHESIS",
            context=prompt_context,
            cache_ttl_minutes=4 # Always fresh
        )

        # 2b. Specialized Possibility Mining (Using Multi-Agent Debate for higher confidence)
        self._log("Mining for high-performance possibilities (Indodax & Polymarket) using AI Debate...")
        possibilities = await self.coordinator.query_ai_debate(
            prompt_type="POSSIBILITY_MINING",
            context=prompt_context,
            debate_rounds=1
        )

        if analysis:
            self._log("Intelligence synthesis complete.")
            # 3. Update World Model
            try:
                world_model = {}
                if WORLD_MODEL_FILE.exists():
                    world_model = json.loads(WORLD_MODEL_FILE.read_text(encoding="utf-8"))
                
                world_model.update({
                    "last_updated": time.time(),
                    "last_updated_str": time.ctime(),
                    "intelligence": analysis,
                    "possibility_matrix": possibilities.get("possibilities", []) if possibilities else [],
                    "raw_summary_length": len(str(scouting_data))
                })
                
                WORLD_MODEL_FILE.write_text(json.dumps(world_model, indent=2), encoding="utf-8")
                self._log("World Model updated successfully with Possibility Matrix.")
                summary_text = ""
                try:
                    summary_text = str((analysis or {}).get("market_summary") or (analysis or {}).get("summary") or "")
                except Exception:
                    summary_text = ""
                self._write_ai_trace(
                    best_action=str((analysis or {}).get("best_action") or "WAIT"),
                    venue=str((analysis or {}).get("venue") or "indodax"),
                    reason=str((analysis or {}).get("reason") or "analysis_update"),
                    confidence=float((analysis or {}).get("confidence") or 0.0),
                    risk_status=str((analysis or {}).get("risk_status") or "UNKNOWN"),
                    next_check_seconds=int((analysis or {}).get("next_check_seconds") or 60),
                    market_summary=summary_text,
                )
                try:
                    patrol = await self.perform_runtime_patrol()
                    self._write_ai_trace(
                        best_action=str((analysis or {}).get("best_action") or "WAIT"),
                        venue=str((analysis or {}).get("venue") or "indodax"),
                        reason=f"{str((analysis or {}).get('reason') or 'analysis_update')} | patrol={len(patrol.get('alerts', []))}",
                        confidence=float((analysis or {}).get("confidence") or 0.0),
                        risk_status=str((analysis or {}).get("risk_status") or "UNKNOWN"),
                        next_check_seconds=int((analysis or {}).get("next_check_seconds") or 60),
                        market_summary=str((analysis or {}).get("market_summary") or summary_text or ""),
                    )
                except Exception as patrol_exc:
                    self._log(f"[WARN] Runtime patrol failed: {patrol_exc}")
                try:
                    self.adaptation_engine.run_adaptation_cycle()
                except Exception as adapt_exc:
                    self._log(f"[WARN] Script adaptation cycle failed: {adapt_exc}")
                self.breaker.record_success()
            except Exception as e:
                self._log(f"Failed to save World Model: {e}")
                self.breaker.record_failure()
        else:
            self._log("[WARN] Intelligence synthesis failed (no AI response).")
            self._write_ai_trace(
                best_action="WAIT",
                venue="indodax",
                reason="analysis_unavailable",
                confidence=0.0,
                risk_status="UNKNOWN",
                next_check_seconds=60,
                market_summary="analysis unavailable",
            )
            if self.breaker.record_failure() == "ESCALATE":
                self._log("[CRITICAL] Scout circuit opened. Escalating to Council/Human.")

    async def perform_targeted_scouting(self, pair: str):
        self._log(f"Initiating URGENT targeted scouting for {pair}...")
        
        # 1. Gather Targeted Data
        symbol = pair.split("_")[0]
        scouting_data = {
            "pair": pair,
            "specific_catalyst": await self.search_service.tavily_search_async(f"latest news catalyst pump reason for {symbol} crypto {pair}", search_depth="advanced") or await self.search_service.jina_search_async(f"latest news catalyst for {symbol}"),
            "social_pulse": await self.search_service.serper_search_async(f"{symbol} crypto price pump news twitter reddit") or await self.search_service.jina_search_async(f"{symbol} crypto social trending news"),
            "news_pulse": (await self.search_service.finnhub_news_async(symbol) or [])[:3]
        }

        # 2. Validate using AI
        self._log(f"Validating {pair} anomaly using AI...")
        daily_state = _load_daily_state()
        prompt_context = {
            "pair": pair,
            "raw_data": scouting_data,
            "current_time": time.ctime(),
            "daily_state": daily_state,
        }
        
        validation = await self.coordinator.query_ai(
            prompt_type="TARGETED_VALIDATION",
            context=prompt_context,
            cache_ttl_minutes=1 # Instant validation, no cache
        )

        if validation:
            self._log(f"Targeted validation for {pair} complete: {validation.get('verdict')}")
            # 3. Update World Model with Urgent Alert
            try:
                world_model = {}
                if WORLD_MODEL_FILE.exists():
                    world_model = json.loads(WORLD_MODEL_FILE.read_text(encoding="utf-8"))
                
                if "urgent_alerts" not in world_model:
                    world_model["urgent_alerts"] = []
                
                world_model["urgent_alerts"].insert(0, {
                    "at": time.time(),
                    "pair": pair,
                    "validation": validation
                })
                # Keep only last 5 urgent alerts
                world_model["urgent_alerts"] = world_model["urgent_alerts"][:5]
                world_model["last_updated"] = time.time()
                
                WORLD_MODEL_FILE.write_text(json.dumps(world_model, indent=2), encoding="utf-8")
                self._log(f"World Model updated with urgent alert for {pair}.")
            except Exception as e:
                self._log(f"Failed to update World Model with urgent alert: {e}")
        else:
            self._log(f"[WARN] Targeted validation for {pair} failed (no AI response).")

async def run_scout_loop():
    print("[SCOUT] Starting World Scout service with Fast-Poll (5s) for urgent requests...", flush=True)
    scout = WorldScout()
    last_global_scout = 0
    last_trace_heartbeat = 0.0
    last_runtime_patrol = 0.0
    
    while True:
        now = time.time()
        
        # 1. Check for Urgent Targeted Scouting
        urgent_file = STATE_DIR / "urgent_scout.json"
        if urgent_file.exists():
            try:
                data = json.loads(urgent_file.read_text(encoding="utf-8"))
                pair = data.get("pair")
                if pair:
                    await scout.perform_targeted_scouting(pair)
                urgent_file.unlink() # Delete after processing
            except Exception as e:
                scout._log(f"[ERROR] Urgent scouting processing failed: {e}")

        # 2. Global Scouting and runtime patrol every 5 minutes (300s)
        if (now - last_global_scout) >= 300:
            try:
                await scout.perform_scouting()
                last_global_scout = now
            except Exception as e:
                import traceback
                scout._log(f"[ERROR] Global scouting failed: {e}\n{traceback.format_exc()}")

        if (now - last_runtime_patrol) >= 300:
            try:
                await scout.perform_runtime_patrol()
                last_runtime_patrol = now
            except Exception as e:
                scout._log(f"[WARN] Runtime patrol failed: {e}")

        # 3. AI decision heartbeat every 60s so healthchecks see a fresh trace
        if (now - last_trace_heartbeat) >= 60:
            try:
                scout._write_ai_trace(
                    best_action="WAIT",
                    venue="indodax",
                    reason="heartbeat",
                    confidence=0.0,
                    risk_status="SCOUTING",
                    next_check_seconds=60,
                    market_summary="heartbeat refresh",
                )
                last_trace_heartbeat = now
            except Exception as e:
                scout._log(f"[WARN] AI trace heartbeat failed: {e}")
        
        await asyncio.sleep(5) # Fast poll interval

if __name__ == "__main__":
    asyncio.run(run_scout_loop())
