"""Per-turn loopback bridge for Codex namespace MCP tools and local Responses APIs.

Some local Responses runtimes accept only function tools. This bridge converts
Codex's MCP namespace tool envelope to ordinary function tools for one worker
turn, then restores namespace/name fields on returned function calls. It keeps
no request log and forwards only the documented local runtime endpoints.
"""
from __future__ import annotations

from http.client import HTTPConnection, HTTPException, HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import socket
import threading
from urllib.parse import urlsplit

MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_SSE_LINE_BYTES = 1024 * 1024
UPSTREAM_TIMEOUT_SECONDS = 15 * 60
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")
_ALLOWED_GET = {"/props", "/health", "/v1/models"}


class TransportError(ValueError):
    """The bridge received an invalid endpoint or tool envelope."""


def _parse_endpoint(endpoint: str) -> tuple[str, int, str]:
    if not isinstance(endpoint, str) or len(endpoint) > 300:
        raise TransportError("Responses endpoint must be a local HTTP /v1 URL")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port or 80
    except ValueError:
        raise TransportError("Responses endpoint must be a local HTTP /v1 URL") from None
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/v1" or not 1 <= port <= 65535):
        raise TransportError("Responses endpoint must be a local HTTP /v1 URL")
    # Avoid resolving a hostname to a non-loopback address at connection time.
    host = "::1" if parsed.hostname == "::1" else "127.0.0.1"
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return host, port, authority


def _flatten_request(payload: dict, mapping: dict[str, tuple[str, str]]) -> dict:
    tools = payload.get("tools")
    result = []
    current: dict[str, tuple[str, str]] = {}
    occupied: set[str] = set()
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict):
            raise TransportError("Tool entries must be objects")
        if tool.get("type") != "namespace":
            name = tool.get("name")
            if tool.get("type") == "function" and isinstance(name, str):
                if name in occupied:
                    raise TransportError("Function tool name collision")
                occupied.add(name)
            result.append(tool)
            continue

        namespace = tool.get("name")
        nested = tool.get("tools")
        if not isinstance(namespace, str) or not _NAME.fullmatch(namespace) or not isinstance(nested, list):
            raise TransportError("Malformed namespace tool definition")
        for subtool in nested:
            if not isinstance(subtool, dict) or subtool.get("type") != "function":
                raise TransportError("Namespace entries must be function tools")
            subname = subtool.get("name")
            if not isinstance(subname, str) or not _NAME.fullmatch(subname):
                raise TransportError("Malformed namespaced function name")
            flat = namespace + "__" + subname
            if flat in occupied or flat in current:
                raise TransportError("Namespaced function tool name collision")
            occupied.add(flat)
            current[flat] = (namespace, subname)
            flattened = {key: value for key, value in subtool.items() if key != "type"}
            flattened["type"] = "function"
            flattened["name"] = flat
            result.append(flattened)

    # Codex repeats tool definitions on each request. Retain known names too,
    # because prior function_call items may appear in its input history.
    mapping.update(current)
    converted = dict(payload)
    if isinstance(tools, list):
        converted["tools"] = result
    input_items = converted.get("input")
    if isinstance(input_items, list):
        rewritten = []
        for item in input_items:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                rewritten.append(item)
                continue
            call = dict(item)
            namespace = call.pop("namespace", None)
            name = call.get("name")
            if namespace is not None:
                if not isinstance(namespace, str) or not isinstance(name, str):
                    raise TransportError("Malformed namespaced function call history")
                flat = namespace + "__" + name
                known = mapping.get(flat)
                if known is None or known != (namespace, name):
                    raise TransportError("Function call history references an unknown namespace tool")
                call["name"] = flat
            elif isinstance(name, str) and name in mapping:
                # Already flattened history is safe to preserve.
                pass
            rewritten.append(call)
        converted["input"] = rewritten
    return converted


def _restore_call(item: dict, mapping: dict[str, tuple[str, str]]) -> dict:
    if item.get("type") != "function_call":
        return item
    name = item.get("name")
    if not isinstance(name, str) or name not in mapping:
        return item
    namespace, plain_name = mapping[name]
    restored = dict(item)
    restored.pop("name", None)
    restored["namespace"] = namespace
    restored["name"] = plain_name
    return restored


