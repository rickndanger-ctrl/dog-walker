import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dog_walker.transport import MAX_REQUEST_BYTES, ResponsesBridge


class FakeResponses:
    def __init__(self):
        self.requests = []
        self.blocking = False
        self.block_after_headers = False
        self.block_started = threading.Event()
        self.block_released = threading.Event()
        self.redirect = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *_args): pass

            def _json(self, status, value, headers=None):
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for key, val in (headers or {}).items(): self.send_header(key, val)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try: self.wfile.write(body)
                except OSError: pass

            def do_GET(self):
                owner.requests.append(("GET", self.path, dict(self.headers)))
                if owner.redirect:
                    self.send_response(302); self.send_header("Location", "https://example.invalid/steal"); self.send_header("Content-Length", "0"); self.end_headers()
                else:
                    self._json(200, {"path": self.path}, {"Set-Cookie": "secret=should-not-forward"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                owner.requests.append(("POST", self.path, dict(self.headers), payload))
                if owner.block_after_headers:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.flush()
                    owner.block_started.set()
                    try: self.rfile.read(1)
                    except OSError: pass
                    owner.block_released.set()
                    return
                if owner.blocking:
                    owner.block_started.set()
                    try: self.rfile.read(1)
                    except OSError: pass
                    owner.block_released.set()
                    return
                if payload.get("stream"):
                    events = [
                        {"type": "response.output_item.added", "item": {"id": "fc1", "type": "function_call", "name": "mcp__dogwalker__project_map", "arguments": "{}"}},
                        {"type": "response.function_call_arguments.done", "name": "mcp__dogwalker__project_map", "arguments": "{}"},
                        {"type": "response.output_text.delta", "delta": "verbatim text Δ"},
                        {"type": "response.completed", "response": {"output": [{"type": "function_call", "name": "mcp__dogwalker__project_map", "call_id": "fc1"}, {"type": "message", "content": [{"text": "done"}]}]}},
                    ]
                    body = b"".join(b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n"
                    self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                else:
                    self._json(200, {"output": [{"type": "function_call", "name": "mcp__dogwalker__project_map", "call_id": "fc1"}, {"type": "message", "content": [{"text": "unchanged"}]}]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(1)


def call(endpoint, path, payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    base = endpoint.removesuffix("/v1") if path in {"/props", "/health"} or path.startswith("/v1/") else endpoint
    request = Request(base + path, data=data, headers=headers or {}, method="GET" if payload is None else "POST")
    with urlopen(request, timeout=3) as response:
        return response.status, response.headers, response.read()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeResponses()
        self.bridge = ResponsesBridge(self.fake.endpoint)

    def tearDown(self):
        self.bridge.close()
        self.fake.close()

    def namespace(self):
        return {"type": "namespace", "name": "mcp__dogwalker", "description": "project tools", "tools": [
            {"type": "function", "name": "project_map", "description": "map it", "parameters": {"type": "object", "properties": {}}, "strict": False},
            {"type": "function", "name": "project_search", "description": "search it", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}, "strict": False},
        ]}

    def test_request_flattening_history_and_sensitive_headers(self):
        payload = {"model": "local", "tools": [self.namespace(), {"type": "function", "name": "plain", "description": "standard", "parameters": {"type": "object"}}],
                   "input": [{"type": "function_call", "namespace": "mcp__dogwalker", "name": "project_search", "call_id": "old"},
                             {"type": "function_call_output", "call_id": "old", "output": "ok"}], "stream": False}
        status, headers, raw = call(self.bridge.endpoint, "/v1/responses", payload,
                                    {"Content-Type": "application/json", "Authorization": "Bearer test-secret", "Cookie": "private=session"})
        self.assertEqual(status, 200)
        sent = self.fake.requests[-1]
        forwarded = sent[2]
        actual = sent[3]
        by_name = {x["name"]: x for x in actual["tools"]}
        self.assertEqual(set(by_name), {"mcp__dogwalker__project_map", "mcp__dogwalker__project_search", "plain"})
        self.assertEqual(by_name["mcp__dogwalker__project_map"]["description"], "map it")
        self.assertEqual(by_name["mcp__dogwalker__project_search"]["parameters"]["properties"]["query"]["type"], "string")
        self.assertEqual(by_name["mcp__dogwalker__project_search"]["strict"], False)
        self.assertEqual(actual["input"][0], {"type": "function_call", "name": "mcp__dogwalker__project_search", "call_id": "old"})
        self.assertEqual(actual["input"][1]["output"], "ok")
        self.assertNotIn("authorization", {k.lower() for k in forwarded})
        self.assertNotIn("cookie", {k.lower() for k in forwarded})
        self.assertNotIn("set-cookie", {k.lower() for k in headers})
        restored = json.loads(raw)
        self.assertEqual(restored["output"][0]["namespace"], "mcp__dogwalker")
        self.assertEqual(restored["output"][0]["name"], "project_map")
        self.assertEqual(restored["output"][1]["content"][0]["text"], "unchanged")

    def test_sse_structured_calls_are_restored_and_deltas_preserved(self):
        payload = {"model": "local", "tools": [self.namespace()], "input": "inspect", "stream": True}
        status, headers, raw = call(self.bridge.endpoint, "/v1/responses", payload)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "text/event-stream")
        events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith(b"data: {")]
        added = events[0]["item"]
        self.assertEqual((added["namespace"], added["name"]), ("mcp__dogwalker", "project_map"))
        self.assertEqual((events[1]["namespace"], events[1]["name"]), ("mcp__dogwalker", "project_map"))
        self.assertEqual(events[2]["delta"], "verbatim text Δ")
        completed = events[3]["response"]["output"]
        self.assertEqual((completed[0]["namespace"], completed[0]["name"]), ("mcp__dogwalker", "project_map"))
        self.assertEqual(completed[1]["content"][0]["text"], "done")

    def test_allowed_get_routes_and_denied_routes(self):
        for path in ("/props", "/health", "/v1/models"):
            status, _headers, body = call(self.bridge.endpoint, path)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["path"], path)
        with self.assertRaises(HTTPError) as error:
            call(self.bridge.endpoint, "/v1/chat/completions")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()
        self.fake.redirect = True
        with self.assertRaises(HTTPError) as error:
            call(self.bridge.endpoint, "/props")
        self.assertEqual(error.exception.code, 502)
        error.exception.close()

    def test_rejects_collisions_and_malformed_namespaces(self):
        ns = self.namespace()
        collision = {"model": "local", "tools": [ns, {"type": "function", "name": "mcp__dogwalker__project_map"}], "input": "x"}
        with self.assertRaises(HTTPError) as error:
            call(self.bridge.endpoint, "/v1/responses", collision)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        malformed = {"model": "local", "tools": [{"type": "namespace", "name": "bad name", "tools": []}], "input": "x"}
        with self.assertRaises(HTTPError) as error:
            call(self.bridge.endpoint, "/v1/responses", malformed)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_oversized_body_rejected_without_reading_payload(self):
        connection = http.client.HTTPConnection("127.0.0.1", int(self.bridge.endpoint.rsplit(":", 1)[1].split("/")[0]), timeout=3)
        connection.putrequest("POST", "/v1/responses")
        connection.putheader("Content-Length", str(MAX_REQUEST_BYTES + 1))
        connection.putheader("Content-Type", "application/json")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        connection.close()
        self.assertFalse(any(row[0] == "POST" for row in self.fake.requests))

    def test_close_cancels_blocked_upstream_and_is_idempotent(self):
        self.fake.blocking = True
        finished = threading.Event()
        def send():
            try: call(self.bridge.endpoint, "/v1/responses", {"model": "local", "tools": [self.namespace()], "input": "x"})
            except Exception: pass
            finally: finished.set()
        client = threading.Thread(target=send, daemon=True)
        client.start()
        self.assertTrue(self.fake.block_started.wait(2))
        self.bridge.close()
        self.bridge.close()
        self.assertTrue(finished.wait(2))
        self.assertTrue(self.fake.block_released.wait(2))

        # Also cover a server that closes after its headers, which makes
        # HTTPConnection.getresponse() clear conn.sock before body streaming.
        self.fake.blocking = False
        self.fake.block_after_headers = True
        self.fake.block_started.clear()
        self.fake.block_released.clear()
        self.bridge = ResponsesBridge(self.fake.endpoint)
        finished.clear()
        client = threading.Thread(target=send, daemon=True)
        client.start()
        self.assertTrue(self.fake.block_started.wait(2))
        self.bridge.close()
        self.assertTrue(finished.wait(2))
        self.assertTrue(self.fake.block_released.wait(2))


if __name__ == "__main__":
    unittest.main()
