import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest

import dog_walker.runtime as runtime
from dog_walker.runtime import RuntimeCheckError, prepare_model, probe_file_cache, verify_runtime


class LocalRuntime:
    def __init__(self, model_path, *, props_path=None, health=None, redirect=None, body=None):
        self.model_path = str(props_path or model_path)
        self.health = health if health is not None else {"status": "ok", "slots_idle": 1, "slots_processing": 0}
        self.redirect = redirect
        self.body = body
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                if owner.redirect:
                    self.send_response(302)
                    self.send_header("Location", owner.redirect)
                    self.end_headers()
                    return
                if owner.body is not None:
                    payload = owner.body
                elif self.path == "/props":
                    payload = json.dumps({"model_path": owner.model_path}).encode()
                elif self.path == "/health":
                    payload = json.dumps(owner.health).encode()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "model.gguf"
    path.write_bytes(b"model weights" * 64)
    return path


@pytest.fixture
def runtime_server(model):
    server = LocalRuntime(model)
    yield server
    server.close()


def test_verify_runtime_matches_identity_and_health_without_reading_model(model, runtime_server, monkeypatch):
    monkeypatch.setattr(runtime.os, "pread", lambda *_args: pytest.fail("readiness must not prefault GGUF"))
    monkeypatch.setattr(runtime, "find_runtime_pid", lambda *_args: (None, "test process not found"))
    result = verify_runtime(model, runtime_server.endpoint)
    assert result["ready"] is True
    assert result["fully_loaded"] is True
    assert result["model_path_matches"] is True
    assert result["health_status"] == "ok"
    assert result["model_bytes"] == model.stat().st_size
    assert result["process_vm_swap_bytes"] is None
    assert runtime_server.requests == ["/props", "/health"]


def test_swap_is_reported_as_warning_without_blocking_current_ready_server(model, runtime_server, monkeypatch):
    monkeypatch.setattr(runtime, "find_runtime_pid", lambda *_args: (42, "matched model path and endpoint port"))
    monkeypatch.setattr(runtime, "_process_status", lambda _pid: {
        "process_pid": 42, "process_vm_rss_bytes": 1000,
        "process_vm_swap_bytes": 512, "process_vm_locked_bytes": 0,
    })
    result = verify_runtime(model, runtime_server.endpoint)
    assert result["ready"] is True
    assert result["process_vm_swap_bytes"] == 512
    assert result["process_swap_clear"] is False
    assert "may reduce response speed" in result["process_vm_swap_warning"]
    assert result["rss_to_model_file_ratio"] == 1000 / model.stat().st_size


def test_wrong_model_identity_fails_closed(model, tmp_path):
    other = tmp_path / "other.gguf"
    other.write_bytes(b"other model")
    server = LocalRuntime(model, props_path=other)
    try:
        result = verify_runtime(model, server.endpoint)
        assert result["ready"] is False
        assert result["fully_loaded"] is False
        assert "different" in result["reason"]
        assert server.requests == ["/props"]
    finally:
        server.close()


def test_health_loading_or_busy_does_not_start_work(model):
    server = LocalRuntime(model, health={"status": "loading"})
    try:
        result = verify_runtime(model, server.endpoint)
        assert result["ready"] is False
        assert result["fully_loaded"] is False
        assert result["reason"] == "Local model server is still loading or unhealthy"
    finally:
        server.close()
    busy = LocalRuntime(model, health={"status": "ok", "slots_idle": 0, "slots_processing": 1})
    try:
        result = verify_runtime(model, busy.endpoint)
        assert result["ready"] is False
        assert result["fully_loaded"] is True
        assert "no idle slot" in result["reason"]
    finally:
        busy.close()
    metrics_missing = LocalRuntime(model, health={"status": "ok"})
    try:
        assert verify_runtime(model, metrics_missing.endpoint)["ready"] is True
    finally:
        metrics_missing.close()
    no_slots = LocalRuntime(model, health={"status": "ok", "slots_idle": 0, "slots_processing": 0})
    try:
        result = verify_runtime(model, no_slots.endpoint)
        assert result["ready"] is False
        assert "no idle slot" in result["reason"]
    finally:
        no_slots.close()


