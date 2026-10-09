import asyncio
import json
import sys
import pytest
from dog_walker.worker import CodexWorker, parse_result
from jsonschema import ValidationError
from dog_walker.workflow import WalkerError
from .test_engine import make_run, output


def test_single_fenced_result_keeps_strict_schema():
    value = output()
    body = json.dumps(value)
    assert parse_result(body) == value
    assert parse_result("Here is the result:\n\n```json\n" + body + "\n```\n") == value
    with pytest.raises(ValidationError):
        parse_result('```json\n{"status":"completed"}\n```')


@pytest.mark.parametrize("text", [
    'Here is an object: {"status":"completed"}',
    '```json\n{"status":"completed"}\n',
    '```json\nnot JSON\n```',
    '```json\n{}\n```\n```json\n{}\n```',
])
def test_ambiguous_or_incomplete_result_is_rejected(text):
    with pytest.raises(json.JSONDecodeError):
        parse_result(text)


def executable(tmp_path, monkeypatch, mode):
    path = tmp_path / "fake-codex"
    result = json.dumps(output())
    source = f'''#!{sys.executable}
import json,sys,time
args=sys.argv
prompt=sys.stdin.read()
print(json.dumps({{"type":"thread.started","thread_id":"fixture-session"}}),flush=True)
if {mode!r} == 'malformed':
 print('NOT JSON',flush=True)
elif {mode!r} == 'timeout':
 time.sleep(30)
else:
 print(json.dumps({{"type":"turn.started"}}),flush=True)
 print(json.dumps({{"type":"item.completed","item":{{"type":"command_execution","command":"python -m unittest","exit_code":0,"aggregated_output":"3 tests passed"}}}}),flush=True)
 print(json.dumps({{"type":"item.completed","item":{{"type":"agent_message","text":{result!r}}}}}),flush=True)
 if {mode!r} != 'truncated':
  print(json.dumps({{"type":"turn.completed","usage":{{}}}}),flush=True)
'''
    path.write_text(source)
    path.chmod(0o700)
    monkeypatch.setattr("dog_walker.worker.shutil.which", lambda cmd: str(path))
    return path


async def test_jsonl_and_resume_id(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    executable(tmp_path, monkeypatch, "good")
    store.save(turns=1)
    worker = CodexWorker(store, lambda x: None, no_start=True)
    result, commands = await worker.turn("do it", 10)
    assert result["status"] == "completed"
    assert store.state["session"] == "fixture-session"
    assert commands[0]["exit_code"] == 0
    store.save(turns=2)
    await worker.turn("next", 10)
    events = [json.loads(x) for x in (store.path / "events.jsonl").read_text().splitlines()]
    assert [e["prompt"] for e in events if e["type"] == "prompt"] == ["do it", "next"]


async def test_truncated_turn_is_not_completed(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    executable(tmp_path, monkeypatch, "truncated")
    store.save(turns=1)
    with pytest.raises(WalkerError, match="Incomplete"):
        await CodexWorker(store, lambda x: None, True).turn("do it", 10)


async def test_timeout_terminates_child(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    executable(tmp_path, monkeypatch, "timeout")
    store.save(turns=1)
    worker = CodexWorker(store, lambda x: None, True)
    with pytest.raises(WalkerError, match="exceeded"):
        await worker.turn("do it", .1)
    assert worker.proc.returncode is not None


async def test_malformed_event_terminates_child(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    executable(tmp_path, monkeypatch, "malformed")
    store.save(turns=1)
    worker = CodexWorker(store, lambda x: None, True)
    with pytest.raises(ExceptionGroup):
        await worker.turn("do it", 10)
    assert worker.proc.returncode is not None
