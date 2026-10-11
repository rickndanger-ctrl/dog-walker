"""Job-scoped plugin grants and MCP configuration; importing executes nothing."""
import json
import os
from pathlib import Path
import re
import sys
from jsonschema import validate, ValidationError
from .storage import APP_ROOT, atomic_json
from .workflow import WalkerError

PLUGIN_DIR = Path(os.environ.get("DOG_WALKER_PLUGIN_DIR", Path.home() / ".config/dog-walker/plugins"))
ID = r"[a-z][a-z0-9_-]{0,63}"
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "name", "description", "category", "adapter", "settings"],
    "properties": {
        "id": {"type": "string", "pattern": "^" + ID + "$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 100},
        "description": {"type": "string", "minLength": 1, "maxLength": 500},
        "category": {"enum": ["project", "browser", "connected"]},
        "adapter": {"enum": ["project", "browser", "obsidian", "mcp", "coder"]},
        "settings": {"type": "object"},
    },
}


def builtin_plugins():
    home = Path.home()
    return [
        {"id": "project", "name": "Project tools", "category": "project", "adapter": "project",
         "description": "Find relevant project code, read workspace files, inspect local Git status, and run this step's authored checks in the offline sandbox.", "settings": {}},
        {"id": "browser", "name": "Browser inspection", "category": "browser", "adapter": "browser",
         "description": "Inspect a project HTML file or an allowed web origin in a fresh headless browser; return visible text and layout/errors.",
         "settings": {"origins": [], "playwright_module": str(home / "Projects/hermes-army/node_modules/playwright")}},
        {"id": "obsidian", "name": "Obsidian reader", "category": "connected", "adapter": "obsidian",
         "description": "Read and search Markdown in the existing connected vault. No writes or replacement vault.",
         "settings": {"root": str(home / "Documents/Obsidian Vault")}},
    ]


def plugin_ids(value):
    if (not isinstance(value, list) or len(value) > 20 or
            not all(isinstance(x, str) and re.fullmatch(ID, x) for x in value) or len(set(value)) != len(value)):
        raise WalkerError("plugins must list up to 20 unique installed plugin IDs")
    return value


