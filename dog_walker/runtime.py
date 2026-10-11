"""Verify a local model server is ready, with honest memory diagnostics.

The server's /props identity and /health status are the readiness authority.
Optional Linux ``mincore`` data describes backing-file page-cache residency
only; it does not describe tensors copied or repacked into a server process.
This module never preloads files, locks memory, changes swap, or starts/stops a
runtime.
"""
from __future__ import annotations

import ctypes
from http.client import HTTPException
import mmap
import os
from pathlib import Path
import stat
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_TIMEOUT_SECONDS = 5.0
MAX_JSON_BYTES = 256 * 1024


class RuntimeCheckError(RuntimeError):
    """Invalid local runtime endpoint or model path."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _cancelled(cancel):
    if cancel is None:
        return False
    if callable(cancel):
        return bool(cancel())
    method = getattr(cancel, "is_set", None)
    if callable(method):
        return bool(method())
    raise RuntimeCheckError("cancel must be an event or zero-argument callable")


def validate_endpoint(endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 300:
        raise RuntimeCheckError("Runtime endpoint must be a local HTTP /v1 URL")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise RuntimeCheckError("Runtime endpoint must be a local HTTP /v1 URL") from None
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/v1" or (port is not None and not 1 <= port <= 65535)):
        raise RuntimeCheckError("Runtime endpoint must be a local HTTP /v1 URL")
    return endpoint.rstrip("/")


def _model_file(model_path):
    path = Path(model_path).expanduser()
    try:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise RuntimeCheckError(f"Model file is unavailable: {exc.strerror or exc}") from None
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise RuntimeCheckError("Model path must name a nonempty regular file")
    return resolved, info


def _fetch_json(url, timeout):
    request = Request(url, headers={"Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_JSON_BYTES + 1)
    if len(body) > MAX_JSON_BYTES:
        raise ValueError("response exceeded 256 KB")
    import json
    return json.loads(body)


def _read_meminfo(path="/proc/meminfo"):
    values = {}
    for line in Path(path).read_text().splitlines():
        key, sep, rest = line.partition(":")
        fields = rest.split()
        if not sep or not fields or not fields[0].isdigit():
            continue
        value = int(fields[0])
        if len(fields) > 1 and fields[1] == "kB":
            value *= 1024
        values[key] = value
    return values


def _process_status(pid):
    try:
        values = {}
        for line in Path(f"/proc/{int(pid)}/status").read_text().splitlines():
            key, sep, rest = line.partition(":")
            if sep and key in {"VmRSS", "VmSwap", "VmLck"}:
                fields = rest.split()
                if fields and fields[0].isdigit():
                    values[key] = int(fields[0]) * (1024 if len(fields) > 1 and fields[1] == "kB" else 1)
        return {"process_pid": int(pid), "process_vm_rss_bytes": values.get("VmRSS"),
                "process_vm_swap_bytes": values.get("VmSwap"), "process_vm_locked_bytes": values.get("VmLck")}
    except (OSError, ValueError, TypeError):
        return {"process_pid": int(pid) if str(pid).isdigit() else None,
                "process_vm_rss_bytes": None, "process_vm_swap_bytes": None,
                "process_vm_locked_bytes": None}


def _port(endpoint):
    return urlsplit(endpoint).port or 80


def find_runtime_pid(model_path, endpoint):
    """Find a process whose argv names this model and endpoint port exactly."""
    if not sys.platform.startswith("linux"):
        return None, "Linux process inspection is unavailable"
    supplied_path = str(Path(model_path).expanduser())
    resolved = str(Path(model_path).expanduser().resolve(strict=True))
    wanted_paths = {resolved.encode(), supplied_path.encode()}
    wanted_port = str(_port(validate_endpoint(endpoint))).encode()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return None, "process table is unavailable"
    matches = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            argv = [arg for arg in argv if arg]
            if not wanted_paths.intersection(argv):
                continue
            has_port = any((arg == b"--port" and index + 1 < len(argv) and argv[index + 1] == wanted_port)
                           or arg == b"--port=" + wanted_port for index, arg in enumerate(argv))
            if has_port:
                matches.append(int(entry.name))
        except (OSError, PermissionError):
            continue
    if len(matches) == 1:
        return matches[0], "matched model path and endpoint port"
    if len(matches) > 1:
        return None, f"ambiguous process match ({len(matches)} processes)"
    return None, "no process matched model path and endpoint port"


def _linux_mincore():
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        fn = libc.mincore
        fn.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)
        fn.restype = ctypes.c_int
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (fn, page_size) if page_size > 0 else None
    except (AttributeError, OSError, ValueError):
        return None


def probe_file_cache(file_path):
    """Read-only mincore sample of one file's page-cache residency."""
    path, info = _model_file(file_path)
    api = _linux_mincore()
    if api is None:
        return {"supported": False, "path": str(path), "bytes": info.st_size,
                "resident_bytes": None, "residency_percent": None,
                "reason": "Linux mincore residency measurement is unavailable"}
    mincore, page_size = api
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        pages = (info.st_size + page_size - 1) // page_size
        vector = ctypes.create_string_buffer(pages)
        with mmap.mmap(fd, info.st_size, access=mmap.ACCESS_COPY) as mapped:
            address = ctypes.addressof(ctypes.c_char.from_buffer(mapped))
            if mincore(address, info.st_size, vector) != 0:
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error))
        bits = memoryview(vector).cast("B")
        resident_pages = sum(1 for item in bits if item & 1)
        del bits
    except (OSError, ValueError, BufferError) as exc:
        return {"supported": False, "path": str(path), "bytes": info.st_size,
                "resident_bytes": None, "residency_percent": None,
                "reason": f"Could not measure backing-file page cache: {exc}"}
    finally:
        os.close(fd)
    resident = min(info.st_size, resident_pages * page_size)
    return {"supported": True, "path": str(path), "bytes": info.st_size,
            "resident_bytes": resident,
            "residency_percent": round(100 * resident / info.st_size, 5)}


