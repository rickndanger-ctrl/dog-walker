import json
import subprocess
import sys

from dog_walker.helper_mcp import dispatch, run_stdio


class FakeServer:
    mode = "review"

    def __init__(self):
        self.calls = []

    def tools(self):
        return [{"name": "inspect", "inputSchema": {"type": "object"}}]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}


def request(method, request_id=1, params=None):
    message = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        message["params"] = params
    return message


def test_initialize_negotiates_supported_version_and_describes_mode():
    server = FakeServer()
    response = dispatch(server, request("initialize", params={
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    }))
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["serverInfo"] == {"name": "handler-helper", "version": "0.1"}
    assert "suggestions only" in response["result"]["instructions"]


def test_dispatch_validates_shape_and_never_answers_notifications():
    server = FakeServer()
    assert dispatch(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert dispatch(server, {"jsonrpc": "1.0", "method": "ping", "id": 2})["error"]["code"] == -32600
    assert dispatch(server, request("tools/call", params={"name": "inspect", "arguments": []}))["error"]["code"] == -32602
    assert dispatch(server, request("unknown"))["error"]["code"] == -32601
    assert server.calls == []


def test_stdio_uses_one_json_rpc_frame_per_line_and_skips_notifications():
    # Exercise the actual newline protocol over OS pipes with an injected server.
    code = r'''
import sys
from dog_walker.helper_mcp import run_stdio
class Fake:
    mode = "drive"
    def tools(self): return [{"name": "inspect"}]
    def call(self, name, arguments):
        return {"content": [{"type": "text", "text": name}], "isError": False}
run_stdio(Fake())
'''
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    frames = [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        request("ping", 7),
        request("tools/call", 8, {"name": "inspect", "arguments": {}}),
    ]
    stdout, stderr = child.communicate("".join(json.dumps(frame) + "\n" for frame in frames), timeout=10)
    assert child.returncode == 0, stderr
    replies = [json.loads(line) for line in stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [7, 8]
    assert replies[0]["result"] == {}
    assert replies[1]["result"]["content"][0]["text"] == "inspect"


def test_stdio_bounds_oversize_frame_and_continues():
    import io

    server = FakeServer()
    stdin = io.BytesIO(b"{" + b" " * (256 * 1024) + b"}\n" + b'{"jsonrpc":"2.0","method":"ping","id":9}\n')
    stdout = io.BytesIO()
    run_stdio(server, stdin=stdin, stdout=stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 9
