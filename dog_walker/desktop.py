"""Offline JSON-line bridge for the native QML desktop. No listening sockets."""
import asyncio
import contextlib
import fcntl
import json
import os
from pathlib import Path
import signal
import shutil
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
    def __init__(self, output=None, engine_factory=None):
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
        self.inbox = Path(os.environ.get("DOG_WALKER_INBOX", Path.home() / "Documents/Dog Walker/Inbox"))
        self.inbox.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write(value):
        print(json.dumps(scrub(value), ensure_ascii=False), flush=True)

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
        self.send("library", runs=runs, inbox=files, inbox_path=str(self.inbox))

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
        if op == "hello":
            from .judge import MODEL_DIR
            from .worker import MODEL_PATH, START_COMMAND, CATALOG
            self.send("hello", version="0.3.0", app_root=str(APP_ROOT),
                      health={"codex": bool(shutil.which("codex")), "worker": Path(MODEL_PATH).is_file(),
                              "catalog": Path(CATALOG).is_file(), "launcher": bool(START_COMMAND and Path(START_COMMAND[0]).is_file()),
                              "judge": (MODEL_DIR / "dog-walker-manifest.json").is_file()})
            self.library()
        elif op == "import":
            self.ensure_idle()
            if "text" in cmd:
                text = cmd["text"]
            else:
                path = local_path(cmd.get("path"))
                if path.stat().st_size > MAX_BYTES:
                    raise WalkerError("Job forms must be smaller than 256 KB")
                text = path.read_text()
            job, workflow = await asyncio.to_thread(compile_form, text)
            self.job, self.workflow = job, workflow
            self.send("job", job=preview(job))
        elif op == "start":
            self.ensure_idle()
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
                self.store.save(job=preview(self.job))
            except Exception:
                self.lease.close()
                self.lease = None
                raise
            self.logs = []
            self.task = asyncio.create_task(self.walk())
            self.snapshot()
            self.send("selected")
        elif op == "load":
            self.ensure_idle()
            self.store = Store.open(cmd.get("id", ""))
            self.logs = []
            self.snapshot()
            self.send("selected")
        elif op == "resume":
            self.ensure_idle()
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
            from .settings import save_settings
            from .worker import reload_settings
            save_settings(cmd.get("settings"))
            reload_settings()
            await self.command({"op": "hello"})
            self.send("saved_settings")
        elif op == "shutdown":
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
        await desktop.pause()
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
