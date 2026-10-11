import asyncio
import json
import sys
import threading
import pytest
from dog_walker.worker import CodexWorker, parse_result
from jsonschema import ValidationError
from dog_walker.workflow import WalkerError
from .test_engine import make_run, output
import dog_walker.worker as worker_module
import dog_walker.runtime as runtime_module


async def test_plugin_transport_is_temporary_and_closes_on_failure(tmp_path, monkeypatch):
    import dog_walker.plugins as plugins
    import dog_walker.transport as transport
    store = make_run(tmp_path, monkeypatch)
    monkeypatch.setattr(plugins, 'freeze_plugins', lambda _store: [{'id': 'project'}])
    lifecycle = []

    class Bridge:
        endpoint = 'http://127.0.0.1:18099/v1'
        def __init__(self, endpoint):
            assert endpoint == worker_module.ENDPOINT
        def __enter__(self):
            lifecycle.append('open')
            return self
        def __exit__(self, *_args):
            lifecycle.append('close')

    monkeypatch.setattr(transport, 'ResponsesBridge', Bridge)
    worker = CodexWorker(store, lambda _line: None)
    async def fail(prompt, timeout, transport_endpoint):
        assert transport_endpoint == Bridge.endpoint
        raise WalkerError('fixture failure')
    monkeypatch.setattr(worker, '_turn', fail)
    with pytest.raises(WalkerError, match='fixture failure'):
        await worker.turn('task', 10)
    assert lifecycle == ['open', 'close']
    assert worker_module.ENDPOINT != Bridge.endpoint


def test_single_fenced_result_keeps_strict_schema():
    value = output()
    body = json.dumps(value)
    assert parse_result(body) == value
    assert parse_result("Here is the result:\n\n```json\n" + body + "\n```\n") == value
    assert parse_result("Result:\n```json\n" + body + "\n</parameter>\n</function>\n</tool_call>") == value
    with pytest.raises(ValidationError):
        parse_result('```json\n{"status":"completed"}\n```')


@pytest.mark.parametrize("text", [
    'Here is an object: {"status":"completed"}',
    '```json\n{"status":"completed"}\n',
    '```json\nnot JSON\n```',
    '```json\n{}\n```\n```json\n{}\n```',
])
def test_ambiguous_or_incomplete_result_is_rejected(text):
    with pytest.raises((json.JSONDecodeError, ValidationError)):
        parse_result(text)


def test_fenced_result_does_not_accept_truncated_json_or_extra_text():
    body = json.dumps(output())
    for text in ("```json\n" + body[:-1], "```json\n" + body + "\nactually failed", "```json\n" + body + "\n" + body):
        with pytest.raises(json.JSONDecodeError):
            parse_result(text)


def test_plan_followed_by_standalone_result():
    value = output()
    body = json.dumps(value)
    assert parse_result("Read the brief. No edits. Plan awaiting approval.\n\n" + body) == value
    assert parse_result("Plan:\n\n  " + json.dumps(value, indent=2) + "\n") == value
    with pytest.raises(ValidationError):
        parse_result('Plan:\n\n{"status":"completed"}')


def test_evidence_allows_a_detailed_sentence_but_remains_bounded():
    value = output()
    value["evidence"] = ["Read the API references. " * 12]
    assert parse_result(json.dumps(value)) == value
    value["evidence"] = ["x" * 501]
    with pytest.raises(ValidationError):
        parse_result(json.dumps(value))


def test_worker_environment_filters_credentials_and_config_never_serializes_them(tmp_path, monkeypatch):
    secret_values = {
        "OPENAI_API_KEY": "openai-key-secret",
        "ALLOWED_TOKEN": "allowed-token-secret",
        "OTHER_TOKEN": "other-token-secret",
        "HTTP_PROXY": "http://proxy-user:proxy-pass@proxy.invalid",
        "https_proxy": "http://proxy-user:proxy-pass@proxy.invalid",
        "ALL_PROXY": "socks5://proxy.invalid",
        "SSH_AUTH_SOCK": "/tmp/private-agent.sock",
        "GIT_ASKPASS": "/tmp/private-askpass",
        "SSH_ASKPASS": "/tmp/private-ssh-askpass",
        "PATH": "/usr/bin:/bin",
    }
    for key, value in secret_values.items():
        monkeypatch.setenv(key, value)

    default = worker_module.environment(home=tmp_path / "default-home")
    for key in ("OPENAI_API_KEY", "ALLOWED_TOKEN", "OTHER_TOKEN", "HTTP_PROXY", "https_proxy",
                "ALL_PROXY", "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS"):
        assert key not in default
    assert default["PATH"] == "/usr/bin:/bin"

    explicitly_allowed = worker_module.environment(
        home=tmp_path / "allowed-home", allowed_env=("OPENAI_API_KEY", "ALLOWED_TOKEN", "OTHER_TOKEN"))
    assert explicitly_allowed["OPENAI_API_KEY"] == secret_values["OPENAI_API_KEY"]
    assert explicitly_allowed["ALLOWED_TOKEN"] == secret_values["ALLOWED_TOKEN"]
    assert explicitly_allowed["OTHER_TOKEN"] == secret_values["OTHER_TOKEN"]
    for key in ("HTTP_PROXY", "https_proxy", "ALL_PROXY", "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS"):
        assert key not in explicitly_allowed

    config_home = tmp_path / "codex-home"
    worker_module.configure(config_home)
    config = (config_home / "config.toml").read_text()
    for key, value in secret_values.items():
        if key != "PATH":
            if key != "SSH_AUTH_SOCK":
                assert key not in config
            assert value not in config


