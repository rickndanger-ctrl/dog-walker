#!/usr/bin/env python3
"""Exercise the desktop chat-to-approved-run flow in a disposable fixture.

The Desktop JSON controller, form compiler, run store, copy workspace, engine,
scope checks, file checks, approval gate, and results recovery are real.
Default mode uses scripted chat and coding workers. ``--live`` uses the current
already-running local model and real Codex workers; it first locks the desktop
and refuses an unready or busy host runtime. Neither mode edits a user project.
"""
import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO_ROOT = Path(__file__).resolve().parents[1]


def plan():
    return {
        "kind": "plan",
        "form": {
            "dog_walker": 1,
            "name": "Disposable todo acceptance",
            "goal": "Create a tiny todo helper and verify its behavior in a protected copy.",
            "constraints": ["Stay in the selected project copy", "Do not install packages"],
            "allowed_changes": ["todo.py", "test_todo.py"],
            "plugins": [],
            "steps": [{
                "id": "implement",
                "title": "Create and verify the todo helper",
                "prompt": "Create todo.py with add(todos, item) and complete(todos, item). Add unittest coverage in test_todo.py and run it.",
                "success_criteria": [
                    "todo.py implements add and complete",
                    "test_todo.py covers adding and completing a todo",
                    "The unittest suite passes",
                ],
                "checks": [
                    {"type": "file_exists", "path": "todo.py"},
                    {"type": "file_contains", "path": "todo.py", "text": "def complete"},
                    {"type": "file_exists", "path": "test_todo.py"},
                    {"type": "file_contains", "path": "test_todo.py", "text": "unittest.TestCase"},
                    {"type": "command", "argv": ["python3", "-m", "unittest", "-v", "test_todo"], "timeout": 60},
                ],
                "max_retries": 0,
                "approval": True,
            }],
        },
    }


def live_fixture_contents():
    return {
        ".gitignore": b"__pycache__/\n",
        "todo.py": (
            b"def add(todos, item):\n"
            b"    return [*todos, item]\n\n"
            b"def complete(todos, item):\n"
            b"    # Bug: keeps the completed item and drops every other item.\n"
            b"    return [todo for todo in todos if todo == item]\n"
        ),
        "test_todo.py": (
            b"import unittest\n"
            b"from todo import add, complete\n\n"
            b"class TodoTests(unittest.TestCase):\n"
            b"    def test_add_keeps_existing_items(self):\n"
            b"        self.assertEqual(add(['feed cat'], 'walk dog'), ['feed cat', 'walk dog'])\n\n"
            b"    def test_complete_removes_only_selected_item(self):\n"
            b"        todos = ['walk dog', 'feed cat', 'walk dog']\n"
            b"        self.assertEqual(complete(todos, 'walk dog'), ['feed cat'])\n\n"
            b"if __name__ == '__main__':\n"
            b"    unittest.main()\n"
        ),
    }


VALID_TODO_TEST_COMMANDS = {
    ("python3", "-m", "unittest", "-v", "test_todo"),
    ("python3", "-m", "unittest", "-v", "test_todo.py"),
}


def validate_live_form(form_data):
    if form_data.get("allowed_changes") != ["todo.py"] or form_data.get("plugins") != []:
        raise RuntimeError(f"Live draft widened scope or changed plugins: {form_data}")
    steps = form_data.get("steps", [])
    if not steps or len(steps) not in {1, 2}:
        raise RuntimeError(f"Live acceptance requires one implementation step and optional inspection step: {steps}")
    if len(steps) == 2:
        inspect = steps[0]
        inspect_checks = inspect.get("checks", [])
        if (inspect.get("id") != "inspect_files" or inspect.get("approval", False)
                or {check.get("path") for check in inspect_checks} != {"todo.py", "test_todo.py"}
                or any(check.get("type") != "file_exists"
                       or check.get("path") not in {"todo.py", "test_todo.py"}
                       for check in inspect_checks)):
            raise RuntimeError(f"Optional first step is not a read-only fixture inspection: {inspect}")
    if not steps[-1].get("approval"):
        raise RuntimeError("Live draft is missing its final approval checkpoint")
    checks = steps[-1].get("checks", [])
    for step in steps:
        for check in step.get("checks", []):
            if check.get("type") == "no_changes":
                raise RuntimeError("The live draft added a no_changes gate against its requested edit")
            if check.get("type") == "command" and tuple(check.get("argv", [])) not in VALID_TODO_TEST_COMMANDS:
                raise RuntimeError(f"The live draft added an unrelated command check: {check}")
    if not any(check.get("type") == "command" and tuple(check.get("argv", [])) in VALID_TODO_TEST_COMMANDS
               for check in checks):
        raise RuntimeError(f"Live draft omitted the real unittest check: {checks}")
    return len(steps)


def workspace_files(root, *, allow_ignored_pycache=False):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Saved run workspace is missing or not a real directory")
    if (root / ".git").is_symlink() or not (root / ".git").is_dir():
        raise RuntimeError("Saved run workspace is missing its local Git baseline")
    files = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git":
            continue
        if allow_ignored_pycache and relative.parts[0] == "__pycache__":
            if path.is_symlink():
                raise RuntimeError("Saved workspace contains a symlink in __pycache__")
            if path.is_dir():
                continue
            if path.is_file() and path.suffix == ".pyc":
                continue
            raise RuntimeError(f"Saved workspace contains an unexpected cache entry: {relative}")
        if path.is_symlink():
            raise RuntimeError(f"Saved workspace contains a symlink: {relative}")
        if path.is_dir():
            raise RuntimeError(f"Saved workspace contains an unexpected directory: {relative}")
        if not path.is_file():
            raise RuntimeError(f"Saved workspace contains a non-file entry: {relative}")
        files[relative.as_posix()] = path.read_bytes()
    return files


