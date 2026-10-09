"""Opt-in real-model acceptance through the rendered QML app.

Requires an already-running compatible local server and the installed source
environment. Test-only IPC is injected into a temporary QML copy to invoke the
actual buttons. No job-starting test IPC is added to the installed app. This
test uses loopback inference; it does not isolate the host's external network.
"""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import http.client
import time


ROOT = Path(__file__).resolve().parents[1]


def run(recover=None, resume=None, phone=False):
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    data = Path(recover or resume).resolve() if recover or resume else Path(tempfile.mkdtemp(prefix="desktop-acceptance-", dir=artifacts))
    os.environ["DOG_WALKER_DATA"] = str(data)
    from dog_walker.cli import fixture
    from dog_walker.settings import load_settings
    from dog_walker.worker import model_ready
    recovered = None
    if recover or resume:
        from dog_walker.storage import Store
        from dog_walker.worker import parse_result
        paths = list((data / "runs").glob("*/state.json"))
        assert len(paths) == 1, "Recovery must name one test run's data directory"
        recovered = Store(paths[0].parent)
        s = recovered.state
        events = [json.loads(line) for line in (recovered.path / "events.jsonl").read_text().splitlines()]
        if recover:
            assert s["phase"] == "interrupted" and str(s.get("reason", "")).startswith("Worker result did not match StepResult")
            turn = [e["event"] for e in events if e["type"] == "codex" and e["turn"] == s["turns"]]
            assert any(e["type"] == "turn.completed" for e in turn), "Never recover an incomplete worker turn"
            result = parse_result((recovered.path / "turns" / f"{s['turns']:03d}" / "answer.json").read_text())
            commands = [e["item"] for e in turn if e["type"] == "item.completed" and e.get("item", {}).get("type") == "command_execution"]
            recovered.acquire()
            try:
                recovered.event("test_harness_result_recovery", reason="Reparsed a completed result with the updated strict envelope adapter; no worker commands replayed")
                recovered.save(result=result, commands=commands, phase="evaluating", status="paused", reason=None)
            finally:
                recovered.release()
        else:
            assert s["phase"] in {"reviewing", "evaluating"} and s["status"] == "paused"

    model_ready()  # Refuse a missing or mismatched server before starting.
    project = Path(recovered.state["original_root"]) if recovered else fixture()
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
              "test_harness_format_recovery": bool(recovered and any(e["type"] == "test_harness_result_recovery" for e in events)),
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
                review: app.review, review_id: app.reviewId, active: app.active, state: app.state})
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
                if recovered:
                    ipc("showWalk", recovered.state["id"])
                    wait(lambda v: v["state"] and v["state"]["id"] == recovered.state["id"])
                    assert ipc("testDrive", "resume", "") == "ok"
                else:
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
                first_review_id = value.get("review_id")
                assert state["step"] == "verify", state
                assert 3 <= state["turns"] <= 9 and len(state["history"]) == 2, state
                assert all(c["pass"] for c in state["evaluation"]["checks"]), state
                report.update(run_id=state["id"], turns_before_reopen=state["turns"],
                              session=state["session"], final_checks=state["evaluation"]["checks"])
                print(f"{state['turns']} turns finished; final review checks passed. Testing reopen.", flush=True)
                assert ipc("testDrive", "pause", "") == "ok"
                wait(lambda v: not v["active"] and v["state"]["status"] == "paused")
                close()
                proc = launch()
                wait(lambda v: v["connected"])
                ipc("showWalk", report["run_id"])
                wait(lambda v: v["state"] and v["state"]["id"] == report["run_id"])
                assert ipc("testDrive", "resume", "") == "ok"
                value = wait(lambda v: v["review"])
                assert value["state"]["turns"] == report["turns_before_reopen"], "Reopening replayed a completed turn"
                assert all(c["pass"] for c in value["state"]["evaluation"]["checks"])
                if phone:
                    from dog_walker.phone import server
                    from dog_walker.phone import ipc as phone_ipc
                    import secrets
                    config = {"origin": "https://test.tailtest.ts.net", "owner": "fixture@example.test"}
                    key = {"secret": secrets.token_hex(32), "pair_code": secrets.token_hex(6).upper()}
                    httpd = server(config, key, 0, data=data, secure=False,
                                   call=lambda method, *args: phone_ipc(method, *args, pid=proc.pid))
                    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
                    def request(path, body=None, cookie="", csrf=""):
                        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=15)
                        headers = {"Host": "test.tailtest.ts.net", "Origin": config["origin"],
                            "Tailscale-User-Login": config["owner"], "Content-Type": "application/json",
                            "Cookie": cookie, "X-Dogwalker-CSRF": csrf}
                        connection.request("POST" if body is not None else "GET", path,
                                           json.dumps(body) if body is not None else None, headers)
                        response = connection.getresponse(); result = json.loads(response.read())
                        status, cookies = response.status, response.getheader("Set-Cookie", "")
                        connection.close(); return status, result, cookies
                    try:
                        status, _, cookie = request("/api/pair", {"code": key["pair_code"]})
                        assert status == 200
                        cookie = cookie.split(";")[0]
                        status, snapshot, _ = request("/api/state", cookie=cookie)
                        assert status == 200
                        token = snapshot["current"]["review_id"]
                        assert token and token != first_review_id, "A reopened review must have a fresh approval token"
                        command = {"action": "approve", "run_id": state["id"], "review_id": first_review_id}
                        assert request("/api/control", command, cookie, snapshot["csrf"])[0] == 409
                        command["review_id"] = token
                        assert request("/api/control", command, cookie, snapshot["csrf"])[0] == 200
                        assert request("/api/control", command, cookie, snapshot["csrf"])[0] == 409
                        report.update(phone_http_approval=True, stale_phone_approval_rejected=True, duplicate_phone_approval_rejected=True)
                    finally:
                        httpd.shutdown(); httpd.server_close(); thread.join(3)
                    report["scripted_approvals"].append({"step": "verify", "reason": "TEST HARNESS paired phone HTTP client approved the exact reopened review after verified checks; stale and duplicate decisions were rejected"})
                else:
                    report["scripted_approvals"].append({"step": "verify",
                        "reason": "TEST HARNESS approved the authored review gate after rechecking files/tests"})
                    assert ipc("testDrive", "approve", "") == "ok"
                value = wait(lambda v: v["state"]["status"] == "completed" and not v["active"])
                state = value["state"]
                assert state["turns"] == report["turns_before_reopen"] and state["session"] == report["session"]
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
    print(f"PASS: real QML job, {report['turns_after_reopen']} turns, reopen without replay, tests pass. {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recover-format", help="Test-only recovery of a completed malformed-envelope result in a prior harness data directory")
    parser.add_argument("--resume-data", help="Continue a paused harness review without replaying model turns")
    parser.add_argument("--phone", action="store_true", help="Approve final review through the paired phone HTTP server and real desktop IPC")
    args = parser.parse_args()
    run(args.recover_format, args.resume_data, args.phone)
