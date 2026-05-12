#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parent.parent


try:
    from Core.Support.ki_vault import load_sovereign_env
    load_sovereign_env()
except Exception as e:
    print(f"⚠️ [OLLAMA_GATEWAY] Vault Load Warning: {e}")


HOST = os.getenv("KIBOT_OLLAMA_GATEWAY_BIND_HOST", "0.0.0.0")
PORT = int(os.getenv("KIBOT_OLLAMA_GATEWAY_PORT", "11435"))
UPSTREAM = os.getenv("KIBOT_OLLAMA_UPSTREAM", "http://127.0.0.1:11434")
TOKEN = (
    os.getenv("KIBOT_OLLAMA_GATEWAY_TOKEN", "").strip()
    or os.getenv("OLLAMA_API_KEY", "").strip()
)
TIMEOUT = float(os.getenv("KIBOT_OLLAMA_GATEWAY_TIMEOUT_SEC", "90"))
ALLOWED_POST = {"/api/chat", "/api/generate", "/api/embed"}
ALLOWED_GET = {"/api/tags", "/api/ps"}
FAST_MODELS = {
    item.strip()
    for item in os.getenv("KIBOT_OLLAMA_GATEWAY_FAST_MODELS", "qwen2.5:0.5b").split(",")
    if item.strip()
}
DEFAULT_MODELS = {
    item.strip()
    for item in os.getenv("KIBOT_OLLAMA_GATEWAY_DEFAULT_MODELS", "qwen2.5:1.5b").split(",")
    if item.strip()
}
FORCE_MODEL = os.getenv("KIBOT_OLLAMA_GATEWAY_FORCE_MODEL", "").strip()
MODEL_ALIASES = {}
for item in os.getenv("KIBOT_OLLAMA_GATEWAY_MODEL_ALIASES", "").split(","):
    raw = item.strip()
    if not raw or "=" not in raw:
        continue
    source, target = raw.split("=", 1)
    source = source.strip()
    target = target.strip()
    if source and target:
        MODEL_ALIASES[source] = target
FAST_MAX_CTX = int(os.getenv("KIBOT_OLLAMA_GATEWAY_FAST_MAX_CTX", "2048"))
DEFAULT_MAX_CTX = int(os.getenv("KIBOT_OLLAMA_GATEWAY_DEFAULT_MAX_CTX", "3072"))
FAST_MAX_PREDICT = int(os.getenv("KIBOT_OLLAMA_GATEWAY_FAST_MAX_PREDICT", "180"))
DEFAULT_MAX_PREDICT = int(os.getenv("KIBOT_OLLAMA_GATEWAY_DEFAULT_MAX_PREDICT", "260"))
FAST_KEEP_ALIVE = os.getenv("KIBOT_OLLAMA_GATEWAY_FAST_KEEP_ALIVE", "90s")
DEFAULT_KEEP_ALIVE = os.getenv("KIBOT_OLLAMA_GATEWAY_DEFAULT_KEEP_ALIVE", "3m")
FAST_MAX_INPUT_CHARS = int(os.getenv("KIBOT_OLLAMA_GATEWAY_FAST_MAX_INPUT_CHARS", "15000"))
DEFAULT_MAX_INPUT_CHARS = int(os.getenv("KIBOT_OLLAMA_GATEWAY_DEFAULT_MAX_INPUT_CHARS", "25000"))


