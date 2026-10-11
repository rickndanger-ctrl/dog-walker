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
            "start_command": [str(Path(__file__).resolve().parents[1] / "scripts/model-start.py")]}


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


def model_profiles():
    """Installed local main models, using the reviewed shared-switch launcher."""
    home = Path.home()
    launcher = Path(__file__).resolve().parents[1] / "scripts/model-start.py"
    catalog = load_settings()["catalog"]
    definitions = (
        ("ornith", "Ornith", "ornith15-35b-a3b", "Ornith-1.5-35B-Q4_K_M.gguf", "mmproj-Ornith-1.5-35B-BF16.gguf", 18081),
        ("gemma", "Gemma 4", "gemma4-26b-a4b", "gemma-4-26B_q4_0-it.gguf", "gemma-4-26B-it-mmproj.gguf", 18082),
        ("qwen", "Qwen 3.8 27B", "qwen38-27b", "Qwen3.8-27B-UD-Q4_K_XL.gguf", "mmproj-F16.gguf", 18080),
    )
    profiles = []
    try:
        entries = json.loads(Path(catalog).read_text())["models"]
        catalog_models = {entry["slug"] for entry in entries}
    except (OSError, ValueError, KeyError, TypeError):
        catalog_models = set()
    for ident, label, directory, filename, projector, port in definitions:
        model = home / "models" / directory / filename
        settings = validate_settings({"model_path": str(model), "endpoint": f"http://127.0.0.1:{port}/v1",
                                      "catalog": catalog, "start_command": [str(launcher), "--model", ident]})
        available = str(model) in catalog_models and all(p.is_file() for p in (model, model.parent / projector, Path(catalog), launcher,
                                             home / "opt/local-model-runtime/launcher.py"))
        profiles.append({"id": ident, "label": label, "available": available, "settings": settings})
    return profiles


def model_summary():
    current = load_settings()
    profiles = model_profiles()
    selected = next((p for p in profiles if p["settings"]["model_path"] == current["model_path"]
                     and p["settings"]["endpoint"] == current["endpoint"]), None)
    return {"model_id": selected["id"] if selected else "custom",
            "model_label": selected["label"] if selected else "Local model",
            "model_profiles": [{k: p[k] for k in ("id", "label", "available")} for p in profiles]}


def select_model(ident):
    profile = next((p for p in model_profiles() if p["id"] == ident), None)
    if not profile or not profile["available"]:
        raise WalkerError("That local model is not installed. Use Settings to connect another model.")
    if any("DOG_WALKER_" + field.upper() in os.environ for field in ("model_path", "endpoint", "catalog")):
        raise WalkerError("The model connection is set by environment variables. Remove those overrides before using the picker.")
    save_settings(profile["settings"])
