import importlib.util
import io
import json
from pathlib import Path
import stat
import urllib.error
import urllib.request

import pytest

from dog_walker import jev


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        if self.error:
            raise self.error
        return self.response


def config_path(tmp_path, *, enabled=True, key="secret-test-key"):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    path = directory / "jev.json"
    jev.save_config({"api_key": key, "enabled": enabled}, path)
    return path


def make_judge(tmp_path, opener, *, enabled=True, timeout=5):
    path = config_path(tmp_path, enabled=enabled)
    return jev.JevJudge(path, opener=opener, timeout=timeout), path


def test_judge_pins_https_request_wire_and_filters_usage(tmp_path):
    response = {"answers": {"route": {"choice": "none", "probabilities": {"none": 0.9, "project_map": 0.1}}},
                "usage": {"input_tokens": 37, "prompt_tokens": 38, "output_tokens": 3, "private": "drop"}}
    opener = FakeOpener(FakeResponse(json.dumps(response).encode()))
    judge, _ = make_judge(tmp_path, opener)
    state = {"task_data": "public toy"}
    questions = {"route": {"type": "choice", "instructions": "choose", "criteria": {"none": "skip", "project_map": "map"},
                           "expected": "none", "threshold": 0.85}}

    result = judge.decide(state, questions)

    assert opener.request.full_url == jev.ENDPOINT
    assert opener.request.get_method() == "POST"
    assert opener.request.get_header("Authorization") == "Bearer secret-test-key"
    assert opener.request.get_header("Content-type") == "application/json"
    assert opener.timeout == 5
    payload = json.loads(opener.request.data)
    assert payload == {"model": "jev-1.13.0", "state": state,
                       "questions": {"route": {"type": "choice", "instructions": "choose",
                                                "criteria": {"none": "skip", "project_map": "map"}}}}
    assert result["answers"] == response["answers"]
    assert result["usage"] == {"input_tokens": 37, "prompt_tokens": 38, "output_tokens": 3}
    assert "private" not in json.dumps(result)


