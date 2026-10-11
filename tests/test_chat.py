import asyncio
import base64
import copy
import json
from pathlib import Path
import sys
import pytest
from dog_walker import chat, desktop, forms, storage, worker
from dog_walker.chat import Conversation, attachment, prompt_for, validate_draft, ChatWorker
from dog_walker.desktop import Desktop
from dog_walker.workflow import WalkerError
from .test_forms import form

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV7sAAAAASUVORK5CYII=")


def plan():
    value = form()
    value.update(allowed_changes=["done.txt"], plugins=["project"])
    value["steps"][-1]["approval"] = True
    return {"kind": "plan", "form": value}


class FakeChat:
    answer = "Let's work through it."
    gate = None
    prompts = []

    def __init__(self, emit):
        self.emit = emit

    async def ready(self):
        pass

    async def reply(self, conversation, prompt, draft):
        self.prompts.append((prompt, draft))
        if self.gate:
            await self.gate.wait()
        return self.answer


@pytest.fixture
def app(tmp_path, monkeypatch):
    for module in (chat, desktop, forms, storage, worker):
        monkeypatch.setattr(module, "DATA", tmp_path / "data")
    monkeypatch.setenv("DOG_WALKER_INBOX", str(tmp_path / "Inbox"))
    events = []
    FakeChat.answer, FakeChat.gate, FakeChat.prompts = "Let's work through it.", None, []
    bridge = Desktop(events.append, chat_factory=FakeChat)
    bridge.events = events
    return bridge


async def opened(app, root=None):
    await app.handle({"op": "chat_new"})
    ident = app.chat.value["id"]
    if root:
        await app.handle({"op": "chat_project", "chat_id": ident, "root": str(root)})
    return ident


async def test_conversation_persists_and_reopen_does_not_replay(app, tmp_path):
    ident = await opened(app)
    await app.handle({"op": "chat_send", "chat_id": ident, "text": "Help me build a small app"})
    await app.chat_task
    assert app.lease is None and app.chat.lock is None
    assert [m["role"] for m in app.chat.value["messages"]] == ["user", "assistant"]
    assert app.chat.value["messages"][-1]["text"] == FakeChat.answer
    await app.handle({"op": "chat_open", "id": ident})
    assert len(FakeChat.prompts) == 1
    assert app.chat.value["title"] == "Help me build a small app"
    assert not (tmp_path / "data/runs").exists()


