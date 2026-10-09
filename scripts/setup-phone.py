#!/usr/bin/env python3
"""Install the optional private companion without changing other Serve routes."""
import json
import os
from pathlib import Path
import subprocess
from dog_walker.phone import CONFIG, credentials

root = Path(__file__).resolve().parents[1]
status = json.loads(subprocess.check_output(["tailscale", "status", "--json"]))
if status["BackendState"] != "Running":
    raise SystemExit("Connect Tailscale on this computer first.")
host = status["Self"]["DNSName"].rstrip(".")
owner = status["User"][str(status["Self"]["UserID"])]["LoginName"]
current = json.loads(subprocess.check_output(["tailscale", "serve", "status", "--json"]))
target = "http://127.0.0.1:18190"
existing = current.get("Web", {}).get(host + ":443", {}).get("Handlers", {}).get("/")
if current and existing != {"Proxy": target}:
    raise SystemExit("This computer already has other Tailscale Serve routes. Keep them; choose a separate HTTPS port before setting up Dog Walker.")
os.umask(0o077)
credentials()
CONFIG.parent.mkdir(parents=True, exist_ok=True)
CONFIG.write_text(json.dumps({"origin": "https://" + host, "owner": owner}, indent=2) + "\n")
CONFIG.chmod(0o600)
unit = Path.home() / ".config/systemd/user/dog-walker-phone.service"
unit.parent.mkdir(parents=True, exist_ok=True)
unit.write_text(f'''[Unit]
Description=Dog Walker private phone companion
After=default.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={root}/.venv/bin/python -m dog_walker.phone
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=default.target
''')
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
subprocess.run(["systemctl", "--user", "enable", "--now", unit.name], check=True)
subprocess.run(["tailscale", "serve", "--bg", "--https=443", target], check=True)
print("Phone companion ready at https://" + host)
print("Open Phone companion in the desktop app to see your private pairing code.")
