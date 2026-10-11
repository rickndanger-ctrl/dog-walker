import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
import yaml

from dog_walker import chat, desktop, forms, projects, storage, worker
from dog_walker.desktop import Desktop
from dog_walker.workflow import WalkerError
from .test_forms import form


@pytest.fixture
def app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for module in (chat, desktop, forms, projects, storage, worker):
        monkeypatch.setattr(module, "DATA", data)
    monkeypatch.setenv("DOG_WALKER_INBOX", str(tmp_path / "Inbox"))
    events = []
    bridge = Desktop(events.append)
    bridge.events = events
    return bridge


def project_root(tmp_path, name="project"):
    path = tmp_path / name
    path.mkdir()
    return path


@pytest.mark.parametrize("picker_url", [False, True])
async def test_chat_accepts_new_empty_folder_from_picker_without_losing_conversation(app, tmp_path, picker_url):
    root = project_root(tmp_path, "to-do-list ü")
    await app.handle({"op": "chat_new"})
    ident = app.chat.value["id"]
    app.chat.append("user", "Build my to-do app")
    messages = app.chat.value["messages"].copy()
    result = await app.handle({"op": "chat_project", "chat_id": ident,
                              "root": root.as_uri() if picker_url else str(root)})
    assert result["ok"]
    assert app.chat.value["id"] == ident
    assert app.chat.value["project"] == str(root)
    assert app.chat.value["messages"] == messages
    assert list(root.iterdir()) == []
    assert app.chat_task is None and app.lease is None


async def test_sidebar_project_accepts_file_picker_url(app, tmp_path):
    root = project_root(tmp_path, "to-do-list ü")
    result = await app.handle({"op": "project_create", "name": "To-do list", "root": root.as_uri()})
    assert result["ok"]
    assert app.chat.value["project"] == str(root)
    assert projects.list_projects()[0]["root"] == str(root)
    assert list(root.iterdir()) == []


def test_project_registry_is_durable_and_theme_is_separate(app, tmp_path):
    root = project_root(tmp_path)
    created = projects.create_project("Client app", str(root))
    assert projects.get_project(created["id"]) == created
    assert projects.list_projects() == [{**created, "available": True}]
    assert projects.set_theme("light") == "light"
    assert projects.theme() == "light"

    data = tmp_path / "data"
    assert json.loads((data / "projects.json").read_text())["projects"][0]["root"] == str(root)
    assert json.loads((data / "preferences.json").read_text()) == {"theme": "light"}
    assert (data / "projects.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("root_factory", [
    lambda tmp, data: str(tmp / "missing"),
    lambda tmp, data: str(tmp),
    lambda tmp, data: str(data),
    lambda tmp, data: str(data.parent),
    lambda tmp, data: str(tmp / ".ssh"),
    lambda tmp, data: str(tmp / ".env.private"),
])
def test_project_roots_reject_missing_or_sensitive_locations(app, tmp_path, root_factory):
    data = tmp_path / "data"
    for name in (".ssh", ".env.private"):
        (tmp_path / name).mkdir()
    with pytest.raises(WalkerError):
        projects.create_project("Unsafe", root_factory(tmp_path, data))


def test_malformed_registry_is_not_overwritten(app, tmp_path):
    root = project_root(tmp_path)
    path = tmp_path / "data/projects.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"version": 1, "projects": [{"id": "bad"}]}')
    before = path.read_text()
    with pytest.raises(WalkerError, match="invalid"):
        projects.create_project("Client", str(root))
    assert path.read_text() == before


async def test_create_open_and_archive_projects_keep_chats_and_files(app, tmp_path):
    root = project_root(tmp_path)
    await app.handle({"op": "project_create", "name": "Client", "root": str(root)})
    item = projects.list_projects()[0]
    first_id = app.chat.value["id"]
    assert app.chat.value["project_id"] == item["id"]
    assert app.chat.value["project"] == str(root)
    assert app.active_project_id == item["id"]

    await app.handle({"op": "project_open", "project_id": item["id"]})
    assert app.chat.value["id"] == first_id
    assert any(c["id"] == first_id and c["project_id"] == item["id"]
               for c in app.events[-1].get("chats", []))

    marker = root / "keep.txt"
    marker.write_text("Keep this directory")
    await app.handle({"op": "project_archive", "project_id": item["id"]})
    archived = projects.get_project(item["id"])
    assert archived["archived"] is True
    assert marker.read_text() == "Keep this directory"
    assert (app.chat.path / "chat.json").is_file()
    assert app.active_project_id is None
    assert not (await app.handle({"op": "project_open", "project_id": item["id"]}))["ok"]


