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

async def fetch_json(session, url, timeout_sec=1.0):
    try:
        timeout = ClientTimeout(total=timeout_sec)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200: return await resp.json()
    except: pass
    return {}

async def get_node_stats(session, host):
    url = f"http://{host}:{NETDATA_PORT}/api/v1/allmetrics?format=json"
    data = await fetch_json(session, url, timeout_sec=0.6)
    stats = {"cpu": 0, "ram": 0, "online": False}
    if data:
        try:
            stats["cpu"] = round(data.get("system.cpu", {}).get("dimensions", {}).get("user", {}).get("value", 0), 1)
            used = data.get("system.ram", {}).get("dimensions", {}).get("used", {}).get("value", 0)
            total = used + data.get("system.ram", {}).get("dimensions", {}).get("cached", {}).get("value", 0) + data.get("system.ram", {}).get("dimensions", {}).get("free", {}).get("value", 0)
            stats["ram"] = round((used / total) * 100, 1) if total > 0 else 0
            stats["online"] = True
        except: stats["online"] = True
    return stats

async def handle_full_state(request):
    session = request.app["client"]
    node_results = await asyncio.gather(*[get_node_stats(session, ip) for ip in NODES.values()])
    engine_data = await fetch_json(session, f"http://{NODES['EXECUTOR']}:8787/api/state", timeout_sec=1.2)
    
    # FIX TIMESTAMP FOR JS (Seconds to Milliseconds)
    js_now = int(time.time() * 1000)
    
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
            "total_usd": engine_data.get("total_usd", 0),
            "pnl_24h": engine_data.get("pnl_24h", 0),
            "pnl_percent": engine_data.get("pnl_percent", 0),
            "holdings": engine_data.get("holdings", []),
            "recent_actions": []
        },
        "manager": {
            "recent_actions": [
                {
                    "time": js_now, # Milliseconds for JS
                    "action": engine_data.get("last_action", "TRINITY V9.1 ACTIVE - Monitoring Market"),
                    "type": "info"
                }
            ]
        },
        "timestamp": js_now,
        "status": "connected"
    }
    return web.json_response(master_state, headers={"Access-Control-Allow-Origin": "*"})

async def on_startup(app):
    app["client"] = ClientSession()

async def on_cleanup(app):
    await app["client"].close()

def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.FileResponse(DASHBOARD_HTML))
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_get("/favicon.ico", lambda r: web.FileResponse(os.path.join(SCRIPT_DIR, "kibot.png")))
    app.router.add_get("/kibot.png", lambda r: web.FileResponse(os.path.join(SCRIPT_DIR, "kibot.png")))
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__":
    main()
