import copy
import json
from pathlib import Path
import subprocess
import sys
import tomllib
import pytest
import yaml
from dog_walker import forms, plugins, storage
from dog_walker.plugins import freeze_plugins, codex_overrides, registry, validate_plugin
from dog_walker.tool_server import ToolServer, dispatch
from dog_walker.workflow import WalkerError
from .test_forms import form
from .test_engine import make_run


@pytest.fixture
def plugin_run(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins, "PLUGIN_DIR", tmp_path / "plugin-config")
    store = make_run(tmp_path, monkeypatch)
    source = store.path / "workflow/workflow.yaml"
    value = yaml.safe_load(source.read_text())
    value["plugins"] = ["project", "browser", "obsidian"]
    source.write_text(yaml.safe_dump(value))
    vault = tmp_path / "connected-vault"
    vault.mkdir()
    (vault / "Mission-Control").mkdir()
    (vault / "Mission-Control/Memory.md").write_text("The harness reads verified memory.")
    config = plugins.PLUGIN_DIR
    config.mkdir()
    obsidian = next(p for p in plugins.builtin_plugins() if p["id"] == "obsidian")
    obsidian["settings"]["root"] = str(vault)
    (config / "obsidian.json").write_text(json.dumps(obsidian))
    freeze_plugins(store)
    store.save(status="running", phase="running", turns=1)
    return store


def content(response):
    assert not response["isError"], response
    return json.loads(response["content"][0]["text"])


def test_discovery_three_equal_plugin_categories(plugin_run):
    server = ToolServer(plugin_run.path)
    names = {t["name"] for t in server.tools()}
    assert {"project_read", "project_verify", "browser_inspect", "obsidian_read", "obsidian_search", "recommend_tool"} <= names
    assert {p["category"] for p in server.plugins} == {"project", "browser", "connected"}


def test_read_search_and_audit_actual_files(plugin_run):
    server = ToolServer(plugin_run.path)
    assert content(server.call("project_read", {"path": "protected.txt"}))["text"] == "keep me"
    assert "protected.txt" in content(server.call("project_list", {}))["entries"]
    assert content(server.call("obsidian_read", {"path": "Mission-Control/Memory.md"}))["text"].startswith("The harness")
    hits = content(server.call("obsidian_search", {"folder": "Mission-Control", "query": "verified"}))["matches"]
    assert hits[0]["path"] == "Mission-Control/Memory.md"
    events = [json.loads(line) for line in (plugin_run.path / "events.jsonl").read_text().splitlines()]
    assert [e["tool"] for e in events if e["type"] == "plugin_tool"] == ["project_read", "project_list", "obsidian_read", "obsidian_search"]


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", ".git/config", ".env"])
def test_project_reader_rejects_escape_and_control_files(plugin_run, path):
    response = ToolServer(plugin_run.path).call("project_read", {"path": path})
    assert response["isError"]


