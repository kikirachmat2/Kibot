import os
import json
import time
import socket
from flask import Flask, render_template, jsonify
from flask_cors import CORS
from pathlib import Path

app = Flask(__name__)
CORS(app)

# Path ke data
ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
SECURITY_LOG = STATE_DIR / "security_ledger.jsonl"

def get_node_status():
    """Simulasi pengecekan status node (Bisa diupgrade dengan heartbeat asli)"""
    return {
        "batam": {"status": "ONLINE", "latency": "12ms", "version": "9.1-Secure"},
        "executor": {"status": "ONLINE", "latency": "45ms", "mode": "Reactive"},
        "scanner": {"status": "STREAMING", "latency": "8ms", "bps": "120kbps"}
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify({
        "nodes": get_node_status(),
        "timestamp": time.time()
    })

@app.route('/api/security')
def security():
    logs = []
    if SECURITY_LOG.exists():
        with open(SECURITY_LOG, "r") as f:
            lines = f.readlines()[-10:] # Ambil 10 log terakhir
            for line in lines:
                logs.append(json.loads(line))
    return jsonify(logs)

if __name__ == '__main__':
    # Pastikan folder templates ada
    os.makedirs(os.path.join(os.path.dirname(__file__), 'templates'), exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