def validate_retained_run(data, original, chat_id, form_data, expected_files):
    import yaml

    run_root = data / "runs"
    if run_root.is_symlink() or not run_root.is_dir():
        raise RuntimeError("Resume-run requires the retained run directory")
    entries = list(run_root.iterdir())
    state_files = sorted(run_root.glob("*/state.json"))
    if len(entries) != 1 or len(state_files) != 1 or entries[0].is_symlink():
        raise RuntimeError("Resume-run requires exactly one regular saved run")
    state_file = state_files[0]
    run_dir = state_file.parent
    if state_file.is_symlink() or run_dir.is_symlink() or run_dir.resolve().parent != run_root.resolve():
        raise RuntimeError("Saved run must be a direct, regular child of the retained fixture")
    state = json.loads(state_file.read_text())
    run_id = state.get("id")
    if run_id != run_dir.name:
        raise RuntimeError("Saved run ID does not match its fixture directory")
    if (state.get("status") != "paused" or state.get("phase") != "interrupted"
            or state.get("step") != "inspect_files" or state.get("turns") != 1
            or state.get("attempts") != 1 or state.get("history") != []
            or state.get("result") is not None or state.get("evaluation") is not None
            or not state.get("session")):
        raise RuntimeError("Resume-run requires the paused, interrupted first inspection turn")
    if state.get("chat_id") != chat_id:
        raise RuntimeError("Saved run is not tied to the retained fixture chat")
    if state.get("original_root") != str(original.resolve()):
        raise RuntimeError("Saved run original_root does not match the retained project")
    workspace = run_dir / "workspace"
    expected_workspace = run_dir.resolve() / "workspace"
    if (state.get("in_place") is not False or state.get("workspace_kind") != "local_copy"
            or Path(state.get("root", "")).resolve() != expected_workspace):
        raise RuntimeError("Saved run does not point to its protected local-copy workspace")
    if state.get("allowed_changes") != ["todo.py"]:
        raise RuntimeError("Saved run allowlist is not pinned to todo.py")
    expected_hashes = {name: hashlib.sha256(content).hexdigest()
                       for name, content in expected_files.items()}
    if state.get("scope_hashes") != expected_hashes:
        raise RuntimeError("Saved run's scope baseline does not match the original fixture bytes")
    actual_workspace = workspace_files(workspace)
    if actual_workspace != expected_files:
        raise RuntimeError("Saved workspace has partial or extra writes; refusing to repeat the interrupted turn")

    if len(form_data.get("steps", [])) != 2 or form_data["steps"][0].get("id") != "inspect_files":
        raise RuntimeError("Resume-run requires the saved inspection step as its current first step")
    snapshot_path = run_dir / "workflow" / "workflow.yaml"
    if snapshot_path.is_symlink() or not snapshot_path.is_file():
        raise RuntimeError("Saved run is missing its immutable workflow snapshot")
    snapshot = yaml.safe_load(snapshot_path.read_text())
    if snapshot.get("allowed_changes") != ["todo.py"] or snapshot.get("plugins", []) != []:
        raise RuntimeError("Saved workflow snapshot changed the pinned scope or plugin grant")
    snap_steps = snapshot.get("steps", [])
    form_steps = form_data["steps"]
    if len(snap_steps) != len(form_steps):
        raise RuntimeError("Saved workflow step count differs from the reviewed form")
    for form_step, snap_step in zip(form_steps, snap_steps):
        if (form_step.get("id") != snap_step.get("id")
                or form_step.get("checks", []) != snap_step.get("checks", [])
                or bool(form_step.get("approval", False)) != bool(snap_step.get("approval", False))):
            raise RuntimeError("Saved workflow checks or approval gates differ from the reviewed form")
    saved_job = state.get("job", {})
    if (saved_job.get("name") != form_data.get("name") or saved_job.get("goal") != form_data.get("goal")
            or saved_job.get("constraints") != form_data.get("constraints")
            or saved_job.get("allowed_changes") != ["todo.py"] or saved_job.get("plugins") != []):
        raise RuntimeError("Saved run preview changed the pinned scope or plugins")
    job_steps = saved_job.get("steps", [])
    if len(job_steps) != len(form_steps) or any(
            job_step.get("id") != form_step.get("id")
            or job_step.get("checks", []) != form_step.get("checks", [])
            or bool(job_step.get("review")) != bool(form_step.get("approval", False) or not form_step.get("checks"))
            for form_step, job_step in zip(form_steps, job_steps)):
        raise RuntimeError("Saved run preview gates differ from the reviewed form")
    grants_path = run_dir / "plugin-grants.json"
    if grants_path.is_symlink() or not grants_path.is_file() or json.loads(grants_path.read_text()).get("plugins") != []:
        raise RuntimeError("Saved run contains an unexpected plugin grant")
    lock_path = run_dir / "run.lock"
    if not lock_path.is_file() or lock_path.is_symlink():
        raise RuntimeError("Saved run lock is missing or invalid")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Saved fixture run is still active; refusing duplicate resume") from exc
    return {"id": run_id, "path": run_dir, "workspace": workspace, "state": state}


