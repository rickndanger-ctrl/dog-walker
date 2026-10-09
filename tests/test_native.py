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
def test_native_import_and_render(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
           "QT_QUICK_CONTROLS_STYLE": "Basic", "QT_QUICK_BACKEND": "software",
           "DOG_WALKER_DATA": str(tmp_path / "data"), "DOG_WALKER_INBOX": str(tmp_path / "inbox"),
           "DOG_WALKER_OPEN_FILE": "", "DOG_WALKER_APP_ROOT": str(APP_ROOT)}
    proc = subprocess.Popen(["quickshell", "-p", str(APP_ROOT / "native")], env=env,
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
    try:
        wait_for(lambda s: s["connected"])
        image = tmp_path / "welcome.png"
        ipc("capture", str(image))
        wait_for(lambda s: s["capture"] == "saved")
        assert image.stat().st_size > 10000
        ipc("open", str(APP_ROOT / "examples/discount.dogwalk"))
        value = wait_for(lambda s: s["job"] == "Fix a percentage discount")
        assert value["page"] == "new" and value["error"] == ""
        ipc("open", str(APP_ROOT / "forms/JOB_FORM.dogwalk"))
        wait_for(lambda s: "placeholders" in s["error"])
        assert not (tmp_path / "data/runs").exists(), "Import must never start a run"
        ipc("library")
        assert json.loads(ipc("snapshot"))["page"] == "library"
    finally:
        proc.terminate()
        try:
            output, _ = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate()
    assert "ReferenceError" not in output and "TypeError" not in output and "ERROR:" not in output, output