def test_cancellation_before_check_returns_not_ready(model, runtime_server):
    cancelled = threading.Event()
    cancelled.set()
    result = verify_runtime(model, runtime_server.endpoint, cancel=cancelled)
    assert result["ready"] is False
    assert result["reason"] == "cancelled before runtime check"
    assert runtime_server.requests == []


def test_optional_emit_callback_can_be_none(model, runtime_server, monkeypatch):
    monkeypatch.setattr(runtime, "find_runtime_pid", lambda *_args: (None, "test process not found"))
    assert verify_runtime(model, runtime_server.endpoint, emit=None)["ready"] is True


def test_nonlocal_endpoints_and_bad_model_paths_are_rejected(model):
    for endpoint in ("https://localhost/v1", "http://example.com/v1", "http://127.0.0.1/v1?x=1"):
        with pytest.raises(RuntimeCheckError):
            verify_runtime(model, endpoint)
    with pytest.raises(RuntimeCheckError, match="regular file"):
        verify_runtime(model.parent, "http://127.0.0.1:18081/v1")


def test_symlink_model_path_resolves_for_read_only_identity_check(model, tmp_path, monkeypatch):
    alias = tmp_path / "active-model.gguf"
    alias.symlink_to(model)
    server = LocalRuntime(model)
    monkeypatch.setattr(runtime, "find_runtime_pid", lambda *_args: (None, "test process not found"))
    try:
        result = verify_runtime(alias, server.endpoint)
        assert result["ready"] is True
        assert result["model_path"] == str(model.resolve())
    finally:
        server.close()


def test_redirect_is_not_followed_and_oversize_json_is_rejected(model):
    redirect = LocalRuntime(model, redirect="http://example.com/collect")
    try:
        result = verify_runtime(model, redirect.endpoint)
        assert result["ready"] is False
        assert redirect.requests == ["/props"]
    finally:
        redirect.close()
    huge = LocalRuntime(model, body=b" " * (runtime.MAX_JSON_BYTES + 1))
    try:
        result = verify_runtime(model, huge.endpoint)
        assert result["ready"] is False
        assert "256 KB" in result["reason"]
    finally:
        huge.close()


def test_optional_mincore_probe_is_read_only(model, monkeypatch):
    monkeypatch.setattr(runtime, "_linux_mincore", lambda: None)
    result = probe_file_cache(model)
    assert result["supported"] is False
    assert result["resident_bytes"] is None
    assert "mincore" in result["reason"]


def test_linux_mincore_reports_backing_file_cache_only(model):
    if not __import__("sys").platform.startswith("linux"):
        pytest.skip("Linux mincore is not available")
    before = model.read_bytes()
    result = probe_file_cache(model)
    after = model.read_bytes()
    assert result["supported"] is True
    assert 0 <= result["resident_bytes"] <= result["bytes"]
    assert 0 <= result["residency_percent"] <= 100
    assert after == before


def test_process_discovery_requires_both_model_path_and_port(model, tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    process = proc / "12345"
    process.mkdir(parents=True)
    (process / "cmdline").write_bytes(
        b"/usr/bin/llama-server\0-m\0" + str(model.resolve()).encode() + b"\0--port\0" + b"18081\0"
    )
    real_path_type = type(Path())

    class FakeProcPath(real_path_type):
        def iterdir(self):
            if str(self) == "/proc":
                return proc.iterdir()
            return super().iterdir()

    monkeypatch.setattr(runtime, "Path", FakeProcPath)
    assert runtime.find_runtime_pid(model, "http://127.0.0.1:18081/v1") == (
        12345, "matched model path and endpoint port"
    )


def test_prepare_model_is_compatibility_wrapper_and_requires_endpoint(model, runtime_server, monkeypatch):
    monkeypatch.setattr(runtime, "find_runtime_pid", lambda *_args: (None, "test process not found"))
    with pytest.raises(RuntimeCheckError, match="explicit"):
        prepare_model(model)
    assert prepare_model(model, endpoint=runtime_server.endpoint)["ready"] is True


def test_transport_http_exception_returns_not_ready(model, runtime_server, monkeypatch):
    from http.client import HTTPException

    monkeypatch.setattr(runtime, "_fetch_json", lambda *_args: (_ for _ in ()).throw(HTTPException("bad body")))
    result = verify_runtime(model, runtime_server.endpoint)
    assert result["ready"] is False
    assert "props check failed" in result["reason"]