def validate_report_recovery_run(data, original, chat_id, form_data, expected_files):
    """Validate the retained real turn before restoring only its completion report."""
    import yaml

    run_root = data / "runs"
    entries = list(run_root.iterdir()) if run_root.is_dir() and not run_root.is_symlink() else []
    state_files = sorted(run_root.glob("*/state.json")) if entries else []
    if len(entries) != 1 or len(state_files) != 1 or entries[0].is_symlink():
        raise RuntimeError("Report recovery requires exactly one regular saved run")
    state_file = state_files[0]
    run_dir = state_file.parent
    if (state_file.is_symlink() or run_dir.is_symlink()
            or run_dir.resolve().parent != run_root.resolve()):
        raise RuntimeError("Saved run must be a direct, regular child of the retained fixture")
    state = json.loads(state_file.read_text())
    if state.get("id") != run_dir.name:
        raise RuntimeError("Saved run ID does not match its fixture directory")
    history = state.get("history", [])
    if history != [{"step": "inspect_files", "outcome": "passed", "attempts": 2, "turn": 2}]:
        raise RuntimeError("Report recovery requires the saved passed inspection history")
    if state.get("chat_id") != chat_id:
        raise RuntimeError("Saved run is not tied to the retained fixture chat")
    if state.get("original_root") != str(original.resolve()):
        raise RuntimeError("Saved run original_root does not match the retained project")
    if (state.get("in_place") is not False or state.get("workspace_kind") != "local_copy"
            or Path(state.get("root", "")).resolve() != (run_dir.resolve() / "workspace")):
        raise RuntimeError("Saved run does not point to its protected local-copy workspace")
    if state.get("allowed_changes") != ["todo.py"]:
        raise RuntimeError("Saved run allowlist is not pinned to todo.py")
    expected_hashes = {name: hashlib.sha256(content).hexdigest()
                       for name, content in expected_files.items()}
    if state.get("scope_hashes") != expected_hashes:
        raise RuntimeError("Saved run's scope baseline does not match the original fixture bytes")

    workspace = run_dir / "workspace"
    actual = workspace_files(workspace, allow_ignored_pycache=True)
    if set(actual) != set(expected_files):
        raise RuntimeError(f"Report recovery found unexpected or missing workspace files: {sorted(actual)}")
    for name, content in expected_files.items():
        if name != "todo.py" and actual[name] != content:
            raise RuntimeError(f"Report recovery found a changed protected fixture file: {name}")
    if actual["todo.py"] == expected_files["todo.py"]:
        raise RuntimeError("Report recovery requires the actual todo.py fix from the saved turn")
    if "return [todo for todo in todos if todo != item]" not in actual["todo.py"].decode("utf-8"):
        raise RuntimeError("Saved todo.py does not contain the intended tested fix")

    if len(form_data.get("steps", [])) != 2 or form_data["steps"][-1].get("id") != "fix_todo_bug":
        raise RuntimeError("Report recovery requires the saved two-step inspection and fix form")
    snapshot_path = run_dir / "workflow" / "workflow.yaml"
    if snapshot_path.is_symlink() or not snapshot_path.is_file():
        raise RuntimeError("Saved run is missing its immutable workflow snapshot")
    snapshot = yaml.safe_load(snapshot_path.read_text())
    if (snapshot.get("allowed_changes") != ["todo.py"] or snapshot.get("plugins", []) != []
            or snapshot.get("name") != form_data.get("name")
            or snapshot.get("max_turns") != form_data.get("max_turns")):
        raise RuntimeError("Saved workflow snapshot changed the pinned scope or plugin grant")
    snap_steps = snapshot.get("steps", [])
    form_steps = form_data["steps"]
    if len(snap_steps) != len(form_steps):
        raise RuntimeError("Saved workflow step count differs from the reviewed form")
    for form_step, snap_step in zip(form_steps, snap_steps):
        if (form_step.get("id") != snap_step.get("id")
                or form_step.get("checks", []) != snap_step.get("checks", [])
                or bool(form_step.get("approval", False)) != bool(snap_step.get("approval", False))):
            raise RuntimeError("Saved workflow checks or approval gates differ from the reviewed form")
        prompt_path = run_dir / "workflow" / snap_step.get("prompt", "")
        if (prompt_path.is_symlink() or not prompt_path.is_file()
                or form_step.get("prompt", "") not in prompt_path.read_text()):
            raise RuntimeError("Saved workflow prompt differs from the reviewed form")
    saved_job = state.get("job", {})
    if (saved_job.get("name") != form_data.get("name") or saved_job.get("goal") != form_data.get("goal")
            or saved_job.get("constraints") != form_data.get("constraints")
            or saved_job.get("allowed_changes") != ["todo.py"] or saved_job.get("plugins") != []):
        raise RuntimeError("Saved run preview changed the reviewed scope or plugin grant")
    grants_path = run_dir / "plugin-grants.json"
    if (grants_path.is_symlink() or not grants_path.is_file()
            or json.loads(grants_path.read_text()) != {"version": 1, "plugins": []}):
        raise RuntimeError("Saved run contains an unexpected plugin grant")

    turn_dir = run_dir / "turns" / "003"
    answer_path = turn_dir / "answer.json"
    schema_path = turn_dir / "schema.json"
    events_path = run_dir / "events.jsonl"
    if any(path.is_symlink() or not path.is_file() for path in (answer_path, schema_path, events_path)):
        raise RuntimeError("Report recovery requires the saved answer, schema, and event log")
    raw_answer = answer_path.read_text()
    raw_sha = hashlib.sha256(raw_answer.encode()).hexdigest()
    schema = json.loads(schema_path.read_text())
    from dog_walker.worker import SCHEMA, parse_completion
    if schema != SCHEMA:
        raise RuntimeError("Saved turn schema differs from the current strict completion schema")
    result, normalized = parse_completion(raw_answer)
    if not normalized or result.get("blockers") != [] or result.get("status") != "completed":
        raise RuntimeError("Saved raw report was not normalized solely by adding empty blockers metadata")

    events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    recovery_events = [row for row in events if row.get("type") == "test_only_report_recovered"]
    if len(recovery_events) > 1:
        raise RuntimeError("Saved run contains duplicate test-only report recovery events")
    codex_turn = [row["event"] for row in events
                  if row.get("type") == "codex" and row.get("turn") == 3]
    completed = [event for event in codex_turn if event.get("type") == "turn.completed"]
    if len(completed) != 1:
        raise RuntimeError("Saved Codex turn 3 does not have exactly one completed turn event")
    command_records = [event["item"] for event in codex_turn
                       if event.get("type") == "item.completed"
                       and event.get("item", {}).get("type") == "command_execution"]
    if not command_records or not any(
            record.get("exit_code") == 0 and "python3 test_todo.py" in record.get("command", "")
            for record in command_records):
        raise RuntimeError("Saved Codex turn has no successful real todo test command")
    messages = [event.get("item", {}).get("text", "") for event in codex_turn
                if event.get("type") == "item.completed"
                and event.get("item", {}).get("type") == "agent_message"]
    matching_messages = []
    for message in messages:
        try:
            message_result, message_normalized = parse_completion(message)
        except Exception:
            continue
        if message_normalized and message_result == result:
            matching_messages.append(message)
    if not matching_messages:
        raise RuntimeError("Saved answer does not match the completed Codex turn message")

    already_recovered = bool(recovery_events)
    expected_recovery_event = {
        "type": "test_only_report_recovered", "turn": 3, "step": "fix_todo_bug",
        "normalized": True, "filled_field": "blockers", "value": [],
        "raw_answer_sha256": raw_sha, "source": "harness-flow-acceptance",
        "coding_worker_replayed": False,
    }
    if already_recovered:
        if any(recovery_events[0].get(key) != value for key, value in expected_recovery_event.items()):
            raise RuntimeError("Saved test-only recovery event does not match the validated raw report")
        if (state.get("status") != "paused" or state.get("phase") not in {"evaluating", "reviewing"}
                or state.get("step") != "fix_todo_bug" or state.get("turns") != 3
                or state.get("attempts") != 1 or not state.get("session")
                or state.get("result") != result or state.get("commands") != command_records
                or not isinstance(state.get("evaluation"), dict)):
            raise RuntimeError("Saved recovered run state does not match its report and actual command events")
    elif (state.get("status") != "paused" or state.get("phase") != "interrupted"
          or state.get("step") != "fix_todo_bug" or state.get("turns") != 3
          or state.get("attempts") != 1 or not state.get("session")
          or state.get("result") is not None
          or state.get("evaluation") is not None):
        raise RuntimeError("An unrecovered report requires the original paused turn-3 interrupted state")

    lock_path = run_dir / "run.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise RuntimeError("Saved run lock is missing or invalid")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Saved fixture run is still active; refusing duplicate recovery") from exc
    return {"id": state["id"], "path": run_dir, "workspace": workspace, "state": state,
            "result": result, "commands": command_records, "raw_answer_sha256": raw_sha,
            "already_recovered": already_recovered}