@pytest.mark.parametrize("suffix", ["\nActually failed", "\n{}", "\n```", "\nnull"])
def test_standalone_result_rejects_ambiguous_tail(suffix):
    with pytest.raises(json.JSONDecodeError):
        parse_result("Plan:\n\n" + json.dumps(output()) + suffix)


def test_standalone_result_does_not_choose_between_objects():
    body = json.dumps(output())
    for text in ("Plan:\n{}\n\n" + body, "Plan: " + body, "Plan:\n" + body[:-1]):
        with pytest.raises(json.JSONDecodeError):
            parse_result(text)


def executable(tmp_path, monkeypatch, mode):
    path = tmp_path / "fake-codex"
    value = output()
    if mode == 'bad_result':
        value.pop('evidence')
    if mode == 'missing_blockers':
        value.pop('blockers')
    result = json.dumps(value)
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
    assert [e["prompt"] for e in events if e["type"] == "prompt"] == [
        "do it" + worker_module.result_contract(), "next" + worker_module.result_contract()]


async def test_invalid_completion_is_concise_and_does_not_replay_worker(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    executable(tmp_path, monkeypatch, 'bad_result')
    store.save(turns=1)
    with pytest.raises(WalkerError) as error:
        await CodexWorker(store, lambda x: None, True).turn('do it', 10)
    assert "'evidence' is a required property" in str(error.value)
    assert 'Failed validating' not in str(error.value)
    assert len(str(error.value)) < 600
    events = [json.loads(x) for x in (store.path / 'events.jsonl').read_text().splitlines()]
    assert len([e for e in events if e['type'] == 'prompt']) == 1
    assert not any(e['type'] == 'worker_result' for e in events)


def test_completion_contract_has_valid_example_and_exact_schema():
    contract = worker_module.result_contract()
    example, schema = contract.split('Valid structural example: ', 1)[1].split('\nExact completion JSON schema: ')
    assert parse_result(example)['status'] == 'blocked'
    assert json.loads(schema) == worker_module.SCHEMA


async def test_completed_report_empty_blockers_metadata_is_normalized_without_replay(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch)
    executable(tmp_path, monkeypatch, 'missing_blockers')
    store.save(turns=1)
    result, commands = await CodexWorker(store, lambda x: None, True).turn('do it', 10)
    assert result == output() and commands[0]['exit_code'] == 0
    events = [json.loads(x) for x in (store.path / 'events.jsonl').read_text().splitlines()]
    assert len([e for e in events if e['type'] == 'prompt']) == 1
    assert len([e for e in events if e['type'] == 'completion_normalized']) == 1
    assert len([e for e in events if e['type'] == 'worker_result']) == 1


@pytest.mark.parametrize('missing', ['status', 'summary', 'evidence', 'files_changed'])
def test_completion_normalization_never_fills_work_claims(missing):
    value = output()
    value.pop(missing)
    with pytest.raises(ValidationError):
        worker_module.parse_completion(json.dumps(value))


def test_completion_normalization_rejects_blocked_missing_blockers_and_invalid_claims():
    value = output()
    value.pop('blockers')
    value['status'] = 'blocked'
    with pytest.raises(ValidationError):
        worker_module.parse_completion(json.dumps(value))
    value['status'] = 'completed'
    value['evidence'] = ['x' * 501]
    with pytest.raises(ValidationError):
        worker_module.parse_completion(json.dumps(value))
    value['evidence'] = []
    value['commands'] = ['not an allowed field']
    with pytest.raises(ValidationError):
        worker_module.parse_completion(json.dumps(value))


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


async def test_ready_waits_for_runtime_identity_and_health_check(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_module.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(worker_module, "configure", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(worker_module, "MODEL_PATH", str(tmp_path / "model.gguf"))
    monkeypatch.setattr(worker_module, "ENDPOINT", "http://127.0.0.1:18081/v1")
    calls = []

    def ready_check(model_path, endpoint, emit):
        calls.append((model_path, endpoint, threading.current_thread().name))
        return {"ready": True, "fully_loaded": True, "reason": "healthy"}

    monkeypatch.setattr(runtime_module, "verify_runtime", ready_check)
    worker = CodexWorker(None, lambda _message: None, no_start=True, home=tmp_path)
    await worker.ready()
    assert calls[0][:2] == (str(tmp_path / "model.gguf"), "http://127.0.0.1:18081/v1")
    assert calls[0][2] != "MainThread"
    assert worker.readiness["fully_loaded"] is True


async def test_ready_blocks_turn_start_when_runtime_is_not_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_module.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(worker_module, "configure", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(runtime_module, "verify_runtime", lambda *_args: {
        "ready": False, "fully_loaded": False, "reason": "model server is still loading",
    })
    worker = CodexWorker(None, lambda _message: None, no_start=True, home=tmp_path)
    with pytest.raises(WalkerError, match="still loading"):
        await worker.ready()
