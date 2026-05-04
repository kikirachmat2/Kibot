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
    "indodax": {"data": None, "expiry": 0},
    "security": {"data": [], "expiry": 0}
}

async def fetch_json(session, url, timeout=3.0):
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
    except: pass
    return {}

async def handle_index(request):
    if os.path.exists(DASHBOARD_HTML):
        return web.FileResponse(DASHBOARD_HTML)
    return web.Response(text="Dashboard HTML missing", status=404)

async def handle_favicon(request):
    icon_path = os.path.join(SCRIPT_DIR, "kibot.png")
    if os.path.exists(icon_path):
        return web.FileResponse(icon_path)
    return web.Response(status=404)

async def handle_security_logs(request):
    logs = []
    if os.path.exists(SECURITY_LOG):
        try:
            with open(SECURITY_LOG, "r") as f:
                lines = f.readlines()[-30:]
                for line in lines: logs.append(json.loads(line))
        except: pass
    return web.json_response(logs, headers={"Access-Control-Allow-Origin": "*"})

async def handle_full_state(request):
    session = request.app["client"]
    
    # Fetch all data in parallel
    engine_task = fetch_json(session, f"{ENGINE_UPSTREAM}/api/state")
    scanner_task = fetch_json(session, f"{SCANNER_UPSTREAM}/api/state")
    
    engine_raw, scanner_raw = await asyncio.gather(engine_task, scanner_task)
    
    # Extract states or use raw
    engine_state = engine_raw.get("engine", engine_raw)
    scanner_state = scanner_raw.get("scanner", scanner_raw)
    
    # Standardize data for UI (Ensuring fields exist)
    master_state = {
        "engine": engine_state,
        "scanner": scanner_state,
        "system": {"cpu": 0, "ram": 0, "online": True}, # Fallback for now
        "timestamp": time.time(),
        "status": "Trinity Active"
    }
    
    return web.json_response(master_state, headers={"Access-Control-Allow-Origin": "*"})

async def on_startup(app):
    app["client"] = ClientSession()

async def on_cleanup(app):
    await app["client"].close()

def main():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/kibot.png", handle_favicon)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/security", handle_security_logs)
    app.router.add_get("/full_state", handle_full_state) # Alias
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    # Serve static assets from current folder
    app.router.add_static("/static/", SCRIPT_DIR)
    
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__":
    main()