class ScriptedChat:
    def __init__(self, _emit):
        pass

    async def ready(self):
        pass

    async def reply(self, _conversation, _prompt, draft):
        if not draft:
            return "Fixture chat reply."
        return json.dumps(plan())


class ScriptedWorker:
    calls = 0

    def __init__(self, store, _emit, _no_start):
        self.store = store

    async def ready(self):
        pass

    async def turn(self, _prompt, _timeout):
        type(self).calls += 1
        root = Path(self.store.state["root"])
        (root / "todo.py").write_text(
            "def add(todos, item):\n"
            "    return [*todos, item]\n\n"
            "def complete(todos, item):\n"
            "    return [todo for todo in todos if todo != item]\n"
        )
        (root / "test_todo.py").write_text(
            "import unittest\n"
            "from todo import add, complete\n\n"
            "class TodoTests(unittest.TestCase):\n"
            "    def test_add_and_complete(self):\n"
            "        todos = add([], 'walk dog')\n"
            "        self.assertEqual(todos, ['walk dog'])\n"
            "        self.assertEqual(complete(todos, 'walk dog'), [])\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        import subprocess
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-m", "unittest", "-v", "test_todo"],
                                cwd=root, env=env, capture_output=True, text=True, timeout=20)
        output = (result.stdout + result.stderr)[-4000:]
        if result.returncode:
            return {"status": "blocked", "summary": "Fixture unittest failed.",
                    "evidence": [output], "files_changed": ["todo.py", "test_todo.py"],
                    "blockers": ["unittest failed"]}, []
        return {"status": "completed", "summary": "Implemented and tested the todo helper.",
                "evidence": ["python -m unittest -v test_todo passed", output],
                "files_changed": ["todo.py", "test_todo.py"], "blockers": []}, []


