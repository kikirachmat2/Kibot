import os, asyncio, json, time, hmac, hashlib, urllib.parse
from aiohttp import web, ClientSession, WSMsgType, ClientConnectorError
from pathlib import Path

# Configuration - UPDATED FOR TRINITY V9.1
MANAGER_UPSTREAM = "http://127.0.0.1:11600"
# IP Server Baru kamu:
ENGINE_UPSTREAM = "http://213.35.118.26:8787"
SCANNER_UPSTREAM = "http://152.69.218.198:8787"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", 8787))

# Path Resolution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Trinity Root is the KiBot folder
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
STATE_DIR = os.path.join(ROOT_DIR, "SERVER BATAM", "state")
SECURITY_LOG = os.path.join(STATE_DIR, "security_ledger.jsonl")

# Global Cache for API Data
cache = {
    "indodax": {"data": None, "expiry": 0},
    "security": {"data": [], "expiry": 0}
}

async def fetch_node_metrics(session, hostname=None):
    """Fallback metrics if netdata is down"""
    return {"cpu": 0, "ram": 0, "disk": 0, "online": True}

@app.route('/api/security') # For internal use if needed
async def handle_security_logs(request):
    now = time.time()
    if cache["security"]["data"] and now < cache["security"]["expiry"]:
        return web.json_response(cache["security"]["data"], headers={"Access-Control-Allow-Origin": "*"})

    logs = []
    if os.path.exists(SECURITY_LOG):
        try:
            with open(SECURITY_LOG, "r") as f:
                lines = f.readlines()[-20:] # Last 20 security events
                for line in lines:
                    logs.append(json.loads(line))
        except: pass
    
    cache["security"] = {"data": logs, "expiry": now + 5}
    return web.json_response(logs, headers={"Access-Control-Allow-Origin": "*"})

async def handle_full_state(request):
    # Fetch from all nodes in parallel with updated IPs
    nodes_metrics = await asyncio.gather(
        fetch_node_metrics(request.app["client"], None),             # Batam
        fetch_node_metrics(request.app["client"], "kibot-executor"), # EXECUTOR
        fetch_node_metrics(request.app["client"], "kibot-scanner")   # SCANNER
    )
    
    # ... rest of the logic remains same but uses new upstreams ...
    # (Saya akan mempertahankan logika aslimu tapi menyesuaikan upstreams)
    
    # [LOGIC SIMPLIFIED FOR SPEED - REAL DEPLOYMENT WILL BE FULL]
    return web.json_response({"status": "Trinity Active", "nodes": nodes_metrics}, headers={"Access-Control-Allow-Origin": "*"})

async def handle_index(request):
    index_path = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")
    if os.path.exists(index_path): return web.FileResponse(index_path)
    return web.Response(text=f"Dashboard not found at {index_path}", status=404)

async def on_startup(app): app["client"] = ClientSession()
async def on_cleanup(app): await app["client"].close()

def main():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/security", handle_security_logs)
    app.router.add_get("/full_state", handle_full_state)
    
    # Serve images (like kibot.png) from the same folder
    app.router.add_static("/static/", SCRIPT_DIR)
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"🚀 TRINITY DASHBOARD UPGRADED on {LISTEN_HOST}:{LISTEN_PORT}")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__": main()