def test_symlink_escape_unknown_arguments_and_disabled_tools(plugin_run, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside data")
    (Path(plugin_run.state["root"]) / "escape").symlink_to(outside)
    server = ToolServer(plugin_run.path)
    assert server.call("project_read", {"path": "escape"})["isError"]
    assert server.call("project_read", {"path": "protected.txt", "execute": True})["isError"]
    assert server.call("delete_everything", {})["isError"]
    storage.atomic_json(plugin_run.path / "plugin-grants.json", {"version": 1, "plugins": []})
    empty = ToolServer(plugin_run.path)
    assert empty.tools() == []
    assert empty.call("project_read", {"path": "protected.txt"})["isError"]


def test_stale_or_paused_server_cannot_call_tools(plugin_run):
    server = ToolServer(plugin_run.path)
    plugin_run.save(status="paused")
    assert server.call("project_read", {"path": "protected.txt"})["isError"]
    plugin_run.save(status="running", turns=2)
    assert server.call("project_read", {"path": "protected.txt"})["isError"]


def test_vault_disconnect_does_not_create_a_replacement(plugin_run):
    server = ToolServer(plugin_run.path)
    root = Path(server.by_adapter["obsidian"]["settings"]["root"])
    root.rename(root.with_name("disconnected-vault"))
    response = server.call("obsidian_read", {"path": "Mission-Control/Memory.md"})
    assert response["isError"] and "Reconnect" in response["content"][0]["text"]
    assert not root.exists()


def test_saved_grants_do_not_follow_config_edits(plugin_run):
    before = (plugin_run.path / "plugin-grants.json").read_bytes()
    path = plugins.PLUGIN_DIR / "obsidian.json"
    value = json.loads(path.read_text())
    value["settings"]["root"] = "/a/different/vault"
    path.write_text(json.dumps(value))
    freeze_plugins(plugin_run)
    assert (plugin_run.path / "plugin-grants.json").read_bytes() == before
    assert content(ToolServer(plugin_run.path).call("obsidian_read", {"path": "Mission-Control/Memory.md"}))["text"]


def test_old_jobs_get_no_new_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(plugins, "PLUGIN_DIR", tmp_path / "config")
    store = make_run(tmp_path, monkeypatch)
    assert codex_overrides(store) == []
    assert json.loads((store.path / "plugin-grants.json").read_text())["plugins"] == []


def test_codex_override_uses_isolated_server_and_exact_allowlist(plugin_run):
    argv = codex_overrides(plugin_run)
    config = tomllib.loads("\n".join(argv[i] for i in range(1, len(argv), 2)))
    server = config["mcp_servers"]["dogwalker"]
    assert server["required"] is True
    assert server["args"][0] == "-I"
    assert server["args"][-1] == str(plugin_run.path)
    assert "recommend_tool" in server["enabled_tools"]
    assert 'env_vars' not in server  # No user-service access without a coder grant.


def test_mcp_stdio_round_trip(plugin_run):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project_read", "arguments": {"path": "protected.txt"}}},
    ]
    proc = subprocess.run([sys.executable, "-I", str(storage.APP_ROOT / "scripts/plugin-server.py"), "--run-dir", str(plugin_run.path)],
        input="".join(json.dumps(r) + "\n" for r in requests), capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    responses = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["id"] for r in responses] == [1, 2, 3]
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert content(responses[2]["result"])["text"] == "keep me"


