#!/usr/bin/env python3
"""Real Codex/MCP/bridge round trip against a scripted local Responses fixture.

This checks project-tool transport, not model intelligence. It performs no
model inference.
"""
import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(output):
    from dog_walker import settings, storage, worker
    from dog_walker.engine import Engine
    from dog_walker.workflow import load_workflow
    from dog_walker.storage import Store
    initial_settings = settings.load_settings()
    model = initial_settings['model_path']
    data = Path(tempfile.mkdtemp(prefix='transport-acceptance-', dir=output.parent))
    requests = []
    failures = []
    answer = {'status': 'completed', 'summary': 'Verified the project map receipt.',
              'evidence': ['project_map returned hello.py'], 'files_changed': [], 'blockers': []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            result = {'model_path': model} if self.path == '/props' else {'status': 'ok', 'slots_idle': 1, 'slots_processing': 0}
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert self.path == '/v1/responses'
                names = [t.get('name') for t in body['tools']]
                assert all(t['type'] != 'namespace' for t in body['tools'])
                assert 'mcp__dogwalker__project_map' in names
                requests.append(body)
                count = len(requests)
                if count == 1:
                    item = {'id': 'fc_probe', 'type': 'function_call', 'name': 'mcp__dogwalker__project_map',
                            'call_id': 'call_probe', 'arguments': '{}', 'status': 'completed'}
                    added = {**item, 'arguments': '', 'status': 'in_progress'}
                    events = [
                        {'type': 'response.output_item.added', 'output_index': 0, 'item': added},
                        {'type': 'response.function_call_arguments.delta', 'item_id': 'fc_probe', 'output_index': 0, 'delta': '{}'},
                        {'type': 'response.function_call_arguments.done', 'item_id': 'fc_probe', 'output_index': 0, 'name': item['name'], 'arguments': '{}'},
                        {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                    ]
                else:
                    assert count == 2, 'Unexpected extra model request'
                    calls = [i for i in body['input'] if i.get('type') == 'function_call']
                    assert calls[-1]['name'] == 'mcp__dogwalker__project_map' and 'namespace' not in calls[-1]
                    results = [i for i in body['input'] if i.get('type') == 'function_call_output']
                    assert 'hello.py' in json.dumps(results[-1]['output'])
                    text = json.dumps(answer)
                    part = {'type': 'output_text', 'text': text, 'annotations': []}
                    item = {'id': 'msg_probe', 'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [part]}
                    events = [
                        {'type': 'response.output_item.added', 'output_index': 0, 'item': {**item, 'status': 'in_progress', 'content': []}},
                        {'type': 'response.content_part.added', 'item_id': 'msg_probe', 'output_index': 0, 'content_index': 0, 'part': {**part, 'text': ''}},
                        {'type': 'response.output_text.delta', 'item_id': 'msg_probe', 'output_index': 0, 'content_index': 0, 'delta': text},
                        {'type': 'response.output_text.done', 'item_id': 'msg_probe', 'output_index': 0, 'content_index': 0, 'text': text},
                        {'type': 'response.content_part.done', 'item_id': 'msg_probe', 'output_index': 0, 'content_index': 0, 'part': part},
                        {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                    ]
                response = {'id': f'resp_{count}', 'object': 'response', 'created_at': 1, 'status': 'in_progress', 'output': []}
                events.insert(0, {'type': 'response.created', 'response': response})
                events.append({'type': 'response.completed', 'response': {**response, 'status': 'completed', 'output': [item],
                    'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}})
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for event in events:
                    self.wfile.write(('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode())
                    self.wfile.flush()
            except Exception as exc:
                failures.append(str(exc))
                self.send_error(500, str(exc))

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    project = data / 'input'
    project.mkdir()
    source = 'def hello():\n    return "hello"\n'
    (project / 'hello.py').write_text(source)
    workflow = data / 'plan'
    workflow.mkdir()
    (workflow / 'task.md').write_text('Call project_map once, then report the receipt. Do not edit files.')
    (workflow / 'workflow.yaml').write_text('version: 1\nname: Transport fixture\nplugins: [project]\nallowed_changes: []\nsteps:\n  - id: probe\n    prompt: task.md\n    max_retries: 0\n    checks:\n      - type: tool_called\n        tool: project_map\n')
    config = data / 'worker.json'
    config.write_text(json.dumps({**settings.load_settings(), 'endpoint': f'http://127.0.0.1:{server.server_port}/v1', 'start_command': []}))
    settings.CONFIG = config
    storage.DATA = data / 'run-data'
    worker.DATA = storage.DATA
    worker.reload_settings()
    store = Store.create(load_workflow(workflow), project, auto=True)
    async def drive():
        engine = Engine(store, lambda _line: None, lambda *_args: asyncio.sleep(0, result='pause'), no_start=True)
        # Routing is also scripted: this acceptance verifies transport without
        # loading either the main model or the optional local decision model.
        from unittest.mock import patch
        class FixtureJudge:
            def decide(self, state, questions):
                choices = list(questions['route']['criteria'])
                return {'answers': {'route': {'type': 'choice', 'choice': 'none',
                        'probabilities': {name: float(name == 'none') for name in choices}}}}
        with patch('dog_walker.routing.decision_judge', return_value=FixtureJudge()):
            await asyncio.wait_for(engine.run(), 30)
    try:
        asyncio.run(drive())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    receipts = [r for line in (store.path / 'events.jsonl').read_text().splitlines()
                if (r := json.loads(line)).get('type') == 'plugin_tool']
    report = {'kind': 'scripted provider transport acceptance', 'model_inference': False,
              'requests': len(requests), 'status': store.state['status'],
              'receipts': [{'tool': r['tool'], 'isError': r['result']['isError']} for r in receipts],
              'input_unchanged': (project / 'hello.py').read_text() == source,
              'data': str(data), 'failures': failures}
    output.write_text(json.dumps(report, indent=2) + '\n')
    assert report['status'] == 'completed' and report['requests'] == 2, report
    assert report['receipts'] == [{'tool': 'project_map', 'isError': False}], report
    assert report['input_unchanged'] and not failures, report
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/transport-acceptance.json'))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run(args.output)
