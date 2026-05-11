import os
import subprocess

SERVICES = {
    "kibot-master": {
        "Description": "KiBot Sovereign Master Node",
        "ExecStart": "/home/ubuntu/KiBot/venv/bin/python3 -u MasterNode.py"
    },
    "kibot-executor": {
        "Description": "KiBot Indodax Executor",
        "ExecStart": "/home/ubuntu/KiBot/venv/bin/python3 -u Core/Executors/indodax_executor.py"
    },
    "kibot-scanner": {
        "Description": "KiBot Universal Scanner",
        "ExecStart": "/home/ubuntu/KiBot/venv/bin/python3 -u Core/Scanner/ki_universal_leadlag_scanner.py"
    }
}

TEMPLATE = """[Unit]
Description={Description}
After=network-online.target redis-server.service
Wants=network-online.target redis-server.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/KiBot
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=.
ExecStart={ExecStart}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier={Name}

[Install]
WantedBy=multi-user.target
"""

def setup():
    for name, config in SERVICES.items():
        content = TEMPLATE.format(
            Description=config["Description"],
            ExecStart=config["ExecStart"],
            Name=name
        )
        path = f"/tmp/{name}.service"
        with open(path, "w") as f:
            f.write(content)
        
        print(f"Installing {name}...")
        subprocess.run(["sudo", "cp", path, f"/etc/systemd/system/{name}.service"], check=True)
    
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    for name in SERVICES.keys():
        subprocess.run(["sudo", "systemctl", "enable", name], check=True)
        subprocess.run(["sudo", "systemctl", "restart", name], check=True)
    
    print("All services restarted successfully.")

if __name__ == "__main__":
    setup()
