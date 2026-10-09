"""Run with unshare -Urn: local model, judge and coding tools have no external network."""
import importlib.util
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from dog_walker.storage import DATA, APP_ROOT, atomic_json, Store
from dog_walker.cli import main


def run(resume=None, form=False):
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    network = subprocess.run(["ip", "-json", "route"], check=True, capture_output=True, text=True).stdout
    assert json.loads(network) == [], "Offline test must have no external routes"
    sock = socket.socket()
    sock.settimeout(1)
    try:
        sock.connect(("1.1.1.1", 443))
        raise AssertionError("External networking was unexpectedly available")
    except OSError:
        pass
    finally:
        sock.close()
    artifact = APP_ROOT / "artifacts"
    artifact.mkdir(exist_ok=True)
    runtime_path = Path(os.environ.get("DOG_WALKER_TEST_RUNTIME", Path.home() / "opt/local-model-runtime/launcher.py"))
    if not runtime_path.is_file():
        raise RuntimeError("This machine-specific real-model test requires DOG_WALKER_TEST_RUNTIME pointing to a local runtime launcher exposing build_plan('ornith').")
    spec = importlib.util.spec_from_file_location("local_runtime", runtime_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = module.build_plan("ornith")
    env = {k: v for k, v in os.environ.items() if k not in module.LLAMA_ENV_NAMES}
    env.update(plan["environment"])
    with (artifact / "offline-model.log").open("w") as handle:
        server = subprocess.Popen(plan["server_argv"], env=env, stdout=handle, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 600
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while True:
                try:
                    with opener.open(plan["url"] + "/props", timeout=2) as response:
                        props = json.load(response)
                    if props.get("model_path") == plan["model_path"]:
                        break
                except Exception:
                    pass
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Offline model did not start; see artifacts/offline-model.log")
                time.sleep(2)
            print("External routes: none. Ornith loaded inside the offline network namespace.", flush=True)
            scripted_approvals = []
            if form:
                from dog_walker.desktop import Desktop
                from dog_walker.engine import Engine
                from dog_walker.cli import fixture
                def engine(store, emit, ask):
                    return Engine(store, emit, ask, no_start=True)
                def output(event):
                    if event["type"] in {"log", "error"}:
                        print(event.get("text") or event.get("message"), flush=True)
                bridge = Desktop(output, engine)
                async def desktop_job():
                    await bridge.command({"op": "import", "text": (APP_ROOT / "examples/discount.dogwalk").read_text()})
                    assert bridge.store is None, "Import must be inert"
                    await bridge.command({"op": "start", "root": str(fixture()), "auto": True, "in_place": False})
                    async with asyncio.timeout(1200):
                        while not bridge.task.done():
                            if bridge.review and not bridge.review.done():
                                evaluation = bridge.store.state.get("evaluation") or {}
                                if bridge.store.state["step"] == "verify" and evaluation.get("checks") and all(c["pass"] for c in evaluation["checks"]):
                                    scripted_approvals.append({"step": "verify", "reason": "TEST HARNESS explicitly approved the authored final review gate after all checks passed"})
                                    await bridge.command({"op": "control", "action": "approve", "run_id": bridge.store.state["id"], "review_id": bridge.review_id})
                                else:
                                    await bridge.command({"op": "control", "action": "pause", "run_id": bridge.store.state["id"]})
                                    break
                            await asyncio.sleep(.1)
                    await bridge.task
                asyncio.run(desktop_job())
                store = bridge.store
                code = 0 if store.state["status"] == "completed" else 2
            elif resume:
                from dog_walker.engine import Engine
                store = Store.open(resume)
                before_turns = store.state["turns"]
                async def accept_verified_summary(reason, passed):
                    evaluation = store.state.get("evaluation") or {}
                    # This is a test-harness approval, explicitly recorded; it is never used by the app.
                    if store.state["step"] == "summary" and evaluation.get("checks") and all(c["pass"] for c in evaluation["checks"]):
                        scripted_approvals.append({"step": "summary", "reason": reason})
                        return "approve"
                    return "pause"
                asyncio.run(Engine(store, lambda x: print(x, flush=True), accept_verified_summary, no_start=True).run())
                assert store.state["turns"] == before_turns, "Reviewed final turn must not be replayed"
                code = 0 if store.state["status"] == "completed" else 2
            else:
                code = main(["demo", "--auto", "--plain", "--no-start", "--offline"])
            latest = max((DATA / "runs").glob("*/state.json"), key=lambda p: p.stat().st_mtime)
            state = store.state if form or resume else json.loads(latest.read_text())
            report = {"external_routes": [], "outbound_connect_blocked": True,
                      "run_id": state["id"], "status": state["status"], "completion": state.get("completion"),
                      "history": state["history"], "reason": state.get("reason"),
                      "workspace": state["root"], "judge": state.get("evaluation"), "exit_code": code}
            report["scripted_approvals"] = scripted_approvals
            atomic_json(artifact / ("offline-form-acceptance.json" if form else "offline-resume-acceptance.json" if resume else "offline-acceptance.json"), report)
            assert "return price - percent" in (Path(state["original_root"]) / "calc.py").read_text()
            tests = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=state["root"], capture_output=True, text=True)
            print(tests.stdout + tests.stderr, flush=True)
            if code == 0:
                assert tests.returncode == 0
                assert len(state["history"]) == (3 if form else 5)
                assert all(h["outcome"] in {"passed", "accepted_manually"} for h in state["history"])
            return code
        finally:
            server.terminate()
            try:
                server.wait(15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume")
    parser.add_argument("--form", action="store_true", help="Test completed-form import and the desktop bridge against the real isolated model")
    args = parser.parse_args()
    raise SystemExit(run(args.resume, args.form))
