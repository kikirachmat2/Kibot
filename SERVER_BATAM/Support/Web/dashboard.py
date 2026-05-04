import os, asyncio, json, time, hmac, hashlib, urllib.parse
from aiohttp import web, ClientSession, WSMsgType, ClientConnectorError
from pathlib import Path

# Configuration - TRINITY V9.1
MANAGER_UPSTREAM = "http://127.0.0.1:11600"
ENGINE_UPSTREAM = "http://213.35.118.26:8787"
SCANNER_UPSTREAM = "http://152.69.218.198:8787"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", 8787))

# FIX PATH RESOLUTION:
# SCRIPT_DIR is KiBot/SERVER_BATAM/Support/Web
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Kita cari file html di folder yang sama dengan script ini
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "kibot_dashboard.html")

# Root KiBot dir
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
STATE_DIR = os.path.join(ROOT_DIR, "SERVER_BATAM", "state")
SECURITY_LOG = os.path.join(STATE_DIR, "security_ledger.jsonl")

# ... (rest of the logic) ...

async def handle_index(request):
    if os.path.exists(DASHBOARD_HTML):
        return web.FileResponse(DASHBOARD_HTML)
    # Debug: Jika gagal, beri tahu path mana yang dicari
    return web.Response(text=f"Dashboard not found. Searching at: {DASHBOARD_HTML}", status=404)

# ... (rest of the functions) ...

def main():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/state", handle_full_state)
    app.router.add_get("/api/security", handle_security_logs)
    app.router.add_get("/full_state", handle_full_state)
    
    # Static files also in the same folder
    app.router.add_static("/static/", SCRIPT_DIR)
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print(f"🚀 DASHBOARD FIXED & RUNNING on {LISTEN_HOST}:{LISTEN_PORT}")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)

if __name__ == "__main__": main()