async def test_project_and_chat_switches_are_rejected_while_reply_is_busy(app, tmp_path):
    root = project_root(tmp_path)
    item = projects.create_project("Client", str(root))
    await app.handle({"op": "project_open", "project_id": item["id"]})
    app.chat_task = asyncio.create_task(asyncio.sleep(5))
    response = await app.handle({"op": "project_open", "project_id": item["id"]})
    assert not response["ok"] and "Stop the current reply" in response["message"]
    response = await app.handle({"op": "chat_new", "project_id": item["id"]})
    assert not response["ok"]
    app.chat_task.cancel()
    await asyncio.gather(app.chat_task, return_exceptions=True)


def test_old_conversations_remain_global_and_project_optional(app, tmp_path):
    path = tmp_path / "data/chats/old"
    path.mkdir(parents=True)
    (path / "chat.json").write_text(json.dumps({
        "id": "old", "title": "Old chat", "updated": "2026-10-01T00:00:00+00:00",
        "project": "", "messages": [], "attachments": [], "draft": None,
    }))
    opened = chat.Conversation.open("old")
    assert opened.value["project_id"] is None
    assert chat.conversations() == [{"id": "old", "title": "Old chat",
                                     "updated": "2026-10-01T00:00:00+00:00", "project_id": None}]


async def test_theme_is_reported_and_can_be_changed(app, tmp_path):
    await app.handle({"op": "hello"})
    hello = next(e for e in app.events if e["type"] == "hello")
    assert hello["theme"] == "dark"
    assert any(e.get("projects") == [] and e.get("active_project_id") is None for e in app.events)
    assert (await app.handle({"op": "set_theme", "theme": "light"}))["ok"]
    await app.handle({"op": "hello"})
    assert [e for e in app.events if e["type"] == "hello"][-1]["theme"] == "light"
    assert not (await app.handle({"op": "set_theme", "theme": "blue"}))["ok"]


async def test_prepare_project_selects_root_without_chat_or_job_work(app, tmp_path):
    root = project_root(tmp_path, "walk target")
    selected = root.as_uri()
    result = await app.handle({"op": "prepare_project", "root": selected})
    assert result["ok"]
    event = next(e for e in app.events if e["type"] == "project_selected")
    assert event == {"type": "project_selected", "root": str(root)}
    assert app.chat is None and app.chat_task is None
    assert app.job is None and app.workflow is None and app.store is None and app.task is None
    assert not (tmp_path / "data/chats").exists()
    assert not (tmp_path / "data/runs").exists()


@pytest.mark.parametrize("root_kind", ["missing", "ssh", "home_data"])
async def test_prepare_project_rejects_missing_and_sensitive_roots(app, tmp_path, root_kind):
    if root_kind == "missing":
        root = tmp_path / "does-not-exist"
    elif root_kind == "ssh":
        root = tmp_path / ".ssh"
        root.mkdir()
    else:
        root = tmp_path
    result = await app.handle({"op": "prepare_project", "root": str(root)})
    assert not result["ok"]
    assert app.chat is None and app.chat_task is None and app.workflow is None and app.task is None
    assert not any(e["type"] == "project_selected" for e in app.events)


async def test_prepare_project_respects_walk_and_chat_busy_guards(app, tmp_path):
    root = project_root(tmp_path)
    for field, message in (("task", "Pause this walk"), ("chat_task", "Stop the current reply")):
        task = asyncio.create_task(asyncio.sleep(5))
        setattr(app, field, task)
        result = await app.handle({"op": "prepare_project", "root": str(root)})
        assert not result["ok"] and message in result["message"]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        setattr(app, field, None)
    assert not any(e["type"] == "project_selected" for e in app.events)


async def test_library_keeps_project_recent_chats_beyond_global_recent_window(app, tmp_path):
    root = project_root(tmp_path)
    project = projects.create_project("Older project", str(root))
    project_chats = [chat.Conversation.create(project["id"]) for _ in range(45)]
    unrelated_chats = [chat.Conversation.create() for _ in range(45)]
    expected_project_chats = {item["id"] for item in chat.conversations(limit=None)
                              if item.get("project_id") == project["id"]}
    assert not (expected_project_chats & {item["id"] for item in chat.conversations()})

    await app.handle({"op": "project_open", "project_id": project["id"]})
    library = [event for event in app.events if event["type"] == "library"][-1]
    ids = {item["id"] for item in library["chats"]}
    global_recent = {item["id"] for item in chat.conversations()}
    expected_recent = [item for item in chat.conversations(limit=None)
                       if item.get("project_id") == project["id"]][:40]
    assert app.chat.value["id"] == project_chats[-1].value["id"]
    assert global_recent.issubset(ids)
    assert {item["id"] for item in expected_recent}.issubset(ids)
    assert project_chats[0].value["id"] not in ids
    assert len(library["chats"]) <= 80