@contextmanager
def host_desktop_lease():
    """Lock the installed app before importing it or changing isolation env."""
    host_data = Path(os.environ.get("DOG_WALKER_DATA", Path.home() / ".local/share/dog-walker")).expanduser()
    lock_path = host_data / "desktop-worker.lock"
    if not host_data.is_dir() or not lock_path.is_file():
        raise RuntimeError(f"Cannot verify the installed app is idle: missing {lock_path}")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("The installed app is using the local model; live acceptance refused") from exc
        run_locks = []
        try:
            for state_file in sorted((host_data / "runs").glob("*/state.json")):
                run_lock_path = state_file.parent / "run.lock"
                if not run_lock_path.exists():
                    continue
                run_lock = run_lock_path.open("a")
                try:
                    fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    run_lock.close()
                    raise RuntimeError(f"A saved run is active ({state_file.parent.name}); live acceptance refused") from exc
                run_locks.append(run_lock)
            yield host_data
        finally:
            for run_lock in reversed(run_locks):
                run_lock.close()


def live_host_preflight(host_data):
    from dog_walker import settings, storage, worker
    from dog_walker.runtime import verify_runtime

    if storage.DATA.resolve() != host_data.resolve():
        raise RuntimeError("DOG_WALKER_DATA changed during preflight; live acceptance refused")
    worker.reload_settings()
    if worker.START_COMMAND != []:
        raise RuntimeError("Live acceptance requires start_command=[] so it cannot start or switch services")
    readiness = verify_runtime(worker.MODEL_PATH, worker.ENDPOINT, timeout=3)
    if not readiness.get("ready"):
        raise RuntimeError("Current local model is not ready: " + str(readiness.get("reason", "unknown readiness failure")))
    if readiness.get("slots_idle", 0) < 1 or readiness.get("slots_processing", 0) != 0:
        raise RuntimeError("Current local model is busy; live acceptance refused")
    return {"model_id": settings.model_summary()["model_id"],
            "slots_idle": readiness.get("slots_idle"),
            "slots_processing": readiness.get("slots_processing")}


async def wait_for_review(app):
    async with asyncio.timeout(1200):
        while app.review is None or app.review.done():
            if app.task and app.task.done():
                state = app.store.state if app.store else {}
                detail = {key: state.get(key) for key in ("status", "phase", "step")}
                detail["reason"] = str(state.get("reason") or "")[:600]
                raise RuntimeError(f"Run ended before review: {detail}")
            await asyncio.sleep(0.01)


async def wait_for_new_review(app, previous_id):
    async with asyncio.timeout(1200):
        while app.review is None or app.review.done() or app.review_id == previous_id:
            if app.task and app.task.done():
                state = app.store.state if app.store else {}
                detail = {key: state.get(key) for key in ("status", "phase", "step")}
                detail["reason"] = str(state.get("reason") or "")[:600]
                raise RuntimeError(f"Resumed run ended before final review: {detail}")
            await asyncio.sleep(0.01)


