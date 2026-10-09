import asyncio
from dog_walker.ui import Dashboard, EditPrompt
from .test_engine import make_run, output, FakeWorker
from dog_walker.engine import Engine


async def test_dashboard_approval_and_auto_control(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, auto=False)
    FakeWorker.responses = [output()]
    FakeWorker.prompts = []
    class FakeEngine(Engine):
        def __init__(self, store, emit, ask, no_start):
            super().__init__(store, emit, ask, no_start, worker_factory=FakeWorker)
    monkeypatch.setattr("dog_walker.ui.Engine", FakeEngine)
    app = Dashboard(store, no_start=True)
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(30):
            await pilot.pause(.05)
            if app.waiting:
                break
        assert app.waiting is not None
        await pilot.click("#approve")
        await pilot.pause(.15)
        assert store.state["status"] == "completed"


async def test_dashboard_pause_and_edit_modal(tmp_path, monkeypatch):
    store = make_run(tmp_path, monkeypatch, auto=False)
    FakeWorker.responses = [output()]
    class FakeEngine(Engine):
        def __init__(self, store, emit, ask, no_start):
            super().__init__(store, emit, ask, no_start, worker_factory=FakeWorker)
    monkeypatch.setattr("dog_walker.ui.Engine", FakeEngine)
    app = Dashboard(store, no_start=True)
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(30):
            await pilot.pause(.05)
            if app.waiting: break
        await pilot.click("#edit")
        await pilot.pause(.1)
        assert isinstance(app.screen, EditPrompt)
        await pilot.click("#cancel")
        await pilot.pause(.1)
        await pilot.click("#pause")
        await pilot.pause(.1)
        assert store.state["status"] == "paused"
