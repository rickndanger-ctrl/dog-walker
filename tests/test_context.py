import json
import subprocess

import pytest

from dog_walker import context
from dog_walker.context import project_map, project_search
from dog_walker.workflow import WalkerError
from dog_walker.tool_server import ToolServer
from .test_plugins import plugin_run, content


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def test_map_landmarks_and_fresh_search(tmp_path):
    write(tmp_path, "pyproject.toml", "[project]\nname='test'")
    write(tmp_path, "src/main.py", "def launch():\n    return 'hello'")
    write(tmp_path, "tests/test_main.py", "assert True")
    result = project_map(tmp_path)
    assert {f['path']: f['kind'] for f in result['files']} == {
        'pyproject.toml': 'manifest', 'src/main.py': 'entrypoint', 'tests/test_main.py': 'test'}
    assert not result['truncated']
    hit = project_search(tmp_path, 'hello')['matches'][0]
    assert hit['path'] == 'src/main.py' and hit['line'] == 2
    write(tmp_path, 'src/main.py', "return 'updated'")
    assert not project_search(tmp_path, 'hello')['matches']
    assert project_search(tmp_path, 'updated')['matches'][0]['line'] == 1


@pytest.mark.parametrize('path', ['.env', '.env.local', '.ssh/key', '.git/config', 'node_modules/a.js', '.venv/a.py', 'dist/a.js', 'target/a.rs', 'artifacts/result.txt', 'build/a.py'])
def test_excluded_data_never_in_results(tmp_path, path):
    write(tmp_path, path, 'PRIVATE')
    assert not project_map(tmp_path)['files']
    assert not project_search(tmp_path, 'PRIVATE')['matches']


def test_symlinks_binary_and_invalid_utf8_skipped(tmp_path):
    write(tmp_path, 'real.txt', 'allowed')
    (tmp_path / 'inside.txt').symlink_to(tmp_path / 'real.txt')
    (tmp_path / 'outside.txt').symlink_to('/etc/passwd')
    (tmp_path / 'directory').symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / 'binary.bin').write_bytes(b'a\0b')
    (tmp_path / 'invalid.txt').write_bytes(b'\xff')
    assert [f['path'] for f in project_map(tmp_path)['files']] == ['real.txt']


def test_source_open_rejects_replaced_parent_and_escape(tmp_path):
    write(tmp_path, 'real/source.py', 'allowed')
    (tmp_path / 'alias').symlink_to(tmp_path / 'real', target_is_directory=True)
    with pytest.raises(OSError):
        context.read_source(tmp_path, 'alias/source.py')
    with pytest.raises(WalkerError):
        context.read_source(tmp_path, '../outside.py')
    assert context.read_source(tmp_path, 'real/source.py') == b'allowed'


def test_git_ignores_and_negations(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    write(tmp_path, '.gitignore', 'ignored/\n*.log\n!keep.log\n')
    for path in ['ignored/nested/source.py', 'drop.log', 'keep.log', 'src/a.py']:
        write(tmp_path, path, 'needle')
    files = {f['path'] for f in project_map(tmp_path)['files']}
    assert files == {'.gitignore', 'keep.log', 'src/a.py'}


def test_limits_are_explicit_and_outputs_valid_json(tmp_path, monkeypatch):
    for number in range(20):
        write(tmp_path, f'{number:02d}.py', 'needle\n' * 10)
    monkeypatch.setattr(context, 'MAX_FILES', 3)
    result = project_map(tmp_path)
    assert result['files_scanned'] == 3 and result['truncated']
    monkeypatch.setattr(context, 'MAX_FILES', 5000)
    monkeypatch.setattr(context, 'MAX_OUTPUT', 600)
    result = project_search(tmp_path, 'needle')
    assert len(json.dumps(result, ensure_ascii=False)) <= 600
    assert result['truncated'] and 'output limit' in result['limits']
    assert 'matches' in result


def test_byte_and_file_limits(tmp_path, monkeypatch):
    write(tmp_path, 'large.py', 'x' * 100)
    monkeypatch.setattr(context, 'MAX_READ', 50)
    result = project_map(tmp_path)
    assert not result['files'] and result['truncated']
    monkeypatch.setattr(context, 'MAX_READ', 1000)
    monkeypatch.setattr(context, 'MAX_BYTES', 80)
    assert not project_map(tmp_path)['files']


def test_filename_matches_first_and_order_stable(tmp_path):
    write(tmp_path, 'a.py', 'needle\nneedle')
    write(tmp_path, 'z-needle.py', 'needle')
    result = project_search(tmp_path, 'needle')
    assert result == project_search(tmp_path, 'needle')
    assert result['matches'][0] == {'path': 'z-needle.py', 'match': 'filename'}
    assert [(m['path'], m['line']) for m in result['matches'][1:]] == [('a.py', 1), ('a.py', 2), ('z-needle.py', 1)]


@pytest.mark.parametrize('query', ['', ' ', 'x' * 1001])
def test_search_rejects_invalid_query(tmp_path, query):
    with pytest.raises(WalkerError):
        project_search(tmp_path, query)


def test_broker_grants_and_audit(plugin_run):
    server = ToolServer(plugin_run.path)
    result = content(server.call('project_map', {}))
    assert any(f['path'] == 'protected.txt' for f in result['files'])
    assert content(server.call('project_search', {'query': 'keep'}))['matches'][0]['line'] == 1
    assert server.call('project_search', {'query': 'keep', 'path': '../'})['isError']
    events = [json.loads(line) for line in (plugin_run.path / 'events.jsonl').read_text().splitlines()]
    assert [e['tool'] for e in events if e['type'] == 'plugin_tool'] == ['project_map', 'project_search', 'project_search']
    plugin_run.save(status='paused')
    assert server.call('project_map', {})['isError']
