import json
import tomllib

import pytest

from dog_walker import plugins, storage
from dog_walker.tool_server import ToolServer
from dog_walker.workflow import WalkerError
from .test_engine import make_run


def legacy_coder():
    return {"id": "local-coder", "name": "Local coder adviser",
            "description": "Historical coding helper", "category": "connected",
            "adapter": "coder", "settings": {"endpoint": "http://127.0.0.1:18083/v1",
            "model": "/historical/qwen-coder.gguf", "timeout": 20}}


def test_removed_coder_is_not_available_for_new_plans(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins, "PLUGIN_DIR", tmp_path / "plugins")
    assert "local-coder" not in plugins.registry()
    with pytest.raises(WalkerError, match="not installed"):
        plugins.resolve_plugins(["local-coder"])
    with pytest.raises(WalkerError, match="removed"):
        plugins.validate_plugin(legacy_coder())


@pytest.mark.parametrize("with_project", [False, True])
def test_historical_coder_grants_are_readable_but_cannot_execute(tmp_path, monkeypatch, with_project):
    store = make_run(tmp_path, monkeypatch)
    grants = [legacy_coder()]
    if with_project:
        grants += [next(p for p in plugins.builtin_plugins() if p["id"] == "project")]
    path = store.path / "plugin-grants.json"
    storage.atomic_json(path, {"version": 1, "plugins": grants})
    before = path.read_bytes()
    store.save(status="running", phase="running", turns=1)
    server = ToolServer(store.path)
    monkeypatch.setattr(server, "process", lambda *a, **k: pytest.fail("Retired helper must never launch"))
    tools = {t["name"] for t in server.tools()}
    assert "local_coder_suggest" not in tools
    assert ("project_map" in tools) is with_project
    assert server.call("local_coder_suggest", {"task": "Review"})["isError"]
    assert path.read_bytes() == before
    assert plugins.load_grants(store.path) == grants
    args = plugins.codex_overrides(store)
    if with_project:
        config = tomllib.loads("\n".join(args[i] for i in range(1, len(args), 2)))
        broker = config["mcp_servers"]["dogwalker"]
        assert "local_coder_suggest" not in broker["enabled_tools"]
        assert "env_vars" not in broker
    else:
        assert args == []


def test_saved_coder_manifest_cannot_reenable_removed_adapter(tmp_path, monkeypatch):
    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "local-coder.json").write_text(json.dumps(legacy_coder()))
    monkeypatch.setattr(plugins, "PLUGIN_DIR", folder)
    with pytest.raises(WalkerError, match="removed"):
        plugins.registry()


def test_saved_chat_does_not_select_retired_tool_or_rewrite_history(tmp_path, monkeypatch):
    from dog_walker import chat
    monkeypatch.setattr(chat, "DATA", tmp_path / "data")
    conversation = chat.Conversation.create()
    conversation.save(selected_plugins=["project", "local-coder"])
    path = conversation.path / "chat.json"
    original = path.read_bytes()
    assert conversation.snapshot()["selected_plugins"] == ["project"]
    assert path.read_bytes() == original