async def test_direct_project_drop_reviews_single_valid_form_without_starting_work(app, tmp_path):
    root = project_root(tmp_path)
    (root / "plan.dogwalk").write_text(yaml.safe_dump(form()))
    model_calls = []
    app.chat_factory = lambda *_args: model_calls.append("called")

    result = await app.handle({"op": "prepare_project", "root": str(root)})

    assert result["ok"]
    types = [event["type"] for event in app.events]
    assert types.index("project_selected") < types.index("job")
    assert next(e for e in app.events if e["type"] == "project_selected")["root"] == str(root)
    job_event = next(e for e in app.events if e["type"] == "job")
    assert job_event["project"] == str(root)
    assert job_event["job"] == forms.preview(form())
    assert app.workflow.name == form()["name"] and app.job["name"] == form()["name"]
    assert app.chat is None and app.chat_task is None and app.store is None and app.task is None
    assert not (tmp_path / "data/runs").exists()
    assert model_calls == []


async def test_direct_project_drop_does_not_choose_between_multiple_forms(app, tmp_path):
    root = project_root(tmp_path)
    (root / "one.dogwalk").write_text(yaml.safe_dump(form()))
    (root / "two.dogwalk").write_text(yaml.safe_dump(form()))
    result = await app.handle({"op": "prepare_project", "root": str(root)})
    assert result["ok"]
    assert [event["type"] for event in app.events] == ["project_selected"]
    assert app.job is None and app.workflow is None and app.chat is None and app.task is None


async def test_direct_project_drop_can_preserve_an_explicitly_imported_plan(app, tmp_path):
    root = project_root(tmp_path)
    (root / "plan.dogwalk").write_text(yaml.safe_dump(form()))
    existing_job, existing_workflow = {"name": "Existing"}, object()
    app.job, app.workflow, app.job_chat = existing_job, existing_workflow, "existing-chat"
    result = await app.handle({"op": "prepare_project", "root": str(root), "auto_plan": False})
    assert result["ok"]
    assert [event["type"] for event in app.events] == ["project_selected"]
    assert app.job is existing_job and app.workflow is existing_workflow and app.job_chat == "existing-chat"


async def test_direct_project_drop_skips_escaping_symlink_without_reading_it(app, tmp_path, monkeypatch):
    root = project_root(tmp_path)
    outside = tmp_path / "outside.dogwalk"
    outside.write_text(yaml.safe_dump(form()))
    try:
        (root / "escape.dogwalk").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")
    monkeypatch.setattr(desktop, "compile_form", lambda _text: pytest.fail("outside form must not be read"))
    result = await app.handle({"op": "prepare_project", "root": str(root)})
    assert result["ok"]
    assert [event["type"] for event in app.events] == ["project_selected"]
    assert app.job is None and app.workflow is None


async def test_direct_project_drop_rejects_invalid_form_without_replacing_current_job(app, tmp_path):
    root = project_root(tmp_path)
    (root / "invalid.dogwalk").write_text("not a Dog Walk form")
    existing_job, existing_workflow = {"name": "Existing"}, object()
    app.job, app.workflow = existing_job, existing_workflow
    result = await app.handle({"op": "prepare_project", "root": str(root)})
    assert not result["ok"]
    assert [event["type"] for event in app.events] == ["project_selected", "error"]
    assert app.job is existing_job and app.workflow is existing_workflow


async def test_prepare_project_auto_plan_requires_a_boolean(app, tmp_path):
    root = project_root(tmp_path)
    result = await app.handle({"op": "prepare_project", "root": str(root), "auto_plan": "yes"})
    assert not result["ok"] and "boolean" in result["message"]
    assert [event["type"] for event in app.events] == ["error"]


def test_registry_concurrent_updates_preserve_all_records_and_future_fields(app, tmp_path):
    root = project_root(tmp_path)
    initial = projects.create_project("Base", str(root))
    registry_path = tmp_path / "data/projects.json"
    data = json.loads(registry_path.read_text())
    data["projects"][0]["future_field"] = {"kept": True}
    registry_path.write_text(json.dumps(data))

    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(lambda i: projects.create_project(f"Project {i}", str(root)), range(12)))
    assert len(projects.list_projects()) == 13
    projects.archive_project(initial["id"])
    records = {item["id"]: item for item in json.loads(registry_path.read_text())["projects"]}
    assert records[initial["id"]]["future_field"] == {"kept": True}
    assert records[initial["id"]]["archived"] is True
    assert {item["id"] for item in created}.issubset(records)


def test_preferences_update_preserves_future_fields(app):
    path = projects.DATA / "preferences.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"future_setting": "kept", "theme": "dark"}))
    projects.set_theme("light")
    assert json.loads(path.read_text()) == {"future_setting": "kept", "theme": "light"}
