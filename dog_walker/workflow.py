"""Readable workflows, strict validation, and safe template expansion."""
from dataclasses import dataclass
from pathlib import Path
from string import Template
import re
import yaml


class WalkerError(Exception):
    pass


VARIABLES = {"project_root", "step_id", "previous_result", "failed_checks"}
CHECKS = {"command", "file_exists", "file_contains", "unchanged", "response_contains", "command_executed", "no_changes"}
TERMINALS = {"complete", "pause"}


def inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise WalkerError(f"Expected a relative path: {relative!r}")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise WalkerError(f"Path leaves its folder: {relative}")
    return target


def prompt_text(root, relative):
    path = inside(root, relative)
    if not path.is_file():
        raise WalkerError(f"Missing prompt: {path}")
    text = path.read_text()
    if not text.strip() or len(text) > 30000:
        raise WalkerError(f"Prompt must contain 1–30,000 characters: {path}")
    template = Template(text)
    if not template.is_valid():
        raise WalkerError(f"Invalid template in {path}; write $$ for a literal dollar sign")
    unknown = set(template.get_identifiers()) - VARIABLES
    if unknown:
        raise WalkerError(f"Unknown variables in {path}: {sorted(unknown)}")
    return text


@dataclass
class Workflow:
    root: Path
    data: dict
    steps: dict

    @property
    def name(self):
        return self.data["name"]

    @property
    def entry(self):
        return self.data["entry"]

    def prompt(self, step, **values):
        spec = self.steps[step]
        field = "retry_prompt" if values.get("failed_checks") and spec.get("retry_prompt") else "prompt"
        return Template(prompt_text(self.root, spec[field])).substitute(values)


def load_workflow(folder) -> Workflow:
    root = Path(folder).expanduser().resolve()
    try:
        data = yaml.safe_load((root / "workflow.yaml").read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise WalkerError(f"Cannot read workflow: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1:
        raise WalkerError("workflow.yaml needs version: 1")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise WalkerError("Workflow needs a name")
    raw = data.get("steps")
    if not isinstance(raw, list) or not raw:
        raise WalkerError("Workflow needs a non-empty steps list")
    if not all(isinstance(item, dict) for item in raw):
        raise WalkerError("Each step must be a mapping")
    steps = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise WalkerError("Each step must be a mapping")
        s = dict(item)
        ident = s.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", ident) or ident in steps or ident in TERMINALS:
            raise WalkerError(f"Invalid or duplicate step ID: {ident}")
        prompt_text(root, s.get("prompt"))
        if s.get("retry_prompt"):
            prompt_text(root, s["retry_prompt"])
        s.setdefault("on_pass", raw[index + 1].get("id") if index + 1 < len(raw) else "complete")
        s.setdefault("on_exhausted", "pause")
        s.setdefault("max_retries", 2)
        s.setdefault("timeout", 1800)
        s.setdefault("checks", [])
        s.setdefault("questions", {})
        s.setdefault("approval", False)
        if type(s["approval"]) is not bool:
            raise WalkerError(f"{ident}: approval must be true or false")
        if type(s["max_retries"]) is not int or not 0 <= s["max_retries"] <= 10:
            raise WalkerError(f"{ident}: max_retries must be between 0 and 10")
        if type(s["timeout"]) is not int or not 10 <= s["timeout"] <= 21600:
            raise WalkerError(f"{ident}: timeout must be 10–21600 seconds")
        if not isinstance(s["checks"], list):
            raise WalkerError(f"{ident}: checks must be a list")
        for check in s["checks"]:
            if not isinstance(check, dict) or check.get("type") not in CHECKS:
                raise WalkerError(f"{ident}: unknown check type")
            typ = check["type"]
            if typ in {"file_exists", "file_contains", "unchanged"}:
                inside(root, check.get("path"))  # syntactic validation, actual project resolved at run time
            if typ == "command":
                argv = check.get("argv")
                if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
                    raise WalkerError(f"{ident}: command requires an argv list")
                timeout = check.get("timeout", 60)
                if type(timeout) is not int or not 1 <= timeout <= 1800:
                    raise WalkerError(f"{ident}: command timeout must be 1–1800 seconds")
            if typ in {"file_contains", "response_contains", "command_executed"} and not isinstance(check.get("text"), str):
                raise WalkerError(f"{ident}: {typ} requires text")
        if not isinstance(s["questions"], dict):
            raise WalkerError(f"{ident}: questions must be a mapping")
        for qid, q in s["questions"].items():
            if not isinstance(q, dict) or q.get("type") not in {"noul", "choice", "score"}:
                raise WalkerError(f"{ident}/{qid}: invalid question type")
            if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
                raise WalkerError(f"{ident}/{qid}: question needs instructions")
            threshold = q.get("threshold", 0.85)
            if not isinstance(threshold, (int, float)) or not 0.5 <= threshold <= 1:
                raise WalkerError(f"{ident}/{qid}: threshold must be 0.5–1")
            if q["type"] == "choice":
                c = q.get("criteria")
                if not isinstance(c, dict) or not 2 <= len(c) <= 10 or not all(isinstance(x, str) and x for x in c.values()):
                    raise WalkerError(f"{ident}/{qid}: choice requires 2–10 named criteria")
                if q.get("expected") not in c:
                    raise WalkerError(f"{ident}/{qid}: expected must name a choice")
            if q["type"] == "score":
                c = q.get("criteria")
                if not isinstance(c, list) or not 2 <= len(c) <= 10 or not all(isinstance(x, str) and x for x in c):
                    raise WalkerError(f"{ident}/{qid}: score requires 2–10 criteria")
                if type(q.get("minimum")) is not int or not 0 <= q["minimum"] < len(c):
                    raise WalkerError(f"{ident}/{qid}: minimum must be a criterion index")
            if q["type"] == "noul" and type(q.get("expected", True)) is not bool:
                raise WalkerError(f"{ident}/{qid}: expected must be true or false")
        steps[ident] = s
    entry = data.get("entry", raw[0]["id"])
    if entry not in steps:
        raise WalkerError("entry must name a step")
    data["entry"] = entry
    for ident, s in steps.items():
        for key in ("on_pass", "on_exhausted"):
            if s[key] not in steps and s[key] not in TERMINALS:
                raise WalkerError(f"{ident}: {key} names missing step {s[key]}")
        if s["on_exhausted"] == "complete":
            raise WalkerError(f"{ident}: failed steps cannot complete a run")
    if type(data.get("max_turns", 40)) is not int or not 1 <= data.get("max_turns", 40) <= 1000:
        raise WalkerError("max_turns must be 1–1000")
    return Workflow(root, data, steps)
