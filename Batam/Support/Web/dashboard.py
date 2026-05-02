import os, asyncio, json, time, hmac, hashlib, urllib.parse
from aiohttp import web, ClientSession, WSMsgType, ClientConnectorError

# Configuration
MANAGER_UPSTREAM = "http://127.0.0.1:11600"
ENGINE_UPSTREAM = "http://100.122.1.109:8787"
SCANNER_UPSTREAM = "http://100.105.139.21:8787"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", 8787))

# Path Resolution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
STATIC_DIR = os.path.join(ROOT_DIR, "web")
MSC_STATE_FILE = os.path.join(ROOT_DIR, "state", "msc_live_state.json")
FULL_STATE_FILE = os.path.join(ROOT_DIR, "state", "full_system_state.json")

def _get_env_optional(name: str) -> str:
    return os.getenv(name, "").strip()

INDODAX_API_KEY = _get_env_optional("INDODAX_API_KEY")
INDODAX_API_SECRET = _get_env_optional("INDODAX_API_SECRET")


# Global Cache for API Data
cache = {
    "indodax": {"data": None, "expiry": 0},
    "polymarket": {"data": None, "expiry": 0}
}

async def fetch_indodax_info(session):
    if not INDODAX_API_KEY or not INDODAX_API_SECRET:
        return None
        
    now = time.time()
    if cache["indodax"]["data"] and now < cache["indodax"]["expiry"]:
        return cache["indodax"]["data"]

    try:
        url = "https://indodax.com/tapi"
        nonce = int(time.time() * 1000)
        params = {"method": "getInfo", "nonce": nonce}
        post_data = urllib.parse.urlencode(params)
        
        sign = hmac.new(INDODAX_API_SECRET.encode(), post_data.encode(), hashlib.sha512).hexdigest()
        headers = {
            "Key": INDODAX_API_KEY,
            "Sign": sign
        }
        
        async with session.post(url, data=params, headers=headers, timeout=3.0) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("success") == 1:
                    info = data["return"]
                    # Calculate estimated total in IDR (simplified)
                    total_idr = float(info["balance"].get("idr", 0))
                    # Add held assets if available
                    for asset, val in info["balance"].items():
                        if asset != "idr" and float(val) > 0:
                            # We could fetch prices here, but for now let's just report IDR + asset list
                            pass
                    
                    result = {
                        "portfolioValueIdr": f"Rp {total_idr:,.0f}",
                        "availableBalanceIdr": f"Rp {total_idr:,.0f}",
                        "holdings_count": len([v for v in info['balance'].values() if float(v) > 0]),
                        "status": "LIVE (Direct API)",
                        "raw_balance": info["balance"]
                    }

                    cache["indodax"] = {"data": result, "expiry": now + 10} # Cache 10s
                    return result
    except Exception as e:
        print(f"Indodax API Error: {e}")
    return None

async def fetch_node_metrics(session, hostname=None):
    """Fetch CPU, RAM, and Disk usage from Netdata Parent API."""
    base_url = f"http://localhost:19999"
    if hostname:
        url = f"{base_url}/host/{hostname}/api/v1/allmetrics?format=json"
    else:
        url = f"{base_url}/api/v1/allmetrics?format=json"
    
    try:
        async with session.get(url, timeout=2.0) as resp:
            if resp.status == 200:
                data = await resp.json()
                
                # 1. CPU Usage
                cpu_chart = data.get("system.cpu", {})
                idle = cpu_chart.get("dimensions", {}).get("idle", {}).get("value", 100)
                cpu_usage = max(0, min(100, 100 - idle))
                
                # 2. RAM Usage
                ram_chart = data.get("system.ram", {})
                dims = ram_chart.get("dimensions", {})
                free = dims.get("free", {}).get("value", 0)
                used = dims.get("used", {}).get("value", 0)
                total = free + used + dims.get("cached", {}).get("value", 0) + dims.get("buffers", {}).get("value", 0)
                ram_usage = (used / total * 100) if total > 0 else 0
                
                # 3. Disk Usage
                disk_chart = data.get("disk_space./", {})
                d_dims = disk_chart.get("dimensions", {})
                d_used = d_dims.get("used", {}).get("value", 0)
                total_disk = d_used + d_dims.get("avail", {}).get("value", 0)
                disk_usage = (d_used / total_disk * 100) if total_disk > 0 else 0
                
                print(f"DEBUG Netdata ({hostname or 'local'}): CPU={cpu_usage:.1f}% RAM={ram_usage:.1f}% DISK={disk_usage:.1f}%")
                return {
                    "cpu": round(cpu_usage, 1),
                    "ram": round(ram_usage, 1),
                    "disk": round(disk_usage, 1),
                    "online": True
                }
            else:
                print(f"DEBUG Netdata ({hostname or 'local'}): HTTP {resp.status}")
    except Exception as e:
        print(f"DEBUG Netdata ({hostname or 'local'}): ERROR {e}")
    return {"cpu": 0, "ram": 0, "disk": 0, "online": False}

