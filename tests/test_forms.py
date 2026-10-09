import copy
import json
from pathlib import Path
import pytest
import yaml
from dog_walker import forms, storage
from dog_walker.forms import compile_form, parse_form, preview
from dog_walker.workflow import WalkerError


def form():
    return {"dog_walker": 1, "name": "A real job", "goal": "Write a result", "constraints": ["Stay local"], "steps": [
        {"id": "write", "title": "Write the result", "prompt": "Write done.txt. The value is $10 and ${NOT_A_VARIABLE}.",
         "success_criteria": ["A result file exists"], "checks": [{"type": "file_exists", "path": "done.txt"}],
         "retry_prompt": "Correct the problem. It costs $0."}]}


def test_compile_and_literal_dollars(tmp_path, monkeypatch):
    monkeypatch.setattr(forms, "DATA", tmp_path)
    data, workflow = compile_form(yaml.safe_dump(form()))
    assert workflow.name == "A real job"
    prompt = workflow.prompt("write", project_root="/tmp/project", step_id="write", previous_result="{}", failed_checks="")
    assert "$10" in prompt and "${NOT_A_VARIABLE}" in prompt and "Stay local" in prompt
    retry = workflow.prompt("write", project_root="/tmp/project", step_id="write", previous_result="previous", failed_checks="missing-file")
    assert "$0" in retry and "missing-file" in retry and "previous" in retry
    assert preview(data)["steps"][0]["review"] is False


@pytest.mark.parametrize("change", [
    lambda d: d.update(secret="not-allowed"),
    lambda d: d.update(dog_walker=2),
    lambda d: d["steps"][0].update(checks=[{"type": "command", "argv": "rm x"}]),
    lambda d: d["steps"][0].update(max_retries=11),
    lambda d: d["steps"].append(copy.deepcopy(d["steps"][0])),
    lambda d: d["steps"][0].update(success_criteria=[]),
])
def test_reject_bad_forms(change):
    value = form()
    change(value)
    with pytest.raises(WalkerError):
        parse_form(yaml.safe_dump(value))


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd"])
def test_reject_check_path_escape(tmp_path, monkeypatch, path):
    monkeypatch.setattr(forms, "DATA", tmp_path)
    value = form()
    value["steps"][0]["checks"][0]["path"] = path
    with pytest.raises(WalkerError):
        compile_form(yaml.safe_dump(value))


def test_duplicate_fields_aliases_size_and_yaml_tags():
    for text in ["name: first\nname: second", "a: &a [one]\nb: *a", "x" * (forms.MAX_BYTES + 1), "!!python/object/apply:os.system [touch /tmp/never]"]:
        with pytest.raises(WalkerError):
            parse_form(text)


def test_official_example_and_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(forms, "DATA", tmp_path)
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(json.loads((storage.APP_ROOT / "forms/job.schema.json").read_text()))
    data, workflow = compile_form((storage.APP_ROOT / "examples/discount.dogwalk").read_text())
    assert len(workflow.steps) == 3
    assert preview(data)["commands"] == [["python3", "-m", "unittest", "-v"]] * 2


def test_blank_template_cannot_be_started():
    with pytest.raises(WalkerError, match="placeholders"):
        parse_form((storage.APP_ROOT / "forms/JOB_FORM.dogwalk").read_text())
