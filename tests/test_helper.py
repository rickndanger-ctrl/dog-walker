import fcntl
import json
from pathlib import Path

import pytest

from dog_walker import helper, storage, terminal
from dog_walker.storage import Store, digest, project_inventory
from dog_walker.workflow import WalkerError
from tests.test_engine import make_run


@pytest.fixture
def helper_run(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, steps=[{
        "id": "one", "prompt": "prompt.md", "retry_prompt": "retry.md",
        "checks": [{"type": "unchanged", "path": "protected.txt"}],
    }])
    monkeypatch.setattr(helper, "DATA", storage.DATA)
    monkeypatch.setattr(helper, "runtime_view", lambda: None)
    root = Path(store.state["root"])
    (root / "editable.txt").write_text("before")
    store.save(status="paused", phase="reviewing",
               allowed_changes=["editable.txt", "protected.txt"],
               scope_hashes=project_inventory(root))
    return store


def result_value(response):
    return json.loads(response["content"][0]["text"]) if not response["isError"] else response["content"][0]["text"]


def write(server, path="editable.txt", text="after", expected=None):
    if expected is None and path == "editable.txt":
        expected = digest(Path(server_run_root(server)) / path)
    return server.call("handler_write_file", {"path": path, "text": text,
                                               "expected_sha256": expected})


def server_run_root(server):
    return Store.open(server.run_id).state["root"]


def test_review_lists_no_control_or_edit_tools_and_rejects_write(helper_run):
    server = helper.HelperServer(helper_run.state["id"], "review")
    names = {tool["name"] for tool in server.tools()}
    assert names == {"handler_status", "handler_activity", "handler_list_files",
                     "handler_read_file", "handler_suggest"}
    response = server.call("handler_write_file", {"path": "editable.txt", "text": "x",
                                                    "expected_sha256": digest(Path(helper_run.state["root"]) / "editable.txt")})
    assert response["isError"]
    assert (Path(helper_run.state["root"]) / "editable.txt").read_text() == "before"


@pytest.mark.parametrize("lease", ["global", "run"])
def test_drive_write_is_refused_while_either_controller_lease_is_held(helper_run, lease):
    server = helper.HelperServer(helper_run.state["id"], "drive")
    root = Path(helper_run.state["root"])
    lock = None
    if lease == "global":
        lock = (storage.DATA / "desktop-worker.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        helper_run.acquire()
    try:
        response = write(server)
        assert response["isError"]
        assert "Pause the walk" in response["content"][0]["text"] or "already open" in response["content"][0]["text"]
        assert (root / "editable.txt").read_text() == "before"
    finally:
        if lock:
            lock.close()
        else:
            helper_run.release()


def test_write_obeys_allowlist_and_protected_hashes(helper_run):
    server = helper.HelperServer(helper_run.state["id"], "drive")
    response = server.call("handler_write_file", {"path": "outside.txt", "text": "x", "expected_sha256": None})
    assert response["isError"]
    response = server.call("handler_write_file", {"path": "protected.txt", "text": "x",
        "expected_sha256": digest(Path(helper_run.state["root"]) / "protected.txt")})
    assert response["isError"]
    assert (Path(helper_run.state["root"]) / "protected.txt").read_text() == "keep me"


def test_write_requires_fresh_hash_and_enforces_utf8_byte_limit(helper_run):
    server = helper.HelperServer(helper_run.state["id"], "drive")
    root = Path(helper_run.state["root"])
    stale = "0" * 64
    response = server.call("handler_write_file", {"path": "editable.txt", "text": "stale",
                                                    "expected_sha256": stale})
    assert response["isError"]
    assert (root / "editable.txt").read_text() == "before"
    over_limit = "€" * (helper.MAX_TEXT // 3 + 1)
    response = server.call("handler_write_file", {"path": "editable.txt", "text": over_limit,
        "expected_sha256": digest(root / "editable.txt")})
    assert response["isError"]
    assert "UTF-8" in response["content"][0]["text"]
    assert (root / "editable.txt").read_text() == "before"


def test_write_rejects_symlinks_and_path_escape(helper_run, tmp_path):
    server = helper.HelperServer(helper_run.state["id"], "drive")
    root = Path(helper_run.state["root"])
    external = tmp_path / "outside.txt"
    external.write_text("outside")
    (root / "link.txt").symlink_to(external)
    latest = Store.open(helper_run.state["id"])
    latest.save(allowed_changes=["editable.txt", "protected.txt", "link.txt", "../outside.txt"],
                scope_hashes=project_inventory(root))
    link_result = server.call("handler_write_file", {"path": "link.txt", "text": "x", "expected_sha256": digest(external)})
    escape_result = server.call("handler_write_file", {"path": "../outside.txt", "text": "x", "expected_sha256": None})
    assert link_result["isError"] and "symlinks" in link_result["content"][0]["text"]
    assert escape_result["isError"]
    assert external.read_text() == "outside"


def test_successful_scoped_edit_writes_utf8_bytes(helper_run):
    server = helper.HelperServer(helper_run.state["id"], "drive")
    root = Path(helper_run.state["root"])
    response = write(server, text="café 🐕")
    assert not response["isError"]
    assert (root / "editable.txt").read_bytes() == "café 🐕".encode("utf-8")
    assert result_value(response)["checks_pending"] is True


def test_guidance_is_consumed_once_and_stale_step_guidance_is_not_injected(helper_run):
    server = helper.HelperServer(helper_run.state["id"], "drive")
    response = server.call("handler_guide_model", {"text": "Consider the parser edge case."})
    assert not response["isError"]
    note = helper_run.path / "helper-guidance.json"
    assert note.exists()
    first = helper.take_guidance(Store.open(helper_run.state["id"]))
    assert "parser edge case" in first and "cannot approve" in first
    assert helper.take_guidance(Store.open(helper_run.state["id"])) == ""
    note.write_text(json.dumps({"run_id": helper_run.state["id"], "step": "previous", "text": "stale advice"}))
    assert helper.take_guidance(Store.open(helper_run.state["id"])) == ""
    assert not note.exists()
    assert list(helper_run.path.glob("stale-helper-guidance-*.json"))


def test_verify_uses_authored_tool_execution_without_evaluation_or_plugin_receipt(helper_run, monkeypatch):
    class FakeToolServer:
        def __init__(self, run_dir):
            self.run_dir = run_dir

        def execute(self, name, args):
            assert name == "project_verify" and args == {}
            return {"checks": [{"id": "authored", "pass": False}], "passed": False}

    monkeypatch.setattr("dog_walker.tool_server.ToolServer", FakeToolServer)
    original_evaluation = {"decision": "review", "checks": [{"id": "old", "pass": True}]}
    helper_run.save(evaluation=original_evaluation)
    server = helper.HelperServer(helper_run.state["id"], "drive")
    response = server.call("handler_verify", {})
    assert result_value(response) == {"checks": [{"id": "authored", "pass": False}], "passed": False}
    fresh = Store.open(helper_run.state["id"])
    assert fresh.state["evaluation"] == original_evaluation
    events = [json.loads(line) for line in (fresh.path / "events.jsonl").read_text().splitlines()]
    assert any(event["type"] == "helper_verification" for event in events)
    assert not any(event["type"] == "plugin_tool" for event in events)


def test_control_rejects_stale_selected_run_before_sending_ipc(helper_run, monkeypatch):
    server = helper.HelperServer(helper_run.state["id"], "drive")
    monkeypatch.setattr(helper, "runtime_view", lambda: {"connected": True, "state": {"id": "other-run"}})
    monkeypatch.setattr(helper, "ipc", lambda *args: pytest.fail("stale run must not send IPC"))
    with pytest.raises(WalkerError, match="controlling it"):
        server.control("pause")


def test_snapshot_context_skips_private_and_symlink_files_without_touching_workspace(helper_run, monkeypatch):
    root = Path(helper_run.state["root"])
    (root / ".env.local").write_text("secret=hidden")
    private = root / ".ssh"
    private.mkdir()
    (private / "id_rsa").write_text("private")
    outside = root.parent / "outside.txt"
    outside.write_text("outside")
    (root / "linked.txt").symlink_to(outside)
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
              if path.is_file() and not path.is_symlink()}
    monkeypatch.setattr(terminal, "DATA", storage.DATA)
    monkeypatch.setattr(helper, "runtime_view", lambda: None)
    folder = terminal.create_context(helper_run, "review")
    snapshot = folder / "project"
    assert not (snapshot / ".env.local").exists()
    assert not (snapshot / ".ssh" / "id_rsa").exists()
    assert not (snapshot / "linked.txt").exists()
    assert ".env.local" in (folder / "CONTEXT.md").read_text()
    after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
             if path.is_file() and not path.is_symlink()}
    assert after == before