def _clamp_int(value: Any, fallback: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return fallback
    if parsed <= 0:
        return fallback
    return min(parsed, maximum)


def _estimate_input_chars(payload: Dict[str, Any]) -> int:
    total = 0
    messages = payload.get("messages")
    if isinstance(messages, list):
        for item in messages:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        total += len(part["text"])
    for key in ("prompt", "system", "input"):
        value = payload.get(key)
        if isinstance(value, str):
            total += len(value)
    return total


def _shape_payload(raw_body: bytes) -> tuple[bytes, Dict[str, Any]]:
    try:
        payload = json.loads((raw_body or b"{}").decode("utf-8"))
    except Exception:
        return raw_body, {}
    if not isinstance(payload, dict):
        return raw_body, {}
    requested_model = str(payload.get("model") or "").strip()
    model = requested_model
    if FORCE_MODEL:
        model = FORCE_MODEL
    elif model in MODEL_ALIASES:
        model = MODEL_ALIASES[model]
    if model:
        payload["model"] = model
    options = payload.get("options")
    if not isinstance(options, dict):
        options = {}
    if model in FAST_MODELS:
        options["num_ctx"] = _clamp_int(options.get("num_ctx"), FAST_MAX_CTX, FAST_MAX_CTX)
        options["num_predict"] = _clamp_int(options.get("num_predict"), FAST_MAX_PREDICT, FAST_MAX_PREDICT)
        payload["keep_alive"] = payload.get("keep_alive") or FAST_KEEP_ALIVE
    elif model in DEFAULT_MODELS:
        options["num_ctx"] = _clamp_int(options.get("num_ctx"), DEFAULT_MAX_CTX, DEFAULT_MAX_CTX)
        options["num_predict"] = _clamp_int(options.get("num_predict"), DEFAULT_MAX_PREDICT, DEFAULT_MAX_PREDICT)
        payload["keep_alive"] = payload.get("keep_alive") or DEFAULT_KEEP_ALIVE
    if options:
        payload["options"] = options
    if model != requested_model:
        print(
            f"[OLLAMA_GATEWAY] model_redirect requested={requested_model or '-'} effective={model}",
            flush=True,
        )
    input_chars = _estimate_input_chars(payload)
    max_input_chars = 0
    if model in FAST_MODELS:
        max_input_chars = FAST_MAX_INPUT_CHARS
    elif model in DEFAULT_MODELS:
        max_input_chars = DEFAULT_MAX_INPUT_CHARS
    if max_input_chars and input_chars > max_input_chars:
        print(
            f"[OLLAMA_GATEWAY] input_reject model={model or '-'} chars={input_chars} limit={max_input_chars}",
            flush=True,
        )
        return b"", {
            "rejected": True,
            "model": model,
            "requested_model": requested_model,
            "input_chars": input_chars,
            "max_input_chars": max_input_chars,
        }
    return json.dumps(payload).encode("utf-8"), {
        "rejected": False,
        "model": model,
        "requested_model": requested_model,
        "input_chars": input_chars,
    }


class OllamaGatewayHandler(BaseHTTPRequestHandler):
    server_version = "KiBotOllamaGateway/1.0"

    def _json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not TOKEN:
            return False
        auth = self.headers.get("Authorization", "").strip()
        return auth == f"Bearer {TOKEN}"

    def _forward(self, method: str, path: str, body: bytes | None = None) -> None:
        upstream_url = f"{UPSTREAM}{path}"
        headers = {"Content-Type": "application/json"}
        request = Request(upstream_url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                payload = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except HTTPError as error:
            payload = error.read() or b"{}"
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except URLError as error:
            self._json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": f"upstream_unreachable:{error.reason}"})
        except Exception as error:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"gateway_error:{type(error).__name__}"})

    def do_GET(self) -> None:
        if self.path == "/health":
            tags_ok = False
            try:
                with urlopen(Request(f"{UPSTREAM}/api/tags", method="GET"), timeout=5) as response:
                    tags_ok = response.status == 200
            except Exception:
                tags_ok = False
            self._json(
                HTTPStatus.OK if tags_ok else HTTPStatus.BAD_GATEWAY,
                {
                    "ok": tags_ok,
                    "upstream": UPSTREAM,
                    "auth_configured": bool(TOKEN),
                },
            )
            return
        if self.path not in ALLOWED_GET:
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        self._forward("GET", self.path)

    def do_POST(self) -> None:
        if self.path not in ALLOWED_POST:
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length > 0 else b"{}"
        body, meta = _shape_payload(body)
        if meta.get("rejected"):
            self._json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {
                    "ok": False,
                    "error": "input_too_large",
                    "model": meta.get("model"),
                    "input_chars": meta.get("input_chars"),
                    "max_input_chars": meta.get("max_input_chars"),
                },
            )
            return
        self._forward("POST", self.path, body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[OLLAMA_GATEWAY] {self.address_string()} {format % args}", flush=True)


def main() -> None:
    if not TOKEN:
        raise SystemExit("KIBOT_OLLAMA_GATEWAY_TOKEN or OLLAMA_API_KEY is required")
    server = ThreadingHTTPServer((HOST, PORT), OllamaGatewayHandler)
    print(f"[OLLAMA_GATEWAY] listening on {HOST}:{PORT} -> {UPSTREAM}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
