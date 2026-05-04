import os, asyncio, json, time, hmac, hashlib, urllib.parse
from aiohttp import web, ClientSession, WSMsgType, ClientConnectorError
from pathlib import Path

# Configuration - TRINITY V9.1
MANAGER_UPSTREAM = "http://127.0.0.1:11600"
ENGINE_UPSTREAM = "http://213.35.118.26:8787"
SCANNER_UPSTREAM = "http://152.69.218.198:8787"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", 8787))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
STATE_DIR = os.path.join(ROOT_DIR, "SERVER_BATAM", "state")
SECURITY_LOG = os.path.join(STATE_DIR, "security_ledger.jsonl")

cache = {
    "security": {"data": [], "expiry": 0}
}

async def handle_index(request):
    if os.path.exists(DASHBOARD_HTML):
        return web.FileResponse(DASHBOARD_HTML)
    return web.Response(text=f"Dashboard not found at: {DASHBOARD_HTML}", status=404)

async def handle_security_logs(request):
    now = time.time()
    if cache["security"]["data"] and now < cache["security"]["expiry"]:
        return web.json_response(cache["security"]["data"], headers={"Access-Control-Allow-Origin": "*"})
    logs = []
    if os.path.exists(SECURITY_LOG):
        try:
            with open(SECURITY_LOG, "r") as f:
                lines = f.readlines()[-20:]
                for line in lines: logs.append(json.loads(line))
        except: pass
    cache["security"] = {"data": logs, "expiry": now + 5}
    return web.json_response(logs, headers={"Access-Control-Allow-Origin": "*"})

async def handle_full_state(request):
    # Simplified state for initial recovery
    return web.json_response({
        "status": "Trinity v9.1 Active",
        "timestamp": time.time(),
        "nodes": {
            "batam": "ONLINE",
            "executor": "CONNECTED",
            "scanner": "STREAMING"
        }
    }, headers={"Access-Control-Allow-Origin": "*"})

async def on_startup(app):
    app["client"] = ClientSession()

async def on_cleanup(app):
    await app["client"].close()

def main():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/security", handle_security_logs)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
    
    print(f"🚀 TRINITY DASHBOARD RUNNING on {LISTEN_HOST}:{LISTEN_PORT}")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__":
    main()