async def handle_full_state(request):
    # 1. Get Local Manager State
    manager_state = {}
    if os.path.exists(FULL_STATE_FILE):
        try:
            with open(FULL_STATE_FILE, "r") as f:
                manager_state = json.load(f)
        except: pass
    
    # MSC Scanner Data (Optional local overlay)
    scanner_overlay = {}
    try:
        if os.path.exists(MSC_STATE_FILE):
            with open(MSC_STATE_FILE, "r") as f:
                scanner_overlay = json.load(f)
    except: pass

    # 2. Fetch Netdata Metrics for all nodes in parallel
    nodes_metrics = await asyncio.gather(
        fetch_node_metrics(request.app["client"], None),             # Batam
        fetch_node_metrics(request.app["client"], "kibot-kotlin-1"), # EXECUTOR
        fetch_node_metrics(request.app["client"], "kibot-binance")   # SCANNER
    )
    batam_sys, EXECUTOR_sys, SCANNER_sys = nodes_metrics

    # 3. Get EXECUTOR Engine State
    engine_state = {}
    engine_source = "None"
    try:
        async with request.app["client"].get(f"{ENGINE_UPSTREAM}/api/state", timeout=3.0, ssl=False) as resp:
            if resp.status == 200:
                raw = await resp.json()
                engine_source = "Java/EXECUTOR"
                engine_state = raw.get("engine", raw)
                # Inject real Netdata stats
                engine_state["system"] = EXECUTOR_sys if EXECUTOR_sys["online"] else {"cpu": 0, "ram": 0, "disk": 0}
    except Exception as e:
        engine_source = f"Error ({type(e).__name__})"
        # Fallback to just Netdata if Java is down
        engine_state["system"] = EXECUTOR_sys if EXECUTOR_sys["online"] else None

    # 4. Get Polymarket Data (from EXECUTOR:11600)
    try:
        async with request.app["client"].get("http://213.35.118.26:11600/api/state", timeout=2.0, ssl=False) as resp:
            if resp.status == 200:
                poly_raw = await resp.json()
                engine_state["poly_usdc"] = poly_raw.get("cash_usd", 0.0)
                engine_state["poly_matic"] = poly_raw.get("matic_balance", 0.0)
    except:
        engine_state.setdefault("poly_usdc", 0.0)
        engine_state.setdefault("poly_matic", 0.0)

    # 5. IF Engine is empty/dead/Rp 0, Try to fetch from Indodax Direct
    current_val = str(engine_state.get("portfolioValueIdr", "Rp 0")).replace(" ", "").upper()
    if not engine_state.get("portfolioValueIdr") or current_val in ["RP0", "NULL", "NONE"]:
        direct_data = await fetch_indodax_info(request.app["client"])
        if direct_data:
            engine_state.update(direct_data)
            engine_source = "DirectAPI_Fallback"
        else:
            engine_state.update({
                'portfolioValueIdr': "Rp --",
                'availableBalanceIdr': "Rp --",
                'dailyPnlIdr': "Rp --",
                'dailyPnlPct': 0.0,
                'status': "OFFLINE"
            })

    # 6. Get SCANNER Scanner State
    scanner_state = {}
    try:
        async with request.app["client"].get(f"{SCANNER_UPSTREAM}/api/state", timeout=3.0, ssl=False) as resp:
            if resp.status == 200:
                raw = await resp.json()
                scanner_state = raw.get("scanner", raw)
                # Inject real Netdata stats
                scanner_state["system"] = SCANNER_sys if SCANNER_sys["online"] else {"cpu": 0, "ram": 0, "disk": 0}
    except Exception as e:
        scanner_state["system"] = SCANNER_sys if SCANNER_sys["online"] else None

    # Final enrichment: ensure system keys exist
    if not engine_state.get('system'):
        engine_state['system'] = EXECUTOR_sys if EXECUTOR_sys["online"] else {"cpu": 0, "ram": 0, "disk": 0}
    if not scanner_state.get('system'):
        scanner_state['system'] = SCANNER_sys if SCANNER_sys["online"] else {"cpu": 0, "ram": 0, "disk": 0}

    master_state = {
        "manager": manager_state,
        "engine": engine_state,
        "scanner": scanner_state,
        "scanner_overlay": scanner_overlay,
        "system": batam_sys,
        "telemetry_source": engine_source,
        "timestamp": time.time()
    }
    return web.json_response(master_state, headers={"Access-Control-Allow-Origin": "*"})