def test_mcp_protocol_errors_are_explicit(plugin_run):
    server = ToolServer(plugin_run.path)
    assert dispatch(server, [])['error']['code'] == -32600
    assert dispatch(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": [1]})['error']['code'] == -32602
    assert dispatch(server, {"jsonrpc": "2.0", "id": 1, "method": "unknown"})['error']['code'] == -32601


def test_laya_recommends_without_executing(plugin_run):
    class Judge:
        def decide(self, state, questions):
            assert state['task'] == 'Read the source file'
            keys = list(questions['tool']['criteria'])
            probs = [0.001] * len(keys)
            probs[keys.index('project_read')] = 1 - .001 * (len(keys) - 1)
            return {"answers": {"tool": {"choice": "project_read", "probabilities": probs}}}
    server = ToolServer(plugin_run.path, Judge())
    result = content(server.call('recommend_tool', {'task': 'Read the source file'}))
    assert result['tool'] == 'project_read' and result['executed'] is False
    events = [json.loads(l) for l in (plugin_run.path / 'events.jsonl').read_text().splitlines()]
    assert [e['tool'] for e in events if e['type'] == 'plugin_tool'] == ['recommend_tool']


@pytest.mark.parametrize('answer', [
    {'choice': 'project_read', 'probabilities': [1/7] * 7},
    {'choice': 'not_granted', 'probabilities': [1/7] * 7},
    {'choice': 'project_read', 'probabilities': [float('nan')] * 7},
])
def test_laya_uncertainty_never_grants_or_runs_tools(plugin_run, answer):
    class Judge:
        def decide(self, *args):return {'answers': {'tool': answer}}
    result = content(ToolServer(plugin_run.path, Judge()).call('recommend_tool', {'task': 'Choose a tool'}))
    assert result['decision'] == 'review' and result['tool'] is None


def test_browser_rejects_ungranted_origins_before_launch(plugin_run, monkeypatch):
    server = ToolServer(plugin_run.path)
    monkeypatch.setattr(server, 'process', lambda *a, **k: pytest.fail('Browser must not launch'))
    for url in ['https://example.com', 'file:///etc/passwd', 'http://user:password@localhost', 'http://127.0.0.1:8080']:
        assert server.call('browser_inspect', {'url': url})['isError']
    assert server.call('browser_inspect', {'path': 'protected.txt'})['isError']
    assert server.call('browser_inspect', {'path': 'x.html', 'url': 'https://example.com'})['isError']


def test_browser_request_uses_runtime_and_workspace_boundaries(plugin_run, monkeypatch):
    root = Path(plugin_run.state['root'])
    (root/'index.html').write_text('<title>Browser fixture</title>')
    server = ToolServer(plugin_run.path)
    def fake(argv, timeout, input):
        request = json.loads(input)
        assert request['path'] == str(root/'index.html')
        assert request['width'] == 390 and request['origins'] == []
        return 0, json.dumps({'title': 'Browser fixture', 'errors': []}), ''
    monkeypatch.setattr(server, 'process', fake)
    # Isolate request construction from availability of a machine-specific runtime.
    server.by_adapter['browser']['settings']['playwright_module'] = str(root)
    monkeypatch.setattr('dog_walker.tool_server.shutil.which', lambda _: '/usr/bin/node')
    assert content(server.call('browser_inspect', {'path': 'index.html', 'width': 390}))['title'] == 'Browser fixture'


def test_forms_request_plugins_but_import_does_not_start_them(tmp_path, monkeypatch):
    monkeypatch.setattr(forms, 'DATA', tmp_path/'data')
    monkeypatch.setattr(plugins, 'PLUGIN_DIR', tmp_path/'config')
    value = form(); value['plugins'] = ['project', 'browser', 'obsidian']
    data, workflow = forms.compile_form(yaml.safe_dump(value))
    assert workflow.data['plugins'] == value['plugins']
    preview = forms.preview(data)
    assert len(preview['plugins']) == 3
    assert 'origins' in '\n'.join(preview['constraints'])
    assert not (tmp_path/'data/runs').exists()
    value['plugins'] = ['missing']
    with pytest.raises(WalkerError, match='not installed'):
        forms.preview(value)


def test_custom_stdio_mcp_manifest_is_data_until_job_requests_it(plugin_run):
    manifest = {'id': 'my-app', 'name': 'My app', 'description': 'Read connected app records',
        'category': 'connected', 'adapter': 'mcp',
        'settings': {'command': '/installed/app-server', 'args': ['--stdio'], 'enabled_tools': ['records_read']}}
    validate_plugin(manifest)
    (plugins.PLUGIN_DIR/'my-app.json').write_text(json.dumps(manifest))
    assert registry()['my-app'] == manifest
    existing = json.loads((plugin_run.path/'plugin-grants.json').read_text())
    existing['plugins'].append(manifest)
    storage.atomic_json(plugin_run.path/'plugin-grants.json', existing)
    argv = codex_overrides(plugin_run)
    config = tomllib.loads('\n'.join(argv[i] for i in range(1,len(argv),2)))
    assert config['mcp_servers']['dw_my-app']['enabled_tools'] == ['records_read']
    assert config['mcp_servers']['dw_my-app']['required'] is True
    bad = copy.deepcopy(manifest); bad['settings']['enabled_tools'] = []
    with pytest.raises(WalkerError):validate_plugin(bad)


def test_mcp_declares_only_named_environment_secrets(plugin_run):
    manifest = {'id': 'keyed-service', 'name': 'Keyed service', 'description': 'Read connected records',
        'category': 'connected', 'adapter': 'mcp',
        'settings': {'command': '/installed/app-server', 'args': [], 'enabled_tools': ['records_read'],
                     'env_vars': ['SERVICE_API_KEY']}}
    validate_plugin(manifest)
    (plugins.PLUGIN_DIR/'keyed-service.json').write_text(json.dumps(manifest))
    existing = json.loads((plugin_run.path/'plugin-grants.json').read_text())
    existing['plugins'].append(manifest)
    storage.atomic_json(plugin_run.path/'plugin-grants.json', existing)
    argv = codex_overrides(plugin_run)
    config = tomllib.loads('\n'.join(argv[i] for i in range(1, len(argv), 2)))
    assert config['mcp_servers']['dw_keyed-service']['env_vars'] == ['SERVICE_API_KEY']
    assert 'env' not in config['mcp_servers']['dw_keyed-service']
    assert 'SERVICE_API_KEY' in (plugin_run.path/'plugin-grants.json').read_text()
    bad = copy.deepcopy(manifest); bad['settings']['env_vars'] = ['apiKey=literal-secret']
    with pytest.raises(WalkerError):validate_plugin(bad)


def test_authored_checks_and_scope_stay_authoritative(plugin_run):
    server = ToolServer(plugin_run.path)
    # The fixture's response-only check has no worker result yet: it must fail.
    result = content(server.call('project_verify', {}))
    assert result['passed'] is False
    assert result['checks'][0]['pass'] is False


def test_cancelled_plugin_subprocess_exits(plugin_run):
    server = ToolServer(plugin_run.path)
    server.stopped.set()
    with pytest.raises(WalkerError, match='cancelled'):
        server.process([sys.executable, '-c', 'import time; time.sleep(30)'], 5)


def test_checkpoint_requires_real_successful_receipt_from_current_turn(plugin_run):
    from dog_walker.engine import run_checks
    from dog_walker.plugins import tool_events
    checks = [{'type': 'tool_called', 'tool': 'project_read'}]
    root = Path(plugin_run.state['root'])
    server = ToolServer(plugin_run.path)
    claimed = {'summary': 'I used project_read successfully'}
    assert run_checks(checks, root, claimed, [], {}, tool_calls=tool_events(plugin_run))[0]['pass'] is False
    server.call('project_read', {'path': 'missing.txt'})
    assert run_checks(checks, root, claimed, [], {}, tool_calls=tool_events(plugin_run))[0]['pass'] is False
    server.call('project_read', {'path': 'protected.txt'})
    assert run_checks(checks, root, claimed, [], {}, tool_calls=tool_events(plugin_run))[0]['pass'] is True
    plugin_run.save(turns=2)
    assert run_checks(checks, root, claimed, [], {}, tool_calls=tool_events(plugin_run))[0]['pass'] is False


def test_install_manifest_does_not_execute_server(tmp_path, monkeypatch):
    from dog_walker.cli import main
    monkeypatch.setattr(plugins, 'PLUGIN_DIR', tmp_path/'config')
    value = {'id': 'custom', 'name': 'A custom tool', 'description': 'Read app data',
        'category': 'connected', 'adapter': 'mcp',
        'settings': {'command': '/does/not/exist', 'args': [], 'enabled_tools': ['read']}}
    source = tmp_path/'custom.json';source.write_text(json.dumps(value))
    assert main(['plugin-add', str(source)]) == 0
    assert json.loads((plugins.PLUGIN_DIR/'custom.json').read_text()) == value


def test_git_status_uses_actual_workspace(plugin_run):
    root = Path(plugin_run.state['root'])
    (root/'new-file.txt').write_text('new')
    result = content(ToolServer(plugin_run.path).call('project_git_status', {}))
    assert '?? new-file.txt' in result['status']


def test_browser_resource_policy_in_node_without_launching_chromium(tmp_path):
    (tmp_path/'index.html').write_text('<h1>Local page</h1>')
    (tmp_path/'.env').write_text('private')
    (tmp_path/'escape.txt').symlink_to('/etc/passwd')
    source = '''
const {authorizeResource} = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const checks = [
 ['http://dogwalker.invalid/index.html', 'GET'],
 ['http://dogwalker.invalid/.env', 'GET'],
 ['http://dogwalker.invalid/escape.txt', 'GET'],
 ['file:///etc/passwd', 'GET'],
 ['https://allowed.example/page', 'GET'],
 ['https://allowed.example/page', 'POST'],
 ['https://other.example/page', 'GET'],
 ['https://user:password@allowed.example/page', 'GET'],
];
console.log(JSON.stringify(checks.map(([url, method]) => !!authorizeResource(input, url, method))));
'''
    request = {'root': str(tmp_path), 'path': str(tmp_path/'index.html'), 'origins': ['https://allowed.example']}
    proc = subprocess.run(['node', '-e', source, str(storage.APP_ROOT/'scripts/browser-inspect.cjs'), json.dumps(request)],
        capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [True, False, False, False, True, False, False, False]
