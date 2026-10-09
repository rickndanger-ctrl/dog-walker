"""Private phone companion: loopback HTTP behind Tailscale Serve, paired sessions.

The desktop owns every workflow and review lock. This server only observes its
IPC and submits context-bound review actions; it never edits saved run state.
"""
import argparse
import fcntl
from collections import deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from urllib.parse import urlparse
from uuid import uuid4
from .storage import APP_ROOT, DATA, atomic_json, scrub
from .workflow import WalkerError

CONFIG = Path.home() / ".config/dog-walker/phone.json"
SESSION_AGE = 12 * 3600
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css"), "/sw.js": ("sw.js", "text/javascript"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/icon-192.png": ("icon-192.png", "image/png"), "/icon-512.png": ("icon-512.png", "image/png")}


def credentials(data=DATA):
    path = data / "phone-secret.json"
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation prevents concurrent installers from replacing pairing credentials.
    with open(data / "phone-credentials.lock", "a", opener=lambda p, flags: os.open(p, flags, 0o600)) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists():
            atomic_json(path, {"secret": secrets.token_hex(32), "pair_code": secrets.token_hex(6).upper()})
        path.chmod(0o600)
        return json.loads(path.read_text())


def info():
    config = json.loads(CONFIG.read_text())
    key = credentials()
    return {"url": config["origin"], "pair_code": key["pair_code"],
            "instructions": "Turn on Tailscale on your phone, open this private address, and enter the pairing code. Add Dog Walker to your Home Screen. Keep the desktop app open while a walk is running."}


