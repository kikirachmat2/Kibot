import os, asyncio, json, time
from aiohttp import web, ClientSession, ClientTimeout

# Configuration - TRINITY V9.1 CLUSTER
NODES = {
    "BATAM": "127.0.0.1",
    "EXECUTOR": "213.35.118.26",
    "SCANNER": "152.69.218.198"
}

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8787
NETDATA_PORT = 19999
ENGINE_API_PORT = 8787

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
STATE_DIR = os.path.join(ROOT_DIR, "SERVER_BATAM", "state")
SECURITY_LOG = os.path.join(STATE_DIR, "security_ledger.jsonl")

async def fetch_json(session, url, timeout_sec=0.8):
    try:
        timeout = ClientTimeout(total=timeout_sec)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200: return await resp.json()
    except: pass
    return {}

async def get_netdata_lite(session, host):
    url = f"http://{host}:{NETDATA_PORT}/api/v1/allmetrics?format=json"
    data = await fetch_json(session, url, timeout_sec=0.5)
    metrics = {"cpu": 0, "ram": 0, "online": False}
    if data:
        try:
            metrics["cpu"] = round(data.get("system.cpu", {}).get("dimensions", {}).get("user", {}).get("value", 0), 1)
            metrics["ram"] = round(data.get("system.ram", {}).get("dimensions", {}).get("used", {}).get("value", 0), 1)
            metrics["online"] = True
        except: metrics["online"] = True
    return metrics

async def handle_full_state(request):
    session = request.app["client"]
    
    # 1. Fetch Node Metrics (Netdata)
    results = await asyncio.gather(*[get_netdata_lite(session, ip) for ip in NODES.values()])
    nodes_health = {
        "BATAM": results[0],
        "EXECUTOR": results[1],
        "SCANNER": results[2]
    }
    
    # 2. Fetch Engine Data (Portfolio & Bot Status)
    engine_data = await fetch_json(session, f"http://{NODES['EXECUTOR']}:{ENGINE_API_PORT}/api/state", timeout_sec=1.0)
    
    # 3. Format EXACTLY for kibot_dashboard.html
    # UI expects state.engine.total_rp, state.nodes, state.engine.recent_actions
    master_state = {
        "nodes": nodes_health,
        "engine": {
            "total_rp": engine_data.get("total_rp", 0),
            "total_usd": engine_data.get("total_usd", 0),
            "pnl_24h": engine_data.get("pnl_24h", 0),
            "holdings": engine_data.get("holdings", []),
            "recent_actions": engine_data.get("recent_actions", [
                {"time": time.strftime("%H:%M:%S"), "text": engine_data.get("last_action", "Monitoring Market..."), "type": "info"}
            ])
        },
        "scanner": engine_data.get("scanner", {}),
        "system": {
            "online": True,
            "master": "BATAM",
            "uptime": time.time()
        },
        "timestamp": time.time()
    }
    return web.json_response(master_state, headers={"Access-Control-Allow-Origin": "*"})

async def handle_index(request):
    if os.path.exists(DASHBOARD_HTML): return web.FileResponse(DASHBOARD_HTML)
    return web.Response(text="Dashboard HTML missing", status=404)

async def handle_favicon(request):
    icon_path = os.path.join(SCRIPT_DIR, "kibot.png")
    if os.path.exists(icon_path): return web.FileResponse(icon_path)
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
    app.router.add_get("/", handle_index)
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/security", handle_security_logs)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/kibot.png", handle_favicon)
    
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
        
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    print(f"🚀 TRINITY DASHBOARD AGGREGATOR RUNNING on {LISTEN_PORT}")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__":
    main()
