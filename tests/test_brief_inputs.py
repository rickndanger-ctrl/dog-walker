import copy
import hashlib
import json

import pytest

from dog_walker import forms, storage
from dog_walker.briefs import compile_brief_form, install_brief_input
from dog_walker.engine import run_checks
from dog_walker.workflow import WalkerError


def form():
    return {
        "dog_walker": 1,
        "name": "Write release notes",
        "goal": "Write release notes for the requested change",
        "constraints": ["Keep the work scoped"],
        "allowed_changes": ["release-notes.md"],
        "steps": [
            {
                "id": "draft",
                "title": "Draft the notes",
                "prompt": "Write the notes based on current project evidence.",
                "success_criteria": ["The release notes are accurate"],
                "checks": [{"id": "notes-exist", "type": "file_exists", "path": "release-notes.md"}],
                "approval": True,
            },
            {
                "id": "review",
                "title": "Review the notes",
                "prompt": "Review the notes for clarity.",
                "success_criteria": ["The notes are clear"],
                "checks": [{"id": "review-command", "type": "command", "argv": ["true"]}],
            },
        ],
    }


class FakeStore:
    def __init__(self, root):
        self.state = {"root": str(root), "hashes": {}}
        self.events = []

    def save(self, **updates):
        self.state.update(updates)

    def event(self, kind, **payload):
        self.events.append({"type": kind, **payload})


def test_compile_brief_keeps_full_doc_out_of_prompts_and_preserves_authored_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(forms, "DATA", tmp_path / "imports")
    original = form()
    saved = copy.deepcopy(original)
    brief = "# Release context\n\n" + ("A detailed reference paragraph.\n" * 4000)

    job, workflow, input_name = compile_brief_form(original, brief)

    assert original == saved
    assert input_name == f".handler-inputs/brief-{hashlib.sha256(brief.encode()).hexdigest()[:16]}.md"
    assert len(brief) > 20_000
    assert brief not in workflow.prompt("draft", project_root="/tmp/project", step_id="draft",
                                        previous_result="{}", failed_checks="")
    assert f"Read {input_name} before work" in workflow.prompt(
        "draft", project_root="/tmp/project", step_id="draft", previous_result="{}", failed_checks="")
    assert job["steps"][0]["checks"][0] == original["steps"][0]["checks"][0]
    assert job["steps"][1]["checks"][0] == original["steps"][1]["checks"][0]
    assert all(any(c["type"] == "unchanged" and c["path"] == input_name for c in step["checks"])
               for step in job["steps"])
    assert job["steps"][0]["approval"] is True
    assert job["constraints"][-1] == f"Keep the reference input {input_name} unchanged."


@pytest.mark.parametrize("allowed", [
    [".handler-inputs"],
    [".handler-inputs/other.md"],
    ["."],
    ["./.handler-inputs/other.md"],
])
def test_compile_rejects_allowed_changes_overlapping_reserved_directory(allowed):
    value = form()
    value["allowed_changes"] = allowed
    with pytest.raises(WalkerError, match="conflicts"):
        compile_brief_form(value, "# input\n")


def test_compile_rejects_step_with_no_check_capacity():
    value = form()
    value["steps"][0]["checks"] = [
        {"id": f"check-{n}", "type": "file_exists", "path": f"file-{n}"}
        for n in range(30)
    ]
    with pytest.raises(WalkerError, match="no room"):
        compile_brief_form(value, "# input\n")


def test_compile_and_install_enforce_brief_size_limit(tmp_path):
    oversized = "x" * (forms.MAX_BYTES + 1)
    with pytest.raises(WalkerError, match="256 KB"):
        compile_brief_form(form(), oversized)

    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(WalkerError, match="256 KB"):
        install_brief_input(FakeStore(root), ".handler-inputs/brief-0000000000000000.md", oversized)


def test_install_creates_protected_snapshot_updates_only_input_baselines_and_records_hash(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(forms, "DATA", tmp_path / "imports")
    monkeypatch.setattr(storage, "DATA", tmp_path / "app-data")
    project = tmp_path / "project"
    project.mkdir()
    (project / "readme.txt").write_text("project source stays here", encoding="utf-8")
    brief = "# Secret planning context\n\nSpecific private context.\n"
    _, workflow, input_name = compile_brief_form(form(), brief)
    store = storage.Store.create(workflow, project)
    store.state["scope_hashes"]["stale-existing-entry"] = "preserve-me"
    store.save(scope_hashes=store.state["scope_hashes"])
    before_scope = copy.deepcopy(store.state["scope_hashes"])
    assert store.state["hashes"][input_name] is None
    source_before = (project / "readme.txt").read_bytes()

    sha = install_brief_input(store, input_name, brief)

    workspace = store.state["root"]
    assert (storage.Path(workspace) / input_name).read_text(encoding="utf-8") == brief
    assert (project / "readme.txt").read_bytes() == source_before
    assert sha == hashlib.sha256(brief.encode()).hexdigest()
    assert store.state["hashes"][input_name] == sha
    assert store.state["scope_hashes"][input_name] == sha
    assert {key: value for key, value in store.state["scope_hashes"].items() if key != input_name} == before_scope
    event_log = (store.path / "events.jsonl").read_text(encoding="utf-8")
    event = json.loads(event_log.splitlines()[-1])
    assert event["type"] == "brief_input"
    assert event["path"] == input_name and event["sha256"] == sha
    assert "Specific private context" not in event_log

    target = storage.Path(workspace) / input_name
    target.write_text("tampered", encoding="utf-8")
    rows = run_checks(workflow.steps[workflow.entry]["checks"], storage.Path(workspace), {}, [],
                      store.state["hashes"])
    assert next(row for row in rows if row["type"] == "unchanged")["pass"] is False


def test_install_accepts_matching_snapshot_idempotently_and_rejects_conflicts(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    brief = "# Context\n"
    _, _, input_name = compile_brief_form(form(), brief)
    store = FakeStore(root)

    install_brief_input(store, input_name, brief)
    install_brief_input(store, input_name, brief)
    assert (root / input_name).read_text(encoding="utf-8") == brief
    assert len(store.events) == 2

    (root / input_name).write_text("different content", encoding="utf-8")
    with pytest.raises(WalkerError, match="different file"):
        install_brief_input(store, input_name, brief)


def test_install_rejects_unreserved_names_and_symlink_parent(tmp_path):
    brief = "# Context\n"
    _, _, input_name = compile_brief_form(form(), brief)
    root = tmp_path / "workspace"
    root.mkdir()
    store = FakeStore(root)
    with pytest.raises(WalkerError, match="Invalid protected brief path"):
        install_brief_input(store, "outside.md", brief)

    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / ".handler-inputs").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(WalkerError, match="real directory"):
        install_brief_input(store, input_name, brief)
    assert list(outside.iterdir()) == []


def test_install_rejects_different_existing_symlink(tmp_path):
    brief = "# Context\n"
    _, _, input_name = compile_brief_form(form(), brief)
    root = tmp_path / "workspace"
    directory = root / ".handler-inputs"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text(brief, encoding="utf-8")
    (directory / input_name.rsplit("/", 1)[1]).symlink_to(outside)
    with pytest.raises(WalkerError):
        install_brief_input(FakeStore(root), input_name, brief)