def _restore_event(event: dict, mapping: dict[str, tuple[str, str]]) -> dict:
    """Restore a runtime response event without changing textual delta values."""
    result = dict(event)
    typ = result.get("type")
    if typ in {"response.output_item.added", "response.output_item.done"}:
        item = result.get("item")
        if isinstance(item, dict):
            result["item"] = _restore_call(item, mapping)
    elif typ == "response.function_call_arguments.done":
        name = result.get("name")
        if isinstance(name, str) and name in mapping:
            namespace, plain_name = mapping[name]
            result["namespace"] = namespace
            result["name"] = plain_name
    elif typ == "response.completed":
        response = result.get("response")
        if isinstance(response, dict):
            response = dict(response)
            output = response.get("output")
            if isinstance(output, list):
                response["output"] = [_restore_call(item, mapping) if isinstance(item, dict) else item
                                       for item in output]
            result["response"] = response
    return result


class _BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, address, handler, bridge):
        self.bridge = bridge
        super().__init__(address, handler)


class ResponsesBridge:
    """A short-lived loopback proxy for one worker turn.

    Construction starts a daemon listener on an ephemeral loopback port.
    ``endpoint`` is the local URL Codex should use. Call ``close`` in the
    worker's ``finally`` path; it is safe to call more than once.
    """

    def __init__(self, upstream_endpoint: str):
        self.host, self.port, self.authority = _parse_endpoint(upstream_endpoint)
        self.mapping: dict[str, tuple[str, str]] = {}
        self._mapping_lock = threading.Lock()
        self._closing = threading.Event()
        self._connections: dict[HTTPConnection, socket.socket | None] = {}
        self._connections_lock = threading.Lock()
        self._clients: set[socket.socket] = set()
        self._clients_lock = threading.Lock()
        self._closed = False
        self._close_lock = threading.Lock()
        self._server = _BridgeHTTPServer(("127.0.0.1", 0), self._handler_type(), self)
        self._thread = threading.Thread(target=self._server.serve_forever, name="dog-walker-responses-bridge", daemon=True)
        self._thread.start()
        self.endpoint = f"http://127.0.0.1:{self._server.server_port}/v1"

    @staticmethod
    def _handler_type():
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.server.bridge._register_client(self.connection)

            def finish(self):
                try:
                    super().finish()
                finally:
                    self.server.bridge._unregister_client(self.connection)

            def log_message(self, _format, *_args):
                return

            def _reply(self, status: int, body: bytes, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                self.close_connection = True

            def _bad(self, status: int, message: str):
                self._reply(status, json.dumps({"error": {"message": message}}).encode())

            def do_GET(self):
                bridge = self.server.bridge
                if self.path not in _ALLOWED_GET | {"/models"}:
                    return self._bad(404, "Route is not available through the local bridge")
                upstream_path = "/v1/models" if self.path in {"/v1/models", "/models"} else self.path
                bridge._proxy(self, "GET", upstream_path, None, None)

            def do_POST(self):
                bridge = self.server.bridge
                if self.path not in {"/v1/responses", "/responses"}:
                    return self._bad(404, "Route is not available through the local bridge")
                if self.headers.get("Transfer-Encoding"):
                    return self._bad(400, "Chunked client request bodies are not accepted")
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    return self._bad(400, "Invalid Content-Length")
                if length < 0:
                    return self._bad(411, "Content-Length is required")
                if length > MAX_REQUEST_BYTES:
                    return self._bad(413, "Request body exceeds the 16 MiB bridge limit")
                body = self.rfile.read(length)
                if len(body) != length:
                    return self._bad(400, "Incomplete request body")
                try:
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise TransportError("Responses request must be a JSON object")
                    with bridge._mapping_lock:
                        rewritten = _flatten_request(payload, bridge.mapping)
                    body = json.dumps(rewritten, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    return self._bad(400, str(exc)[:500] or "Invalid Responses request")
                bridge._proxy(self, "POST", "/v1/responses", body,
                              "text/event-stream" if rewritten.get("stream") else "application/json")

            def do_PUT(self): self._bad(405, "Method is not available through the local bridge")
            def do_PATCH(self): self._bad(405, "Method is not available through the local bridge")
            def do_DELETE(self): self._bad(405, "Method is not available through the local bridge")
            def do_OPTIONS(self): self._bad(405, "Method is not available through the local bridge")

        return Handler

    def _register(self, conn):
        with self._connections_lock:
            if self._closing.is_set():
                conn.close()
                return False
            self._connections[conn] = None
            return True

    def _set_upstream_socket(self, conn):
        with self._connections_lock:
            if conn not in self._connections or self._closing.is_set():
                return False
            self._connections[conn] = conn.sock
            return conn.sock is not None

    def _unregister(self, conn):
        with self._connections_lock:
            self._connections.pop(conn, None)
        conn.close()

    def _register_client(self, client_socket):
        with self._clients_lock:
            if self._closing.is_set():
                try: client_socket.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                try: client_socket.close()
                except OSError: pass
                return
            self._clients.add(client_socket)

    def _unregister_client(self, client_socket):
        with self._clients_lock:
            self._clients.discard(client_socket)

    def _proxy(self, client, method: str, path: str, body: bytes | None, accept: str | None):
        if self._closing.is_set():
            return
        conn = HTTPConnection(self.host, self.port, timeout=UPSTREAM_TIMEOUT_SECONDS)
        response = None
        if not self._register(conn):
            return
        try:
            headers = {"Host": self.authority, "Accept": accept or "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(body))
            conn.request(method, path, body=body, headers=headers)
            if not self._set_upstream_socket(conn):
                return
            response = conn.getresponse()
            if 300 <= response.status < 400:
                client._reply(502, b'{"error":{"message":"Upstream redirects are disabled"}}')
                return
            content_type = response.getheader("Content-Type", "application/json").split(";", 1)[0].strip().lower()
            if method == "POST" and content_type == "text/event-stream":
                client.send_response(response.status)
                client.send_header("Content-Type", "text/event-stream; charset=utf-8")
                cache_control = response.getheader("Cache-Control")
                if cache_control:
                    client.send_header("Cache-Control", cache_control[:200])
                client.send_header("Connection", "close")
                client.send_header("Transfer-Encoding", "chunked")
                client.end_headers()
                self._stream_sse(response, client)
                return
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                client._reply(502, b'{"error":{"message":"Upstream response exceeded bridge limit"}}')
                return
            if method == "POST" and 200 <= response.status < 300:
                try:
                    payload = json.loads(data)
                    if isinstance(payload, dict):
                        with self._mapping_lock:
                            data = json.dumps(_restore_json_response(payload, self.mapping),
                                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    pass
            client._reply(response.status, data, response.getheader("Content-Type", "application/json"))
        except (OSError, HTTPException, socket.timeout) as exc:
            if not self._closing.is_set():
                try:
                    client._reply(502, json.dumps({"error": {"message": f"Local runtime transport failed: {type(exc).__name__}"}}).encode())
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        finally:
            if response is not None:
                try: response.close()
                except OSError: pass
            self._unregister(conn)

    def _stream_sse(self, response: HTTPResponse, client):
        """Transform one SSE line at a time; no whole-response buffering."""
        try:
            while not self._closing.is_set():
                line = response.readline(MAX_SSE_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_SSE_LINE_BYTES:
                    raise TransportError("SSE line exceeds the 1 MiB bridge limit")
                if line.startswith(b"data:"):
                    raw = line[5:].strip()
                    if raw and raw != b"[DONE]":
                        try:
                            event = json.loads(raw)
                            if isinstance(event, dict):
                                with self._mapping_lock:
                                    event = _restore_event(event, self.mapping)
                                line = b"data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                        except (ValueError, UnicodeDecodeError):
                            pass
                # HTTP/1.1 chunked framing keeps streaming and avoids buffering.
                client.wfile.write(f"{len(line):X}\r\n".encode("ascii") + line + b"\r\n")
                client.wfile.flush()
            client.wfile.write(b"0\r\n\r\n")
            client.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError, HTTPException):
            return
        except TransportError:
            return

    def close(self):
        """Close the listener and cancel active upstream sockets, idempotently."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._closing.set()
            self._server.shutdown()
            self._server.server_close()
            with self._connections_lock:
                active = tuple(self._connections.items())
            for conn, tracked_socket in active:
                try:
                    active_socket = tracked_socket or conn.sock
                    if active_socket is not None:
                        active_socket.shutdown(socket.SHUT_RDWR)
                    conn.close()
                except OSError:
                    try: conn.close()
                    except OSError: pass
            with self._clients_lock:
                clients = tuple(self._clients)
            for client_socket in clients:
                try: client_socket.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                try: client_socket.close()
                except OSError: pass
            self._thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _restore_json_response(payload: dict, mapping: dict[str, tuple[str, str]]) -> dict:
    result = dict(payload)
    output = result.get("output")
    if isinstance(output, list):
        result["output"] = [_restore_call(item, mapping) if isinstance(item, dict) else item for item in output]
    return result
