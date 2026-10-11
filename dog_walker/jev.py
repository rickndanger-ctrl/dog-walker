"""Optional Typesafe Jev decision adapter with private, explicit opt-in config."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import tempfile
import urllib.error
import urllib.request

MODEL_ID = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
CONFIG_PATH = Path.home() / ".config/dog-walker/jev.json"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_CONFIG_BYTES = 8192
MAX_TIMEOUT = 5.0
INPUT_COST_PER_MILLION = 0.042


class JevError(RuntimeError):
    """Safe-to-display provider/configuration error; never contains response bodies."""


def _valid_key(value: object) -> bool:
    return (isinstance(value, str) and len(value) <= 4096 and
            all(33 <= ord(character) <= 126 for character in value))


def load_config(path: str | Path | None = None) -> dict:
    """Read the owner-only config without following a symlink or accepting loose modes."""
    config = Path(path) if path is not None else CONFIG_PATH
    try:
        info = config.lstat()
    except FileNotFoundError as exc:
        raise JevError("Jev is not configured. Run scripts/configure-jev.py.") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise JevError("Jev config must be a regular, non-symlink file")
    if info.st_uid != os.getuid():
        raise JevError("Jev config must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise JevError("Jev config permissions must be exactly 600")
    if info.st_size > MAX_CONFIG_BYTES:
        raise JevError("Jev config is too large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(config, flags)
        with os.fdopen(descriptor, "rb") as handle:
            verified = os.fstat(handle.fileno())
            if not stat.S_ISREG(verified.st_mode) or verified.st_uid != os.getuid() or stat.S_IMODE(verified.st_mode) != 0o600:
                raise JevError("Jev config changed or has unsafe ownership or permissions")
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        raise JevError("Jev config could not be read safely") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise JevError("Jev config is too large")
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise JevError("Jev config is not valid JSON") from exc
    if (not isinstance(value, dict) or set(value) != {"api_key", "enabled"} or
            not _valid_key(value["api_key"]) or not isinstance(value["enabled"], bool)):
        raise JevError("Jev config must contain an API key field and an enabled boolean")
    return value


def is_enabled(path: str | Path | None = None) -> bool:
    """Return whether explicit opt-in is configured; a key by itself is inactive."""
    config_path = Path(path) if path is not None else CONFIG_PATH
    try:
        config = load_config(config_path)
        return config["enabled"] and bool(os.environ.get("TYPESAFE_API_KEY", "").strip() or config["api_key"].strip())
    except JevError:
        if not config_path.exists() and not config_path.is_symlink():
            return False
        raise


def has_key(path: str | Path | None = None) -> bool:
    """Report whether a usable key exists without activating a disabled config."""
    config_path = Path(path) if path is not None else CONFIG_PATH
    env_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    try:
        config = load_config(config_path)
    except JevError:
        if not config_path.exists() and not config_path.is_symlink():
            return bool(env_key and _valid_key(env_key))
        raise
    return bool((env_key and _valid_key(env_key)) or config["api_key"])


def _check_config_directory(directory: Path) -> None:
    if directory.is_symlink():
        raise JevError("Jev config directory must not be a symlink")
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise JevError("Jev config directory must be owned by the current user with private permissions")


def save_config(value: dict, path: str | Path | None = None, *, replace: bool = False) -> Path:
    """Atomically write a 0600 config; replacement must be explicit at the call site."""
    config = Path(path) if path is not None else CONFIG_PATH
    if (not isinstance(value, dict) or set(value) != {"api_key", "enabled"} or
            not _valid_key(value["api_key"]) or not isinstance(value["enabled"], bool)):
        raise JevError("Jev config must contain an API key field and an enabled boolean")
    config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_config_directory(config.parent)
    if config.exists() or config.is_symlink():
        if not replace:
            raise JevError("Jev config already exists; explicit replacement is required")
        # Do not overwrite an unsafe file, even when replacement was requested.
        load_config(config)
    temporary = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".jev-", dir=config.parent)
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, config)
        directory_descriptor = os.open(config.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise JevError("Jev config could not be saved safely") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return config


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _wire_questions(questions: dict) -> dict:
    if not isinstance(questions, dict):
        raise JevError("Jev questions are invalid")
    wire = {}
    for name, question in questions.items():
        if not isinstance(name, str) or not isinstance(question, dict):
            raise JevError("Jev questions are invalid")
        wire[name] = {key: question[key] for key in ("type", "instructions", "criteria") if key in question}
    return wire


class JevJudge:
    """Synchronous HTTPS client; callers should run decide() off the UI event loop."""

    def __init__(self, config_path: str | Path | None = None, *, opener=None,
                 timeout: float = MAX_TIMEOUT, test_only: bool = False):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
            raise ValueError(f"Jev timeout must be between zero and {MAX_TIMEOUT:g} seconds")
        if not isinstance(test_only, bool):
            raise ValueError("Jev test_only must be a boolean")
        config_file = Path(config_path) if config_path is not None else CONFIG_PATH
        env_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        try:
            config = load_config(config_file)
        except JevError:
            # Test-only operation may use an environment key with no config at all.
            # Existing malformed, unsafe, or symlinked config is never bypassed.
            if test_only and env_key and not config_file.exists() and not config_file.is_symlink():
                config = {"api_key": "", "enabled": False}
            else:
                raise
        if not config["enabled"] and not test_only:
            raise JevError("Jev is disabled; run scripts/configure-jev.py --enable to opt in")
        self._api_key = env_key or config["api_key"].strip()
        if not self._api_key:
            raise JevError("Jev is enabled but no API key is available")
        if not _valid_key(self._api_key):
            raise JevError("Jev API key contains unsupported characters")
        self._opener = opener if opener is not None else _build_opener()
        self._timeout = float(timeout)

    def decide(self, state: dict, questions: dict) -> dict:
        payload = {"model": MODEL_ID, "state": state, "questions": _wire_questions(questions)}
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise JevError("Jev request data is invalid") from exc
        request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise JevError(f"Jev request failed with HTTP status {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise JevError("Jev request failed due to a network or TLS error") from None
        except Exception:
            # Avoid exposing provider client errors, request headers, or private state.
            raise JevError("Jev request failed") from None
        if len(response_body) > MAX_RESPONSE_BYTES:
            raise JevError("Jev response exceeded the 64 KiB limit")
        try:
            result = json.loads(response_body)
        except (UnicodeError, ValueError):
            raise JevError("Jev returned invalid JSON") from None
        if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
            raise JevError("Jev response did not contain answers")
        safe_result = {"answers": result["answers"]}
        usage = result.get("usage")
        if isinstance(usage, dict):
            safe_usage = {key: usage[key] for key in ("input_tokens", "prompt_tokens", "output_tokens")
                          if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool) and usage[key] >= 0}
            if safe_usage:
                safe_result["usage"] = safe_usage
        return safe_result


def estimate_input_tokens(state: dict, questions: dict) -> int:
    """Conservative display estimate for probe output when the API omits usage."""
    payload = {"model": MODEL_ID, "state": state, "questions": _wire_questions(questions)}
    return max(1, (len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) + 3) // 4)