async def test_valid_draft_is_inert_and_uses_official_preview(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    ident = await opened(app, project)
    FakeChat.answer = json.dumps(plan())
    await app.handle({"op": "chat_draft", "chat_id": ident, "text": "Create done.txt with a result", "plugins": ["project"]})
    await app.chat_task
    draft = app.chat.value["draft"]
    assert draft and app.workflow is None and app.store is None and app.task is None
    assert not (project / ".git").exists() and not (tmp_path / "data/runs").exists()
    await app.handle({"op": "chat_use_draft", "chat_id": ident, "draft_id": draft["id"]})
    message = [e for e in app.events if e["type"] == "job"][-1]
    assert message["type"] == "job" and message["project"] == str(project)
    saved_form = forms.parse_form((app.chat.path / (draft['id'] + '.dogwalk')).read_text())
    assert message["job"] == forms.preview(saved_form)
    assert 'Create done.txt with a result' in saved_form['steps'][0]['prompt']
    assert app.job_chat == ident and app.workflow.name == plan()["form"]["name"]
    assert not (tmp_path / "data/runs").exists()
    await app.handle({"op": "chat_use_draft", "chat_id": ident, "draft_id": "f" * 32})
    assert app.events[-1]["type"] == "error"


async def test_model_question_and_invalid_plan_never_replace_current_job(app, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    ident = await opened(app, project)
    await app.handle({"op": "import", "text": json.dumps(form())})
    original = app.workflow
    for answer in ('{"kind":"question","message":"Which files should change?"}', '{"kind":"plan","form":{}}'):
        FakeChat.answer = answer
        await app.handle({"op": "chat_draft", "chat_id": ident, "text": "Build it", "plugins": []})
        await app.chat_task
        assert app.workflow is original and app.chat.value["draft"] is None and app.store is None
    assert app.chat.value["messages"][-1]["status"] == "error"


async def test_stale_ids_and_unknown_plugins_fail_before_calling_model(app, tmp_path):
    ident = await opened(app, tmp_path)
    for cmd in ({"op": "chat_send", "chat_id": "stale", "text": "Hi"},
                {"op": "chat_draft", "chat_id": ident, "text": "Hi", "plugins": ["missing"]},
                {"op": "chat_send", "chat_id": ident, "text": "x" * 8001}):
        result = await app.handle(cmd)
        assert not result["ok"] and app.chat_task is None
    assert FakeChat.prompts == [] and app.chat.value["messages"] == []


async def test_cancel_preserves_history_and_releases_model_for_other_window(app):
    ident = await opened(app)
    FakeChat.gate = asyncio.Event()
    await app.handle({"op": "chat_send", "chat_id": ident, "text": "Think about this"})
    while not FakeChat.prompts:
        await asyncio.sleep(0)
    other = Desktop(lambda _: None, chat_factory=FakeChat)
    with pytest.raises(WalkerError, match="busy"):
        other.take_lease()
    await app.handle({"op": "chat_cancel"})
    assert app.chat.value["messages"][-1]["status"] == "interrupted"
    assert app.lease is None and app.chat.lock is None
    other.take_lease()
    other.lease.close()


async def test_cancel_before_task_starts_releases_locks(app):
    ident = await opened(app)
    await app.handle({"op": "chat_send", "chat_id": ident, "text": "Hi"})
    await app.cancel_chat()
    assert app.lease is None and app.chat.lock is None and app.chat_task is None
    app.take_lease()
    app.lease.close()
    app.lease = None


async def test_shutdown_and_crash_recovery_do_not_replay(app):
    ident = await opened(app)
    app.chat.append("assistant", "", status="working")
    await app.handle({"op": "chat_open", "id": ident})
    assert app.chat.value["messages"][-1]["status"] == "interrupted"
    assert FakeChat.prompts == []
    FakeChat.gate = asyncio.Event()
    await app.handle({"op": "chat_send", "chat_id": ident, "text": "Hi"})
    await asyncio.sleep(0)
    await app.handle({"op": "shutdown"})
    assert app.chat_task is None and app.lease is None


async def test_attachments_snapshot_images_and_invalidate_old_draft(app, tmp_path):
    ident = await opened(app)
    text = tmp_path / "brief.md"
    text.write_text("Keep the interface clean.")
    image = tmp_path / "reference.png"
    image.write_bytes(PNG)
    app.chat.save(draft={"id": "f" * 32})
    for path in (text, image):
        await app.handle({"op": "chat_attach", "chat_id": ident, "path": str(path)})
    items = app.chat.value["attachments"]
    assert len(items) == 2 and app.chat.value["draft"] is None
    assert items[0]["text"] == "Keep the interface clean."
    stored = Path(items[1]["image_path"])
    assert stored.read_bytes() == PNG and stored.stat().st_mode & 0o777 == 0o600
    image.unlink()
    assert stored.is_file() and "preview" in app.chat.snapshot()["attachments"][1]
    assert "text" not in app.chat.snapshot()["attachments"][0]
    assert "Keep the interface clean." in prompt_for(app.chat)
    await app.handle({"op": "chat_remove_attachment", "chat_id": ident, "id": items[0]["id"]})
    assert len(app.chat.value["attachments"]) == 1


@pytest.mark.parametrize("name,content", [("binary.dat", b"a\x00b"), ("bad.txt", b"\xff"), ("big.md", b"a" * 50000), (".env.local", b"secret")])
def test_unsupported_and_credential_files_fail(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(WalkerError):
        attachment(path)


async def test_attachment_limit_and_project_change(app, tmp_path):
    ident = await opened(app)
    path = tmp_path / "image.png"
    path.write_bytes(PNG)
    for _ in range(4):
        await app.handle({"op": "chat_attach", "chat_id": ident, "path": str(path)})
    assert not (await app.handle({"op": "chat_attach", "chat_id": ident, "path": str(path)}))["ok"]
    assert len(app.chat.value["attachments"]) == 4
    assert len(list((app.chat.path / "attachments").iterdir())) == 4
    app.chat.save(draft={"id": "f" * 32})
    project = tmp_path / "project"
    project.mkdir()
    await app.handle({"op": "chat_project", "chat_id": ident, "root": str(project)})
    assert app.chat.value["project"] == str(project) and app.chat.value["draft"] is None


@pytest.mark.parametrize("change", [
    lambda d: d["form"].pop("allowed_changes"),
    lambda d: d["form"].update(plugins=["browser"]),
    lambda d: d["form"]["steps"][-1].update(approval=False),
    lambda d: d["form"]["steps"][0]["checks"][0].update(path="../outside"),
])
def test_generated_plan_keeps_scope_grants_and_review(app, change):
    draft = copy.deepcopy(plan())
    change(draft)
    with pytest.raises(WalkerError):
        validate_draft(json.dumps(draft), ["project"])


def test_chat_configuration_is_read_only_and_separate(app):
    home = worker.configure(chat.DATA / "chat-codex-home", chat.INSTRUCTIONS, "read-only")
    assert 'sandbox_mode = "read-only"' in (home / "config.toml").read_text()
    assert "READ ONLY" in (home / "instructions.md").read_text()
    assert not (chat.DATA / "codex-home").exists()
    assert worker.environment(home)["CODEX_HOME"] == str(home)


def test_plugin_order_does_not_change_a_draft_grant(app):
    draft = plan()
    draft["form"]["plugins"] = ["obsidian", "project"]
    result, workflow = validate_draft(json.dumps(draft), ["project", "obsidian"])
    assert result["form"]["plugins"] == workflow.data["plugins"] == ["project", "obsidian"]


def test_readable_pdf_is_extracted_locally(tmp_path):
    import shutil
    if not shutil.which("pdftotext"):
        pytest.skip("PDF support needs the optional local pdftotext command")
    stream = b"BT /F1 12 Tf 72 720 Td (Hello from the PDF brief) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    content = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    start = len(content)
    content += b"xref\n0 6\n0000000000 65535 f \n"
    content += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    content += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(start).encode() + b"\n%%EOF\n"
    pdf = tmp_path / "brief.pdf"
    pdf.write_bytes(content)
    result = attachment(pdf)
    assert result["kind"] == "text" and "Hello from the PDF brief" in result["text"]
    assert "20 pages" in result["note"]


async def test_real_codex_jsonl_adapter_passes_images_and_read_only_args(app, tmp_path, monkeypatch):
    conversation = Conversation.create()
    image = tmp_path / "image.png"
    image.write_bytes(PNG)
    conversation.save(attachments=[attachment(image, conversation.path)])
    fake = tmp_path / "codex"
    fake.write_text("#!" + sys.executable + "\n" + '''import sys,json,pathlib,os
args=sys.argv[1:]
pathlib.Path(os.environ['CODEX_HOME']).mkdir(parents=True,exist_ok=True)
pathlib.Path(os.environ['CODEX_HOME'],'args.json').write_text(json.dumps(args))
assert sys.stdin.read() == 'Look at this picture'
pathlib.Path(args[args.index('--output-last-message')+1]).write_text('I can see your picture.')
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'I can see your picture.'}}))
print(json.dumps({'type':'turn.completed'}))
''')
    fake.chmod(0o755)
    real_which = chat.shutil.which
    monkeypatch.setattr(chat.shutil, "which", lambda name: str(fake) if name == "codex" else real_which(name))
    adapter = ChatWorker(lambda _: None)
    result = await adapter.reply(conversation, "Look at this picture")
    args = json.loads((adapter.home / "args.json").read_text())
    assert result == "I can see your picture."
    assert args[args.index('--sandbox') + 1] == 'read-only'
    original_path = Path(conversation.value["attachments"][0]["image_path"])
    model_path = Path(args[args.index('--image') + 1])
    assert model_path.parent == original_path.parent / "inference"
    assert model_path.is_file() and model_path != original_path
    assert original_path.read_bytes() == PNG
    assert conversation.value["attachments"][0]["preview"] == original_path.as_uri()
    from PIL import Image
    with Image.open(model_path) as processed:
        assert processed.format == "JPEG" and max(processed.size) <= 384
    assert '--skip-git-repo-check' in args and '--ephemeral' in args
    assert args[-2:] == ['--', '-']  # '-' must not become another --image value.


async def test_incomplete_model_turn_does_not_publish_reply(app, tmp_path, monkeypatch):
    conversation = Conversation.create()
    fake = tmp_path / "codex"
    fake.write_text("#!" + sys.executable + "\nimport sys,json\nsys.stdin.read()\nprint(json.dumps({'type':'error','message':'failed'}))\n")
    fake.chmod(0o755)
    monkeypatch.setattr(chat.shutil, "which", lambda _: str(fake))
    with pytest.raises(WalkerError, match="did not finish"):
        await ChatWorker(lambda _: None).reply(conversation, "Hello")


async def test_pending_conversation_in_another_window_is_not_overwritten(app):
    ident = await opened(app)
    FakeChat.gate = asyncio.Event()
    await app.handle({"op": "chat_send", "chat_id": ident, "text": "Hi"})
    while not FakeChat.prompts:
        await asyncio.sleep(0)
    before = (app.chat.path / "chat.json").read_bytes()
    other = Desktop(lambda _: None, chat_factory=FakeChat)
    result = await other.handle({"op": "chat_open", "id": ident})
    assert not result["ok"] and (app.chat.path / "chat.json").read_bytes() == before
    await app.cancel_chat()


async def test_chat_plan_starts_through_existing_engine_and_results_return_to_chat(app, tmp_path, monkeypatch):
    from dog_walker.routing import RouteResult
    async def fixture_route(*args):
        return RouteResult(status="skipped")
    monkeypatch.setattr("dog_walker.routing.route_context", fixture_route)
    from dog_walker.engine import Engine
    from .test_engine import FakeWorker, output
    from .test_desktop import wait_review
    root = tmp_path / "project"
    root.mkdir()
    (root / "done.txt").write_text("done")
    ident = await opened(app, root)
    FakeChat.answer = json.dumps(plan())
    await app.handle({"op": "chat_draft", "chat_id": ident, "text": "Check done.txt", "plugins": ["project"]})
    await app.chat_task
    await app.handle({"op": "chat_use_draft", "chat_id": ident, "draft_id": app.chat.value["draft"]["id"]})
    FakeWorker.responses, FakeWorker.prompts = [output()], []
    app.engine_factory = lambda store, emit, ask: Engine(store, emit, ask, worker_factory=FakeWorker)
    await app.handle({"op": "start", "root": str(root), "in_place": False})
    await wait_review(app)
    assert app.store.state["chat_id"] == ident
    assert app.store.state["original_root"] == str(root)
    assert all(c["pass"] for c in app.store.state["evaluation"]["checks"])
    assert len(FakeWorker.prompts) == 1
    await app.handle({"op": "control", "action": "approve", "run_id": app.store.state["id"], "review_id": app.review_id})
    await app.task
    await app.handle({"op": "chat_results", "chat_id": ident, "run_id": app.store.state["id"]})
    assert '"status": "completed"' in app.chat.value["messages"][-1]["text"]
    assert app.store.state["id"] in prompt_for(app.chat)
    assert not (root / ".git").exists()
