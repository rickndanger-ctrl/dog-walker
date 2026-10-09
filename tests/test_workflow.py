from pathlib import Path
import yaml
import pytest
from dog_walker.workflow import load_workflow, WalkerError


def workflow(tmp_path, **overrides):
    (tmp_path / "one.md").write_text("Do ${step_id} in ${project_root}; $$ is literal.")
    data = {"version": 1, "name": "test", "steps": [{"id": "one", "prompt": "one.md", "checks": [{"type": "response_contains", "text": "done"}]}]}
    data["steps"][0].update(overrides)
    (tmp_path / "workflow.yaml").write_text(yaml.safe_dump(data))
    return tmp_path


def test_render_and_default_transition(tmp_path):
    w = load_workflow(workflow(tmp_path))
    assert w.steps["one"]["on_pass"] == "complete"
    assert w.prompt("one", step_id="one", project_root="/tmp/project", previous_result="{}", failed_checks="") == "Do one in /tmp/project; $ is literal."


@pytest.mark.parametrize("override", [{"on_pass": "missing"}, {"on_exhausted": "complete"}, {"max_retries": -1}, {"timeout": 0}, {"checks": [{"type": "command", "argv": "echo x"}]}, {"checks": [{"type": "file_exists", "path": "../../x"}]}])
def test_invalid_workflows(tmp_path, override):
    with pytest.raises(WalkerError):
        load_workflow(workflow(tmp_path, **override))


def test_unknown_variable_and_prompt_escape(tmp_path):
    workflow(tmp_path)
    (tmp_path / "one.md").write_text("${missing}")
    with pytest.raises(WalkerError, match="Unknown"):
        load_workflow(tmp_path)
    (tmp_path / "one.md").write_text("okay")
    data = yaml.safe_load((tmp_path / "workflow.yaml").read_text())
    data["steps"][0]["prompt"] = "../outside.md"
    (tmp_path / "workflow.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(WalkerError):
        load_workflow(tmp_path)
