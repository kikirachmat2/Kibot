import os, asyncio, json, time
from aiohttp import web, ClientSession

# Configuration - TRINITY V9.1
ENGINE_UPSTREAM = "http://213.35.118.26:8787"
SCANNER_UPSTREAM = "http://152.69.218.198:8787"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", 8787))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
STATE_DIR = os.path.join(ROOT_DIR, "SERVER_BATAM", "state")
SECURITY_LOG = os.path.join(STATE_DIR, "security_ledger.jsonl")

async def fetch_json(session, url, timeout=1.5):
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200: return await resp.json()
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

async def handle_full_state(request):
    session = request.app["client"]
    # Parallel fetch
    engine_raw, scanner_raw = await asyncio.gather(
        fetch_json(session, f"{ENGINE_UPSTREAM}/api/state"),
        fetch_json(session, f"{SCANNER_UPSTREAM}/api/state")
    )
    
    # Structure for kibot_dashboard.html
    full_state = {
        "engine": engine_raw.get("engine", engine_raw),
        "scanner": scanner_raw.get("scanner", scanner_raw),
        "system": {
            "online": True,
            "node": "BATAM_MASTER",
            "cpu": 5.4, # Simulating for now if hardware stats missing
            "ram": 12.8
        },
        "timestamp": time.time()
    }
    return web.json_response(full_state, headers={"Access-Control-Allow-Origin": "*"})

async def handle_security_logs(request):
    logs = []
    if os.path.exists(SECURITY_LOG):
        try:
            with open(SECURITY_LOG, "r") as f:
                lines = f.readlines()[-20:]
                for line in lines: logs.append(json.loads(line))
        except: pass
    return web.json_response(logs, headers={"Access-Control-Allow-Origin": "*"})

async def on_startup(app):
    app["client"] = ClientSession()

async def on_cleanup(app):
    await app["client"].close()

def main():
    app = web.Application()
    
    # STRICT ROUTING - Prioritize API
    app.router.add_get("/", handle_index)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/kibot.png", handle_favicon)
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/security", handle_security_logs)
    
    # Static files ONLY on /static/ prefix to avoid collision
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
        
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    print(f"🚀 TRINITY DASHBOARD (FIXED API) on {LISTEN_PORT}")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__":
    main()
