import os, asyncio, json, time, logging
from datetime import datetime, timezone
from pathlib import Path
from aiohttp import web, ClientSession, ClientTimeout, WSMsgType

# Configuration - TRINITY V9.1 CLUSTER
NODES = {
    "BATAM": "127.0.0.1",
    "EXECUTOR": "213.35.118.26",
    "SCANNER": "152.69.218.198"
}

LISTEN_HOST = os.environ.get("KIBOT_DASHBOARD_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("KIBOT_DASHBOARD_PORT", "8787"))
NETDATA_PORT = 19999

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")

RUNTIME_STATE_PATH = Path(os.environ.get(
    "KIBOT_RUNTIME_NOTE_PATH",
    os.path.join(os.path.dirname(SCRIPT_DIR), "state", "runtime_note.json")
))

# Connected WebSocket clients
_ws_clients: set = set()
_last_broadcast_snapshot: dict = {}

log = logging.getLogger("dashboard")


async def fetch_json(session, url, timeout_sec=1.5):
    try:
        timeout = ClientTimeout(total=timeout_sec)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status == 200: return await resp.json()
    except Exception as e:
        log.debug(f"Fetch {url}: {e}")
    return {}


async def get_node_stats(session, host):
    url = f"http://{host}:{NETDATA_PORT}/api/v1/allmetrics?format=json"
    data = await fetch_json(session, url, timeout_sec=0.8)
    stats = {"cpu": 0, "ram": 0, "online": False}
    if data:
        try:
            stats["cpu"] = round(data.get("system.cpu", {}).get("dimensions", {}).get("user", {}).get("value", 0), 1)
            mem = data.get("system.ram", {}).get("dimensions", {})
            used = mem.get("used", 0)
            total = used + mem.get("cached", 0) + mem.get("free", 0)
            stats["ram"] = round((used / total) * 100, 1) if total > 0 else 0
            stats["online"] = True
        except:
            stats["online"] = True
    return stats


def _load_runtime_state() -> dict:
    """Load kibot_manager runtime note (snapshot) from disk."""
    try:
        if RUNTIME_STATE_PATH.exists():
            raw = RUNTIME_STATE_PATH.read_text(encoding="utf-8", errors="replace")
            return json.loads(raw)
    except Exception as e:
        log.debug(f"runtime_state load error: {e}")
    return {}


def _build_ws_snapshot(runtime: dict, nodes: list, engine_data: dict) -> dict:
    """Build the snapshot envelope expected by the Android APK (CommandCenterLiveSnapshot)."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Try to pull formatted fields from runtime note
    def rp(val):
        if val is None:
            return "Rp0"
        v = float(val) if isinstance(val, (int, float)) else 0.0
        return f"Rp{v:,.0f}".replace(",", ".")

    total_val_idr = runtime.get("totalValueIdr") or engine_data.get("total_rp") or runtime.get("portfolioValueIdr") or 0
    free_idr = runtime.get("freeIdr") or runtime.get("freeIdrRaw") or 0
    pnl_today_idr = runtime.get("pnlTodayIdr") or runtime.get("pnlToday") or 0
    pnl_today_pct = runtime.get("pnlTodayPct") or runtime.get("dailyPnlPct") or 0
    effective_state = runtime.get("effectiveState") or runtime.get("status") or "STOPPED"
    sync_health = runtime.get("syncHealth") or "OK"
    bot_id = runtime.get("botId") or "kibot"
    ai_summary = runtime.get("aiProviderSummary") or "AI ONLINE"
    health_summary = runtime.get("healthSummary") or "Monitoring..."
    status_msg = runtime.get("statusMessage") or "KiBot Batam aktif."
    top_candidate = runtime.get("topCandidate") or runtime.get("activePair") or "-"
    radar_pairs = runtime.get("radarPairs") or []
    live_exec = runtime.get("liveExecutionEnabled") or (effective_state not in ("STOPPED", "PAUSED"))

    # Holdings
    holdings = engine_data.get("holdings") or runtime.get("holdingsDetailed") or []

    # Recent orders
    recent_orders = runtime.get("recentOrders") or runtime.get("lastOrders") or []

    snapshot = {
        "botId": bot_id,
        "totalValueIdr": total_val_idr if isinstance(total_val_idr, str) else rp(total_val_idr),
        "freeIdrLabel": free_idr if isinstance(free_idr, str) else rp(free_idr),
        "pnlTodayIdr": pnl_today_idr if isinstance(pnl_today_idr, str) else rp(pnl_today_idr),
        "pnlTodayPctLabel": f"{float(pnl_today_pct):+.2f}%" if isinstance(pnl_today_pct, (int, float)) else str(pnl_today_pct),
        "totalReturnPctLabel": f"{float(pnl_today_pct):+.2f}%" if isinstance(pnl_today_pct, (int, float)) else str(pnl_today_pct),
        "return7dIdr": rp(runtime.get("return7dIdr") or 0),
        "return7dPctLabel": f"{float(runtime.get('return7dPct') or 0):+.2f}%",
        "return30dIdr": rp(runtime.get("return30dIdr") or 0),
        "return30dPctLabel": f"{float(runtime.get('return30dPct') or 0):+.2f}%",
        "effectiveState": effective_state,
        "syncHealth": sync_health,
        "liveExecutionEnabled": live_exec,
        "aiProviderSummary": ai_summary,
        "healthSummary": health_summary,
        "statusMessage": status_msg,
        "topCandidate": top_candidate,
        "radarPairs": radar_pairs,
        "holdingsDetailed": holdings,
        "recentOrders": recent_orders,
        "netWorthHistory": runtime.get("netWorthHistory") or [],
        "assetAllocationDetailed": runtime.get("assetAllocationDetailed") or [],
        "KiBotNodeStatus": "online" if nodes and nodes[0].get("online") else "offline",
        "kibotNodeStatus": "online" if nodes and nodes[0].get("online") else "offline",
        "exchangePingValueMs": runtime.get("exchangePingMs") or 0,
        "sentAtEpochMs": now_ms,
    }
    return {"snapshot": snapshot}


async def handle_full_state(request):
    session = request.app["client"]
    now = datetime.now()
    now_ms = int(now.timestamp() * 1000)
    time_str = now.strftime("%H:%M:%S")

    # Parallel Fetch
    node_results = await asyncio.gather(*[get_node_stats(session, ip) for ip in NODES.values()])
    engine_data = await fetch_json(session, f"http://{NODES['EXECUTOR']}:8787/api/state", timeout_sec=1.5)

    last_act = engine_data.get("last_action", "TRINITY V9.1 ACTIVE - Monitoring")

    recent_item = {
        "time": now_ms, "timestamp": now_ms, "time_str": time_str,
        "action": last_act, "text": last_act, "type": "info"
    }
    master_state = {
        "nodes": {
            "BATAM": node_results[0], "EXECUTOR": node_results[1], "SCANNER": node_results[2],
            "SG-Executor": node_results[1], "SG-Scanner": node_results[2]
        },
        "system": node_results[0],
        "engine": {
            "total_rp": engine_data.get("total_rp", 0),
            "portfolioValueIdr": engine_data.get("total_rp", 0),
            "holdings": engine_data.get("holdings", []),
            "recent_actions": [recent_item]
        },
        "manager": {"recent_actions": [recent_item]},
        "timestamp": now_ms, "time_str": time_str, "status": "connected"
    }
    return web.json_response(master_state, headers={"Access-Control-Allow-Origin": "*"})


async def handle_websocket(request):
    """WebSocket endpoint /ws — serves CommandCenterLiveSnapshot to Android APK."""
    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=1024*1024)
    await ws.prepare(request)
    _ws_clients.add(ws)
    log.info(f"[WS] Client connected: {request.remote} | total={len(_ws_clients)}")

    try:
        # Send initial snapshot immediately on connect
        runtime = _load_runtime_state()
        node_results = [{"online": True}]
        snapshot_msg = _build_ws_snapshot(runtime, node_results, {})
        await ws.send_str(json.dumps(snapshot_msg))

        # Handle incoming messages from APK (commands, subscribe, full_state requests)
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = str(data.get("type") or data.get("command") or "").lower()
                    log.debug(f"[WS] Received from {request.remote}: {msg.data[:120]}")

                    if msg_type in ("request", "full_state") or data.get("data") == "full_state":
                        runtime = _load_runtime_state()
                        snap = _build_ws_snapshot(runtime, [{"online": True}], {})
                        await ws.send_str(json.dumps(snap))
                    elif msg_type == "subscribe":
                        # Acknowledge subscribe
                        await ws.send_str(json.dumps({"type": "subscribed", "channels": data.get("channels", [])}))
                    elif "command" in data or data.get("type") == "command":
                        # Forward commands to kibot_manager via a command file drop
                        cmd_path = RUNTIME_STATE_PATH.parent / "android_command.json"
                        try:
                            cmd_path.parent.mkdir(parents=True, exist_ok=True)
                            cmd_path.write_text(json.dumps({
                                "from": "android",
                                "at": int(time.time() * 1000),
                                **data
                            }), encoding="utf-8")
                        except Exception as e:
                            log.warning(f"[WS] Failed to write command: {e}")
                        await ws.send_str(json.dumps({"reply": {"message": "Command queued", "echoCommand": data.get("command", "")}}))
                except json.JSONDecodeError:
                    pass
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    except Exception as e:
        log.error(f"[WS] Error: {e}")
    finally:
        _ws_clients.discard(ws)
        log.info(f"[WS] Client disconnected: {request.remote} | remaining={len(_ws_clients)}")

    return ws


async def _broadcast_loop(app):
    """Push fresh snapshots to all connected WebSocket clients every 3 seconds."""
    global _last_broadcast_snapshot
    while True:
        await asyncio.sleep(3)
        if not _ws_clients:
            continue
        try:
            runtime = _load_runtime_state()
            snap = _build_ws_snapshot(runtime, [{"online": True}], {})
            if snap == _last_broadcast_snapshot:
                continue  # No change, skip broadcast
            _last_broadcast_snapshot = snap
            payload = json.dumps(snap)
            dead = set()
            for ws in list(_ws_clients):
                try:
                    await ws.send_str(payload)
                except Exception:
                    dead.add(ws)
            _ws_clients.difference_update(dead)
        except Exception as e:
            log.debug(f"[WS][BROADCAST] {e}")


async def on_startup(app):
    app["client"] = ClientSession()
    app["broadcast_task"] = asyncio.create_task(_broadcast_loop(app))


async def on_cleanup(app):
    app["broadcast_task"].cancel()
    await app["client"].close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = web.Application()
    app.router.add_get("/ws", handle_websocket)          # ← Android APK WebSocket
    app.router.add_get("/", lambda r: web.FileResponse(DASHBOARD_HTML))
    app.router.add_get("/full_state", handle_full_state)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/favicon.ico", lambda r: web.FileResponse(os.path.join(SCRIPT_DIR, "kibot.png")))
    app.router.add_get("/kibot.png", lambda r: web.FileResponse(os.path.join(SCRIPT_DIR, "kibot.png")))
    if os.path.exists(SCRIPT_DIR):
        app.router.add_static("/static/", SCRIPT_DIR)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"🚀 TRINITY DASHBOARD v9.2 | WebSocket /ws ONLINE | port {LISTEN_PORT}")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)


if __name__ == "__main__":
    main()