async def handle_dashboard(request):
    index_path = os.path.join(ROOT_DIR, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="index.html not found", status=404)

async def handle_live_state(request):
    try:
        # Use a fresh session to bypass any potential shared session issues
        async with ClientSession() as session:
            async with session.get(f"{SCANNER_UPSTREAM}/api/state", timeout=10.0, ssl=False) as resp:
                if resp.status == 200:
                    raw = await resp.json()
                    scanner_data = raw.get("scanner", {})
                    # Standardize for UI
                    if "active_signals" not in scanner_data:
                        if "signals" in scanner_data:
                            scanner_data["active_signals"] = scanner_data["signals"]
                        elif "scanners" in scanner_data:
                            scanner_data["active_signals"] = scanner_data["scanners"]
                    return web.json_response(scanner_data, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        print(f"DEBUG: Live state fetch from SCANNER failed (Fresh Session): {e}")
    
    return web.json_response({"active_signals": [], "error": "upstream_error"}, headers={"Access-Control-Allow-Origin": "*"})

async def handle_index(request):
    index_path = os.path.join(STATIC_DIR, "kibot_dashboard.html")
    if os.path.exists(index_path): return web.FileResponse(index_path)
    return web.Response(text="Dashboard not found", status=404)

async def proxy_request(request, upstream_base):
    target = f"{upstream_base}{request.rel_url}"
    try:
        async with request.app["client"].request(
            request.method, target, headers=request.headers, data=await request.read(), allow_redirects=False
        ) as resp:
            body = await resp.read()
            response = web.Response(status=resp.status, body=body)
            for k, v in resp.headers.items():
                if k.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}:
                    response.headers[k] = v
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response
    except Exception as e:
        return web.json_response({"error": "upstream_err", "msg": str(e)}, status=503)

async def handle_api(request):
    if request.path == "/api/state": return await handle_full_state(request)
    if request.path.startswith("/api/manager"): return await proxy_request(request, MANAGER_UPSTREAM)
    elif request.path.startswith("/api/engine"): return await proxy_request(request, ENGINE_UPSTREAM)
    return await proxy_request(request, MANAGER_UPSTREAM)

async def handle_ws(request):
    target_ws = f"{ENGINE_UPSTREAM}/ws"
    ws_server = web.WebSocketResponse(autoping=True, heartbeat=30)
    await ws_server.prepare(request)
    try:
        async with request.app["client"].ws_connect(target_ws, heartbeat=30) as ws_client:
            async def forward(src, dst):
                async for msg in src:
                    if msg.type == WSMsgType.TEXT: await dst.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY: await dst.send_bytes(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR): break
            await asyncio.gather(forward(ws_client, ws_server), forward(ws_server, ws_client))
    except Exception: await ws_server.close()
    return ws_server

async def on_startup(app): app["client"] = ClientSession()
async def on_cleanup(app): await app["client"].close()

def main():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/live", handle_live_state)
    app.router.add_route("*", "/api/{tail:.*}", handle_api)
    app.router.add_get("/live_state", handle_live_state)
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_route("*", "/ws", handle_ws)
    
    # Serve static files (CSS, JS) if they exist
    if os.path.exists(STATIC_DIR):
        app.router.add_static("/static/", STATIC_DIR)
        # Fallback for root assets
        app.router.add_static("/", STATIC_DIR)
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"Starting Proxy on {LISTEN_HOST}:{LISTEN_PORT}")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__": main()