def verify_runtime(model_path, endpoint, emit=lambda _message: None, cancel=None, *,
                   timeout=DEFAULT_TIMEOUT_SECONDS, include_file_cache=False,
                   projector_path=None):
    """Confirm loopback server identity and readiness; report process memory.

    A ``ready`` result requires /props to identify ``model_path`` and /health
    to report status ``ok`` with an idle slot. Existing swap use is reported as
    a warning but does not block an already-running service. For future starts,
    the caller may enforce a zero-swap launch policy separately.
    """
    started = time.monotonic()
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0.1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise RuntimeCheckError("Runtime check timeout must be 0.1–5 seconds")
    endpoint = validate_endpoint(endpoint)
    expected, info = _model_file(model_path)
    if _cancelled(cancel):
        return {"supported": True, "ready": False, "fully_loaded": False,
                "reason": "cancelled before runtime check", "model_path_matches": False,
                "duration_seconds": round(time.monotonic() - started, 3)}
    try:
        _emit(emit, "Checking local model identity and readiness…")
        props = _fetch_json(endpoint.removesuffix("/v1") + "/props", timeout)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, HTTPException) as exc:
        return {"supported": True, "ready": False, "fully_loaded": False,
                "reason": f"Local model /props check failed: {getattr(exc, 'reason', exc)}",
                "model_path_matches": False,
                "duration_seconds": round(time.monotonic() - started, 3)}
    if not isinstance(props, dict) or not isinstance(props.get("model_path"), str):
        return {"supported": True, "ready": False, "fully_loaded": False,
                "reason": "Local /props did not identify a model path", "model_path_matches": False,
                "duration_seconds": round(time.monotonic() - started, 3)}
    try:
        actual = Path(props["model_path"]).resolve(strict=True)
    except OSError:
        actual = None
    matches = actual == expected
    if not matches:
        return {"supported": True, "ready": False, "fully_loaded": False,
                "reason": "Local endpoint is serving a different or unidentified model",
                "model_path_matches": False, "expected_model_path": str(expected),
                "actual_model_path": props["model_path"],
                "duration_seconds": round(time.monotonic() - started, 3)}
    if _cancelled(cancel):
        return {"supported": True, "ready": False, "fully_loaded": False,
                "reason": "cancelled before health check", "model_path_matches": True,
                "duration_seconds": round(time.monotonic() - started, 3)}
    try:
        health = _fetch_json(endpoint.removesuffix("/v1") + "/health", timeout)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, HTTPException) as exc:
        return {"supported": True, "ready": False, "fully_loaded": False,
                "reason": f"Local model /health check failed: {getattr(exc, 'reason', exc)}",
                "model_path_matches": True,
                "duration_seconds": round(time.monotonic() - started, 3)}
    if not isinstance(health, dict) or health.get("status") != "ok":
        return {"supported": True, "ready": False, "fully_loaded": False,
                "reason": "Local model server is still loading or unhealthy",
                "model_path_matches": True, "health_status": health.get("status") if isinstance(health, dict) else None,
                "duration_seconds": round(time.monotonic() - started, 3)}
    processing = health.get("slots_processing")
    idle = health.get("slots_idle")
    if type(idle) is int and idle <= 0:
        return {"supported": True, "ready": False, "fully_loaded": True,
                "reason": "Local model is loaded but has no idle slot", "model_path_matches": True,
                "health_status": "ok", "slots_idle": idle, "slots_processing": processing,
                "duration_seconds": round(time.monotonic() - started, 3)}

    pid, process_match = find_runtime_pid(model_path, endpoint)
    process = _process_status(pid) if pid is not None else {
        "process_pid": None, "process_vm_rss_bytes": None,
        "process_vm_swap_bytes": None, "process_vm_locked_bytes": None,
    }
    try:
        system_memory = _read_meminfo()
    except OSError:
        system_memory = {}
    system_swap_used = None
    if "SwapTotal" in system_memory and "SwapFree" in system_memory:
        system_swap_used = max(0, system_memory["SwapTotal"] - system_memory["SwapFree"])
    vm_swap = process["process_vm_swap_bytes"]
    swap_warning = None
    if vm_swap:
        swap_warning = (f"Model server reports {vm_swap} bytes of VmSwap; runtime is ready, "
                        "but swapped pages may reduce response speed")
    result = {
        "supported": True,
        "ready": True,
        "fully_loaded": True,
        "reason": "model identity matches and server health is ok",
        "model_path_matches": True,
        "model_path": str(expected),
        "model_bytes": info.st_size,
        "health_status": "ok",
        "slots_idle": idle,
        "slots_processing": processing,
        "process_match": process_match,
        "process_swap_clear": (vm_swap == 0 if vm_swap is not None else None),
        "process_vm_swap_warning": swap_warning,
        "system_mem_available_bytes": system_memory.get("MemAvailable"),
        "system_swap_used_bytes": system_swap_used,
        "rss_to_model_file_ratio": (process["process_vm_rss_bytes"] / info.st_size
                                     if process["process_vm_rss_bytes"] is not None else None),
        "duration_seconds": round(time.monotonic() - started, 3),
        **process,
    }
    if include_file_cache:
        cache = probe_file_cache(expected)
        result["model_file_cache"] = cache
        if projector_path is None:
            candidates = [p for p in expected.parent.iterdir()
                          if p.name.startswith("mmproj-") and p.suffix.lower() == ".gguf"
                          and not p.is_symlink() and p.is_file()]
            if len(candidates) == 1:
                projector_path = candidates[0]
        if projector_path is not None:
            result["projector_file_cache"] = probe_file_cache(projector_path)
    _emit(emit, "Local model server reports ready" + (f"; {swap_warning}" if swap_warning else "."))
    return result


def _emit(emit, message):
    if emit is not None:
        emit(message)


def prepare_model(model_path, emit=lambda _message: None, cancel=None, *, endpoint=None,
                  timeout=DEFAULT_TIMEOUT_SECONDS, include_file_cache=False,
                  projector_path=None):
    """Compatibility name; verifies an already-started runtime and never warms files."""
    if endpoint is None:
        raise RuntimeCheckError("An explicit local runtime endpoint is required")
    return verify_runtime(model_path, endpoint, emit, cancel, timeout=timeout,
                          include_file_cache=include_file_cache,
                          projector_path=projector_path)
