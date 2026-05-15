import os
import subprocess
import logging
import json
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger("SystemCommander")

class SystemCommander:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.state_dir = Path(root_dir) / "state"
        self.inventory_path = Path(root_dir) / "Core" / "Intelligence" / "SERVER_INVENTORY.md"

    def _parse_inventory_models(self) -> Dict[str, str]:
        """Parse SERVER_INVENTORY.md for expected models."""
        models = {}
        if not self.inventory_path.exists():
            return models
        try:
            lines = self.inventory_path.read_text().splitlines()
            in_models_section = False
            for line in lines:
                if line.startswith("## 🤖 AI Models (Ollama)"):
                    in_models_section = True
                    continue
                if in_models_section and line.startswith("## "):
                    break
                if in_models_section and line.startswith("| `"):
                    parts = line.split("|")
                    if len(parts) >= 3:
                        model_name = parts[1].strip().strip("`")
                        status = "ACTIVE" if "ADA" in parts[2] else "MISSING"
                        models[model_name] = status
        except Exception as e:
            logger.debug(f"Failed to parse inventory models: {e}")
        return models

    def _get_provider_health(self) -> Dict[str, Any]:
        """Read provider health from state."""
        health_path = self.state_dir / "provider_health.json"
        if not health_path.exists():
            return {}
        try:
            return json.loads(health_path.read_text())
        except Exception:
            return {}

    def _detect_drift(self) -> str:
        """
        Check GitHub/Server drift.
        SYNCED, RUNTIME_DIRTY, STATE_ONLY, DANGEROUS_DRIFT
        """
        try:
            status_output = subprocess.check_output(
                ["git", "status", "--porcelain"], 
                cwd=self.root_dir, 
                text=True
            )
            is_dirty = len(status_output.strip()) > 0
            
            try:
                # Note: skipping fetch to avoid latency, rely on local remote branch tracking
                rev_output = subprocess.check_output(
                    ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"], 
                    cwd=self.root_dir, 
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip().split()
                ahead, behind = int(rev_output[0]), int(rev_output[1])
            except Exception:
                ahead, behind = 0, 0
                
            dangerous_files = ["MasterNode.py", "Core/Intelligence/strategy/", "kibot_manager", "systemd", "Core/Support/ki_vault.py"]
            has_dangerous_changes = any(
                any(df in line for df in dangerous_files) 
                for line in status_output.splitlines()
            )
            
            if has_dangerous_changes:
                return "DANGEROUS_DRIFT"
                
            if is_dirty or ahead > 0 or behind > 0:
                state_only_files = ["logs/", "state/", "data/", "scratch/"]
                only_state = True
                if is_dirty:
                    for line in status_output.splitlines():
                        if len(line) < 4: continue
                        file_path = line[3:]
                        if not any(file_path.startswith(sf) for sf in state_only_files):
                            only_state = False
                            break
                            
                if is_dirty and only_state and ahead == 0 and behind == 0:
                    return "STATE_ONLY"
                return "RUNTIME_DIRTY"
                
            return "SYNCED"
        except Exception as e:
            logger.debug(f"Failed to detect drift: {e}")
            return "UNKNOWN"

    def _calculate_inventory_utilization(self) -> float:
        """
        Calculate inventory utilization score based on models, services, etc.
        [G-002] Generate inventory_matrix.json
        """
        score = 0.55
        inventory_matrix = {
            "services": [],
            "models": [],
            "providers": []
        }
        try:
            # Check Redis
            redis_running = subprocess.run(["pgrep", "-f", "redis-server"], stdout=subprocess.DEVNULL).returncode == 0
            if redis_running: score += 0.15
            inventory_matrix["services"].append({
                "name": "redis",
                "active": redis_running,
                "role": "state_cache"
            })
            
            # Check Tailscale
            ts_running = subprocess.run(["pgrep", "-f", "tailscaled"], stdout=subprocess.DEVNULL).returncode == 0
            if ts_running: score += 0.15
            inventory_matrix["services"].append({
                "name": "tailscale",
                "active": ts_running,
                "role": "mesh_vpn"
            })
            
            # Pull models from SERVER_INVENTORY.md
            models = self._parse_inventory_models()
            for model_name, status in models.items():
                inventory_matrix["models"].append({
                    "name": model_name,
                    "active": status == "ACTIVE",
                    "role": "reasoning" if "deepseek" in model_name else "fast_council"
                })
                if status == "ACTIVE":
                    score += 0.05
                    
            # Pull providers from state
            provider_health = self._get_provider_health().get("providers", {})
            for provider, data in provider_health.items():
                inventory_matrix["providers"].append({
                    "name": provider,
                    "active": data.get("status") != "COOLDOWN",
                    "role": "external_llm"
                })
            
            # Persist Matrix
            try:
                self.state_dir.mkdir(parents=True, exist_ok=True)
                matrix_file = self.state_dir / "inventory_matrix.json"
                matrix_file.write_text(json.dumps(inventory_matrix, indent=2))
            except Exception as e:
                logger.error(f"Failed to save inventory matrix: {e}")
            
            return min(score, 1.0)
        except Exception as e:
            logger.debug(f"Failed to calculate inventory utilization: {e}")
            return 0.55

    def _classify_health(self, telemetry: Dict[str, Any], drift: str) -> str:
        """
        Classify system health: HEALTHY, DEGRADED, RECOVERING, BLIND, UNSAFE
        """
        redis_status = telemetry.get("redis", "UNKNOWN")
        
        if drift == "DANGEROUS_DRIFT":
            return "UNSAFE"
        
        if redis_status == "OFFLINE":
            return "DEGRADED"
            
        sys_stats = telemetry.get("system_stats", {}).get("BATAM_MASTER", {})
        ram = sys_stats.get("ram", 0)
        if float(ram) > 95:
            return "DEGRADED"
            
        return "HEALTHY"

    def get_system_state(self, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns the JSON-compliant dictionary payload expected by the strategy.
        """
        drift = self._detect_drift()
        utilization = self._calculate_inventory_utilization()
        health = self._classify_health(telemetry, drift)
        
        provider_data = self._get_provider_health()
        
        # Use parsed models, fallback to defaults if parsing fails
        models = self._parse_inventory_models()
        if not models:
            models = {
                "qwen2.5:0.5b": "ACTIVE",
                "qwen2.5:1.5b": "ACTIVE",
                "qwen2.5:3b": "AVAILABLE",
                "llama3.2:3b": "AVAILABLE"
            }
        
        
        state_dict = {
            "system_state": health,
            "inventory_utilization_score": round(utilization, 2),
            "services": {
                "redis": telemetry.get("redis", "UNKNOWN"),
                "tailscale": telemetry.get("tailscale", "UNKNOWN")
            },
            "models": models,
            "providers": provider_data.get("providers", {}),
            "sources": provider_data.get("sources", {}),
            "drift": drift,
            "self_healing_actions": [],
            "operator_required": health in ["UNSAFE", "BLIND"]
        }
        
        # [G-001] Persist System Commander state
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            commander_state_file = self.state_dir / "system_commander.json"
            commander_state_file.write_text(json.dumps(state_dict, indent=2))
        except Exception as e:
            logger.error(f"Failed to save system commander state: {e}")
            
        return state_dict
