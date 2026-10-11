import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from dog_walker import desktop, terminal, storage
from tests.test_engine import make_run
from tests.test_desktop import app
from dog_walker.workflow import WalkerError


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux unavailable")
def test_embedded_shell_uses_real_persistent_pty_without_opening_external_window(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    monkeypatch.setattr(terminal, "DATA", storage.DATA)
    monkeypatch.setenv("DOG_WALKER_DATA", str(storage.DATA))
    monkeypatch.setattr(terminal, "open_terminal", lambda *a: pytest.fail("embedded tabs must not open windows"))
    names = ["walk-" + store.state["id"] + "-context", "walk-" + store.state["id"] + "-shell"]
    try:
        shell = terminal.embedded_terminal(store, "shell")
        context = terminal.embedded_terminal(store, "context")
        assert context["kind"] == "context" and context["session"] != shell["session"]
        again = terminal.embedded_terminal(store, "shell")
        assert shell == again
        assert shell["cwd"] == store.state["root"]
        argv = ["tmux", "-L", "handler"]
        before = subprocess.check_output([*argv, "list-panes", "-t", shell["session"], "-F", "#{pane_pid}"], text=True)
        context_before = subprocess.check_output([*argv, "list-panes", "-t", context["session"], "-F", "#{pane_pid}"], text=True)
        assert len(before.splitlines()) == len(context_before.splitlines()) == 1
        command = "printf '%s\\n' HANDLER_PTY_OK > handler-pty-check.txt"
        subprocess.run([*argv, "send-keys", "-t", shell["session"], "-l", command], check=True)
        subprocess.run([*argv, "send-keys", "-t", shell["session"], "Enter"], check=True)
        import time
        marker = Path(store.state["root"]) / "handler-pty-check.txt"
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.read_text() == "HANDLER_PTY_OK\n"
        terminal.embedded_terminal(store, "shell")
        after = subprocess.check_output([*argv, "list-panes", "-t", shell["session"], "-F", "#{pane_pid}"], text=True)
        assert before == after
        terminal.embedded_terminal(store, "context")
        assert context_before == subprocess.check_output([*argv, "list-panes", "-t", context["session"], "-F", "#{pane_pid}"], text=True)
    finally:
        for name in names:
            subprocess.run(["tmux", "-L", "handler", "kill-session", "-t", name], capture_output=True)


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux unavailable")
def test_restoring_agent_reconnects_only_existing_session_and_never_starts_a_provider(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    monkeypatch.setattr(terminal, "DATA", storage.DATA)
    name = "walk-" + store.state["id"] + "-claude-review"
    argv = ["tmux", "-L", "handler"]
    with pytest.raises(WalkerError, match="No saved agent"):
        terminal.embedded_terminal(store, "helper", "claude", "review", attach_only=True)
    assert subprocess.run([*argv, "has-session", "-t", name], capture_output=True).returncode
    subprocess.run([*argv, "new-session", "-d", "-s", name, "/bin/sh", "-c", "read hold"], check=True)
    try:
        before = subprocess.check_output([*argv, "list-panes", "-t", name, "-F", "#{pane_pid}"], text=True)
        restored = terminal.embedded_terminal(store, "helper", "claude", "review", attach_only=True)
        assert restored["session"] == name
        assert subprocess.check_output([*argv, "list-panes", "-t", name, "-F", "#{pane_pid}"], text=True) == before
    finally:
        subprocess.run([*argv, "kill-session", "-t", name], capture_output=True)


@pytest.mark.parametrize("mode", ["review", "drive"])
async def test_embedded_helper_descriptor_is_sent_after_required_pause(app, tmp_path, monkeypatch, mode):
    from tests.test_forms import form
    import yaml
    project = tmp_path / "project"
    project.mkdir()
    await app.handle({"op": "import", "text": yaml.safe_dump(form())})
    app.store = storage.Store.create(app.workflow, project, in_place=True)
    plugin = tmp_path / "app/.runtime/qml/QMLTermWidget/libqmltermwidget.so"
    plugin.parent.mkdir(parents=True)
    plugin.touch()
    monkeypatch.setattr(desktop, "APP_ROOT", tmp_path / "app")
    calls = []
    task = asyncio.create_task(asyncio.sleep(30))
    app.task = task
    async def pause():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        app.task = None
        calls.append("pause")
    monkeypatch.setattr(app, "pause", pause)
    def prepare(store, kind, provider, role):
        calls.append((provider, role, task.done()))
        return {"id": "test-terminal", "program": "tmux", "args": [], "cwd": str(project)}
    monkeypatch.setattr(terminal, "embedded_terminal", prepare)
    try:
        await app.command({"op": "terminal", "kind": "helper", "embedded": True,
            "run_id": app.store.state["id"], "provider": "claude", "mode": mode})
        assert calls == (["pause", ("claude", "drive", True)] if mode == "drive" else [("claude", "review", False)])
        assert app.events[-1]["type"] == "terminal_ready"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
