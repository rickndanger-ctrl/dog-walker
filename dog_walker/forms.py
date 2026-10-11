"""The portable, agent-fillable .dogwalk contract. Import never executes a job."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import yaml
from jsonschema import Draft202012Validator
from .storage import APP_ROOT, DATA
from .workflow import WalkerError, load_workflow

MAX_BYTES = 256 * 1024
MARKDOWN_BRIEF_MAX_BYTES = MAX_BYTES

_MARKDOWN_FENCE = re.compile(
    r"(?ims)^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*"
    r"(?P<language>yaml|yml|dogwalk|handler)(?:[ \t]+[^\r\n]*)?\r?\n"
    r"(?P<body>.*?)^[ \t]*(?P=fence)[ \t]*$"
)
_MARKDOWN_HEADING = re.compile(r"(?m)^\s{0,3}#\s+(.+?)\s*#*\s*$")


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


def read_markdown_brief(path):
    """Read a bounded Markdown drop as planning input, or recognize a valid embedded form.

    The return value is a plain dict suitable for the desktop protocol. ``kind`` is
    ``"handler_form"`` only when a labeled YAML fence passes the official form
    parser; otherwise the Markdown remains an ordinary planning brief.
    """
    source = Path(path).expanduser()
    if source.suffix.lower() != ".md":
        raise WalkerError("Choose a Markdown (.md) file")
    try:
        info = source.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise WalkerError("Markdown briefs must be regular files, not symlinks")
        if info.st_size > MARKDOWN_BRIEF_MAX_BYTES:
            raise WalkerError("Markdown briefs must be smaller than 256 KB")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(source, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise WalkerError("Markdown briefs must be regular files, not symlinks")
            if opened.st_size > MARKDOWN_BRIEF_MAX_BYTES:
                raise WalkerError("Markdown briefs must be smaller than 256 KB")
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                content = handle.read(MARKDOWN_BRIEF_MAX_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    except WalkerError:
        raise
    except OSError as exc:
        # Keep OS errors (which may include private path details) out of logs/UI.
        raise WalkerError("Cannot read this Markdown brief") from exc

    if len(content) > MARKDOWN_BRIEF_MAX_BYTES:
        raise WalkerError("Markdown briefs must be smaller than 256 KB")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WalkerError("Markdown briefs must be UTF-8 text") from exc
    if any(ord(char) < 32 and char not in "\t\n\r" for char in text):
        raise WalkerError("Markdown briefs must be UTF-8 text")

    title_match = _MARKDOWN_HEADING.search(text)
    title = (title_match.group(1).strip() if title_match else source.stem).replace("\n", " ")[:160]
    folder = re.sub(r"[^a-z0-9_-]+", "-", title.lower()).strip("-_")[:60] or "markdown-brief"
    result = {
        "kind": "brief",
        "source": str(source),
        "text": text,
        "title": title or "Markdown brief",
        "suggested_folder": folder,
        "form_text": None,
        "form": None,
    }
    for match in _MARKDOWN_FENCE.finditer(text):
        form_text = match.group("body")
        try:
            data = parse_form(form_text)
        except WalkerError:
            continue
        result.update(kind="handler_form", form_text=form_text, form=data)
        # The official form title is authoritative when the Markdown has no heading.
        if not title_match:
            result["title"] = data["name"][:160]
            result["suggested_folder"] = re.sub(
                r"[^a-z0-9_-]+", "-", data["name"].lower()
            ).strip("-_")[:60] or "markdown-brief"
        break
    return result


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
    if "plugins" in data:
        workflow["plugins"] = data["plugins"]
    (root / "workflow.yaml").write_text(yaml.safe_dump(workflow, sort_keys=False))
    (root / "source.dogwalk").write_text(text)
    compiled = load_workflow(root)
    return data, compiled


def preview(data):
    checks = [c for s in data["steps"] for c in s.get("checks", [])]
    from .plugins import resolve_plugins
    plugins = resolve_plugins(data.get("plugins", []))
    constraints = [*data["constraints"]]
    for plugin in plugins:
        constraints.append(f"Plugin {plugin['name']} ({plugin['id']}): {plugin['description']} Settings: {json.dumps(plugin['settings'], ensure_ascii=False)}")
    return {"name": data["name"], "goal": data["goal"], "constraints": constraints,
            "plugins": plugins,
            "allowed_changes": data.get("allowed_changes"),
            "mode": data.get("mode", "auto"), "steps": [
                {"id": s["id"], "title": s["title"], "criteria": s["success_criteria"],
                 "prompt": s["prompt"], "checks": s.get("checks", []),
                 "review": s.get("approval", False) or not s.get("checks"),
                 "semantic": bool(s.get("questions"))} for s in data["steps"]],
            "commands": [c["argv"] for c in checks if c["type"] == "command"],
            "fingerprint": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]}
