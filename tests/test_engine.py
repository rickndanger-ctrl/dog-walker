import asyncio
from pathlib import Path
import sys
import yaml
import pytest
from dog_walker import storage
from dog_walker.storage import Store, git, digest, scrub
from dog_walker.workflow import load_workflow, WalkerError
from dog_walker.engine import Engine, run_checks
from dog_walker.judge import classify


def make_run(tmp_path, monkeypatch, steps=None, auto=True, in_place=True):
    monkeypatch.setattr(storage, "DATA", tmp_path / "data")
    project = tmp_path / "project"
    project.mkdir()
    (project / "protected.txt").write_text("keep me")
    git(project, "init", "-q")
    git(project, "add", ".")
    git(project, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-qm", "test")
    folder = tmp_path / "workflow"
    folder.mkdir()
    (folder / "prompt.md").write_text("do ${step_id}")
    (folder / "retry.md").write_text("fix ${failed_checks}")
    steps = steps or [{"id": "one", "prompt": "prompt.md", "retry_prompt": "retry.md", "checks": [{"type": "response_contains", "text": "done"}]}]
    (folder / "workflow.yaml").write_text(yaml.safe_dump({"version": 1, "name": "test", "steps": steps}))
    return Store.create(load_workflow(folder), project, auto, in_place)


def output(text="done", blocked=False):
    return {"status": "blocked" if blocked else "completed", "summary": text, "evidence": [], "files_changed": [], "blockers": ["missing input"] if blocked else []}


class FakeWorker:
    responses = []
    prompts = []
    def __init__(self, store, emit, no_start):
        self.store = store
    async def ready(self):
        pass
    async def turn(self, prompt, timeout):
        self.prompts.append(prompt)
        self.store.save(session="fixture-session")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, []


async def paused(*args):
    return "pause"


async def approved(*args):
    return "approve"


@pytest.fixture(autouse=True)
def reset_fake():
    FakeWorker.prompts = []
    FakeWorker.responses = []


async def test_retry_then_complete(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    FakeWorker.responses = [output("wrong"), output()]
    await Engine(store, lambda x: None, paused, worker_factory=FakeWorker).run()
    assert store.state["status"] == "completed"
    assert store.state["turns"] == 2
    assert "fix response_contains-1" in FakeWorker.prompts[1]


async def test_retry_exhaustion_stops_at_three_attempts(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    FakeWorker.responses = [output("wrong")] * 3
    await Engine(store, lambda x: None, paused, worker_factory=FakeWorker).run()
    assert store.state["status"] == "paused"
    assert store.state["turns"] == 3
    assert not store.state["history"]


async def test_resume_review_does_not_resend_completed_turn(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, auto=False)
    FakeWorker.responses = [output()]
    await Engine(store, lambda x: None, paused, worker_factory=FakeWorker).run()
    resumed = Store(store.path)
    await Engine(resumed, lambda x: None, approved, worker_factory=FakeWorker).run()
    assert resumed.state["status"] == "completed"
    assert len(FakeWorker.prompts) == 1


async def test_resume_rechecks_files_changed_while_paused(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, auto=False, steps=[{"id": "one", "prompt": "prompt.md", "checks": [{"type": "unchanged", "path": "protected.txt"}]}])
    FakeWorker.responses = [output()]
    await Engine(store, lambda x: None, paused, worker_factory=FakeWorker).run()
    (Path(store.state["root"]) / "protected.txt").write_text("changed while paused")
    resumed = Store(store.path)
    await Engine(resumed, lambda x: None, approved, worker_factory=FakeWorker).run()
    assert resumed.state["status"] == "paused"
    assert not resumed.state["evaluation"]["checks"][0]["pass"]
    assert len(FakeWorker.prompts) == 1


async def test_crash_requires_explicit_retry(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    FakeWorker.responses = [WalkerError("stream interrupted")]
    await Engine(store, lambda x: None, paused, worker_factory=FakeWorker).run()
    assert store.state["phase"] == "interrupted"
    resumed = Store(store.path)
    await Engine(resumed, lambda x: None, approved, worker_factory=FakeWorker).run()
    assert resumed.state["status"] == "paused"
    assert len(FakeWorker.prompts) == 1


async def test_blocked_stops_before_auto_retry(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    FakeWorker.responses = [output(blocked=True)]
    await Engine(store, lambda x: None, paused, worker_factory=FakeWorker).run()
    assert store.state["status"] == "paused"
    assert store.state["turns"] == 1


async def test_manual_approval_cannot_override_failed_test(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, auto=False, steps=[{"id": "one", "prompt": "prompt.md", "checks": [{"type": "command", "argv": [sys.executable, "-c", "raise SystemExit(1)"]}]}])
    FakeWorker.responses = [output()]
    await Engine(store, lambda x: None, approved, worker_factory=FakeWorker).run()
    assert store.state["status"] == "paused"


async def test_branch_and_skip_recorded(tmp_path, monkeypatch):
    steps = [{"id": "one", "prompt": "prompt.md", "max_retries": 0, "on_exhausted": "fallback", "checks": [{"type": "response_contains", "text": "done"}]}, {"id": "fallback", "prompt": "prompt.md", "checks": []}]
    store = make_run(tmp_path, monkeypatch, steps=steps)
    FakeWorker.responses = [output("wrong"), output()]
    async def skip(*args): return "skip"
    await Engine(store, lambda x: None, skip, worker_factory=FakeWorker).run()
    assert store.state["completion"] == "with_skips"
    assert store.state["history"][0]["outcome"] == "exhausted"
    assert store.state["history"][1]["outcome"] == "skipped"


async def test_global_turn_limit_handles_cycle(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, steps=[{"id": "one", "prompt": "prompt.md", "on_pass": "one", "checks": [{"type": "response_contains", "text": "done"}]}])
    engine = Engine(store, lambda x: None, paused, worker_factory=FakeWorker)
    engine.workflow.data["max_turns"] = 2
    FakeWorker.responses = [output(), output()]
    await engine.run()
    assert store.state["status"] == "paused"
    assert store.state["turns"] == 2


def test_isolated_worktree_and_snapshot(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, in_place=False)
    work = Path(store.state["root"])
    (work / "protected.txt").write_text("modified")
    assert (Path(store.state["original_root"]) / "protected.txt").read_text() == "keep me"
    (tmp_path / "workflow/prompt.md").write_text("changed later")
    assert (store.path / "workflow/prompt.md").read_text() == "do ${step_id}"


def test_run_lock(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    store.acquire()
    try:
        with pytest.raises(WalkerError, match="already open"):
            Store(store.path).acquire()
    finally:
        store.release()


def test_checks_detect_modified_protected_file_and_failed_command(tmp_path):
    p = tmp_path / "tests.py"
    p.write_text("original")
    hashes = {"tests.py": digest(p)}
    p.write_text("tampered")
    checks = [{"type": "unchanged", "path": "tests.py"}, {"type": "command", "argv": [sys.executable, "-c", "raise SystemExit(3)"]}]
    assert not any(r["pass"] for r in run_checks(checks, tmp_path, output(), [], hashes))


@pytest.mark.parametrize("value,decision", [(0.99, "pass"), (.01, "retry"), (.6, "review"), (float("nan"), "review")])
def test_typed_probability_and_abstention(value, decision):
    questions = {"ok": {"type": "noul", "instructions": "Completed?"}}
    assert classify(questions, {"answers": {"ok": {"noul": value}}})[0] == decision


def test_redaction():
    text = "Authorization: Bearer secret-value api_key=123456 sk-abcdefghijklmnopqr"
    redacted = scrub(text)
    assert "secret-value" not in redacted and "123456" not in redacted and "sk-" not in redacted
