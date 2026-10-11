"""Load and render the real QML app; no worker inference or desktop changes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import pytest
from dog_walker.storage import APP_ROOT


@pytest.mark.skipif(not shutil.which("quickshell"), reason="Quickshell is not installed")
def test_native_import_and_render(tmp_path, monkeypatch):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
           "QT_QUICK_CONTROLS_STYLE": "Basic", "QT_QUICK_BACKEND": "software",
           "DOG_WALKER_DATA": str(tmp_path / "data"), "DOG_WALKER_INBOX": str(tmp_path / "inbox"),
           "DOG_WALKER_OPEN_FILE": "", "DOG_WALKER_APP_ROOT": str(APP_ROOT)}
    env["QML_IMPORT_PATH"] = str(APP_ROOT / ".runtime/qml")
    config = os.environ.get("HANDLER_NATIVE_TEST_PATH", str(APP_ROOT / "native"))
    proc = subprocess.Popen(["quickshell", "-p", config], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    def ipc(method, *args):
        result = subprocess.run(["quickshell", "ipc", "--pid", str(proc.pid), "call", "dogwalker", method, *args],
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout.strip()
    def wait_for(check):
        deadline = time.monotonic() + 10
        last = "No response"
        while time.monotonic() < deadline:
            try:
                value = json.loads(ipc("snapshot"))
                last = value
                if check(value):
                    return value
            except (RuntimeError, ValueError) as exc:
                last = str(exc)
            if proc.poll() is not None:
                break
            time.sleep(.05)
        raise AssertionError(f"Native UI did not reach expected state: {last}")
    terminal_sessions = []
    try:
        wait_for(lambda s: s["connected"])
        image = tmp_path / "welcome.png"
        ipc("capture", str(image))
        wait_for(lambda s: s["capture"] == "saved")
        assert image.stat().st_size > 10000
        ipc("open", str(APP_ROOT / "examples/discount.dogwalk"))
        value = wait_for(lambda s: s["job"] == "Fix a percentage discount")
        assert value["page"] == "new" and value["error"] == ""
        assert not value["setup_ready"]
        project = tmp_path / "drop-project"
        project.mkdir()
        assert ipc("setupDrop", json.dumps({"urls": [project.as_uri(), (APP_ROOT / "examples/discount.dogwalk").as_uri()]})) == "accepted"
        value = wait_for(lambda s: s["project"] == str(project) and s["setup_ready"])
        assert value["job"] == "Fix a percentage discount"
        assert ipc("newWalk") == "ok"
        value = wait_for(lambda s: not s["job"] and not s["project"])
        assert value["page"] == "new" and not value["setup_ready"]
        markdown = tmp_path / "ordinary task.md"
        markdown.write_text("# Ordinary Markdown\nBuild a notes app and test persistence.\n")
        ipc("setupDrop", json.dumps({"urls": [markdown.as_uri()]}))
        value = wait_for(lambda s: s.get("brief") == "Ordinary Markdown")
        assert not value["project"] and not value["job"], "A Markdown attachment never chooses a folder or starts work"
        ipc("setupDrop", json.dumps({"urls": [project.as_uri()]}))
        value = wait_for(lambda s: s["project"] == str(project))
        assert not value["setup_ready"], "A brief must be planned and reviewed before Start"
        ipc("open", str(APP_ROOT / "forms/JOB_FORM.dogwalk"))
        wait_for(lambda s: "placeholders" in s["error"])
        assert not (tmp_path / "data/runs").exists(), "Import must never start a run"
        ipc("library")
        assert json.loads(ipc("snapshot"))["page"] == "library"
        from .test_engine import make_run, output
        store = make_run(tmp_path, monkeypatch, steps=[{"id": f"step{i}", "prompt": "prompt.md"} for i in range(3)])
        store.save(status="completed", step="complete", turns=3,
                   history=[{"step": f"step{i}", "outcome": "passed", "attempts": 1, "turn": i + 1} for i in range(3)],
                   previous_result=output("Completed render fixture"), completion="all_passed")
        has_terminal = shutil.which("tmux") and (APP_ROOT / ".runtime/qml/QMLTermWidget/libqmltermwidget.so").is_file()
        if has_terminal:
            terminal_sessions = ["walk-" + store.state["id"] + "-context", "walk-" + store.state["id"] + "-shell"]
        ipc("showWalk", store.state["id"])
        wait_for(lambda s: s["state"] == store.state["id"] and s["progress"] == 1)
        if has_terminal:
            wait_for(lambda s: s.get("terminals") == 2)
            ipc("openTerminal", "shell")
            wait_for(lambda s: s.get("terminals") == 2)
            ipc("openTerminal", "live")
            wait_for(lambda s: s.get("terminals") == 2)
            ipc("selectTerminal", store.state["id"] + ":shell")
            image = tmp_path / "embedded-terminal.png"
            ipc("capture", str(image))
            wait_for(lambda s: s["capture"] == "saved")
            assert image.stat().st_size > 10000
    finally:
        proc.terminate()
        try:
            output, _ = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate()
        for session in terminal_sessions:
            subprocess.run(["tmux", "-L", "handler", "kill-session", "-t", session], capture_output=True)
    assert "ReferenceError" not in output and "TypeError" not in output and "ERROR:" not in output, output
    assert 'plugin "qmltermwidget" not found' not in output, output
