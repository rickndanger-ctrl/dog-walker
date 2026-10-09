"""Opt-in real-model acceptance through the rendered QML app.

Requires an already-running compatible local server and the installed source
environment. Test-only IPC is injected into a temporary QML copy to invoke the
actual buttons. No job-starting test IPC is added to the installed app. This
test uses loopback inference; it does not isolate the host's external network.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def run():
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix="desktop-acceptance-", dir=artifacts))
    os.environ["DOG_WALKER_DATA"] = str(data)
    from dog_walker.cli import fixture
    from dog_walker.settings import load_settings
    from dog_walker.worker import model_ready

    model_ready()  # Refuse a missing or mismatched server before starting.
    project = fixture()
    original = {p.name: p.read_bytes() for p in project.glob("*.py")}
    settings = load_settings()
    settings["start_command"] = []  # Reuse the existing model; never launch a second one.
    config = data / "worker.json"
    config.write_text(json.dumps(settings))
    env = {**os.environ, "DOG_WALKER_CONFIG": str(config),
           "DOG_WALKER_INBOX": str(data / "inbox"), "DOG_WALKER_APP_ROOT": str(ROOT),
           "DOG_WALKER_OPEN_FILE": "", "QT_QPA_PLATFORM": "offscreen",
           "QT_QPA_PLATFORMTHEME": "", "QT_QUICK_CONTROLS_STYLE": "Basic",
           "QT_QUICK_BACKEND": "software"}
    report = {"data": str(data), "network_isolated": False,
              "automation": "Temporary QML test IPC invokes actual button handlers",
              "scripted_approvals": []}
    proc = None
    with tempfile.TemporaryDirectory(prefix="dog-walker-qml-") as scratch:
        native = Path(scratch) / "native"
        shutil.copytree(ROOT / "native", native)
        shell = native / "shell.qml"
        qml = shell.read_text()
        for label, ident in (("Start walk  →", "testStart"),
                             ("Approve & continue", "testApprove"),
                             ("Pause walk", "testPause"), ("Resume walk", "testResume")):
            needle = 'ActionButton { text: "' + label + '";'
            if needle not in qml:
                # Pause/resume buttons have visibility declarations before text.
                needle = 'text: "' + label + '";'
                replacement = 'id: ' + ident + '; ' + needle
            else:
                replacement = 'ActionButton { id: ' + ident + '; text: "' + label + '";'
            assert qml.count(needle) == 1, f"Button changed: {label}"
            qml = qml.replace(needle, replacement)
        qml = qml.replace('// Read-only diagnostics', '''
        function testDrive(action: string, root: string): string {
            if (action === "configure") { app.project = root; app.inPlace = false; app.automatic = true }
            else if (action === "start" && testStart.enabled) testStart.clicked()
            else if (action === "approve" && app.review && testApprove.enabled) testApprove.clicked()
            else if (action === "pause" && app.active) testPause.clicked()
            else if (action === "resume" && !app.active) testResume.clicked()
            else return "rejected"
            return "ok"
        }
        function testSnapshot(): string {
            return JSON.stringify({connected: app.online, error: app.error,
                review: app.review, active: app.active, state: app.state})
        }
        // Read-only diagnostics''')
        shell.write_text(qml)

        with (data / "qml.log").open("w") as log:
            def launch():
                return subprocess.Popen(["quickshell", "-p", str(native)], env=env,
                                        stdout=log, stderr=subprocess.STDOUT)

            def ipc(method, *args):
                result = subprocess.run(["quickshell", "ipc", "--pid", str(proc.pid),
                    "call", "dogwalker", method, *args], capture_output=True, text=True, timeout=5)
                if result.returncode:
                    raise RuntimeError(result.stdout + result.stderr)
                return result.stdout.strip()

            def wait(check, timeout=30):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError(f"QML exited; see {data / 'qml.log'}")
                    try:
                        value = json.loads(ipc("testSnapshot"))
                    except (RuntimeError, ValueError):
                        time.sleep(.2)
                        continue
                    if value["error"]:
                        raise RuntimeError(value["error"])
                    if check(value):
                        return value
                    if value["state"] and value["state"]["status"] == "paused" and value["state"]["phase"] == "interrupted":
                        raise RuntimeError(value["state"].get("reason") or "Worker was interrupted")
                    time.sleep(.5)
                raise TimeoutError(f"Desktop did not reach expected state; see {data}")

            def close():
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

            try:
                proc = launch()
                wait(lambda v: v["connected"])
                ipc("open", str(ROOT / "examples/discount.dogwalk"))
                deadline = time.monotonic() + 20
                while json.loads(ipc("snapshot"))["job"] != "Fix a percentage discount":
                    assert time.monotonic() < deadline, "Form did not import"
                    time.sleep(.2)
                assert not (data / "runs").exists(), "Import must be inert"
                assert ipc("testDrive", "configure", str(project)) == "ok"
                assert ipc("testDrive", "start", "") == "ok"
                print("Native desktop started the real-model job.", flush=True)
                value = wait(lambda v: v["review"], timeout=1200)
                state = value["state"]
                assert state["step"] == "verify", state
                assert state["turns"] == 3 and len(state["history"]) == 2, state
                assert all(c["pass"] for c in state["evaluation"]["checks"]), state
                report.update(run_id=state["id"], turns_before_reopen=state["turns"],
                              session=state["session"], final_checks=state["evaluation"]["checks"])
                print("Three turns finished; final review checks passed. Testing reopen.", flush=True)
                assert ipc("testDrive", "pause", "") == "ok"
                wait(lambda v: not v["active"] and v["state"]["status"] == "paused")
                close()
                proc = launch()
                wait(lambda v: v["connected"])
                ipc("showWalk", report["run_id"])
                wait(lambda v: v["state"] and v["state"]["id"] == report["run_id"])
                assert ipc("testDrive", "resume", "") == "ok"
                value = wait(lambda v: v["review"])
                assert value["state"]["turns"] == 3, "Reopening replayed a completed turn"
                assert all(c["pass"] for c in value["state"]["evaluation"]["checks"])
                report["scripted_approvals"].append({"step": "verify",
                    "reason": "TEST HARNESS approved the authored review gate after rechecking files/tests"})
                assert ipc("testDrive", "approve", "") == "ok"
                value = wait(lambda v: v["state"]["status"] == "completed" and not v["active"])
                state = value["state"]
                assert state["turns"] == 3 and state["session"] == report["session"]
                report.update(status=state["status"], completion=state["completion"],
                              history=state["history"], turns_after_reopen=state["turns"])
                assert original == {p.name: p.read_bytes() for p in project.glob("*.py")}
                workspace = Path(state["root"])
                assert (workspace / "test_calc.py").read_bytes() == original["test_calc.py"]
                tests = subprocess.run([sys.executable, "-m", "unittest", "-v"],
                                       cwd=workspace, capture_output=True, text=True)
                assert tests.returncode == 0, tests.stdout + tests.stderr
                report.update(original_unchanged=True, protected_tests_unchanged=True,
                              test_output=tests.stdout + tests.stderr)
                image = artifacts / "desktop-complete.png"
                ipc("capture", str(image))
                deadline = time.monotonic() + 10
                while json.loads(ipc("snapshot"))["capture"] != "saved":
                    assert time.monotonic() < deadline, "Completion capture failed"
                    time.sleep(.2)
                assert image.stat().st_size > 10000
            finally:
                if proc is not None and proc.poll() is None:
                    close()
    output = artifacts / "desktop-acceptance.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: real QML job, 3 turns, reopen without replay, tests pass. {output}", flush=True)


if __name__ == "__main__":
    run()
