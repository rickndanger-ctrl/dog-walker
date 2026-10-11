"""Saved project folders and small desktop preferences."""
from datetime import datetime, timezone
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import re
from uuid import uuid4

from .storage import DATA, atomic_json
from .workflow import WalkerError


PROJECTS_FILE = "projects.json"
PREFERENCES_FILE = "preferences.json"
PROJECTS_LOCK = "projects.lock"
PREFERENCES_LOCK = "preferences.lock"
_ID = re.compile(r"[a-f0-9]{32}")
_UNSAFE_PARTS = {".ssh", ".codex", ".config", ".local", ".gnupg", ".aws", ".azure"}


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _exclusive(name):
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (DATA / name).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def validate_root(value):
    if not isinstance(value, str) or not value:
        raise WalkerError("Choose an existing project folder")
    root = Path(value).expanduser().resolve()
    home = Path.home().resolve()
    data = DATA.expanduser().resolve()
    if not root.is_dir():
        raise WalkerError("Choose an existing project folder")
    if root == Path(root.anchor) or root == home or home.is_relative_to(root):
        raise WalkerError("Choose a dedicated project folder, not a home or system folder")
    if root.is_relative_to(data) or data.is_relative_to(root):
        raise WalkerError("Choose a project folder outside Dog Walker's private data folder")
    if any(part in _UNSAFE_PARTS or part.startswith(".env") for part in root.parts):
        raise WalkerError("Choose a project folder that does not contain credentials or private settings")
    return root


def _read():
    path = DATA / PROJECTS_FILE
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise WalkerError("Saved projects could not be read. Fix projects.json before changing the library.") from exc
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("projects"), list):
        raise WalkerError("Saved projects file is invalid. Fix projects.json before changing the library.")
    checked = []
    for item in value["projects"]:
        valid = isinstance(item, dict)
        if valid:
            ident, name, root, created, updated = (item.get(k) for k in ("id", "name", "root", "created", "updated"))
            try:
                datetime.fromisoformat(created) if isinstance(created, str) else None
                datetime.fromisoformat(updated) if isinstance(updated, str) else None
                dates_valid = isinstance(created, str) and isinstance(updated, str)
            except ValueError:
                dates_valid = False
            valid = (
                isinstance(ident, str) and bool(_ID.fullmatch(ident))
                and isinstance(name, str) and bool(name.strip()) and name == name.strip() and len(name) <= 80
                and isinstance(root, str) and Path(root).is_absolute()
                and dates_valid and type(item.get("archived")) is bool
            )
        if not valid:
            raise WalkerError("Saved projects file is invalid. Fix projects.json before changing the library.")
        checked.append(dict(item))  # Preserve fields written by newer app versions.
    if len({item["id"] for item in checked}) != len(checked):
        raise WalkerError("Saved projects file has duplicate IDs. Fix projects.json before changing the library.")
    return checked


def list_projects(include_archived=True):
    values = _read()
    result = []
    for item in values:
        root = Path(item["root"])
        # Keep records visible even when a folder is offline or has moved. The
        # UI can explain that the folder needs attention without losing chats.
        result.append({**item, "available": root.is_dir()})
    return result if include_archived else [item for item in result if not item["archived"]]


def get_project(project_id, include_archived=True):
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise WalkerError("Invalid project ID")
    item = next((p for p in _read() if p["id"] == project_id), None)
    if not item or (item["archived"] and not include_archived):
        raise WalkerError("Project not found")
    return item


def create_project(name, root):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise WalkerError("Project names must contain 1 to 80 characters")
    folder = validate_root(root)
    ident, timestamp = uuid4().hex, _now()
    item = {"id": ident, "name": name.strip(), "root": str(folder), "created": timestamp,
            "updated": timestamp, "archived": False}
    with _exclusive(PROJECTS_LOCK):
        projects = _read()
        projects.append(item)
        atomic_json(DATA / PROJECTS_FILE, {"version": 1, "projects": projects})
    return item


def archive_project(project_id):
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise WalkerError("Invalid project ID")
    with _exclusive(PROJECTS_LOCK):
        projects = _read()
        item = next((p for p in projects if p["id"] == project_id), None)
        if item is None:
            raise WalkerError("Project not found")
        item["archived"] = True
        item["updated"] = _now()
        atomic_json(DATA / PROJECTS_FILE, {"version": 1, "projects": projects})
    return item


def theme():
    try:
        value = json.loads((DATA / PREFERENCES_FILE).read_text())
    except FileNotFoundError:
        return "dark"
    except (OSError, ValueError):
        return "dark"
    return value.get("theme", "dark") if isinstance(value, dict) and value.get("theme") in {"dark", "light"} else "dark"


def set_theme(value):
    if value not in {"dark", "light"}:
        raise WalkerError("Theme must be dark or light")
    with _exclusive(PREFERENCES_LOCK):
        try:
            current = json.loads((DATA / PREFERENCES_FILE).read_text())
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        atomic_json(DATA / PREFERENCES_FILE, {**current, "theme": value})
    return value
