import asyncio
import fcntl
import json

import pytest

from dog_walker import settings, worker
from dog_walker.workflow import WalkerError
from .test_desktop import app


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(settings.Path, 'home', staticmethod(lambda: tmp_path))
    monkeypatch.setattr(settings, 'CONFIG', tmp_path / 'worker.json')
    for field in ('MODEL_PATH', 'ENDPOINT', 'CATALOG'):
        monkeypatch.delenv('DOG_WALKER_' + field, raising=False)
    runtime = tmp_path / 'opt/local-model-runtime/launcher.py'
    runtime.parent.mkdir(parents=True)
    runtime.write_text('# test')
    rows = settings.model_profiles()
    for profile in rows:
        model = settings.Path(profile['settings']['model_path'])
        model.parent.mkdir(parents=True)
        model.write_text('test model')
        projector = {'ornith': 'mmproj-Ornith-1.5-35B-BF16.gguf',
                     'gemma': 'gemma-4-26B-it-mmproj.gguf',
                     'qwen': 'mmproj-F16.gguf'}[profile['id']]
        (model.parent / projector).write_text('test projector')
    catalog = settings.Path(settings.defaults()['catalog'])
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps({'models': [{'slug': p['settings']['model_path']} for p in rows]}))
    monkeypatch.setattr(worker, 'reload_settings', lambda: None)
    return rows


@pytest.mark.parametrize('ident, port', [('gemma', 18082), ('qwen', 18080)])
def test_selection_saves_matching_profile_without_starting_server(profiles, ident, port):
    assert settings.model_summary()['model_id'] == 'ornith'
    settings.select_model(ident)
    value = settings.load_settings()
    assert value['endpoint'] == f'http://127.0.0.1:{port}/v1'
    assert value['start_command'][-2:] == ['--model', ident]
    assert settings.model_summary()['model_id'] == ident
    assert settings.CONFIG.stat().st_mode & 0o777 == 0o600


def test_qwen_requires_its_vision_projector_and_keeps_saved_model(profiles):
    settings.save_settings(settings.defaults())
    before = settings.CONFIG.read_bytes()
    qwen = next(p for p in profiles if p['id'] == 'qwen')
    model = settings.Path(qwen['settings']['model_path'])
    assert model.name == 'Qwen3.8-27B-UD-Q4_K_XL.gguf'
    (model.parent / 'mmproj-F16.gguf').unlink()
    assert not next(p for p in settings.model_profiles() if p['id'] == 'qwen')['available']
    with pytest.raises(WalkerError, match='not installed'):
        settings.select_model('qwen')
    assert settings.CONFIG.read_bytes() == before


def test_missing_or_unknown_profile_does_not_replace_saved_connection(profiles):
    settings.save_settings(settings.defaults())
    before = settings.CONFIG.read_bytes()
    settings.Path(profiles[1]['settings']['model_path']).unlink()
    for ident in ('gemma', 'unknown'):
        with pytest.raises(WalkerError):
            settings.select_model(ident)
        assert settings.CONFIG.read_bytes() == before


def test_missing_catalog_entry_is_not_available(profiles):
    catalog = settings.Path(settings.defaults()['catalog'])
    catalog.write_text(json.dumps({'models': []}))
    assert not any(p['available'] for p in settings.model_profiles())


def test_environment_override_cannot_silently_defeat_picker(profiles, monkeypatch):
    monkeypatch.setenv('DOG_WALKER_ENDPOINT', settings.defaults()['endpoint'])
    with pytest.raises(WalkerError, match='environment'):
        settings.select_model('gemma')
    assert not settings.CONFIG.exists()


@pytest.mark.parametrize('ident', ['gemma', 'qwen'])
async def test_desktop_selection_guard_and_result(app, profiles, ident):
    await app.handle({'op': 'select_model', 'model_id': ident})
    assert app.events[-1]['type'] == 'model_selected'
    assert app.events[-1]['model_id'] == ident
    assert app.lease is None
    app.chat_task = asyncio.create_task(asyncio.sleep(10))
    before = settings.CONFIG.read_bytes()
    try:
        await app.handle({'op': 'select_model', 'model_id': 'ornith'})
        assert app.events[-1]['type'] == 'error'
        assert settings.CONFIG.read_bytes() == before
    finally:
        app.chat_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await app.chat_task


@pytest.mark.parametrize('ident', ['gemma', 'qwen'])
async def test_other_window_lease_blocks_settings_changes(app, profiles, ident):
    from dog_walker import desktop
    desktop.DATA.mkdir(parents=True)
    with (desktop.DATA / 'desktop-worker.lock').open('a') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        await app.handle({'op': 'select_model', 'model_id': ident})
    assert app.events[-1]['type'] == 'error'
    assert not settings.CONFIG.exists()
    assert app.lease is None
