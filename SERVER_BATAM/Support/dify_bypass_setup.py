#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def _load_env_file(env_path: str = ".env") -> None:
    """Load .env file into os.environ if it exists."""
    env_file = Path(env_path)
    if not env_file.exists():
        return
    
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                if key and key not in os.environ:
                    os.environ[key] = value


@dataclass(frozen=True)
class DifyConfig:
    console_api_url: str
    console_token: str
    api_base_url: str
    workflow_url: str
    workflow_id: str
    workflow_user: str
    ollama_base_url: str
    ollama_model: str
    request_timeout_sec: float
    provider_slug: str = "ollama"


def _clean(value: Optional[str], fallback: str) -> str:
    value = str(value or "").strip()
    return value or fallback


def load_config() -> DifyConfig:
    # Load .env file first if it exists
    _load_env_file(".env")
    _load_env_file("/home/ubuntu/KiBot/.env")
    
    console_api_url = _clean(os.getenv("DIFY_CONSOLE_API_URL"), "http://localhost:5001/console/api").rstrip("/")
    console_token = _clean(
        os.getenv("DIFY_CONSOLE_TOKEN")
        or os.getenv("DIFY_API_TOKEN")
        or os.getenv("DIFY_ACCESS_TOKEN"),
        "",
    )
    api_base_url = _clean(os.getenv("DIFY_API_BASE_URL"), "http://localhost:5001/v1").rstrip("/")
    workflow_url = _clean(
        os.getenv("DIFY_WORKFLOW_URL"),
        f"{api_base_url}/{str(os.getenv('DIFY_WORKFLOW_PATH', '/workflows/run')).lstrip('/')}",
    )
    workflow_id = _clean(os.getenv("DIFY_WORKFLOW_ID"), "")
    workflow_user = _clean(os.getenv("DIFY_WORKFLOW_USER"), "kibot-batam")
    ollama_base_url = _clean(os.getenv("KIBOT_OLLAMA_BASE_URL"), "http://127.0.0.1:11435/api/chat")
    ollama_model = _clean(os.getenv("KIBOT_OLLAMA_MODEL"), "qwen3:1.7b")
    request_timeout_sec = float(os.getenv("DIFY_REQUEST_TIMEOUT_SEC", "30"))
    return DifyConfig(
        console_api_url=console_api_url,
        console_token=console_token,
        api_base_url=api_base_url,
        workflow_url=workflow_url,
        workflow_id=workflow_id,
        workflow_user=workflow_user,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        request_timeout_sec=request_timeout_sec,
    )


def _headers(token: str) -> Dict[str, str]:
    if not token:
        raise SystemExit("DIFY_CONSOLE_TOKEN or DIFY_API_TOKEN is required")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def doctor(cfg: DifyConfig) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    for label, url in ("console", cfg.console_api_url), ("api", cfg.api_base_url):
        try:
            response = requests.get(url, timeout=cfg.request_timeout_sec, allow_redirects=False)
            checks[label] = {
                "url": url,
                "status_code": response.status_code,
                "reachable": True,
            }
        except Exception as exc:
            checks[label] = {
                "url": url,
                "reachable": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    checks["workflow"] = {
        "url": cfg.workflow_url,
        "workflow_id": cfg.workflow_id,
        "configured": bool(cfg.workflow_id),
    }
    return checks


def configure_ollama_provider(cfg: DifyConfig) -> Dict[str, Any]:
    payload = {
        "model_name": cfg.ollama_model,
        "base_url": cfg.ollama_base_url,
        "model_type": "chat",
        "config": {},
    }
    url = f"{cfg.console_api_url}/model-providers/{cfg.provider_slug}/setup"
    response = requests.post(url, json=payload, headers=_headers(cfg.console_token), timeout=cfg.request_timeout_sec)
    response.raise_for_status()
    return response.json()


def run_workflow(cfg: DifyConfig, prompt: str, context_json: str = "") -> Dict[str, Any]:
    api_token = os.getenv("DIFY_API_KEY") or os.getenv("DIFY_APP_TOKEN") or os.getenv("KIBOT_DIFY_API_KEY") or ""
    if not api_token:
        raise SystemExit("DIFY_API_KEY, DIFY_APP_TOKEN, or KIBOT_DIFY_API_KEY is required for workflow calls")

    inputs: Dict[str, Any] = {"prompt": prompt, "workflow_user": cfg.workflow_user}
    if context_json.strip():
        inputs["context"] = json.loads(context_json)
    payload: Dict[str, Any] = {
        "inputs": inputs,
        "response_mode": os.getenv("DIFY_RESPONSE_MODE", "blocking"),
        "user": cfg.workflow_user,
    }
    if cfg.workflow_id:
        payload["workflow_id"] = cfg.workflow_id

    response = requests.post(cfg.workflow_url, json=payload, headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}, timeout=cfg.request_timeout_sec)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Batam Dify bridge and setup helper")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Check Dify reachability and config")
    subparsers.add_parser("configure-ollama", help="Configure the local Ollama provider in Dify")
    workflow_parser = subparsers.add_parser("run-workflow", help="Invoke a Dify workflow")
    workflow_parser.add_argument("--prompt", required=True, help="Prompt or task description to send to Dify")
    workflow_parser.add_argument("--context-json", default="", help="Optional JSON context string")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "doctor":
        print(json.dumps(doctor(cfg), indent=2, ensure_ascii=False))
        return
    if args.command == "run-workflow":
        result = run_workflow(cfg, args.prompt, args.context_json)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    result = configure_ollama_provider(cfg)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
