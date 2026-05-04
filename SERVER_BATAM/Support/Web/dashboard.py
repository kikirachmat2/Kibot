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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")

async def fetch_json(session, url, timeout_sec=0.8):
    try:
        timeout = ClientTimeout(total=timeout_sec)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200: return await resp.json()
    except: pass
    return {}

async def get_node_stats(session, host):
    url = f"http://{host}:{NETDATA_PORT}/api/v1/allmetrics?format=json"
    data = await fetch_json(session, url, timeout_sec=0.5)
    stats = {"cpu": 0, "ram": 0.1, "online": False} # Default RAM 0.1 to avoid 0% look
    if data:
        try:
            stats["cpu"] = round(data.get("system.cpu", {}).get("dimensions", {}).get("user", {}).get("value", 0), 1)
            mem = data.get("system.ram", {}).get("dimensions", {})
            used = mem.get("used", 0)
            total = used + mem.get("cached", 0) + mem.get("free", 0)
            if total > 0:
                calc_ram = (used / total) * 100
                stats["ram"] = round(max(0.1, calc_ram), 1)
            stats["online"] = True
        except: stats["online"] = True
    return stats

async def handle_full_state(request):
    session = request.app["client"]
    now_ms = int(time.time() * 1000)
    
    # Parallel Fetch
    node_results = await asyncio.gather(*[get_node_stats(session, ip) for ip in NODES.values()])
    engine_data = await fetch_json(session, f"http://{NODES['EXECUTOR']}:8787/api/state", timeout_sec=1.2)
    
    last_act_text = engine_data.get("last_action", "TRINITY V9.1 ACTIVE")
    
    # ABSOLUTE COMPATIBILITY MAPPING
    master_state = {
        "nodes": {
            "BATAM": node_results[0],
            "EXECUTOR": node_results[1],
            "SCANNER": node_results[2],
            "SG-Executor": node_results[1],
            "SG-Scanner": node_results[2]
        },
        "system": node_results[0],
        "engine": {
            "total_rp": engine_data.get("total_rp", 0),
            "portfolioValueIdr": engine_data.get("total_rp", 0),
            "holdings": engine_data.get("holdings", []),
            "recent_actions": [
                {"time": now_ms, "text": last_act_text, "action": last_act_text, "type": "info"}
            ]
        },
        "manager": {
            "recent_actions": [
                {"time": now_ms, "text": last_act_text, "action": last_act_text, "type": "info"}
            ]
        },
        "timestamp": now_ms,
        "status": "connected"
    }
    return web.json_response(master_state, headers={"Access-Control-Allow-Origin": "*"})

def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.FileResponse(DASHBOARD_HTML))
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/favicon.ico", lambda r: web.FileResponse(os.path.join(SCRIPT_DIR, "kibot.png")))
    app.router.add_get("/kibot.png", lambda r: web.FileResponse(os.path.join(SCRIPT_DIR, "kibot.png")))
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

async def on_startup(app): app["client"] = ClientSession()
async def on_cleanup(app): await app["client"].close()

if __name__ == "__main__": main()
