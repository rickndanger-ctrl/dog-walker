import json
from pathlib import Path

from dog_walker import storage
from .test_chat import FakeChat, app, opened, plan


def events(app, kind):
    return [event for event in app.events if event["type"] == kind]


async def test_markdown_import_previews_without_model_or_project_writes(app, tmp_path):
    project = tmp_path / "chosen-project"
    project.mkdir()
    source = tmp_path / "Add search.md"
    text = "# Add search\n\nLet people find items by name.\n"
    source.write_text(text, encoding="utf-8")

    result = await app.handle({"op": "import", "path": source.as_uri()})

    assert result["ok"]
    brief = events(app, "brief")[-1]["brief"]
    assert brief["title"] == "Add search"
    assert brief["source"] == str(source)
    assert brief["bytes"] == len(text.encode()) and brief["preview"] == text
    assert app.brief["text"] == text
    assert app.job is None and app.workflow is None and app.task is None and app.store is None
    assert FakeChat.prompts == []
    assert not (tmp_path / "data/runs").exists()
    assert not (project / ".git").exists()
    assert list(project.iterdir()) == []


async def test_brief_plan_uses_independently_chosen_file_url_project_and_stays_inert_until_start(
    app, tmp_path, monkeypatch
):
    project = tmp_path / "chosen-project"
    project.mkdir()
    source = tmp_path / "full brief.md"
    text = "# Build release notes\n\n" + ("Specific source context.\n" * 500)
    source.write_text(text, encoding="utf-8")
    await app.handle({"op": "import", "path": source.as_uri()})
    brief_id = app.brief["id"]

    selected = await app.handle({"op": "prepare_project", "root": project.as_uri(), "auto_plan": False})
    assert selected["ok"]
    assert events(app, "project_selected")[-1]["root"] == str(project)
    FakeChat.answer = json.dumps(plan())
    planned = await app.handle({"op": "brief_plan", "brief_id": brief_id, "root": project.as_uri()})
    assert planned["ok"]
    await app.chat_task

    assert app.job and app.workflow and app.store is None and app.task is None
    assert app.job["steps"][-1]["approval"] is True
    assert app.job["steps"][0]["prompt"].startswith("Read .handler-inputs/brief-")
    assert list(app.workflow.steps.values())[-1]["approval"] is True
    assert app.brief_input[1] == text
    assert app.job_chat == app.brief_chat_id
    private_chat = storage.DATA / "chats" / app.brief_chat_id
    assert (private_chat / "brief.md").read_text(encoding="utf-8") == text
    assert not (project / ".handler-inputs").exists()
    assert not (project / ".git").exists()
    assert not (tmp_path / "data/runs").exists()

    class FakeEngine:
        def __init__(self, store, emit, ask):
            self.store = store

        async def run(self):
            self.store.event("fake_engine_started")

    app.engine_factory = FakeEngine
    started = await app.handle({"op": "start", "root": project.as_uri(), "in_place": False})
    assert started["ok"]
    workspace = Path(app.store.state["root"])
    input_path = workspace / app.brief_input[0]
    assert input_path.read_text(encoding="utf-8") == text
    assert app.store.state["hashes"][app.brief_input[0]]
    assert not (project / ".handler-inputs").exists()
    await app.task
    assert events(app, "finished")


async def test_brief_question_is_emitted_and_answer_reuses_private_conversation(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "unclear.md"
    source.write_text("# Change\n\nImplement a useful change.\n", encoding="utf-8")
    await app.handle({"op": "import", "path": source.as_uri()})
    brief_id = app.brief["id"]

    FakeChat.answer = json.dumps({"kind": "question", "message": "Which files should change?"})
    await app.handle({"op": "brief_plan", "brief_id": brief_id, "root": project.as_uri()})
    await app.chat_task
    assert events(app, "brief_question")[-1]["message"] == "Which files should change?"
    conversation_id = app.brief_chat_id
    assert conversation_id
    assert len(FakeChat.prompts) == 1

    FakeChat.answer = json.dumps(plan())
    await app.handle({"op": "brief_plan", "brief_id": brief_id, "root": project.as_uri(),
                      "answer": "Only update the release notes."})
    await app.chat_task
    assert app.brief_chat_id == conversation_id
    assert len(FakeChat.prompts) == 2
    assert any(message["role"] == "user" and "Only update the release notes." in message["text"]
               for message in app.chat.value["messages"])


async def test_stale_brief_id_is_rejected_before_model_call(app, tmp_path):
    source = tmp_path / "brief.md"
    source.write_text("# Brief\n\nContext.\n", encoding="utf-8")
    await app.handle({"op": "import", "path": source.as_uri()})

    result = await app.handle({"op": "brief_plan", "brief_id": "stale-id",
                               "root": tmp_path.as_uri()})

    assert not result["ok"] and "Attach your Markdown brief again" in result["message"]
    assert FakeChat.prompts == []
    assert app.brief_chat_id is None


async def test_typed_brief_question_keeps_identity_and_conversation(app, tmp_path):
    FakeChat.answer = json.dumps({"kind": "question", "message": "Which screen?"})
    result = await app.handle({"op": "brief_plan", "text": "Improve navigation", "root": tmp_path.as_uri()})
    assert result["ok"]
    await app.chat_task
    brief_id = events(app, "brief")[-1]["brief"]["id"]
    conversation_id = app.brief_chat_id
    FakeChat.answer = json.dumps(plan())
    await app.handle({"op": "brief_plan", "brief_id": brief_id, "answer": "The home screen", "root": tmp_path.as_uri()})
    await app.chat_task
    assert app.brief_chat_id == conversation_id
    assert app.brief["text"] == "Improve navigation"
    assert any("The home screen" in m["text"] for m in app.chat.value["messages"])


async def test_selecting_folder_with_bundled_plan_retains_attached_markdown(app, tmp_path):
    source = tmp_path / "my-task.md"
    source.write_text("# My task\nKeep this brief selected.")
    await app.handle({"op": "import", "path": source.as_uri()})
    brief_id = app.brief["id"]
    # Even a malformed old plan must not displace the user's new brief.
    (tmp_path / "old.dogwalk").write_text("obsolete plan")
    result = await app.handle({"op": "prepare_project", "root": tmp_path.as_uri()})
    assert result["ok"]
    assert app.brief["id"] == brief_id and app.job is None
    assert not events(app, "job") and FakeChat.prompts == []


async def test_large_brief_preview_is_accepted_but_local_planning_has_48kb_limit(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "large.md"
    source.write_text("# Long\n\n" + "x" * (50 * 1024), encoding="utf-8")

    imported = await app.handle({"op": "import", "path": source.as_uri()})
    assert imported["ok"]
    assert events(app, "brief")[-1]["brief"]["bytes"] > 48 * 1024

    result = await app.handle({"op": "brief_plan", "brief_id": app.brief["id"], "root": project.as_uri()})

    assert not result["ok"]
    assert "under 48 KB" in result["message"]
    assert FakeChat.prompts == []
    assert app.chat is None and app.brief_chat_id is None
