import os, asyncio, json, time
from aiohttp import web, ClientSession, ClientTimeout

# Configuration - TRINITY V9.1 CLUSTER
NODES = {
    "BATAM": "127.0.0.1",
    "EXECUTOR": "213.35.118.26",
    "SCANNER": "152.69.218.198"
}

NETDATA_PORT = 19999
ENGINE_API_PORT = 8787
SCANNER_API_PORT = 8787
LISTEN_PORT = 8787

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")

async def safe_fetch_json(session, url, timeout_sec=0.5):
    try:
        # Strict timeout to prevent dashboard hanging
        timeout = ClientTimeout(total=timeout_sec)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
    except: pass
    return {}

async def get_node_metrics(session, name, host):
    # Netdata metrics polling
    url = f"http://{host}:{NETDATA_PORT}/api/v1/allmetrics?format=json"
    data = await safe_fetch_json(session, url, timeout_sec=0.4)
    
    # Defaults
    metrics = {"cpu": 0, "ram": 0, "online": False}
    if not data: return metrics
    
    try:
        # Extract basic metrics from Netdata structure
        metrics["cpu"] = round(data.get("system.cpu", {}).get("dimensions", {}).get("user", {}).get("value", 0), 1)
        metrics["ram"] = round(data.get("system.ram", {}).get("dimensions", {}).get("used", {}).get("value", 0), 1)
        metrics["online"] = True
    except:
        metrics["online"] = True
    return metrics

async def handle_full_state(request):
    session = request.app["client"]
    
    # Parallel fetching with strict timeouts
    health_tasks = [get_node_metrics(session, name, ip) for name, ip in NODES.items()]
    engine_task = safe_fetch_json(session, f"http://{NODES['EXECUTOR']}:{ENGINE_API_PORT}/api/state", timeout_sec=0.8)
    
    results = await asyncio.gather(*health_tasks, engine_task)
    
    health_map = {
        "BATAM": results[0],
        "EXECUTOR": results[1],
        "SCANNER": results[2]
    }
    engine_data = results[3]
    
    # Final JSON assembly
    full_state = {
        "nodes": health_map,
        "engine": engine_data.get("engine", engine_data),
        "bot_activity": engine_data.get("last_action", "READY - Monitoring Market"),
        "timestamp": time.time(),
        "system": {"master": "BATAM", "online": True}
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

async def on_startup(app):
    # Use a shared session for efficiency
    app["client"] = ClientSession()

async def on_cleanup(app):
    await app["client"].close()

def main():
    app = web.Application()
    
    # Routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/kibot.png", handle_favicon)
    
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
        
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    print(f"🚀 RESILIENT DASHBOARD V9.1 (NETDATA + BOT STATUS) on {LISTEN_PORT}")
    web.run_app(app, host="0.0.0.0", port=LISTEN_PORT, access_log=None)

if __name__ == "__main__":
    main()
