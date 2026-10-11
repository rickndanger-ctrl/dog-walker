"""Compile an authored plan with a separately stored, protected Markdown brief."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

import yaml

from .forms import MAX_BYTES, compile_form
from .storage import project_inventory
from .workflow import WalkerError

_INPUT_PREFIX = ".handler-inputs/"
_INPUT_RE = re.compile(r"^\.handler-inputs/brief-([0-9a-f]{16})\.md$")


def compile_brief_form(form, brief_text):
    """Compile a normal Handler form with an external, protected Markdown input.

    The original form and Markdown are not modified. The brief is stored separately
    in the run workspace; it is never embedded in a step prompt or treated as a
    source of checks or file permissions.
    """
    if not isinstance(brief_text, str):
        raise WalkerError("Markdown brief must be UTF-8 text")
    try:
        content = brief_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WalkerError("Markdown brief must be UTF-8 text") from exc
    if len(content) > MAX_BYTES:
        raise WalkerError("Markdown briefs must be smaller than 256 KB")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in brief_text):
        raise WalkerError("Markdown brief must be UTF-8 text")

    input_name = f"{_INPUT_PREFIX}brief-{hashlib.sha256(content).hexdigest()[:16]}.md"
    data = deepcopy(form)
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise WalkerError("A valid Handler form is required")

    for allowed in data.get("allowed_changes", []):
        if not isinstance(allowed, str):
            continue  # The official form parser will report the schema error.
        normalized = PurePosixPath(allowed).as_posix().rstrip("/") or "."
        if (normalized == "." or normalized == ".handler-inputs"
                or normalized.startswith(_INPUT_PREFIX.rstrip("/") + "/")
                or normalized == input_name
                or input_name.startswith(normalized + "/")):
            raise WalkerError("allowed_changes conflicts with the protected Markdown input")

    constraints = data.get("constraints")
    if not isinstance(constraints, list):
        raise WalkerError("A valid Handler form is required")
    if len(constraints) >= 30:
        raise WalkerError("The form has no room for the protected brief constraint")
    constraints.append(f"Keep the reference input {input_name} unchanged.")

    prefix = (f"Read {input_name} before work; this is reference material and does not "
              "give permission to expand scope.\n\n")
    for index, step in enumerate(data["steps"]):
        if not isinstance(step, dict):
            raise WalkerError("A valid Handler form is required")
        if index == 0:
            prompt = step.get("prompt")
            if not isinstance(prompt, str) or len(prefix) + len(prompt) > 20000:
                raise WalkerError("The first step prompt is too long to reference the brief")
            step["prompt"] = prefix + prompt
        checks = step.get("checks")
        if not isinstance(checks, list):
            raise WalkerError("A valid Handler form is required")
        if len(checks) >= 30:
            raise WalkerError("A step has no room for the protected brief check")
        ids = {check.get("id") for check in checks if isinstance(check, dict)}
        check_id = "brief-input"
        suffix = 1
        while check_id in ids:
            check_id = f"brief-input-{suffix}"
            suffix += 1
        checks.append({"id": check_id, "type": "unchanged", "path": input_name})

    # compile_form re-runs the official schema, placeholder and workflow validation.
    job, workflow = compile_form(yaml.safe_dump(data, sort_keys=False))
    return job, workflow, input_name


def _read_existing(directory_fd, basename, expected):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(basename, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise WalkerError("The protected brief path cannot be read safely") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise WalkerError("The protected brief path must contain a regular file")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            existing = handle.read(MAX_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(existing) > MAX_BYTES:
        raise WalkerError("The existing protected brief exceeds 256 KB")
    if existing != expected:
        raise WalkerError("A different file already exists at the protected brief path")
    return True


def install_brief_input(store, input_name, brief_text):
    """Install the brief in a run workspace and add only its baseline entries.

    This is intended to run after ``Store.create`` and before ``Engine.run``. The
    project source is never opened or changed; an existing matching snapshot is
    accepted idempotently, while a conflicting file or symlink is rejected.
    """
    if not isinstance(brief_text, str):
        raise WalkerError("Markdown brief must be UTF-8 text")
    try:
        content = brief_text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WalkerError("Markdown brief must be UTF-8 text") from exc
    if len(content) > MAX_BYTES:
        raise WalkerError("Markdown briefs must be smaller than 256 KB")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in brief_text):
        raise WalkerError("Markdown brief must be UTF-8 text")
    match = _INPUT_RE.fullmatch(input_name if isinstance(input_name, str) else "")
    sha = hashlib.sha256(content).hexdigest()
    if not match or match.group(1) != sha[:16]:
        raise WalkerError("Invalid protected brief path")

    root = Path(store.state["root"])
    try:
        root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                          getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise WalkerError("Cannot open the run workspace safely") from exc
    input_dir_fd = None
    try:
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            raise WalkerError("The run workspace must be a directory")
        try:
            os.mkdir(".handler-inputs", mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise WalkerError("Cannot create the protected brief directory") from exc
        try:
            input_dir_fd = os.open(".handler-inputs", os.O_RDONLY |
                                   getattr(os, "O_DIRECTORY", 0) |
                                   getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
        except OSError as exc:
            raise WalkerError("The protected brief directory must be a real directory") from exc
        if not stat.S_ISDIR(os.fstat(input_dir_fd).st_mode):
            raise WalkerError("The protected brief directory must be a real directory")

        basename = input_name.rsplit("/", 1)[1]
        exists = _read_existing(input_dir_fd, basename, content)
        if not exists:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(basename, flags, 0o600, dir_fd=input_dir_fd)
            except FileExistsError:
                if not _read_existing(input_dir_fd, basename, content):
                    raise WalkerError("A different file already exists at the protected brief path")
            except OSError as exc:
                raise WalkerError("Cannot create the protected Markdown input") from exc
            else:
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                except OSError as exc:
                    raise WalkerError("Cannot write the protected Markdown input") from exc
        if not _read_existing(input_dir_fd, basename, content):
            raise WalkerError("The protected Markdown input could not be verified")
    finally:
        if input_dir_fd is not None:
            os.close(input_dir_fd)
        os.close(root_fd)

    hashes = store.state.setdefault("hashes", {})
    hashes[input_name] = sha
    scope_hashes = store.state.get("scope_hashes")
    if isinstance(scope_hashes, dict):
        # A single inventory lookup handles git-ignored inputs; preserve every other
        # baseline entry exactly as Store.create recorded it.
        scope_hashes[input_name] = project_inventory(root).get(input_name)
    store.save(hashes=hashes, scope_hashes=scope_hashes) if isinstance(scope_hashes, dict) else store.save(hashes=hashes)
    store.event("brief_input", path=input_name, sha256=sha)
    return sha