def test_production_opener_disables_proxies_and_redirects(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:9999")
    monkeypatch.setenv("https_proxy", "http://proxy.invalid:9999")
    opener = jev._build_opener()
    redirects = [handler for handler in opener.handlers if isinstance(handler, jev._NoRedirect)]
    # An empty ProxyHandler contributes no protocol handlers; the opener does
    # not fall back to urllib's environment proxy handler.
    assert not any(isinstance(handler, urllib.request.ProxyHandler) for handler in opener.handlers)
    assert len(redirects) == 1
    request = urllib.request.Request(jev.ENDPOINT)
    assert redirects[0].redirect_request(request, None, 302, "Found", {}, "https://other.invalid/") is None


def test_key_alone_is_disabled_and_enable_is_required(tmp_path):
    path = config_path(tmp_path, enabled=False)
    assert jev.is_enabled(path) is False
    with pytest.raises(jev.JevError, match="disabled"):
        jev.JevJudge(path, opener=FakeOpener())
    jev.save_config({"api_key": "secret-test-key", "enabled": True}, path, replace=True)
    assert jev.is_enabled(path) is True


def test_environment_key_still_requires_explicit_enabled_config(tmp_path, monkeypatch):
    path = config_path(tmp_path, enabled=False, key="")
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-secret")
    assert jev.is_enabled(path) is False
    with pytest.raises(jev.JevError, match="disabled"):
        jev.JevJudge(path, opener=FakeOpener())
    jev.save_config({"api_key": "", "enabled": True}, path, replace=True)
    assert jev.is_enabled(path) is True
    opener = FakeOpener(FakeResponse(b'{"answers":{}}'))
    judge = jev.JevJudge(path, opener=opener)
    judge.decide({}, {})
    assert opener.request.get_header("Authorization") == "Bearer environment-secret"


def test_disabled_config_works_only_in_explicit_test_mode(tmp_path):
    path = config_path(tmp_path, enabled=False)
    opener = FakeOpener(FakeResponse(b'{"answers":{}}'))
    with pytest.raises(jev.JevError, match="disabled"):
        jev.JevJudge(path, opener=opener)
    test_judge = jev.JevJudge(path, opener=opener, test_only=True)
    assert test_judge.decide({}, {}) == {"answers": {}}
    assert opener.request.full_url == jev.ENDPOINT


def test_test_only_mode_still_requires_a_key(tmp_path):
    path = config_path(tmp_path, enabled=False, key="")
    assert jev.has_key(path) is False
    with pytest.raises(jev.JevError, match="no API key"):
        jev.JevJudge(path, opener=FakeOpener(), test_only=True)


def test_constructor_config_failure_is_sanitized(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    path = directory / "jev.json"
    path.write_text('{"api_key":"secret-test-key"')
    path.chmod(0o600)
    with pytest.raises(jev.JevError) as caught:
        jev.JevJudge(path)
    assert "secret-test-key" not in str(caught.value)


def test_config_is_atomic_private_and_refuses_implicit_overwrite(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    path = directory / "jev.json"
    jev.save_config({"api_key": "secret-test-key", "enabled": False}, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert jev.load_config(path) == {"api_key": "secret-test-key", "enabled": False}
    with pytest.raises(jev.JevError, match="already exists"):
        jev.save_config({"api_key": "replacement", "enabled": False}, path)


def test_config_rejects_symlinks_and_unsafe_permissions(tmp_path):
    path = config_path(tmp_path)
    path.chmod(0o640)
    with pytest.raises(jev.JevError, match="permissions"):
        jev.load_config(path)
    path.chmod(0o600)
    alias = path.with_name("alias.json")
    alias.symlink_to(path)
    with pytest.raises(jev.JevError, match="symlink"):
        jev.load_config(alias)


@pytest.mark.parametrize("error, expected", [
    (RuntimeError("client leaked secret-test-key and private task"), "Jev request failed"),
    (urllib.error.HTTPError(jev.ENDPOINT, 401, "unauthorized secret-test-key", {}, io.BytesIO(b"private body")),
     "HTTP status 401"),
])
def test_request_errors_are_sanitized(tmp_path, error, expected):
    opener = FakeOpener(error=error)
    judge, _ = make_judge(tmp_path, opener)
    with pytest.raises(jev.JevError) as caught:
        judge.decide({"task_data": "private task"}, {"route": {"type": "choice", "criteria": {"none": "skip"}}})
    assert expected in str(caught.value)
    assert "secret-test-key" not in str(caught.value)
    assert "private body" not in str(caught.value)
    assert "private task" not in str(caught.value)


@pytest.mark.parametrize("body, message", [
    (b"x" * (jev.MAX_RESPONSE_BYTES + 1), "64 KiB"),
    (b"not json", "invalid JSON"),
    (b"{}", "did not contain answers"),
])
def test_response_is_bounded_and_validated(tmp_path, body, message):
    judge, _ = make_judge(tmp_path, FakeOpener(FakeResponse(body)))
    with pytest.raises(jev.JevError, match=message):
        judge.decide({}, {})


def test_timeout_cannot_exceed_five_seconds(tmp_path):
    path = config_path(tmp_path)
    with pytest.raises(ValueError, match="5 seconds"):
        jev.JevJudge(path, opener=FakeOpener(), timeout=5.01)


def load_script(name):
    script = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configure_script_stores_disabled_key_without_printing_it(tmp_path, monkeypatch, capsys):
    configure = load_script("configure-jev.py")
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    path = directory / "jev.json"
    monkeypatch.setattr(configure, "CONFIG_PATH", path)
    inputs = iter(["secret-test-key", "secret-test-key"])
    monkeypatch.setattr(configure, "getpass", lambda prompt: next(inputs))

    assert configure.main([]) == 0
    output = capsys.readouterr().out
    assert "disabled" in output and "secret-test-key" not in output
    assert jev.load_config(path) == {"api_key": "secret-test-key", "enabled": False}


def test_probe_default_sends_no_request(capsys):
    probe = load_script("jev-probe.py")
    assert probe.main([]) == 0
    assert "No request sent" in capsys.readouterr().out


def test_probe_uses_test_only_mode_for_exactly_three_synthetic_tasks(monkeypatch, capsys):
    probe = load_script("jev-probe.py")
    monkeypatch.setattr(probe, "has_key", lambda: True)
    calls = []

    class SyntheticProbe:
        def __init__(self, *, test_only):
            assert test_only is True

        def decide(self, state, questions):
            calls.append((state, questions))
            choice = ("project_map", "project_search", "none")[len(calls) - 1]
            probabilities = {name: (0.95 if name == choice else 0.025) for name in probe.CRITERIA}
            return {"answers": {"route": {"choice": choice, "probabilities": probabilities}},
                    "usage": {"input_tokens": 5}}

    monkeypatch.setattr(probe, "JevJudge", SyntheticProbe)
    assert probe.main(["--run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(calls) == 3
    assert [state["task_data"] for state, _ in calls] == [task for task, _ in probe.PROBES]
    assert [row["choice"] for row in report["probes"]] == ["project_map", "project_search", "none"]
    assert "secret-test-key" not in json.dumps(report)


def test_probe_with_unavailable_key_sends_no_requests(monkeypatch, capsys):
    probe = load_script("jev-probe.py")
    monkeypatch.setattr(probe, "has_key", lambda: False)

    def should_not_construct(*args, **kwargs):
        raise AssertionError("no key means no client construction or request")

    monkeypatch.setattr(probe, "JevJudge", should_not_construct)
    assert probe.main(["--run"]) == 1
    assert "no request sent" in capsys.readouterr().err
