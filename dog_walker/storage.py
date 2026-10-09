"""Crash-resistant local runs and immutable workflow snapshots."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone
from uuid import uuid4
from .workflow import WalkerError, load_workflow

APP_ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("DOG_WALKER_DATA", Path.home() / ".local/share/dog-walker"))


def scrub(value):
    """Redact common credentials from logs; local run data may still contain private project text."""
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", value)
        value = re.sub(r"\b(?:sk-|hf_)[A-Za-z0-9_-]{16,}\b", "[REDACTED]", value)
        value = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|password)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.fullmatch(r"(?i).*password|.*api[_-]?key|.*access[_-]?token", str(k)) else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def atomic_json(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as handle:
        json.dump(scrub(value), handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise WalkerError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def digest(path):
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lock = None
        self.state = json.loads((self.path / "state.json").read_text())

    @classmethod
    def create(cls, workflow, root, auto=False, in_place=False):
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            raise WalkerError(f"Project folder does not exist: {root}")
        if not in_place and git(root, "status", "--porcelain"):
            raise WalkerError("Project has uncommitted files. Commit them first or use --in-place to work on the current files.")
        ident = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
        path = DATA / "runs" / ident
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
        snap = path / "workflow"
        snap.mkdir()
        shutil.copy2(workflow.root / "workflow.yaml", snap / "workflow.yaml")
        for spec in workflow.steps.values():
            for field in ("prompt", "retry_prompt"):
                if spec.get(field):
                    destination = snap / spec[field]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(workflow.root / spec[field], destination)
        work = root
        if not in_place:
            work = path / "workspace"
            git(root, "worktree", "add", "--detach", str(work), "HEAD")
        files = {c["path"] for s in workflow.steps.values() for c in s["checks"] if c["type"] == "unchanged"}
        state = dict(id=ident, name=workflow.name, original_root=str(root), root=str(work),
                     in_place=in_place, step=workflow.entry, phase="pending", status="ready", session=None,
                     auto=auto, attempts=0, turns=0, history=[], result=None, evaluation=None,
                     hashes={f: digest(work / f) for f in files}, created=datetime.now(timezone.utc).isoformat())
        atomic_json(path / "state.json", state)
        return cls(path)

    @classmethod
    def open(cls, ident):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", ident):
            raise WalkerError("Invalid run ID")
        path = DATA / "runs" / ident
        if not (path / "state.json").is_file():
            raise WalkerError(f"Run not found: {ident}")
        return cls(path)

    def acquire(self):
        self.lock = (self.path / "run.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            self.lock = None
            raise WalkerError("This run is already open in another Dog Walker") from exc

    def release(self):
        if self.lock:
            self.lock.close()
            self.lock = None

    def save(self, **updates):
        self.state.update(updates)
        atomic_json(self.path / "state.json", self.state)

    def event(self, kind, **payload):
        value = scrub(dict(time=datetime.now(timezone.utc).isoformat(), type=kind, **payload))
        with (self.path / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return value

    def workflow(self):
        return load_workflow(self.path / "workflow")
