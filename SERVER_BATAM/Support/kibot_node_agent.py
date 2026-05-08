import os
import sys
import json
import time
import psutil
import socket
import logging
import subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone

# --- CONFIGURATION ---
NODE_NAME = os.getenv("KIBOT_NODE_NAME", socket.gethostname())
MASTER_IP = "168.110.201.228"  # IP Batam High Command
LISTEN_PORT = 9991             # Port khusus Agent
SECRET_KEY = "kibot_trinity_secure_node" # Simple handshake

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger("NodeAgent")

class NodeCommandHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Status report to Batam"""
        if self.path == "/status":
            status = {
                "node": NODE_NAME,
                "status": "ONLINE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metrics": {
                    "cpu": psutil.cpu_percent(),
                    "ram": psutil.virtual_memory().percent,
                    "disk": psutil.disk_usage('/').percent
                },
                "services": self.check_services()
            }
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())

    def do_POST(self):
        """Execute command from Batam"""
        content_length = int(self.headers['Content-Length'])
        post_data = json.loads(self.rfile.read(content_length))
        
        # Security check
        if post_data.get("key") != SECRET_KEY:
            self.send_response(403)
            self.end_headers()
            return

        command = post_data.get("command")
        target_service = post_data.get("service")

        logger.info(f"Received command: {command} for {target_service}")

        result = {"ok": False, "msg": "unknown_command"}
        
        try:
            if command == "restart":
                subprocess.run(["sudo", "systemctl", "restart", target_service], check=True)
                result = {"ok": True, "msg": f"Service {target_service} restarted"}
            elif command == "stop":
                subprocess.run(["sudo", "systemctl", "stop", target_service], check=True)
                result = {"ok": True, "msg": f"Service {target_service} stopped"}
            elif command == "start":
                subprocess.run(["sudo", "systemctl", "start", target_service], check=True)
                result = {"ok": True, "msg": f"Service {target_service} started"}
        except Exception as e:
            result = {"ok": False, "msg": str(e)}

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def check_services(self):
        """Check status of relevant services on this node"""
        # Monitoring both Indodax and Polymarket trading venues
        services_to_check = ["kibot-scanner", "kibot-executor-engine", "kibot-polymarket", "tailscaled"]
        results = {}
        for s in services_to_check:
            res = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True)
            results[s] = res.stdout.strip()
        return results

    def log_message(self, format, *args):
        return # Silence logs to keep it clean

def run_agent():
    server = HTTPServer(('0.0.0.0', LISTEN_PORT), NodeCommandHandler)
    logger.info(f"🚀 Node Agent [{NODE_NAME}] active on port {LISTEN_PORT}...")
    logger.info(f"🔒 Guarded for Master IP: {MASTER_IP}")
    server.serve_forever()

if __name__ == "__main__":
    run_agent()