def validate_plugin(value, *, allow_retired=False):
    try:
        validate(value, SCHEMA)
    except ValidationError as exc:
        raise WalkerError(f"Invalid plugin manifest: {exc.message}") from exc
    settings = value["settings"]
    adapter = value["adapter"]
    if adapter == "coder" and not allow_retired:
        raise WalkerError("The small coder has been removed from Dog Walk. Remove local-coder from this plan.")
    keys = {"project": set(), "obsidian": {"root"}, "browser": {"origins", "playwright_module"},
            "mcp": {"command", "args", "enabled_tools"}, "coder": {"endpoint", "model", "timeout"}}[adapter]
    if set(settings) != keys:
        if adapter == "mcp" and set(settings) == keys | {"env_vars"}:
            pass
        else:
            raise WalkerError(f"{adapter} settings require exactly {sorted(keys)}")
    if adapter in {"obsidian", "browser", "mcp"}:
        key = {"obsidian": "root", "browser": "playwright_module", "mcp": "command"}[adapter]
        if not isinstance(settings[key], str) or not Path(settings[key]).is_absolute():
            raise WalkerError(f"Plugin {key} must be an absolute local path")
    if adapter == "browser":
        from urllib.parse import urlsplit
        origins = settings["origins"]
        if not isinstance(origins, list) or len(origins) > 30:
            raise WalkerError("Browser origins must be a list of at most 30 exact HTTP(S) origins")
        for origin in origins:
            if not isinstance(origin, str):
                raise WalkerError("Browser origins must be text")
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or
                    parsed.path or parsed.query or parsed.fragment or origin != f"{parsed.scheme}://{parsed.netloc}"):
                raise WalkerError("Browser origins must be exact HTTP(S) origins without paths or credentials")
            try:
                parsed.port
            except ValueError as exc:
                raise WalkerError("Invalid browser origin port") from exc
    if adapter == "mcp":
        for key in ("args", "enabled_tools"):
            if (not isinstance(settings[key], list) or len(settings[key]) > 100 or
                    not all(isinstance(x, str) and x and len(x) <= 1000 for x in settings[key])):
                raise WalkerError(f"MCP {key} must be an argument/name list")
        if not settings["enabled_tools"] or len(set(settings["enabled_tools"])) != len(settings["enabled_tools"]):
            raise WalkerError("An MCP plugin needs a non-empty unique tool allowlist")
        env_vars = settings.get("env_vars", [])
        if (not isinstance(env_vars, list) or len(env_vars) > 20 or
                not all(isinstance(x, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", x) for x in env_vars) or
                len(set(env_vars)) != len(env_vars)):
            raise WalkerError("MCP env_vars must be a unique list of environment variable names")
    return value


def registry():
    plugins = {p["id"]: validate_plugin(p) for p in builtin_plugins()}
    for path in sorted(PLUGIN_DIR.glob("*.json")):
        if path.stat().st_size > 64 * 1024:
            raise WalkerError(f"Plugin manifest is too large: {path.name}")
        try:
            plugin = validate_plugin(json.loads(path.read_text()))
        except (OSError, ValueError) as exc:
            raise WalkerError(f"Cannot read plugin {path.name}: {exc}") from exc
        if path.stem != plugin["id"]:
            raise WalkerError("Plugin filename must match its ID")
        plugins[plugin["id"]] = plugin
    return plugins


def resolve_plugins(ids):
    plugin_ids(ids)
    if not ids:
        return []
    installed = registry()
    missing = set(ids) - installed.keys()
    if missing:
        raise WalkerError(f"Plugins are not installed: {', '.join(sorted(missing))}")
    # Return independent data so a running walk never follows subsequent config edits.
    resolved = json.loads(json.dumps([installed[x] for x in ids]))
    adapters = [p["adapter"] for p in resolved if p["adapter"] != "mcp"]
    if len(set(adapters)) != len(adapters):
        raise WalkerError("A job may request only one plugin for each built-in adapter")
    return resolved


def freeze_plugins(store):
    """A run opts in explicitly. Old runs/forms retain their original tool set."""
    target = store.path / "plugin-grants.json"
    if not target.exists():
        plugins = resolve_plugins(store.workflow().data.get("plugins", []))
        atomic_json(target, {"version": 1, "plugins": plugins})
        if plugins:
            store.event("plugin_grants", plugins=plugins)
    return load_grants(store.path)


def load_grants(run_dir):
    path = Path(run_dir) / "plugin-grants.json"
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {"version", "plugins"} or value["version"] != 1:
        raise WalkerError("Invalid saved plugin grants")
    if not isinstance(value["plugins"], list):
        raise WalkerError("Invalid saved plugin list")
    # Historical grants remain readable, but retired adapters cannot execute.
    plugins = [validate_plugin(p, allow_retired=True) for p in value["plugins"]]
    plugin_ids([p["id"] for p in plugins])
    return plugins


def tool_events(store):
    """Only controller-recorded tool receipts from this step and turn count."""
    path = store.path / "events.jsonl"
    calls = []
    if not path.exists():
        return calls
    with path.open() as handle:
        for line in handle:
            event = json.loads(line)
            if (event.get("type") == "plugin_tool" and event.get("step") == store.state["step"] and
                    event.get("turn") == store.state["turns"]):
                calls.append(event)
    return calls


def codex_overrides(store):
    """Per-turn config overrides keep plugins out of other walks/Codex homes."""
    plugins = freeze_plugins(store)
    if not plugins:
        return []
    from .tool_server import ToolServer
    builtin = [p for p in plugins if p["adapter"] not in {"mcp", "coder"}]
    servers = {}
    if builtin:
        tools = [t["name"] for t in ToolServer(store.path).tools()]
        servers["dogwalker"] = {"command": sys.executable,
            "args": ["-I", str(APP_ROOT / "scripts/plugin-server.py"), "--run-dir", str(store.path)],
            "enabled_tools": tools}
    for plugin in plugins:
        if plugin["adapter"] == "mcp":
            settings = {key: value for key, value in plugin["settings"].items() if key != "env_vars"}
            if plugin["settings"].get("env_vars"):
                # Ask Codex to pass these names through from its already-sanitized
                # process environment. Never place secret values in argv/config.
                settings["env_vars"] = plugin["settings"]["env_vars"]
            servers["dw_" + plugin["id"]] = settings
    argv = []
    for ident, server in servers.items():
        for key, value in {**server, "required": True, "startup_timeout_sec": 15, "tool_timeout_sec": 90}.items():
            encoded = "true" if value is True else json.dumps(value)
            argv += ["-c", f"mcp_servers.{ident}.{key}={encoded}"]
    return argv
