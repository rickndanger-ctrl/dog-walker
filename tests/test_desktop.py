import asyncio
import json
import os
from pathlib import Path
import sys
import pytest
import yaml
from dog_walker import desktop, storage, forms
from dog_walker.desktop import Desktop, local_path
from dog_walker.engine import Engine
from dog_walker.workflow import WalkerError
from .test_forms import form
from .test_engine import FakeWorker, output


@pytest.fixture
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for module in (desktop, storage, forms):
        monkeypatch.setattr(module, "DATA", data)
    monkeypatch.setenv("DOG_WALKER_INBOX", str(tmp_path / "Inbox"))
    events = []
    def factory(store, emit, ask):
        return Engine(store, emit, ask, worker_factory=FakeWorker)
    bridge = Desktop(events.append, factory)
    bridge.events = events
    FakeWorker.responses = []
    FakeWorker.prompts = []
    return bridge


async def wait_review(app):
    async with asyncio.timeout(3):
        while app.review is None:
            await asyncio.sleep(.01)


async def test_import_is_preview_only_and_fails_without_execution(app):
    await app.handle({"op": "import", "text": yaml.safe_dump(form())})
    assert app.events[-1]["type"] == "job"
    assert app.store is None and app.task is None and not FakeWorker.prompts
    previous = app.workflow
    await app.handle({"op": "import", "text": "broken: data"})
    assert app.events[-1]["type"] == "error"
    assert app.workflow is previous and not FakeWorker.prompts


async def test_start_review_approve_completes_and_records_manual_acceptance(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "done.txt").write_text("done")
    value = form()
    value["steps"][0]["approval"] = True
    value["steps"][0]["checks"] = []
    await app.handle({"op": "import", "text": yaml.safe_dump(value)})
    FakeWorker.responses = [output()]
    await app.handle({"op": "start", "root": str(project), "in_place": True, "auto": True})
    await wait_review(app)
    assert any(e["type"] == "state" and e["needs_review"] for e in app.events)
    await app.handle({"op": "control", "action": "approve"})
    await app.task
    assert app.store.state["completion"] == "with_manual_acceptance"
    assert app.lease is None


async def test_pause_resume_does_not_duplicate_completed_worker_turn(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "done.txt").write_text("done")
    value = form()
    value["steps"][0]["approval"] = True
    await app.handle({"op": "import", "text": yaml.safe_dump(value)})
    FakeWorker.responses = [output()]
    await app.handle({"op": "start", "root": str(project), "in_place": True})
    await wait_review(app)
    await app.handle({"op": "control", "action": "pause"})
    assert app.store.state["status"] == "paused"
    await app.handle({"op": "resume"})
    await wait_review(app)
    await app.handle({"op": "control", "action": "approve"})
    await app.task
    assert app.store.state["turns"] == 1
    assert len(FakeWorker.prompts) == 1


async def test_locked_run_is_observation_only(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    await app.handle({"op": "import", "text": yaml.safe_dump(form())})
    other = storage.Store.create(app.workflow, project, in_place=True)
    other.acquire()
    before = (other.path / "state.json").read_text()
    try:
        await app.handle({"op": "load", "id": other.state["id"]})
        assert any(e.get("external") for e in app.events if e["type"] == "state")
        await app.handle({"op": "resume"})
        assert app.events[-1]["type"] == "error"
        assert (other.path / "state.json").read_text() == before
        assert app.lease is None
    finally:
        other.release()


async def test_failed_check_cannot_be_approved(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    value = form()
    value["steps"][0].pop("retry_prompt")
    await app.handle({"op": "import", "text": yaml.safe_dump(value)})
    FakeWorker.responses = [output()]
    await app.handle({"op": "start", "root": str(project), "in_place": True})
    await wait_review(app)
    await app.handle({"op": "control", "action": "approve"})
    assert app.events[-1]["type"] == "error"
    assert app.store.state["history"] == []
    await app.pause()


def test_local_urls_only():
    assert local_path("file:///tmp/a%20b") == Path("/tmp/a b")
    for value in ("https://example.org/job", "file://elsewhere/file", None):
        with pytest.raises(WalkerError):
            local_path(value)


async def test_real_pipe_protocol_eof_shutdown(tmp_path):
    env = {**os.environ, "DOG_WALKER_DATA": str(tmp_path / "data"), "DOG_WALKER_INBOX": str(tmp_path / "Inbox")}
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "dog_walker.desktop", env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    commands = [{"op": "hello"}, {"op": "import", "text": yaml.safe_dump(form())}, {"op": "shutdown"}]
    stdout, stderr = await asyncio.wait_for(proc.communicate("".join(json.dumps(c) + "\n" for c in commands).encode()), 10)
    events = [json.loads(line) for line in stdout.splitlines()]
    assert proc.returncode == 0, stderr.decode()
    assert [e["type"] for e in events][:3] == ["hello", "library", "job"]
    assert not (tmp_path / "data/runs").exists()


def test_settings_reject_cloud_endpoints():
    from dog_walker.settings import defaults, validate_settings
    for endpoint in ("https://api.openai.com/v1", "http://127.0.0.1.evil.com/v1", "http://user:pass@localhost/v1"):
        with pytest.raises(WalkerError):
            validate_settings({**defaults(), "endpoint": endpoint})
