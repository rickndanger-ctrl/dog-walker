"""Offline JSON-line bridge for the native QML desktop. No listening sockets."""
import asyncio
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import sys
from urllib.parse import unquote, urlparse
from uuid import uuid4
from .storage import APP_ROOT, DATA, Store, scrub
from .forms import compile_form, preview, MAX_BYTES
from .workflow import WalkerError


def local_path(value):
    if not isinstance(value, str) or not value:
        raise WalkerError("Choose a local file or folder")
    parsed = urlparse(value)
    if parsed.scheme:
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            raise WalkerError("Only local files are supported")
        value = unquote(parsed.path)
    return Path(value).expanduser().resolve()


def is_busy(store):
    try:
        store.acquire()
        store.release()
        return False
    except WalkerError:
        return True


class Desktop:
    def __init__(self, output=None, engine_factory=None, chat_factory=None):
        self.output = output or self.write
        self.engine_factory = engine_factory
        self.store = None
        self.job = self.workflow = None
        self.task = None
        self.review = None
        self.review_id = None
        self.review_reason = ""
        self.logs = []
        self.lease = None
        self.chat = None
        self.chat_task = None
        self.chat_factory = chat_factory
        self.chat_progress = ""
        self.active_project_id = None
        self.job_chat = None
        self.brief = None
        self.brief_chat_id = None
        self.brief_input = None
        self.inbox = Path(os.environ.get("DOG_WALKER_INBOX", Path.home() / "Documents/Dog Walker/Inbox"))
        self.inbox.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write(value):
        sys.stdout.write(json.dumps(scrub(value), ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def send(self, kind, **value):
        self.output(scrub({"type": kind, **value}))

    def log(self, text):
        self.logs = [*self.logs[-99:], str(text)[-6000:]]
        self.send("log", text=str(text)[-6000:])
        self.snapshot()

    def snapshot(self):
        if not self.store:
            return
        # An observer never writes another window's state or takes its lock.
        if not self.task or self.task.done():
            try:
                self.store = Store.open(self.store.state["id"])
            except (OSError, ValueError, WalkerError):
                return
        s = self.store.state
        busy = bool(self.task and not self.task.done())
        external = not busy and is_busy(self.store)
        self.send("state", state=s, active=busy, external=external,
                  review_id=self.review_id,
                  needs_review=bool(self.review and not self.review.done()), reason=self.review_reason,
                  total=len(self.store.workflow().steps), job=s.get("job") or {
                      "name": s["name"], "steps": [{"id": ident, "title": ident} for ident in self.store.workflow().steps]})

    def library(self):
        runs = []
        for path in sorted((DATA / "runs").glob("*/state.json"), reverse=True)[:30]:
            try:
                s = json.loads(path.read_text())
                runs.append({k: s.get(k) for k in ("id", "name", "status", "phase", "step", "created", "completion")})
            except (OSError, ValueError):
                continue
        files = [{"name": p.name, "path": str(p)} for p in sorted(self.inbox.iterdir())
                 if p.is_file() and p.suffix.lower() in {".dogwalk", ".yaml", ".yml", ".json"}][:50]
        from .chat import conversations
        from .projects import list_projects
        chats = conversations()
        if self.active_project_id:
            # Keep the global recent-chat window while ensuring a project's
            # own recent chats remain available when many unrelated chats are
            # newer. The merged result is bounded at 80 entries.
            seen = {chat["id"] for chat in chats}
            project_chats = [item for item in conversations(limit=None)
                             if item.get("project_id") == self.active_project_id][:40]
            chats.extend(item for item in project_chats if item["id"] not in seen)
        self.send("library", runs=runs, inbox=files, inbox_path=str(self.inbox),
                  chats=chats, projects=list_projects(), active_project_id=self.active_project_id)

    def chat_snapshot(self):
        self.send("chat", chat=self.chat.snapshot() if self.chat else None,
                  busy=bool(self.chat_task and not self.chat_task.done()), progress=self.chat_progress)

    def ensure_chat_idle(self):
        if self.chat_task and not self.chat_task.done():
            raise WalkerError("Stop the current reply before switching conversations or starting a walk")

    async def cancel_chat(self):
        if self.chat_task and not self.chat_task.done():
            self.chat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.chat_task
            # Cancellation may arrive before the new coroutine's first line.
            if self.chat:
                self.chat.release()
            if self.lease:
                self.lease.close()
                self.lease = None
        self.chat_task = None
        self.chat_snapshot()

    async def chat_turn(self, draft, plugins, from_brief=False):
        from .chat import ChatWorker, prompt_for, prepare_draft
        pending = None
        try:
            pending = self.chat.append("assistant", "", status="working", operation="draft" if draft else "reply")
            self.chat_snapshot()
            def emit(text):
                self.chat_progress = str(text)[-400:]
                self.chat_snapshot()
            model = (self.chat_factory or ChatWorker)(emit)
            await model.ready()
            prompt = prompt_for(self.chat, draft, plugins)
            if draft:
                result, _ = await prepare_draft(model, self.chat, prompt, plugins, emit)
                if result["kind"] == "question":
                    pending.update(text=result["message"], status="complete")
                    if from_brief:
                        self.send("brief_question", message=result["message"])
                else:
                    if from_brief:
                        from .briefs import compile_brief_form
                        job, workflow, input_name = await asyncio.to_thread(compile_brief_form,
                            result["form"], self.brief["text"])
                        result["form"] = job
                        self.brief_input = (input_name, self.brief["text"])
                    ident = uuid4().hex
                    path = self.chat.path / (ident + ".dogwalk")
                    from .storage import atomic_json
                    atomic_json(path, result["form"])
                    summary = preview(result["form"])
                    self.chat.save(draft={"id": ident, "name": summary["name"], "goal": summary["goal"],
                                          "steps": len(summary["steps"]), "created": self.chat.value["updated"]})
                    pending.update(text="Your plan is ready to review. " + summary["goal"], status="complete", draft_id=ident)
                    if from_brief:
                        self.chat.value["draft"]["brief_source"] = "brief.md"
                        self.chat.value["draft"]["brief_input_name"] = input_name
                        self.job, self.workflow, self.job_chat = job, workflow, self.chat.value["id"]
                        self.send("job", job=summary, project=self.chat.value["project"], chat_id=self.job_chat)
            else:
                answer = await model.reply(self.chat, prompt, False)
                pending.update(text=answer, status="complete")
        except asyncio.CancelledError:
            if pending:
                pending.update(text="Reply stopped. Send another message when you are ready.", status="interrupted")
            raise
        except Exception as exc:
            if pending:
                pending.update(text=str(exc)[:2000], status="error")
            self.send("error", message=str(exc)[:2000])
        finally:
            if self.chat:
                try:
                    self.chat.save()
                finally:
                    self.chat.release()
            if self.lease:
                self.lease.close()
                self.lease = None
            self.chat_progress = ""
            self.chat_task = None
            self.chat_snapshot()
            self.library()

    async def chat_command(self, cmd):
        from .chat import Conversation, conversations, attachment
        op = cmd["op"]
        if op == "chat_cancel":
            await self.cancel_chat()
            return
        self.ensure_chat_idle()
        if op in {"chat_open", "chat_new"}:
            if op == "chat_new":
                project_id = cmd.get("project_id")
                candidate = Conversation.create(project_id=project_id)
            else:
                ident = cmd.get("id") or (conversations()[0]["id"] if conversations() else None)
                candidate = Conversation.open(ident) if ident else Conversation.create()
            # A crashed/closed app never replays a pending message on reopen.
            candidate.acquire()
            self.chat = candidate
            self.active_project_id = candidate.value.get("project_id")
            try:
                for message in self.chat.value["messages"]:
                    if message["status"] == "working":
                        message.update(status="interrupted", text="This reply was interrupted. Send a new message to continue.")
                self.chat.save()
            finally:
                self.chat.release()
            self.chat_snapshot()
            self.library()
            return
        if not self.chat or cmd.get("chat_id") != self.chat.value["id"]:
            raise WalkerError("The selected conversation changed. Refresh before continuing.")
        if op in {"chat_send", "chat_draft"}:
            self.ensure_idle()
            text = cmd.get("text", "")
            if not isinstance(text, str) or len(text.encode()) > 8000 or (op == "chat_send" and not text.strip()):
                raise WalkerError("Write a message shorter than 8 KB")
            if op == "chat_draft" and not self.chat.value["project"]:
                raise WalkerError("Choose the project folder before creating a walk")
            from .plugins import resolve_plugins
            plugins = resolve_plugins(cmd.get("plugins", [])) if op == "chat_draft" else []
            self.take_lease()
            try:
                self.chat.acquire()
                if text.strip():
                    self.chat.append("user", text.strip(), attachments=self.chat.snapshot()["attachments"])
                    if self.chat.value["title"] == "New conversation":
                        self.chat.save(title=text.strip().splitlines()[0][:70])
                if op == "chat_draft":
                    if not any(m["role"] == "user" and m["status"] == "complete" for m in self.chat.value["messages"]):
                        raise WalkerError("Describe the work in chat before creating a walk")
                    self.chat.append("system", "Create a walk from our conversation. Selected plugins: " +
                                     (", ".join(p["id"] for p in plugins) or "none"))
                    self.chat.save(selected_plugins=[p["id"] for p in plugins])
                self.chat_progress = "Preparing your plan…" if op == "chat_draft" else "Thinking locally…"
                self.chat_task = asyncio.create_task(self.chat_turn(op == "chat_draft", plugins))
                self.send("chat_accepted", chat_id=self.chat.value["id"], text=text)
            except Exception:
                self.chat.release()
                self.lease.close()
                self.lease = None
                raise
        elif op == "chat_use_draft":
            self.ensure_idle()
            draft = self.chat.value.get("draft")
            if not draft or cmd.get("draft_id") != draft["id"] or not re.fullmatch(r"[a-f0-9]{32}", draft["id"]):
                raise WalkerError("This plan has been replaced. Review the latest draft.")
            text = (self.chat.path / (draft["id"] + ".dogwalk")).read_text()
            job, workflow = await asyncio.to_thread(compile_form, text)
            summary = preview(job)
            self.job, self.workflow, self.job_chat = job, workflow, self.chat.value["id"]
            self.brief_input = None
            if draft.get("brief_source") == "brief.md" and isinstance(draft.get("brief_input_name"), str):
                from .forms import read_markdown_brief
                saved = read_markdown_brief(self.chat.path / "brief.md")
                self.brief_input = (draft["brief_input_name"], saved["text"])
            self.send("job", job=summary, project=self.chat.value["project"], chat_id=self.job_chat)
        elif op in {"chat_project", "chat_attach", "chat_remove_attachment", "chat_results", "chat_plugins"}:
            self.chat.acquire()
            try:
                if op == "chat_plugins":
                    from .plugins import resolve_plugins
                    plugins = resolve_plugins(cmd.get("plugins"))
                    self.chat.save(selected_plugins=[p["id"] for p in plugins], draft=None)
                elif op == "chat_project":
                    if cmd.get("root"):
                        from .projects import validate_root
                        root = validate_root(str(local_path(cmd["root"])))
                    else:
                        root = None
                    self.chat.save(project=str(root) if root else "", project_id=None, draft=None)
                    self.active_project_id = None
                elif op == "chat_attach":
                    item = await asyncio.to_thread(attachment, local_path(cmd.get("path")), self.chat.path)
                    items = self.chat.value["attachments"]
                    image = item.get("kind") == "image"
                    if (len(items) >= 6 or (image and sum(a.get("kind") == "image" for a in items) >= 4) or
                            (not image and sum(a["bytes"] for a in items if a.get("kind") != "image") + item["bytes"] > 48 * 1024)):
                        if image:
                            Path(item["image_path"]).unlink(missing_ok=True)
                        raise WalkerError("Use up to six files: at most four pictures and 48 KB of text")
                    self.chat.save(attachments=[*items, item], draft=None)
                elif op == "chat_remove_attachment":
                    self.chat.save(attachments=[a for a in self.chat.value["attachments"] if a["id"] != cmd.get("id")], draft=None)
                else:
                    if not self.store or cmd.get("run_id") != self.store.state["id"]:
                        raise WalkerError("Select the walk whose results you want to discuss")
                    state = Store.open(self.store.state["id"]).state
                    context = {k: state.get(k) for k in ("id", "name", "status", "step", "phase", "root", "completion", "history")}
                    context["result"] = state.get("result") or state.get("previous_result")
                    context["checks"] = state.get("evaluation") or state.get("last_evaluation")
                    self.chat.append("system", "Saved walk snapshot (status is authoritative; this does not mark unfinished work complete):\n" + json.dumps(context, ensure_ascii=False))
            finally:
                self.chat.release()
        else:
            raise WalkerError("Unknown chat command")
        self.chat_snapshot()

    async def project_command(self, cmd):
        from .chat import Conversation, conversations
        from .projects import archive_project, create_project, get_project
        op = cmd.get("op")
        self.ensure_idle()
        self.ensure_chat_idle()
        if op == "project_create":
            item = create_project(cmd.get("name"), str(local_path(cmd.get("root"))))
            self.active_project_id = item["id"]
            candidate = Conversation.create(item["id"])
        elif op == "project_open":
            item = get_project(cmd.get("project_id"), include_archived=False)
            from .projects import validate_root
            root = validate_root(item["root"])
            if not root.is_dir():
                raise WalkerError("The project's folder is no longer available")
            self.active_project_id = item["id"]
            prior = next((c for c in conversations(limit=None) if c.get("project_id") == item["id"]), None)
            candidate = Conversation.open(prior["id"]) if prior else Conversation.create(item["id"])
        elif op == "project_archive":
            item = archive_project(cmd.get("project_id"))
            if self.active_project_id == item["id"]:
                self.active_project_id = None
            self.library()
            return
        else:
            raise WalkerError("Unknown project command")
        candidate.acquire()
        self.chat = candidate
        try:
            for message in self.chat.value["messages"]:
                if message["status"] == "working":
                    message.update(status="interrupted", text="This reply was interrupted. Send a new message to continue.")
            self.chat.save()
        finally:
            self.chat.release()
        self.chat_snapshot()
        self.library()

    async def ask(self, reason, passed=False):
        self.review_reason = reason
        self.review = asyncio.get_running_loop().create_future()
        self.review_id = uuid4().hex
        self.snapshot()
        try:
            return await self.review
        finally:
            self.review = None
            self.review_id = None
            self.review_reason = ""

    def ensure_idle(self):
        if self.task and not self.task.done():
            raise WalkerError("Pause this walk before switching jobs")

    def take_lease(self):
        DATA.mkdir(parents=True, exist_ok=True)
        self.lease = (DATA / "desktop-worker.lock").open("a")
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for path in (DATA / "runs").glob("*/state.json"):
                other = Store(path.parent)
                if is_busy(other):
                    raise WalkerError("A walk is open in another window. Pause and close that window first.")
        except BlockingIOError as exc:
            self.lease.close()
            self.lease = None
            raise WalkerError("The local model is busy in another chat or walk. Wait for it to finish or pause it first.") from exc
        except Exception:
            self.lease.close()
            self.lease = None
            raise

    async def walk(self):
        try:
            if self.engine_factory is None:
                from .engine import Engine
                factory = Engine
            else:
                factory = self.engine_factory
            await factory(self.store, self.log, self.ask).run()
        except Exception as exc:
            self.send("error", message=str(exc))
        finally:
            if self.lease:
                self.lease.close()
                self.lease = None
            self.snapshot()
            self.library()
            self.send("finished")

    async def pause(self):
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.task = None
        self.snapshot()

    async def command(self, cmd):
        op = cmd.get("op")
        if isinstance(op, str) and op.startswith("chat_"):
            await self.chat_command(cmd)
        elif isinstance(op, str) and op.startswith("project_"):
            await self.project_command(cmd)
        elif op == "hello":
            from .settings import model_summary
            from .judge import MODEL_DIR
            from .worker import MODEL_PATH, START_COMMAND, CATALOG
            from .plugins import registry
            from .projects import theme
            from .terminal_theme import sync_omarchy_theme
            self.send("hello", version="0.4.0", app_root=str(APP_ROOT), plugins=list(registry().values()), theme=theme(),
                      **sync_omarchy_theme(),
                      terminal_available=(APP_ROOT / ".runtime/qml/QMLTermWidget/libqmltermwidget.so").is_file(),
                      project_area=str(Path.home() / "Projects" if (Path.home() / "Projects").is_dir() else Path.home()),
                      helper_clients={name: bool(shutil.which(name)) for name in ("claude", "codex", "tmux")}, **model_summary(),
                      health={"codex": bool(shutil.which("codex")), "worker": Path(MODEL_PATH).is_file(),
                              "catalog": Path(CATALOG).is_file(), "launcher": bool(START_COMMAND and Path(START_COMMAND[0]).is_file()),
                              "judge": (MODEL_DIR / "dog-walker-manifest.json").is_file()})
            self.library()
        elif op == "set_theme":
            from .projects import set_theme
            value = set_theme(cmd.get("theme"))
            self.send("theme", theme=value)
        elif op == "prepare_project":
            self.ensure_idle()
            self.ensure_chat_idle()
            auto_plan = cmd.get("auto_plan", True)
            if type(auto_plan) is not bool:
                raise WalkerError("auto_plan must be a boolean")
            from .projects import validate_root
            root = validate_root(str(local_path(cmd.get("root"))))
            clear_plan = bool(self.brief)
            if clear_plan:
                self.job = self.workflow = self.job_chat = self.brief_input = None
                self.brief_chat_id = None
            self.send("project_selected", root=str(root), **({"clear_plan": True} if clear_plan else {}))
            if auto_plan and not self.brief:
                candidates = []
                for entry in root.iterdir():
                    if entry.suffix.lower() != ".dogwalk":
                        continue
                    try:
                        resolved = entry.resolve(strict=True)
                        if not resolved.is_relative_to(root) or not stat.S_ISREG(resolved.stat().st_mode):
                            continue
                    except (OSError, RuntimeError):
                        continue
                    candidates.append(resolved)
                if len(candidates) == 1:
                    form_path = candidates[0]
                    if form_path.stat().st_size > MAX_BYTES:
                        raise WalkerError("Job forms must be smaller than 256 KB")
                    with form_path.open("rb") as handle:
                        content = handle.read(MAX_BYTES + 1)
                    if len(content) > MAX_BYTES:
                        raise WalkerError("Job forms must be smaller than 256 KB")
                    try:
                        text = content.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise WalkerError("Job forms must be UTF-8 text") from exc
                    job, workflow = await asyncio.to_thread(compile_form, text)
                    summary = preview(job)
                    self.job, self.workflow, self.job_chat = job, workflow, None
                    self.send("job", job=summary, project=str(root))
        elif op == "import":
            self.ensure_idle()
            self.ensure_chat_idle()
            if "text" in cmd:
                text = cmd["text"]
            else:
                path = local_path(cmd.get("path"))
                if path.suffix.lower() == ".md":
                    from .forms import read_markdown_brief
                    brief = await asyncio.to_thread(read_markdown_brief, path)
                    if brief["kind"] == "brief":
                        self.brief = {**brief, "id": uuid4().hex}
                        self.brief_chat_id = self.brief_input = None
                        self.job = self.workflow = self.job_chat = None
                        self.send("brief", brief={"id": self.brief["id"], "title": brief["title"],
                            "source": brief["source"], "bytes": len(brief["text"].encode()),
                            "preview": brief["text"][:4000]})
                        return
                    text = brief["form_text"]
                else:
                    if path.stat().st_size > MAX_BYTES:
                        raise WalkerError("Job forms must be smaller than 256 KB")
                    text = path.read_text()
            job, workflow = await asyncio.to_thread(compile_form, text)
            summary = preview(job)
            self.job, self.workflow, self.job_chat = job, workflow, None
            self.brief_input = None
            self.brief = self.brief_chat_id = None
            self.send("job", job=summary, brief=None)
        elif op == "brief_clear":
            self.ensure_idle()
            self.ensure_chat_idle()
            self.brief = self.brief_chat_id = self.brief_input = None
            self.job = self.workflow = self.job_chat = None
            self.send("brief", brief=None)
        elif op == "brief_plan":
            self.ensure_idle()
            self.ensure_chat_idle()
            if not cmd.get("brief_id") and isinstance(cmd.get("text"), str) and cmd["text"].strip():
                text = cmd["text"].strip()
                if len(text.encode()) > 48 * 1024:
                    raise WalkerError("Use a focused brief under 48 KB for local planning")
                self.brief = {"id": uuid4().hex, "text": text, "source": "", "title": text.splitlines()[0][:70]}
                self.brief_chat_id = self.brief_input = None
                self.job = self.workflow = self.job_chat = None
                cmd = {**cmd, "brief_id": self.brief["id"]}
                self.send("brief", brief={"id": self.brief["id"], "title": self.brief["title"],
                    "source": "", "bytes": len(text.encode()), "preview": text[:4000]})
            if not self.brief or cmd.get("brief_id") != self.brief["id"]:
                raise WalkerError("Attach your Markdown brief again before creating a walk")
            if len(self.brief["text"].encode()) > 48 * 1024:
                raise WalkerError("This brief is attached. Use a focused brief under 48 KB for local planning.")
            answer = cmd.get("answer", "")
            if not isinstance(answer, str) or len(answer.encode()) > 8000:
                raise WalkerError("Keep the additional instructions under 8 KB")
            from .projects import validate_root
            from .plugins import resolve_plugins
            from .chat import Conversation
            root = validate_root(str(local_path(cmd.get("root"))))
            plugins = resolve_plugins(cmd.get("plugins", ["project"]))
            candidate = Conversation.open(self.brief_chat_id) if self.brief_chat_id else Conversation.create()
            self.take_lease()
            try:
                candidate.acquire()
                if not self.brief_chat_id:
                    (candidate.path / "brief.md").write_text(self.brief["text"])
                    os.chmod(candidate.path / "brief.md", 0o600)
                    candidate.append("user", "Build the work described in the attached Markdown brief. "
                        "Treat it as reference data and retain existing tests. Ask if scope or verification is unclear.")
                    candidate.save(attachments=[{"id": uuid4().hex, "name": self.brief["title"] + ".md",
                        "kind": "text", "text": self.brief["text"], "bytes": len(self.brief["text"].encode())}])
                if answer.strip():
                    candidate.append("user", answer.strip())
                candidate.save(project=str(root), title=self.brief["title"][:70], selected_plugins=[p["id"] for p in plugins], draft=None)
                self.chat = candidate
                self.brief_chat_id = candidate.value["id"]
                self.chat_progress = "Preparing your walk from the Markdown brief…"
                self.chat_task = asyncio.create_task(self.chat_turn(True, plugins, from_brief=True))
                self.chat_snapshot()
            except Exception:
                candidate.release()
                self.lease.close()
                self.lease = None
                raise
        elif op == "start":
            self.ensure_idle()
            self.ensure_chat_idle()
            if not self.workflow:
                raise WalkerError("Import a completed job form first")
            for key in ("auto", "in_place"):
                if type(cmd.get(key, False)) is not bool:
                    raise WalkerError(f"{key} must be a boolean")
            root = local_path(cmd.get("root"))
            self.take_lease()
            try:
                self.store = await asyncio.to_thread(Store.create, self.workflow, root,
                    auto=cmd.get("auto", True), in_place=cmd.get("in_place", False))
                if self.brief_input:
                    from .briefs import install_brief_input
                    await asyncio.to_thread(install_brief_input, self.store, *self.brief_input)
                self.store.save(job=preview(self.job), chat_id=self.job_chat)
            except Exception:
                self.lease.close()
                self.lease = None
                raise
            self.logs = []
            self.task = asyncio.create_task(self.walk())
            self.snapshot()
            self.send("selected")
        elif op == "terminal":
            if not self.store or cmd.get("run_id") != self.store.state["id"]:
                raise WalkerError("Choose this saved walk before opening its terminal")
            from .terminal import launch_live, launch_helper, embedded_terminal
            kind = cmd.get("kind", "live")
            embedded = cmd.get("embedded", False)
            if type(embedded) is not bool:
                raise WalkerError("Choose an embedded or external terminal")
            if embedded and not (APP_ROOT / ".runtime/qml/QMLTermWidget/libqmltermwidget.so").is_file():
                raise WalkerError("Run scripts/install-terminal.py to enable the embedded terminal")
            if embedded:
                from .terminal_theme import sync_omarchy_theme
                terminal_theme = await asyncio.to_thread(sync_omarchy_theme)
                if terminal_theme:
                    self.send("terminal_theme", **terminal_theme)
            if embedded and kind in {"workspace", "live"}:
                for pane in ("context", "shell"):
                    descriptor = await asyncio.to_thread(embedded_terminal, self.store, pane)
                    self.send("terminal_ready", terminal=descriptor)
                # Reconnect only to helpers the user already opened. Missing
                # sessions never start a provider request during restoration.
                for provider in ("claude", "codex"):
                    for mode in ("review", "drive"):
                        try:
                            descriptor = await asyncio.to_thread(embedded_terminal, self.store, "helper", provider, mode, attach_only=True)
                        except WalkerError:
                            continue
                        self.send("terminal_ready", terminal=descriptor, restored=True)
            elif kind in {"live", "shell", "context"}:
                if embedded:
                    descriptor = await asyncio.to_thread(embedded_terminal, self.store, kind)
                    self.send("terminal_ready", terminal=descriptor)
                elif kind in {"shell", "context"}:
                    raise WalkerError("Shell tabs require the embedded terminal")
                else:
                    await asyncio.to_thread(launch_live, self.store)
            elif kind == "helper":
                mode, provider = cmd.get("mode", "review"), cmd.get("provider")
                if mode not in {"review", "drive"} or provider not in {"claude", "codex"}:
                    raise WalkerError("Choose Claude or Codex, in review or help mode")
                if mode == "drive":
                    self.ensure_chat_idle()
                    if (not self.task or self.task.done()) and is_busy(self.store):
                        raise WalkerError("Another controller owns this walk")
                    await self.pause()
                if embedded:
                    descriptor = await asyncio.to_thread(embedded_terminal, self.store, kind, provider, mode)
                    self.send("terminal_ready", terminal=descriptor)
                else:
                    await asyncio.to_thread(launch_helper, self.store, provider, mode)
            else:
                raise WalkerError("Unknown terminal action")
        elif op == "load":
            self.ensure_idle()
            self.store = Store.open(cmd.get("id", ""))
            self.logs = []
            self.snapshot()
            self.send("selected")
        elif op == "resume":
            self.ensure_idle()
            self.ensure_chat_idle()
            if not self.store:
                raise WalkerError("Choose a saved walk")
            if cmd.get("run_id") != self.store.state["id"]:
                raise WalkerError("The selected walk changed. Refresh before resuming.")
            if self.store.state["status"] in {"completed", "aborted"}:
                raise WalkerError("This walk is already finished")
            self.take_lease()
            self.task = asyncio.create_task(self.walk())
            self.send("selected")
        elif op == "control":
            if not self.store or cmd.get("run_id") != self.store.state["id"]:
                raise WalkerError("The selected walk changed. Refresh before controlling it.")
            action = cmd.get("action")
            if action not in {"approve", "retry", "pause", "abort"}:
                raise WalkerError("Unknown review action")
            if action == "pause":
                await self.pause()
            elif self.review and not self.review.done():
                if cmd.get("review_id") != self.review_id:
                    raise WalkerError("This review request is stale. Refresh before approving or retrying.")
                if action == "approve" and any(not c["pass"] for c in (self.store.state.get("evaluation") or {}).get("checks", [])):
                    raise WalkerError("A verification check failed. Retry is required; approval cannot bypass it.")
                self.store.event("review_decision", action=action, review_id=self.review_id,
                                 step=self.store.state["step"], source=cmd.get("source", "desktop"))
                self.review.set_result(action)
            else:
                raise WalkerError("This walk is not waiting for a review")
        elif op == "refresh":
            self.snapshot()
            self.library()
        elif op == "settings":
            from .settings import load_settings
            self.send("settings", settings=load_settings())
        elif op == "phone":
            from .phone import info
            try:
                self.send("phone_info", **info())
            except FileNotFoundError:
                raise WalkerError("The phone companion has not been set up on this computer yet.")
        elif op == "save_settings":
            self.ensure_idle()
            self.ensure_chat_idle()
            from .settings import save_settings
            from .worker import reload_settings
            self.take_lease()
            try:
                save_settings(cmd.get("settings"))
                reload_settings()
            finally:
                self.lease.close()
                self.lease = None
            await self.command({"op": "hello"})
            self.send("saved_settings")
        elif op == "select_model":
            self.ensure_idle()
            self.ensure_chat_idle()
            from .settings import select_model, model_summary
            from .worker import reload_settings
            self.take_lease()
            try:
                select_model(cmd.get("model_id"))
                reload_settings()
            finally:
                self.lease.close()
                self.lease = None
            self.send("model_selected", **model_summary())
        elif op == "shutdown":
            await self.cancel_chat()
            await self.pause()
        else:
            raise WalkerError("Unknown desktop command")

    async def handle(self, cmd):
        result = {"ok": True}
        try:
            if not isinstance(cmd, dict):
                raise WalkerError("Commands must be JSON objects")
            await self.command(cmd)
        except (WalkerError, OSError, ValueError, TypeError) as exc:
            result = {"ok": False, "message": str(exc)}
            # Remote callers receive their own acknowledgment. A rejected phone
            # tap must not leave a misleading global error on the desktop.
            if not isinstance(cmd, dict) or cmd.get("source") != "phone":
                self.send("error", message=str(exc))
        if isinstance(cmd, dict) and isinstance(cmd.get("request_id"), str) and len(cmd["request_id"]) <= 80:
            self.send("command_result", request_id=cmd["request_id"], **result)
        return result


async def main():
    os.umask(0o077)
    desktop = Desktop()
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    reader = asyncio.StreamReader(limit=2 * MAX_BYTES)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    try:
        while not stopped.is_set():
            reading = asyncio.create_task(reader.readline())
            stopping = asyncio.create_task(stopped.wait())
            done, _ = await asyncio.wait({reading, stopping}, return_when=asyncio.FIRST_COMPLETED)
            if stopping in done:
                reading.cancel()
                break
            stopping.cancel()
            line = reading.result()
            if not line:
                break
            try:
                cmd = json.loads(line)
                await desktop.handle(cmd)
                if isinstance(cmd, dict) and cmd.get("op") == "shutdown":
                    break
            except (ValueError, UnicodeError) as exc:
                desktop.send("error", message=f"Invalid desktop message: {exc}")
    finally:
        await desktop.cancel_chat()
        await desktop.pause()
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