@pytest.mark.parametrize("provider,mode", [("claude", "review"), ("claude", "drive"),
                                            ("codex", "review"), ("codex", "drive")])
def test_helper_argv_keeps_cli_read_only_and_mcp_scoped(provider, mode, tmp_path):
    folder = tmp_path / "helper"
    folder.mkdir()
    server_config = {"mcpServers": {"handler": {"command": "/usr/bin/python",
        "args": ["-I", str(terminal.MCP_SCRIPT), "--run-id", "run-123", "--mode", mode]}}}
    (folder / "mcp.json").write_text(json.dumps(server_config))
    argv = terminal.helper_argv(provider, mode, folder, "run-123")
    if provider == "claude":
        assert argv[argv.index("--permission-mode") + 1] == ("plan" if mode == "review" else "manual")
        mcp_args = json.loads((folder / "mcp.json").read_text())["mcpServers"]["handler"]["args"]
        assert "--safe-mode" not in argv, "safe mode disables the MCP connection"
        assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep"
    else:
        assert argv[argv.index("--sandbox") + 1] == "read-only"
        setting = next(arg for arg in argv if arg.startswith("mcp_servers.handler.args="))
        mcp_args = json.loads(setting.split("=", 1)[1])
    assert "--run-id" in mcp_args and mcp_args[mcp_args.index("--run-id") + 1] == "run-123"
    assert "--mode" in mcp_args and mcp_args[mcp_args.index("--mode") + 1] == mode


def test_terminal_command_boundary_preserves_tmux_arguments(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(terminal.shutil, "which", lambda name: "/usr/bin/omarchy")
    monkeypatch.setattr(terminal.subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)))
    terminal.open_terminal(["tmux", "-L", "handler", "attach-session", "-t", "walk-123"], tmp_path)
    assert calls[0][0] == ["omarchy", "launch", "terminal", "--", "tmux", "-L", "handler", "attach-session", "-t", "walk-123"]


def test_real_helper_verification_detects_protected_input_changes_without_advancing(helper_run):
    from dog_walker.plugins import freeze_plugins
    freeze_plugins(helper_run)  # Started walks already carry their frozen grants.
    server = helper.HelperServer(helper_run.state["id"], "drive")
    before = (helper_run.path / "state.json").read_bytes()
    response = server.call("handler_verify", {})
    assert not response["isError"] and result_value(response)["passed"], response
    (Path(helper_run.state["root"]) / "protected.txt").write_text("tampered")
    response = server.call("handler_verify", {})
    assert not response["isError"] and not result_value(response)["passed"]
    assert any(not c["pass"] and c["type"] == "unchanged" for c in result_value(response)["checks"])
    assert (helper_run.path / "state.json").read_bytes() == before
