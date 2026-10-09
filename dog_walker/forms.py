"""The portable, agent-fillable .dogwalk contract. Import never executes a job."""
import hashlib
import json
from pathlib import Path
import tempfile
import yaml
from jsonschema import Draft202012Validator
from .storage import APP_ROOT, DATA
from .workflow import WalkerError, load_workflow

MAX_BYTES = 256 * 1024


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise WalkerError(f"Duplicate or non-text form field: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_form(text):
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise WalkerError("Job forms must be text and smaller than 256 KB")
    try:
        if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(text)):
            raise WalkerError("YAML aliases are not supported; write each step explicitly")
        data = yaml.load(text, Loader=UniqueLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise WalkerError(f"The form is not valid YAML: {exc}") from exc
    schema = json.loads((APP_ROOT / "forms/job.schema.json").read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: str(e.path))
    if errors:
        error = errors[0]
        field = ".".join(map(str, error.path)) or "form"
        raise WalkerError(f"{field}: {error.message}")
    ids = [s["id"] for s in data["steps"]]
    if len(ids) != len(set(ids)):
        raise WalkerError("Step IDs must be unique")
    placeholders = {"SHORT_JOB_NAME", "MEASURABLE_OUTCOME", "LIMIT_CHANGES_TO_THE_REQUESTED_SCOPE",
                    "EXACT_PROJECT_RELATIVE_FILE_TO_EDIT",
                    "DO_NOT_INSTALL_PACKAGES_OR_USE_THE_INTERNET", "READ_THE_RELEVANT_FILES_AND_REPORT_THE_CURRENT_STATE_WITHOUT_EDITING.",
                    "IDENTIFY_ACTUAL_FILES_AND_THE_TEST_COMMAND", "REINSPECT_AND_CORRECT_THE_REPORTED_ISSUES_WITHOUT_EDITING_THE_PROJECT.",
                    "PRECISE_IMPLEMENTATION_INSTRUCTIONS_WITH_SCOPE_AND_EDGE_CASES.", "DESCRIBE_THE_EXPECTED_BEHAVIOR",
                    "CORRECT_THE_FAILED_CRITERIA_WITHOUT_WIDENING_SCOPE_OR_WEAKENING_TESTS.",
                    "RUN_THE_REAL_TESTS_AND_REPORT_CHANGES_RESULTS_AND_REMAINING_LIMITATIONS.",
                    "ALL_RELEVANT_TESTS_PASS_AND_THE_SUMMARY_MATCHES_ACTUAL_EVIDENCE"}
    def strings(value):
        if isinstance(value, str):
            yield value.strip()
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    if placeholders.intersection(strings(data)):
        raise WalkerError("This form still contains blank-template placeholders. Ask your agent to complete it first.")
    if not data["name"].strip() or not data["goal"].strip() or any(not s["prompt"].strip() or not s["title"].strip() for s in data["steps"]):
        raise WalkerError("The name, goal, step titles, and prompts must not be blank")
    return data


def compile_form(text):
    data = parse_form(text)
    imported = DATA / "imports"
    imported.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = Path(tempfile.mkdtemp(prefix="job-", dir=imported))
    root.chmod(0o700)
    steps = []
    for index, source in enumerate(data["steps"]):
        step = {k: v for k, v in source.items() if k not in {"title", "success_criteria", "prompt", "retry_prompt"}}
        name = f"{index + 1:02d}-{source['id']}"
        criteria = "\n".join(f"- {c}" for c in source["success_criteria"])
        constraints = "\n".join(f"- {c}" for c in data["constraints"])
        # Form prompts are plain text, not executable templates. Dollar signs are literal.
        prompt = f"Job goal: {data['goal']}\n\nConstraints:\n{constraints}\n\nCurrent step: {source['title']}\n{source['prompt']}\n\nAcceptance criteria:\n{criteria}\n"
        step["prompt"] = f"{name}.md"
        (root / step["prompt"]).write_text(prompt.replace("$", "$$"))
        if source.get("retry_prompt"):
            step["retry_prompt"] = f"{name}-retry.md"
            correction = (f"Job goal: {data['goal']}\nConstraints:\n{constraints}\nAcceptance criteria:\n{criteria}\n\n" + source["retry_prompt"]).replace("$", "$$")
            correction += "\n\nFailed checks:\n${failed_checks}\nPrevious result:\n${previous_result}\n"
            (root / step["retry_prompt"]).write_text(correction)
        steps.append(step)
    workflow = {"version": 1, "name": data["name"], "max_turns": data.get("max_turns", 40), "steps": steps}
    if "allowed_changes" in data:
        workflow["allowed_changes"] = data["allowed_changes"]
    (root / "workflow.yaml").write_text(yaml.safe_dump(workflow, sort_keys=False))
    (root / "source.dogwalk").write_text(text)
    compiled = load_workflow(root)
    return data, compiled


def preview(data):
    checks = [c for s in data["steps"] for c in s.get("checks", [])]
    return {"name": data["name"], "goal": data["goal"], "constraints": data["constraints"],
            "allowed_changes": data.get("allowed_changes"),
            "mode": data.get("mode", "auto"), "steps": [
                {"id": s["id"], "title": s["title"], "criteria": s["success_criteria"],
                 "prompt": s["prompt"], "checks": s.get("checks", []),
                 "review": s.get("approval", False) or not s.get("checks"),
                 "semantic": bool(s.get("questions"))} for s in data["steps"]],
            "commands": [c["argv"] for c in checks if c["type"] == "command"],
            "fingerprint": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]}
