from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("SystemCommander")


CANONICAL_SERVICES = (
    "kibot-master",
    "kibot-scanner",
    "kibot-executor",
    "kibot-executor-polymarket",
    "kibot-ai-scout",
    "kibot-janitor",
    "kibot-dashboard",
    "ollama",
    "redis-server",
)

CRITICAL_SERVICES = (
    "kibot-master",
    "kibot-scanner",
    "kibot-executor",
    "ollama",
    "redis-server",
)

CRITICAL_DRIFT_PATHS = (
    "MasterNode.py",
    "Core/Support/ki_vault.py",
    "Core/Support/ki_config.py",
    "Core/Exchange/",
    "Core/Executors/",
    "Core/Scanner/",
    "Core/risk_gate.py",
    "Core/sovereign_council.py",
    "config/systemd/",
    "bin/kibotctl",
)

STATE_ONLY_PATHS = (
    "Logs/",
    "logs/",
    "state/",
    "data/",
    "scratch/",
    "tmp/",
)

EXPECTED_TOOLS = (
    ("kibotctl", "bin/kibotctl"),
    ("gh", "gh"),
    ("aider", "aider"),
    ("copilot", "copilot"),
)


class SystemCommander:
    """
    Runtime brain for non-trading system awareness.

    The commander intentionally avoids inventing server capabilities. If a tool
    or service is not part of the canonical inventory, it is not scored as a
    missing dependency. This keeps dashboard health aligned with the real Batam
    runtime instead of old assumptions.
    """

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.state_dir = self.root_dir / "state"
        self.inventory_path = self.root_dir / "Core" / "Intelligence" / "SERVER_INVENTORY.md"

    def _run(self, args: List[str], timeout: float = 2.0) -> Tuple[int, str, str]:
        try:
            result = subprocess.run(
                args,
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except Exception as exc:
            return 127, "", str(exc)

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed reading %s: %s", path, exc)
        return default

    def _parse_inventory_models(self) -> Dict[str, str]:
        """Parse SERVER_INVENTORY.md for model rows without depending on emoji headings."""
        models: Dict[str, str] = {}
        if not self.inventory_path.exists():
            return models
        try:
            in_models_section = False
            for line in self.inventory_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                lower = line.lower()
                if line.startswith("## ") and ("ollama" in lower or "ai models" in lower):
                    in_models_section = True
                    continue
                if in_models_section and line.startswith("## "):
                    break
                if not in_models_section or not line.startswith("|"):
                    continue
                parts = [part.strip() for part in line.split("|")]
                if len(parts) < 4:
                    continue
                model_name = parts[1].strip("` ")
                if not model_name or model_name.lower() in {"model", "-------"}:
                    continue
                status_text = " ".join(parts[2:]).upper()
                if any(token in status_text for token in ("ADA", "ACTIVE", "OK", "INSTALLED")):
                    models[model_name] = "ACTIVE"
                elif any(token in status_text for token in ("MISSING", "BELUM", "SKIP")):
                    models[model_name] = "MISSING"
                else:
                    models[model_name] = "UNKNOWN"
        except Exception as exc:
            logger.debug("Failed to parse inventory models: %s", exc)
        return models

    def _ollama_models(self) -> Dict[str, str]:
        code, output, _ = self._run(["ollama", "list"], timeout=3.5)
        if code != 0 or not output:
            return {}
        models: Dict[str, str] = {}
        for line in output.splitlines()[1:]:
            name = line.split(maxsplit=1)[0].strip()
            if name:
                models[name] = "ACTIVE"
        return models

    def _systemctl_status(self, service: str) -> str:
        code, output, error = self._run(["systemctl", "is-active", service], timeout=1.2)
        status = (output or error or "").strip()
        if code == 0 and status == "active":
            return "active"
        if status in {"inactive", "failed", "activating", "deactivating"}:
            return status
        return "unknown"

    def _get_service_matrix(self, telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
        telemetry_services = telemetry.get("services", {}) if isinstance(telemetry, dict) else {}
        rows = []
        for name in CANONICAL_SERVICES:
            status = "unknown"
            if isinstance(telemetry_services, dict) and telemetry_services.get(name):
                raw = telemetry_services.get(name)
                status = str(raw.get("status") if isinstance(raw, dict) else raw)
            systemd_status = self._systemctl_status(name)
            if systemd_status != "unknown":
                status = systemd_status
            rows.append({
                "name": name,
                "active": status == "active",
                "status": status,
                "role": self._service_role(name),
                "critical": name in CRITICAL_SERVICES,
            })
        return rows

    @staticmethod
    def _service_role(name: str) -> str:
        roles = {
            "kibot-master": "council_runtime",
            "kibot-scanner": "market_scanner",
            "kibot-executor": "indodax_executor",
            "kibot-executor-polymarket": "polymarket_executor",
            "kibot-ai-scout": "world_model",
            "kibot-janitor": "self_healing",
            "kibot-dashboard": "control_plane",
            "ollama": "local_ai",
            "redis-server": "state_cache",
        }
        return roles.get(name, "runtime")

    def _get_provider_health(self) -> Dict[str, Any]:
        health = self._read_json(self.state_dir / "provider_health.json", {})
        if isinstance(health, dict) and isinstance(health.get("providers"), dict):
            return health

        legacy = self._read_json(self.state_dir / "ai_coordinator_providers.json", {})
        providers = legacy.get("providers", {}) if isinstance(legacy, dict) else {}
        return {"providers": providers}

    def _get_source_health(self) -> Dict[str, Any]:
        source_health = self._read_json(self.state_dir / "source_health.json", {})
        if isinstance(source_health, dict) and isinstance(source_health.get("sources"), dict):
            return source_health
        return {"sources": {}}

    def _provider_matrix(self) -> List[Dict[str, Any]]:
        providers = self._get_provider_health().get("providers", {})
        rows = []
        if not isinstance(providers, dict):
            return rows
        now = time.time()
        for name, data in sorted(providers.items()):
            payload = data if isinstance(data, dict) else {}
            cooldown_until = float(payload.get("cooldown_until", 0.0) or 0.0)
            status = str(payload.get("status") or payload.get("health") or "").upper()
            active = status not in {"COOLDOWN", "FAILED", "OFFLINE"} and cooldown_until <= now
            rows.append({
                "name": name,
                "active": active,
                "status": status or ("COOLDOWN" if cooldown_until > now else "UNKNOWN"),
                "role": "external_ai_provider",
                "cooldown_remaining_sec": max(0, int(cooldown_until - now)),
                "last_failure_reason": payload.get("last_failure_reason", ""),
            })
        return rows

    def _source_matrix(self) -> List[Dict[str, Any]]:
        sources = self._get_source_health().get("sources", {})
        rows = []
        if not isinstance(sources, dict):
            return rows
        for name, data in sorted(sources.items()):
            payload = data if isinstance(data, dict) else {}
            health = str(payload.get("health") or payload.get("status") or "unknown").lower()
            rows.append({
                "name": name,
                "active": health not in {"down", "failed", "offline", "blocked"},
                "health": health,
                "avg_latency": payload.get("avg_latency"),
                "role": "online_evidence_source",
            })
        return rows

    def _tool_matrix(self) -> List[Dict[str, Any]]:
        rows = []
        for name, executable in EXPECTED_TOOLS:
            if executable.startswith("bin/"):
                path = self.root_dir / executable
                active = path.exists() and path.stat().st_size > 0
                version = "repo-wrapper" if active else "missing"
            else:
                resolved = shutil.which(executable) or shutil.which(str(Path.home() / ".local" / "bin" / executable))
                active = bool(resolved)
                version = resolved or "missing"
            rows.append({
                "name": name,
                "active": active,
                "status": "available" if active else "missing",
                "role": "operator_tooling",
                "version": version,
            })
        return rows

    def _state_matrix(self) -> List[Dict[str, Any]]:
        important = (
            "telemetry_snapshot.json",
            "active_strategy.json",
            "active_trades.json",
            "risk_state.json",
            "world_model.json",
            "decision_journal.jsonl",
        )
        now = time.time()
        rows = []
        for filename in important:
            path = self.state_dir / filename
            exists = path.exists()
            age = now - path.stat().st_mtime if exists else None
            rows.append({
                "name": filename,
                "active": exists,
                "status": "present" if exists else "missing",
                "age_sec": round(age, 1) if age is not None else None,
                "role": "runtime_state",
            })
        return rows

    def _detect_drift(self) -> Dict[str, Any]:
        """Detect repository drift without treating strategy docs as dangerous code drift."""
        code, status_output, error = self._run(["git", "status", "--porcelain"], timeout=2.5)
        if code != 0:
            return {"status": "UNKNOWN", "dirty_files": [], "ahead": 0, "behind": 0, "error": error}

        dirty_lines = [line for line in status_output.splitlines() if line.strip()]
        dirty_files = [line[3:] if len(line) > 3 else line for line in dirty_lines]

        ahead = behind = 0
        code, rev_output, _ = self._run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"],
            timeout=2.0,
        )
        if code == 0:
            parts = rev_output.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])

        has_dangerous_changes = any(
            any(path.startswith(pattern) or pattern in path for pattern in CRITICAL_DRIFT_PATHS)
            for path in dirty_files
        )
        if has_dangerous_changes:
            status = "DANGEROUS_DRIFT"
        elif dirty_files:
            only_state = all(any(path.startswith(prefix) for prefix in STATE_ONLY_PATHS) for path in dirty_files)
            status = "STATE_ONLY" if only_state and ahead == 0 and behind == 0 else "RUNTIME_DIRTY"
        elif ahead > 0 or behind > 0:
            status = "RUNTIME_DIRTY"
        else:
            status = "SYNCED"

        return {
            "status": status,
            "dirty_files": dirty_files[:25],
            "ahead": ahead,
            "behind": behind,
        }

    def _resource_state(self, telemetry: Dict[str, Any]) -> Dict[str, float]:
        stats = {}
        try:
            sys_stats = telemetry.get("system_stats", {}).get("BATAM_MASTER", {})
            if isinstance(sys_stats, dict):
                stats = dict(sys_stats)
        except Exception:
            stats = {}

        disk_pct = 0.0
        try:
            usage = shutil.disk_usage("/")
            disk_pct = (usage.used / usage.total) * 100.0
        except Exception:
            disk_pct = float(stats.get("disk", 0.0) or 0.0)

        ram_pct = float(stats.get("ram", 0.0) or 0.0)
        cpu_pct = float(stats.get("cpu", 0.0) or 0.0)
        return {"cpu": cpu_pct, "ram": ram_pct, "disk": disk_pct}

    def _calculate_inventory_matrix(self, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        services = self._get_service_matrix(telemetry)
        installed_models = self._ollama_models()
        expected_models = self._parse_inventory_models()
        all_model_names = sorted(set(expected_models) | set(installed_models))
        models = [
            {
                "name": name,
                "active": installed_models.get(name) == "ACTIVE" or expected_models.get(name) == "ACTIVE",
                "status": installed_models.get(name) or expected_models.get(name, "UNKNOWN"),
                "role": self._model_role(name),
            }
            for name in all_model_names
        ]
        providers = self._provider_matrix()
        sources = self._source_matrix()
        tools = self._tool_matrix()
        state_files = self._state_matrix()

        scored_items = services + models + tools + state_files
        if providers:
            scored_items += providers
        if sources:
            scored_items += sources

        total_slots = max(len(scored_items), 1)
        used_slots = sum(1 for item in scored_items if bool(item.get("active")))
        utilization_score = used_slots / total_slots

        matrix = {
            "generated_at": time.time(),
            "utilization_score": round(utilization_score, 3),
            "total_slots": total_slots,
            "used_slots": used_slots,
            "captured_opportunities": self._count_jsonl_lines(self.state_dir / "decision_journal.jsonl", limit=250),
            "rejected_today": self._count_rejections(self.state_dir / "decision_journal.jsonl"),
            "services": services,
            "models": models,
            "providers": providers,
            "sources": sources,
            "tools": tools,
            "state": state_files,
        }

        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / "inventory_matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save inventory matrix: %s", exc)
        return matrix

    @staticmethod
    def _model_role(name: str) -> str:
        lower = name.lower()
        if "embed" in lower:
            return "rag_embedding"
        if "deepseek" in lower or "7b" in lower:
            return "deep_reasoning"
        if "0.5b" in lower:
            return "fast_watchman"
        if "1.5b" in lower or "3b" in lower:
            return "council_reasoning"
        return "local_ai"

    @staticmethod
    def _count_jsonl_lines(path: Path, limit: int = 1000) -> int:
        try:
            if not path.exists():
                return 0
            count = 0
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for count, _ in enumerate(handle, start=1):
                    if count >= limit:
                        break
            return count
        except Exception:
            return 0

    @staticmethod
    def _count_rejections(path: Path) -> int:
        try:
            if not path.exists():
                return 0
            count = 0
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]:
                upper = line.upper()
                if any(token in upper for token in ("WAIT", "REJECT", "VETO", "AVOID")):
                    count += 1
            return count
        except Exception:
            return 0

    def _classify_health(
        self,
        telemetry: Dict[str, Any],
        drift: Dict[str, Any],
        matrix: Dict[str, Any],
        resources: Dict[str, float],
    ) -> str:
        if drift.get("status") == "DANGEROUS_DRIFT":
            return "UNSAFE"

        service_rows = {row["name"]: row for row in matrix.get("services", []) if isinstance(row, dict)}
        critical_down = [
            name
            for name in CRITICAL_SERVICES
            if service_rows.get(name, {}).get("status") not in {"active", "unknown"}
        ]
        if critical_down:
            return "UNSAFE"

        if resources.get("disk", 0.0) >= 97.0:
            return "UNSAFE"
        if resources.get("disk", 0.0) >= 90.0 or resources.get("ram", 0.0) >= 95.0:
            return "DEGRADED"

        redis_status = str(telemetry.get("redis", "")).upper() if isinstance(telemetry, dict) else ""
        if redis_status == "OFFLINE":
            return "DEGRADED"

        telemetry_path = self.state_dir / "telemetry_snapshot.json"
        if telemetry_path.exists() and time.time() - telemetry_path.stat().st_mtime > 180:
            return "BLIND"

        return "HEALTHY"

    def get_system_state(self, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        drift = self._detect_drift()
        matrix = self._calculate_inventory_matrix(telemetry if isinstance(telemetry, dict) else {})
        resources = self._resource_state(telemetry if isinstance(telemetry, dict) else {})
        health = self._classify_health(telemetry if isinstance(telemetry, dict) else {}, drift, matrix, resources)

        provider_data = self._get_provider_health()
        source_data = self._get_source_health()
        state_dict = {
            "system_state": health,
            "inventory_utilization_score": round(float(matrix.get("utilization_score", 0.0)), 2),
            "services": {
                row["name"]: row.get("status", "unknown")
                for row in matrix.get("services", [])
                if isinstance(row, dict)
            },
            "models": {row["name"]: row.get("status", "UNKNOWN") for row in matrix.get("models", [])},
            "providers": provider_data.get("providers", {}),
            "sources": source_data.get("sources", {}),
            "source_health": source_data.get("sources", {}),
            "drift": drift.get("status", "UNKNOWN"),
            "config_drift": drift,
            "inventory_matrix": matrix,
            "resources": resources,
            "self_healing_actions": [],
            "operator_required": health in {"UNSAFE", "BLIND"},
            "trading_allowed_by_system": health not in {"UNSAFE", "BLIND"},
        }

        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            (self.state_dir / "system_commander.json").write_text(
                json.dumps(state_dict, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to save system commander state: %s", exc)

        return state_dict
