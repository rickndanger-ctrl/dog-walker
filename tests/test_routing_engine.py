import json
import yaml
import pytest

from dog_walker import routing
from dog_walker.engine import Engine
from .test_engine import make_run, FakeWorker, output, paused


@pytest.mark.parametrize('routed', [True, False])
async def test_preparation_preserves_checks_and_never_fakes_tool_receipts(tmp_path, monkeypatch, routed):
    store = make_run(tmp_path, monkeypatch, steps=[{'id': 'one', 'prompt': 'prompt.md',
                     'checks': [{'type': 'tool_called', 'tool': 'project_map'}]}])
    path = store.path / 'workflow/workflow.yaml'
    spec = yaml.safe_load(path.read_text())
    spec['plugins'] = ['project']
    path.write_text(yaml.safe_dump(spec))
    calls = []
    async def route(task, root, grants):
        calls.append((task, root, grants))
        return routing.RouteResult(status='routed' if routed else 'uncertain',
                                   tool='project_map' if routed else None,
                                   context='[Untrusted project data] fixture' if routed else None)
    monkeypatch.setattr(routing, 'route_context', route)
    FakeWorker.responses = [output()]
    FakeWorker.prompts = []
    engine = Engine(store, lambda _: None, paused, worker_factory=FakeWorker)
    await engine.run()
    assert len(calls) == 1 and set(calls[0][2]) == {'project_map', 'project_search'}
    assert ('[Untrusted project data] fixture' in FakeWorker.prompts[-1]) == routed
    assert store.state['turns'] == 1 and store.state['status'] == 'paused'
    assert not store.state['evaluation']['checks'][0]['pass']
    events = [json.loads(line) for line in (store.path / 'events.jsonl').read_text().splitlines()]
    assert len([e for e in events if e['type'] == 'context_routing']) == 1
    assert not any(e['type'] == 'plugin_tool' for e in events)
