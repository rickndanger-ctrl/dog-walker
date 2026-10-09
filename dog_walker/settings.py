"""Machine-local worker settings; never included in exported job forms."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from .workflow import WalkerError

CONFIG = Path(os.environ.get("DOG_WALKER_CONFIG", Path.home() / ".config/dog-walker/worker.json"))


def defaults():
    home = Path.home()
    return {"model_path": str(home / "models/ornith15-35b-a3b/Ornith-1.5-35B-Q4_K_M.gguf"),
            "endpoint": "http://127.0.0.1:18081/v1",
            "catalog": str(home / "qwen-experiments/codex-cli-20261005/models.json"),
            "start_command": [str(home / "bin/ornith15-start")]}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != set(defaults()):
        raise WalkerError("Worker settings require model_path, endpoint, catalog, and start_command")
    if not isinstance(value["endpoint"], str):
        raise WalkerError("Worker endpoint must be a local HTTP /v1 address")
    parsed = urlparse(value["endpoint"])
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/v1":
        raise WalkerError("Worker endpoint must be a local HTTP /v1 address; cloud endpoints are not allowed")
    for key in ("model_path", "catalog"):
        if not isinstance(value[key], str) or not Path(value[key]).expanduser().is_absolute():
            raise WalkerError(f"{key} must be an absolute local file path")
    command = value["start_command"]
    if not isinstance(command, list) or not all(isinstance(x, str) and x for x in command):
        raise WalkerError("start_command must be an argument list, or [] to use an already-running server")
    if command and not Path(command[0]).expanduser().is_absolute():
        raise WalkerError("The model launcher must be an absolute local path")
    normalized = {**value, "model_path": str(Path(value["model_path"]).expanduser()),
                  "catalog": str(Path(value["catalog"]).expanduser())}
    normalized["start_command"] = [str(Path(command[0]).expanduser()), *command[1:]] if command else []
    return normalized


def load_settings():
    value = defaults()
    if CONFIG.exists():
        value.update(json.loads(CONFIG.read_text()))
    for field in ("model_path", "endpoint", "catalog"):
        key = "DOG_WALKER_" + field.upper()
        if key in os.environ:
            value[field] = os.environ[key]
    return validate_settings(value)


def save_settings(value):
    value = validate_settings(value)
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(CONFIG)
