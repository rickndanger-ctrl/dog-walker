from dog_walker import cli, storage
from dog_walker.workflow import load_workflow


def test_resume_auto_cannot_mutate_a_locked_run(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path / "data")
    project = tmp_path / "project"
    project.mkdir()
    workflow = load_workflow(storage.APP_ROOT / "examples/coding")
    owner = storage.Store.create(workflow, project, in_place=True)
    owner.acquire()
    before = (owner.path / "state.json").read_bytes()
    try:
        assert cli.main(["resume", owner.state["id"], "--auto", "--plain"]) == 1
        assert (owner.path / "state.json").read_bytes() == before
    finally:
        owner.release()