def ipc(method, *args, pid=None):
    selection = ["--pid", str(pid)] if pid else ["-p", str(APP_ROOT / "native")]
    result = subprocess.run(["quickshell", "ipc", *selection, "call", "dogwalker", method, *args],
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise WalkerError("The desktop is unavailable. Open Dog Walker on the computer.")
    return result.stdout.strip()


def public_state(state):
    if not state:
        return None
    return scrub({k: state.get(k) for k in ("id", "name", "status", "phase", "step", "turns", "history",
        "result", "previous_result", "evaluation", "last_evaluation", "completion", "reason", "allowed_changes", "job")})


class Companion:
    def __init__(self, config, key, call=ipc, data=DATA, secure=True):
        origin = urlparse(config.get("origin", ""))
        if origin.scheme != "https" or not origin.hostname or not origin.hostname.endswith(".ts.net") or origin.path not in {"", "/"} or origin.username or origin.query or origin.fragment:
            raise WalkerError("Phone origin must be the HTTPS address of your Tailscale device")
        if not isinstance(config.get("owner"), str) or not config["owner"]:
            raise WalkerError("Phone access requires an explicit Tailscale owner identity")
        self.config, self.key, self.call, self.data = config, key, call, data
        self.origin = config["origin"].rstrip("/")
        self.host = origin.netloc
        self.secure = secure
        self.control_lock = threading.Lock()
        self.pair_lock = threading.Lock()
        self.attempts = deque()

    def signature(self, value):
        return hmac.new(bytes.fromhex(self.key["secret"]), value.encode(), hashlib.sha256).hexdigest()

    def session(self):
        value = f"{int(time.time())}.{secrets.token_hex(16)}"
        return value + "." + self.signature(value)

    def valid_session(self, value):
        try:
            stamp, nonce, signature = value.split(".")
            age = time.time() - int(stamp)
            return len(nonce) == 32 and 0 <= age <= SESSION_AGE and hmac.compare_digest(signature, self.signature(stamp + "." + nonce))
        except (ValueError, TypeError):
            return False

    def csrf(self, session):
        return self.signature("csrf:" + session)

    def pair(self, value):
        with self.pair_lock:
            now = time.monotonic()
            while self.attempts and now - self.attempts[0] > 60:
                self.attempts.popleft()
            if len(self.attempts) >= 5:
                raise WalkerError("Too many pairing attempts. Wait one minute.")
            self.attempts.append(now)
            code = value.replace("-", "").replace(" ", "").upper() if isinstance(value, str) else ""
            return hmac.compare_digest(code, self.key["pair_code"])

    def snapshot(self):
        try:
            current = json.loads(self.call("companionSnapshot"))
            current["state"] = public_state(current.get("state"))
        except (WalkerError, ValueError, subprocess.TimeoutExpired):
            current = {"connected": False, "active": False, "review": False, "state": None,
                       "reason": "Open Dog Walker on the computer to see or control the current walk."}
        runs = []
        for path in sorted((self.data / "runs").glob("*/state.json"), reverse=True)[:30]:
            try:
                s = json.loads(path.read_text())
                runs.append({k: s.get(k) for k in ("id", "name", "status", "step", "completion")})
            except (OSError, ValueError):
                pass
        return {"current": current, "runs": runs, "time": time.time()}

    def control(self, value):
        if not isinstance(value, dict) or set(value) != {"action", "run_id", "review_id"}:
            raise WalkerError("An action must identify its run and review request")
        if value["action"] not in {"approve", "retry", "pause", "resume"} or not all(isinstance(v, str) and len(v) <= 100 for v in value.values()):
            raise WalkerError("Unsupported phone action")
        with self.control_lock:
            request = {**value, "request_id": uuid4().hex}
            status = self.call("companionControl", json.dumps(request))
            if status != "sent":
                raise WalkerError("This review or walk changed. Refresh before trying again.")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                result = json.loads(self.call("companionReply", request["request_id"]))
                if result is not None:
                    if not result["ok"]:
                        raise WalkerError(result["message"])
                    return {"ok": True, "message": "Decision accepted by the desktop. Verification still runs before advancement."}
                time.sleep(.05)
            raise WalkerError("The desktop did not confirm this request. Refresh before trying again.")


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DogWalkerPhone"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass  # Never log cookies, pairing codes, or project content.

        def respond(self, status, value, kind="application/json", cookie=None):
            body = json.dumps(value).encode() if kind == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def identity(self):
            return (self.headers.get("Host") == app.host and
                    self.headers.get("Tailscale-User-Login") == app.config["owner"])

        def session_cookie(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                return cookie["dogwalker"].value if "dogwalker" in cookie else ""
            except Exception:
                return ""

        def do_GET(self):
            if not self.identity():
                self.respond(403, {"message": "Connect through the owner's private Tailscale account."})
                return
            if self.path in ASSETS:
                name, kind = ASSETS[self.path]
                self.respond(200, (APP_ROOT / "phone" / name).read_bytes(), kind)
            elif self.path == "/api/state":
                session = self.session_cookie()
                if not app.valid_session(session):
                    self.respond(401, {"message": "Pair this phone with the desktop first."})
                    return
                self.respond(200, {**app.snapshot(), "csrf": app.csrf(session)})
            else:
                self.respond(404, {"message": "Not found"})

        def do_POST(self):
            if not self.identity() or self.headers.get("Origin") != app.origin or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.respond(403, {"message": "Request origin or private identity was rejected."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    self.respond(413, {"message": "Request must be smaller than 8 KB."})
                    return
                value = json.loads(self.rfile.read(length))
                if self.path == "/api/pair":
                    if not isinstance(value, dict) or set(value) != {"code"} or not app.pair(value["code"]):
                        self.respond(403, {"message": "Pairing code was not accepted."})
                        return
                    session = app.session()
                    cookie = f"dogwalker={session}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_AGE}" + ("; Secure" if app.secure else "")
                    self.respond(200, {"ok": True}, cookie=cookie)
                elif self.path == "/api/control":
                    session = self.session_cookie()
                    if not app.valid_session(session) or not hmac.compare_digest(self.headers.get("X-Dogwalker-CSRF", ""), app.csrf(session)):
                        self.respond(403, {"message": "Pairing session or action token was rejected."})
                        return
                    self.respond(200, app.control(value))
                else:
                    self.respond(404, {"message": "Not found"})
            except (ValueError, UnicodeError, TypeError):
                self.respond(400, {"message": "Invalid request"})
            except (WalkerError, subprocess.TimeoutExpired) as exc:
                self.respond(409, {"message": str(exc)})
    return Handler


def server(config, key, port=18190, **options):
    app = Companion(config, key, **options)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler(app))
    httpd.daemon_threads = True
    return httpd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--port", type=int, default=18190)
    args = parser.parse_args()
    os.umask(0o077)
    httpd = server(json.loads(args.config.read_text()), credentials(), args.port)
    print("Dog Walker phone companion is listening on loopback behind private Tailscale Serve.", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
