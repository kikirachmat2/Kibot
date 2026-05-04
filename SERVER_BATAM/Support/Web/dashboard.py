import os, asyncio, json, time
from aiohttp import web, ClientSession

# Configuration - TRINITY V9.1 CLUSTER
NODES = {
    "BATAM": "127.0.0.1",
    "EXECUTOR": "213.35.118.26",
    "SCANNER": "152.69.218.198"
}

# Port definitions
DASHBOARD_PORT = 8787
NETDATA_PORT = 19999
ENGINE_API_PORT = 8787 # Executor API
SCANNER_API_PORT = 8787 # Scanner API

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
STATE_DIR = os.path.join(ROOT_DIR, "SERVER_BATAM", "state")
SECURITY_LOG = os.path.join(STATE_DIR, "security_ledger.jsonl")

async def fetch_json(session, url, timeout=1.0):
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200: return await resp.json()
    except: pass
    return {}

async def get_netdata_stats(session, host):
    # Pulling basic system stats from Netdata API
    url = f"http://{host}:{NETDATA_PORT}/api/v1/allmetrics?format=json"
    data = await fetch_json(session, url, timeout=0.8)
    if not data: return {"cpu": 0, "ram": 0, "online": False}
    
    # Netdata metric extraction (Simplified)
    try:
        cpu = data.get("system.cpu", {}).get("dimensions", {}).get("user", {}).get("value", 0)
        ram = data.get("system.ram", {}).get("dimensions", {}).get("used", {}).get("value", 0)
        return {"cpu": round(cpu, 1), "ram": round(ram, 1), "online": True}
    except:
        return {"cpu": 0, "ram": 0, "online": True}

async def handle_full_state(request):
    session = request.app["client"]
    
    # 1. Fetch Node Health (Netdata)
    health_tasks = [get_netdata_stats(session, ip) for ip in NODES.values()]
    health_results = await asyncio.gather(*health_tasks)
    health_map = dict(zip(NODES.keys(), health_results))
    
    # 2. Fetch Bot Activity (Executor)
    engine_url = f"http://{NODES['EXECUTOR']}:{ENGINE_API_PORT}/api/state"
    engine_data = await fetch_json(session, engine_url)
    
    # 3. Fetch Scanner Status
    scanner_url = f"http://{NODES['SCANNER']}:{SCANNER_API_PORT}/api/state"
    scanner_data = await fetch_json(session, scanner_url)
    
    # Structure for kibot_dashboard.html
    full_state = {
        "nodes": health_map,
        "engine": engine_data.get("engine", engine_data), # Bot Status & Activity
        "scanner": scanner_data.get("scanner", scanner_data),
        "system": {
            "online": True,
            "master": "BATAM",
            "timestamp": time.time()
        },
        "bot_activity": engine_data.get("last_action", "IDLE - Waiting for Signal"),
        "timestamp": time.time()
    }
    return web.json_response(full_state, headers={"Access-Control-Allow-Origin": "*"})

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
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/security", handle_security_logs)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/kibot.png", handle_favicon)
    app.router.add_get("/", handle_index)
    
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
        async def static_fallback(request):
            file_path = os.path.join(SCRIPT_DIR, request.match_info['filename'])
            if os.path.isfile(file_path): return web.FileResponse(file_path)
            raise web.HTTPNotFound()
        app.router.add_get("/{filename:.+\\..+}", static_fallback)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__":
    main()