async def drive(temp_root, live=False, model=None, resume_draft=False, resume_run=False,
               recover_report=False):
    from dog_walker import chat, desktop, engine, forms, settings, storage, worker
    from dog_walker.desktop import Desktop

    data = temp_root / "data"
    os.environ["DOG_WALKER_DATA"] = str(data)
    os.environ["DOG_WALKER_INBOX"] = str(temp_root / "inbox")
    (data / "codex-home").mkdir(parents=True, mode=0o700, exist_ok=True)
    for module in (chat, desktop, forms, storage, worker):
        module.DATA = data
    if not live:
        settings.CONFIG = temp_root / "worker.json"
        worker.reload_settings()

    original = temp_root / "selected-project"
    resume_existing = resume_draft or resume_run or recover_report
    if live:
        contents = live_fixture_contents()
        if not original.is_dir():
            if resume_existing:
                raise RuntimeError(f"Retained fixture is missing selected-project: {original}")
            original.mkdir()
            for name, content in contents.items():
                (original / name).write_bytes(content)
            import subprocess
            initial = subprocess.run([sys.executable, "-m", "unittest", "-v", "test_todo"],
                                     cwd=original,
                                     env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                     capture_output=True, text=True, timeout=20)
            if initial.returncode == 0 or "AssertionError" not in initial.stdout + initial.stderr:
                raise RuntimeError("Live fixture did not reproduce its intended todo bug")
        elif not resume_existing:
            raise RuntimeError(f"Refusing to overwrite existing live fixture: {original}")
        expected_root = temp_root.resolve() / "selected-project"
        if original.is_symlink() or original.resolve() != expected_root:
            raise RuntimeError("Live fixture selected-project must be a real directory directly under its fixture root")
        for name, content in contents.items():
            path = original / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
                raise RuntimeError(f"Live fixture source changed or is invalid: {path}")
        if original.resolve() != (temp_root / "selected-project").resolve():
            raise RuntimeError("Live fixture project path does not match selected-project")
        untouched = dict(contents)
    else:
        original.mkdir()
        (original / ".gitignore").write_text("__pycache__/\n")
        protected = original / "brief.md"
        source_bytes = b"Keep this fixture file byte-for-byte unchanged.\n"
        protected.write_bytes(source_bytes)
        untouched = {"brief.md": source_bytes}
    events = []
    engine_factory = None if live else lambda store, emit, ask: engine.Engine(
        store, emit, ask, worker_factory=ScriptedWorker)

    app = Desktop(events.append, engine_factory=engine_factory,
                  chat_factory=None if live else ScriptedChat)
    saved_run = None
    if resume_existing:
        chat_root = data / "chats"
        if data.is_symlink() or chat_root.is_symlink() or not chat_root.is_dir():
            raise RuntimeError("Resume chat data must stay inside the retained fixture")
        chats = sorted(chat_root.glob("*/chat.json"))
        if len(chats) != 1:
            raise RuntimeError(f"Resume requires exactly one saved chat, found {len(chats)}")
        if chats[0].is_symlink() or chats[0].parent.is_symlink():
            raise RuntimeError("Resume chat metadata must be a regular local file")
        if not chats[0].parent.resolve().is_relative_to(chat_root.resolve()):
            raise RuntimeError("Resume chat directory resolves outside the retained fixture")
        if resume_draft and any((data / "runs").glob("*")):
            raise RuntimeError("Resume requires a fixture with no prior runs")
        saved = json.loads(chats[0].read_text())
        if saved.get("id") != chats[0].parent.name:
            raise RuntimeError("Saved chat ID does not match its fixture directory")
        if saved.get("project") != str(original.resolve()) or saved.get("project_id") is not None:
            raise RuntimeError("Saved chat does not point exactly to the selected-project fixture")
        if any(message.get("status") == "working" for message in saved.get("messages", [])):
            raise RuntimeError("Resume requires the saved chat reply to be finished")
        if saved.get("selected_plugins", []) != []:
            raise RuntimeError("Resume requires the saved chat to have no selected plugins")
        if not isinstance(saved.get("draft"), dict) or not saved["draft"].get("id"):
            raise RuntimeError("Saved chat has no draft to resume")
        draft_id = saved["draft"]["id"]
        if not isinstance(draft_id, str) or not re.fullmatch(r"[a-f0-9]{32}", draft_id):
            raise RuntimeError("Saved chat has an invalid draft ID")
        draft_file = chats[0].parent / (draft_id + ".dogwalk")
        if draft_file.is_symlink() or not draft_file.is_file():
            raise RuntimeError("Saved chat draft file is missing or not a regular file")
        await app.handle({"op": "chat_open", "id": saved["id"]})
        chat_id = app.chat.value["id"]
        draft = app.chat.value["draft"]
    else:
        await app.handle({"op": "chat_new"})
        chat_id = app.chat.value["id"]
        await app.handle({"op": "chat_project", "chat_id": chat_id, "root": original.as_uri()})
        await app.handle({"op": "chat_draft", "chat_id": chat_id,
                          "text": ("Fix the existing bug in todo.py only. `complete(todos, item)` must "
                                   "remove every matching item and preserve all other todos. The existing "
                                   "test_todo.py has two real unit tests; one currently fails. Do not edit "
                                   "test_todo.py. Make a one-step plan scoped exactly to allowed_changes "
                                   "['todo.py'], use no plugins, include a command check for "
                                   "['python3', '-m', 'unittest', '-v', 'test_todo'], and require final "
                                   "approval. Do not install packages or touch any other file.") if live else
                                   "Build a tiny todo helper and test it.", "plugins": []})
        await app.chat_task
        draft = app.chat.value["draft"]
    if not draft:
        raise RuntimeError(f"Chat did not produce a draft: {app.chat.value['messages'][-2:]}")
    draft_path = app.chat.path / (draft["id"] + ".dogwalk")
    form_data = None
    draft_step_count = None
    if live:
        import yaml
        form_data = yaml.safe_load(draft_path.read_text())
        draft_step_count = validate_live_form(form_data)
        if resume_run:
            saved_run = validate_retained_run(data, original, chat_id, form_data, contents)
        if recover_report:
            saved_run = validate_report_recovery_run(data, original, chat_id, form_data, contents)

    preview_event = None
    if not (resume_run or recover_report):
        await app.handle({"op": "chat_use_draft", "chat_id": chat_id, "draft_id": draft["id"]})
        preview_event = next(event for event in reversed(events) if event["type"] == "job")
        if app.store is not None or any((data / "runs").glob("*")):
            raise RuntimeError("Drafting or preview unexpectedly started a run")

    retry_authorizations = 0
    initial_turns = None
    if resume_run:
        run_id = saved_run["id"]
        await app.handle({"op": "load", "id": run_id})
        if app.store.state["id"] != run_id:
            raise RuntimeError("Desktop loaded a different retained run")
        initial_turns = app.store.state["turns"]
        await app.handle({"op": "resume", "run_id": run_id})
        await wait_for_review(app)
        first_review_id = app.review_id
        state = app.store.state
        if (state["step"] != "inspect_files" or state["phase"] != "interrupted"
                or state["turns"] != initial_turns or state["result"] is not None
                or "Previous turn was interrupted" not in app.review_reason
                or workspace_files(state["root"]) != contents):
            raise RuntimeError("Interrupted inspection state or workspace changed before explicit retry")
        await app.handle({"op": "control", "action": "retry", "run_id": run_id,
                          "review_id": first_review_id, "source": "live_acceptance_retry"})
        retry_authorizations += 1
        await wait_for_new_review(app, first_review_id)
    elif recover_report:
        run_id = saved_run["id"]
        await app.handle({"op": "load", "id": run_id})
        if app.store.state["id"] != run_id:
            raise RuntimeError("Desktop loaded a different retained run")
        if app.store.state["turns"] != 3 or app.store.state["phase"] != saved_run["state"]["phase"]:
            raise RuntimeError("Retained run changed before report recovery")
        if not saved_run["already_recovered"]:
            app.store.event("test_only_report_recovered", turn=3, step="fix_todo_bug",
                            normalized=True, filled_field="blockers", value=[],
                            raw_answer_sha256=saved_run["raw_answer_sha256"],
                            source="harness-flow-acceptance", coding_worker_replayed=False)
            app.store.save(result=saved_run["result"], commands=saved_run["commands"],
                           phase="evaluating", reason=None)
        before_events = [json.loads(line) for line in (saved_run["path"] / "events.jsonl").read_text().splitlines()
                         if line.strip()]
        before_codex = sum(row.get("type") == "codex" for row in before_events)
        before_prompts = sum(row.get("type") == "prompt" for row in before_events)
        initial_turns = app.store.state["turns"]
        await app.handle({"op": "resume", "run_id": run_id})
        await wait_for_review(app)
        after_events = [json.loads(line) for line in (saved_run["path"] / "events.jsonl").read_text().splitlines()
                        if line.strip()]
        after_codex = sum(row.get("type") == "codex" for row in after_events)
        after_prompts = sum(row.get("type") == "prompt" for row in after_events)
        if (app.store.state["turns"] != initial_turns or after_codex != before_codex
                or after_prompts != before_prompts):
            raise RuntimeError("Report recovery replayed a coding worker turn or prompt")
        recovery_no_replay = True
    else:
        await app.handle({"op": "start", "root": original.as_uri(), "in_place": False, "auto": True})
        await wait_for_review(app)
    store = app.store
    checks = store.state["evaluation"]["checks"]
    if store.state["result"]["status"] != "completed":
        raise RuntimeError(f"Worker did not complete its fixture task: {store.state['result']}")
    if resume_run:
        history = store.state.get("history", [])
        if not any(item.get("step") == "inspect_files" and item.get("outcome") == "passed" for item in history):
            raise RuntimeError(f"Resumed inspection step did not pass: {history}")
        if store.state["turns"] < initial_turns + 2:
            raise RuntimeError("Run did not perform an explicit first-step retry and implementation turn")
    if recover_report and not recovery_no_replay:
        raise RuntimeError("Recovered report did not preserve the saved coding worker turn")
    if not all(check["pass"] for check in checks):
        raise RuntimeError(f"Authored checks failed: {checks}")
    if store.state["root"] == str(original) or store.state["in_place"]:
        raise RuntimeError("Start did not create a protected workspace copy")
    if any((original / name).read_bytes() != content for name, content in untouched.items()):
        raise RuntimeError("The original project fixture changed")
    if live and store.state["root"] and store.state["evaluation"]["checks"]:
        command_rows = [row for row in checks if row["type"] == "command"]
        if not command_rows or not all(row["pass"] for row in command_rows):
            raise RuntimeError(f"The run's authored unittest command did not pass: {command_rows}")
    if store.state["status"] not in {"running", "ready"}:
        raise RuntimeError(f"Unexpected status at review gate: {store.state['status']}")

    run_id, review_id = store.state["id"], app.review_id
    await app.handle({"op": "control", "action": "approve", "run_id": run_id,
                      "review_id": review_id,
                      "source": "live_acceptance" if live else "scripted_acceptance"})
    await app.task
    if store.state["status"] != "completed":
        raise RuntimeError(f"Approved run did not complete: {store.state['status']}")

    turns = store.state["turns"]
    await app.handle({"op": "chat_open", "id": chat_id})
    statuses = [message["status"] for message in app.chat.value["messages"]]
    if any(status == "working" for status in statuses):
        raise RuntimeError("Reopened conversation retained an active reply")
    await app.handle({"op": "chat_results", "chat_id": chat_id, "run_id": run_id})
    if store.state["turns"] != turns or (not live and ScriptedWorker.calls != 1):
        raise RuntimeError("Reopening results replayed the worker turn")
    if "completed" not in app.chat.value["messages"][-1]["text"]:
        raise RuntimeError("Recovered chat results did not include the completed status")
    if any((original / name).read_bytes() != content for name, content in untouched.items()):
        raise RuntimeError("The original project fixture changed after approval")

    return {
        "kind": "live desktop flow acceptance" if live else "scripted desktop flow acceptance",
        "model_inference": bool(live),
        "chat_provider": "current local ChatWorker" if live else "scripted valid portable form",
        "coding_worker": "current local CodexWorker" if live else "scripted fixture writer; runs the fixture unittest suite",
        "model": model if live else None,
        "requested_step_count": 1 if live else None,
        "draft_step_count": len(form_data["steps"]) if live else None,
        "request_step_count_honored": len(form_data["steps"]) == 1 if live else None,
        "controller_engine_store_and_checks": "real application code",
        "approval_source": "test-only live_acceptance" if live else "test-only scripted_acceptance",
        "operations": (["chat_open existing chat", "load paused run", "test-only normalize saved completed report",
                         "resume at evaluation without coding worker replay"] if recover_report else
                       ["chat_open existing chat", "load paused run", "resume", "test-only retry of interrupted inspection"]
                       if resume_run else ["chat_open existing draft", "chat_use_draft"] if resume_draft else
                        ["chat_new", "chat_project", "chat_draft", "chat_use_draft"]) + [
                       *([] if resume_run or recover_report else ["start protected copy"]),
                       "final approval", "chat_open", "chat_results"],
        "draft_reused": bool(resume_draft or resume_run or recover_report),
        "run_resumed": bool(resume_run or recover_report),
        "report_recovered": bool(recover_report),
        "coding_worker_replayed": False if recover_report and recovery_no_replay else None,
        "retry_authorizations": retry_authorizations,
        "interrupted_retry_source": "test-only live_acceptance_retry" if resume_run else None,
        "turns_before_resume": initial_turns,
        "turns_recovered": store.state["turns"] - initial_turns if resume_run else 0 if recover_report else None,
        "run_id": run_id,
        "status": store.state["status"],
        "workspace_kind": store.state["workspace_kind"],
        "original_unchanged": all((original / name).read_bytes() == content for name, content in untouched.items()),
        "checks": checks,
        "fixture_unittest": "passed" if live else "passed by scripted fixture worker",
        "worker_turns_after_recovery": turns,
        "worker_calls": turns if live else ScriptedWorker.calls,
        "draft_previewed_before_start": (saved_run["state"].get("job", {}).get("name") == draft["name"]
                                          if resume_run or recover_report else
                                          bool(draft_path.is_file() and preview_event["job"]["name"] == draft["name"])),
        "results_recovered_to_chat": True,
        "fixture_root": str(temp_root.resolve()) if live else None,
        "app_data": str(data.resolve()) if live else None,
        "project_root": str(original.resolve()) if live else None,
    }


