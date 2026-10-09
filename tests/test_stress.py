"""Adversarial acceptance cases: bad workers must not become successful walks."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
import random
import pytest
import yaml
from dog_walker.engine import Engine, run_checks
from dog_walker.forms import compile_form, parse_form
from dog_walker.storage import Store, project_inventory, scope_check
from dog_walker.workflow import WalkerError
from dog_walker.workflow import load_workflow
from .test_engine import FakeWorker, make_run, output, paused, approved
from .test_desktop import app, wait_review
from .test_forms import form


async def test_approval_rechecks_changes_made_during_live_review(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, auto=False, steps=[{"id": "one", "prompt": "prompt.md", "checks": [{"type": "unchanged", "path": "protected.txt"}]}])
    FakeWorker.responses = [output()]
    async def tamper_then_approve(*args):
        (Path(store.state["root"]) / "protected.txt").write_text("tampered during review")
        return "approve"
    await Engine(store, lambda x: None, tamper_then_approve, worker_factory=FakeWorker).run()
    assert store.state["status"] == "paused" and store.state["history"] == []
    assert not store.state["evaluation"]["checks"][0]["pass"]
    assert store.state["turns"] == 1


async def test_cancelling_verification_kills_command_before_unlock(tmp_path, monkeypatch):
    started = tmp_path / "started"
    escaped = tmp_path / "should-never-be-written"
    code = f"from pathlib import Path; import time; Path({str(started)!r}).touch(); time.sleep(1); Path({str(escaped)!r}).touch()"
    store = make_run(tmp_path, monkeypatch, steps=[{"id": "one", "prompt": "prompt.md", "checks": [{"type": "command", "argv": [sys.executable, "-c", code]}]}])
    FakeWorker.responses = [output()]
    task = asyncio.create_task(Engine(store, lambda x: None, paused, worker_factory=FakeWorker).run())
    async with asyncio.timeout(5):
        while not started.exists():
            await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    reopened = Store(store.path)
    reopened.acquire()
    reopened.release()
    await asyncio.sleep(1.1)
    assert not escaped.exists(), "A cancelled verification command continued writing after unlock"
    assert reopened.state["status"] == "paused"


def test_verification_timeout_terminates_descendants(tmp_path):
    escaped = tmp_path / "descendant-wrote-after-timeout"
    child = f"import time; from pathlib import Path; time.sleep(1); Path({str(escaped)!r}).touch()"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(20)"
    started = time.monotonic()
    rows = run_checks([{"type": "command", "argv": [sys.executable, "-c", parent], "timeout": .2}], tmp_path, output(), [], {})
    assert not rows[0]["pass"] and time.monotonic() - started < 3
    time.sleep(1.1)
    assert not escaped.exists()


@pytest.mark.parametrize("mutation", ["edit", "delete", "new", "rename", "symlink"])
def test_allowlist_detects_every_persistent_out_of_scope_change(tmp_path, mutation):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    allowed = tmp_path / "allowed.txt"
    protected = tmp_path / "protected.txt"
    allowed.write_text("original"); protected.write_text("keep")
    baseline = project_inventory(tmp_path)
    allowed.write_text("intended edit")
    assert scope_check(tmp_path, ["allowed.txt"], baseline)["pass"]
    if mutation == "edit": protected.write_text("scope drift")
    elif mutation == "delete": protected.unlink()
    elif mutation == "new": (tmp_path / "unrelated.txt").write_text("scope drift")
    elif mutation == "rename": protected.rename(tmp_path / "renamed.txt")
    else: protected.unlink(); protected.symlink_to("allowed.txt")
    assert not scope_check(tmp_path, ["allowed.txt"], baseline)["pass"]


def test_allowlisted_file_cannot_be_replaced_by_outside_symlink(tmp_path):
    root = tmp_path / "project"; root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    target = root / "allowed.txt"; target.write_text("original")
    baseline = project_inventory(root)
    outside = tmp_path / "outside.txt"; outside.write_text("outside")
    target.unlink(); target.symlink_to(outside)
    assert not scope_check(root, ["allowed.txt"], baseline)["pass"]


@pytest.mark.parametrize("guard_first", [True, False])
def test_modified_protected_file_blocks_verification_execution(tmp_path, guard_first):
    marker = tmp_path / "should-not-run"
    guarded = tmp_path / "test.py"; guarded.write_text("changed")
    checks = [{"type": "unchanged", "path": "test.py"}, {"type": "command", "argv": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]}]
    if not guard_first: checks.reverse()
    rows = run_checks(checks, tmp_path, output(), [], {"test.py": "old-hash"})
    assert not marker.exists() and not any(r["pass"] for r in rows)


async def test_scope_drift_blocks_verification_execution(tmp_path, monkeypatch):
    marker = tmp_path / "should-not-run"
    store = make_run(tmp_path, monkeypatch, steps=[{"id": "one", "prompt": "prompt.md", "checks": [{"type": "command", "argv": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]}]}])
    store.save(allowed_changes=[], scope_hashes=project_inventory(Path(store.state["root"])))
    class DriftWorker(FakeWorker):
        async def turn(self, prompt, timeout):
            (Path(self.store.state["root"]) / "unrelated.txt").touch()
            return output(), []
    await Engine(store, lambda x: None, paused, worker_factory=DriftWorker).run()
    assert not marker.exists() and store.state["status"] == "paused"


async def test_worker_cannot_claim_away_scope_drift(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    store.save(allowed_changes=[], scope_hashes=project_inventory(Path(store.state["root"])))
    class DriftWorker(FakeWorker):
        async def turn(self, prompt, timeout):
            (Path(self.store.state["root"]) / "unrelated.txt").write_text("I widened the task")
            return output("done; all work completed perfectly"), []
    await Engine(store, lambda x: None, approved, worker_factory=DriftWorker).run()
    assert store.state["status"] == "paused" and not store.state["history"]
    assert any(c["id"] == "job-scope" and not c["pass"] for c in store.state["evaluation"]["checks"])


@pytest.mark.parametrize("semantic", [False, True])
async def test_scope_compliance_alone_is_not_completion_evidence(tmp_path, monkeypatch, semantic):
    questions = {"done": {"type": "noul", "instructions": "Is the task done?", "expected": True}} if semantic else {}
    store = make_run(tmp_path, monkeypatch, steps=[{"id": "one", "prompt": "prompt.md", "checks": [], "questions": questions}])
    store.save(allowed_changes=[], scope_hashes=project_inventory(Path(store.state["root"])))
    FakeWorker.responses = [output("Everything is done")]
    class PositiveJudge:
        def decide(self, *args):
            return {"answers": {"done": {"noul": 1.0}}}
    await Engine(store, lambda x: None, paused, worker_factory=FakeWorker, judge=PositiveJudge()).run()
    assert store.state["status"] == "paused" and not store.state["history"]
    assert store.state["evaluation"]["decision"] == "review"
    assert all(c["pass"] for c in store.state["evaluation"]["checks"])


async def test_stale_duplicate_and_wrong_run_approvals_are_rejected(app, tmp_path):
    project = tmp_path / "project"; project.mkdir(); (project / "done.txt").touch()
    value = form(); value["steps"][0]["approval"] = True
    await app.handle({"op": "import", "text": yaml.safe_dump(value)})
    FakeWorker.responses = [output()]
    await app.handle({"op": "start", "root": str(project), "in_place": True})
    await wait_review(app)
    run_id, token = app.store.state["id"], app.review_id
    for run, review in (("wrong-run", token), (run_id, "old-token"), (run_id, None)):
        result = await app.handle({"op": "control", "action": "approve", "run_id": run, "review_id": review})
        assert not result["ok"] and not app.review.done() and app.store.state["history"] == []
    command = {"op": "control", "action": "approve", "run_id": run_id, "review_id": token}
    assert (await app.handle(command))["ok"]
    assert not (await app.handle(command))["ok"]
    await app.task
    events = [json.loads(l) for l in (app.store.path / "events.jsonl").read_text().splitlines()]
    assert len([e for e in events if e["type"] == "review_decision"]) == 1


@pytest.mark.parametrize("kind", ["noul", "choice", "score"])
@pytest.mark.parametrize("broken", [{}, {"answers": {}}, {"answers": {"ok": {"noul": float("nan")}}}, {"answers": {"ok": {"confidence": 1}}}])
def test_missing_or_malformed_judge_answers_never_pass(kind, broken):
    from dog_walker.judge import classify
    question = {"type": kind, "instructions": "Did the actual work finish?", "expected": "yes", "minimum": 1, "criteria": {"yes": "Done", "no": "Not done"}}
    if kind == "noul": question["expected"] = True
    assert classify({"ok": question}, broken)[0] != "pass"


def test_deep_yaml_fails_cleanly():
    with pytest.raises(WalkerError):
        parse_form("a: " + "[" * 1500 + "0" + "]" * 1500)


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd"])
def test_form_allowlist_rejects_escape(tmp_path, monkeypatch, path):
    from dog_walker import forms
    monkeypatch.setattr(forms, "DATA", tmp_path)
    value = form(); value["allowed_changes"] = [path]
    with pytest.raises(WalkerError):
        compile_form(yaml.safe_dump(value))


@pytest.mark.parametrize("seed", range(50))
async def test_varied_workers_keep_building_or_stop_without_false_completion(tmp_path, monkeypatch, seed):
    """Every worker claims success; real files vary, so claims cannot advance it."""
    steps = [{"id": f"step{i}", "prompt": "prompt.md", "retry_prompt": "retry.md",
              "checks": [{"type": "file_contains", "path": f"result{i}.txt", "text": f"verified-{i}"}]} for i in range(3)]
    store = make_run(tmp_path, monkeypatch, steps=steps)
    root = Path(store.state["root"])
    store.save(allowed_changes=[f"result{i}.txt" for i in range(3)], scope_hashes=project_inventory(root))
    rng = random.Random(seed)
    correct = set()
    class VariedWorker(FakeWorker):
        async def turn(self, prompt, timeout):
            i = int(self.store.state["step"].removeprefix("step"))
            actual = rng.random() < .65
            (root / f"result{i}.txt").write_text(f"verified-{i}" if actual else "incorrect work")
            if actual: correct.add(i)
            else: correct.discard(i)
            self.store.save(session=f"fixture-{seed}")
            return output("done, successful, everything passes"), []
    await Engine(store, lambda x: None, paused, worker_factory=VariedWorker).run()
    assert 1 <= store.state["turns"] <= 9
    assert (root / "protected.txt").read_text() == "keep me"
    for finished in store.state["history"]:
        i = int(finished["step"].removeprefix("step"))
        assert i in correct and (root / f"result{i}.txt").read_text() == f"verified-{i}"
    if store.state["status"] == "completed":
        assert len(store.state["history"]) == 3 and correct == {0, 1, 2}
    else:
        assert store.state["status"] == "paused" and len(store.state["history"]) < 3
        assert store.state["evaluation"]["decision"] == "retry"


@pytest.mark.parametrize("target", [None, [], {}, True, 3])
def test_bad_workflow_transitions_fail_cleanly(tmp_path, monkeypatch, target):
    store = make_run(tmp_path, monkeypatch)
    source = store.path / "workflow/workflow.yaml"
    data = yaml.safe_load(source.read_text()); data["steps"][0]["on_pass"] = target
    source.write_text(yaml.safe_dump(data))
    with pytest.raises(WalkerError): load_workflow(source.parent)


def test_workflow_typo_cannot_silently_disable_a_turn_limit(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    source = store.path / "workflow/workflow.yaml"
    data = yaml.safe_load(source.read_text()); data["max_turn"] = 1
    source.write_text(yaml.safe_dump(data))
    with pytest.raises(WalkerError, match="Unknown workflow"): load_workflow(source.parent)


def test_settings_handle_bad_types_and_expand_home_paths():
    from dog_walker.settings import defaults, validate_settings
    with pytest.raises(WalkerError): validate_settings({**defaults(), "endpoint": 123})
    value = validate_settings({**defaults(), "model_path": "~/model.gguf", "catalog": "~/catalog.json", "start_command": ["~/launcher", "literal-$argument"]})
    assert value["model_path"] == str(Path.home() / "model.gguf")
    assert value["start_command"] == [str(Path.home() / "launcher"), "literal-$argument"]
