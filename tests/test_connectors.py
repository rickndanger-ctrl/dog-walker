"""Optional integration checks for the app-local MCP connector installs."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dog_walker import plugins


def installed_manifest(ident):
    path = plugins.PLUGIN_DIR / f"{ident}.json"
    if not path.is_file():
        pytest.skip(f"Optional connector {ident} is not installed")
    return plugins.validate_plugin(json.loads(path.read_text()))


def mcp_process(manifest):
    settings = manifest["settings"]
    env = os.environ.copy()
    env.pop("FIRECRAWL_API_KEY", None)
    return subprocess.Popen([settings["command"], *settings["args"]], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=env)


def send(proc, value):
    proc.stdin.write(json.dumps(value) + "\n")
    proc.stdin.flush()


def receive(proc, ident, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            break
        line = proc.stdout.readline()
        if not line:
            break
        value = json.loads(line)
        if value.get("id") == ident:
            return value
    raise AssertionError(f"MCP server did not answer request {ident}")


def initialize(proc):
    send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "dog-walker-test", "version": "1"}}})
    assert "result" in receive(proc, 1)
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_firecrawl_actual_stdio_tools_list_keyless():
    manifest = installed_manifest("firecrawl")
    proc = mcp_process(manifest)
    try:
        initialize(proc)
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        response = receive(proc, 2)
        assert "result" in response, response
        names = {tool["name"] for tool in response["result"]["tools"]}
        assert set(manifest["settings"]["enabled_tools"]) <= names
    finally:
        stop(proc)


def test_playwright_actual_stdio_tools_list_and_local_fixture():
    manifest = installed_manifest("playwright-browser")
    if not shutil.which("chromium") and not shutil.which("google-chrome"):
        pytest.skip("Chromium is unavailable")

    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            page = (b"<!doctype html><title>Dog Walker fixture</title><h1>Local browser check</h1>"
                    b"<input id='name' aria-label='Name'><button id='submit'>Greet</button>"
                    b"<p id='result'></p><script>document.querySelector('#submit').onclick=()=>document.querySelector('#result').textContent='Hello '+document.querySelector('#name').value</script>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *_):
            pass

    site = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    proc = mcp_process(manifest)
    try:
        initialize(proc)
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = receive(proc, 2)
        assert "result" in listed, listed
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert set(manifest["settings"]["enabled_tools"]) <= names

        send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "browser_navigate", "arguments": {"url": f"http://127.0.0.1:{site.server_port}/"}}})
        opened = receive(proc, 3, timeout=60)
        assert "result" in opened, opened
        send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "browser_type", "arguments": {"target": "#name", "text": "Ada"}}})
        assert "result" in receive(proc, 4)
        send(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "browser_click", "arguments": {"target": "#submit"}}})
        assert "result" in receive(proc, 5)
        send(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "browser_snapshot", "arguments": {}}})
        snapshot = receive(proc, 6)
        rendered = json.dumps([opened["result"], snapshot.get("result", {})])
        assert "Dog Walker fixture" in rendered and "Local browser check" in rendered
        assert "Hello Ada" in rendered
        send(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "browser_close", "arguments": {}}})
        assert "result" in receive(proc, 7)
    finally:
        stop(proc)
        site.shutdown()