def validate_resume_fixture(value, option="--resume-draft"):
    candidate = Path(value)
    artifacts = (REPO_ROOT / "artifacts").resolve(strict=True)
    if not candidate.is_absolute():
        raise RuntimeError(f"{option} requires an absolute fixture directory")
    if candidate.is_symlink():
        raise RuntimeError(f"{option} does not accept a symlink")
    try:
        fixture = candidate.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Retained live fixture is unavailable: {exc}") from exc
    if (not fixture.is_dir() or fixture.parent != artifacts
            or not fixture.name.startswith("harness-live-")):
        raise RuntimeError(f"{option} must name a harness-live-* directory directly under this repository's artifacts")
    return fixture


def run(output_path, live=False, resume_draft=None, resume_run=None, recover_report=None):
    ScriptedWorker.calls = 0
    output_path = Path(output_path)
    report = None
    live_temp = None
    try:
        recovery_modes = [resume_draft is not None, resume_run is not None, recover_report is not None]
        if sum(recovery_modes) > 1:
            raise RuntimeError("Choose only one of --resume-draft, --resume-run, or --recover-report")
        if any(recovery_modes) and not live:
            raise RuntimeError("--resume-draft, --resume-run, and --recover-report require --live")
        if resume_draft is not None:
            live_temp = validate_resume_fixture(resume_draft, "--resume-draft")
        elif resume_run is not None:
            live_temp = validate_resume_fixture(resume_run, "--resume-run")
        elif recover_report is not None:
            live_temp = validate_resume_fixture(recover_report, "--recover-report")
        if live:
            with host_desktop_lease() as host_data:
                model = live_host_preflight(host_data)
                if live_temp is None:
                    artifacts = REPO_ROOT / "artifacts"
                    artifacts.mkdir(exist_ok=True)
                    live_temp = Path(tempfile.mkdtemp(prefix="harness-live-", dir=artifacts))
                report = asyncio.run(drive(live_temp, live=True, model=model,
                                           resume_draft=resume_draft is not None,
                                           resume_run=resume_run is not None,
                                           recover_report=recover_report is not None))
        else:
            with tempfile.TemporaryDirectory(prefix="dog-walker-flow-") as name:
                report = asyncio.run(drive(Path(name)))
    except Exception as exc:
        report = {"kind": "live desktop flow acceptance" if live else "scripted desktop flow acceptance",
                  "status": "failed", "model_inference": bool(live), "error": str(exc),
                  "fixture_root": str(live_temp.resolve()) if live_temp else None,
                  "app_data": str((live_temp / "data").resolve()) if live_temp else None,
                  "project_root": str((live_temp / "selected-project").resolve()) if live_temp else None}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), file=sys.stderr)
        raise
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="use the current healthy local model; never starts or switches a service")
    resume = parser.add_mutually_exclusive_group()
    resume.add_argument("--resume-draft", type=Path,
                        help="continue a saved draft in an absolute artifacts/harness-live-* fixture without drafting again")
    resume.add_argument("--resume-run", type=Path,
                        help="resume the paused interrupted run in an absolute artifacts/harness-live-* fixture")
    resume.add_argument("--recover-report", type=Path,
                        help="recover only the missing empty blockers field from a completed turn-3 report in a retained fixture")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    default_name = ("harness-flow-acceptance-recover-report.json" if args.recover_report else
                    "harness-flow-acceptance-resume-run.json" if args.resume_run else
                    "harness-flow-acceptance-live.json" if args.live else
                    "harness-flow-acceptance.json")
    default = Path("artifacts") / default_name
    run(args.output or default, live=args.live, resume_draft=args.resume_draft,
        resume_run=args.resume_run, recover_report=args.recover_report)
