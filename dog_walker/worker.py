"""Structured, resumable Codex turns against the existing loopback Ornith server."""
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import shutil
import urllib.request
from jsonschema import validate, ValidationError
from .storage import DATA, APP_ROOT, atomic_json
from .workflow import WalkerError

from .settings import load_settings


def reload_settings():
    global MODEL_PATH, ENDPOINT, CATALOG, START_COMMAND
    settings = load_settings()
    MODEL_PATH, ENDPOINT, CATALOG = (settings[k] for k in ("model_path", "endpoint", "catalog"))
    START_COMMAND = settings["start_command"]


reload_settings()
SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ["completed", "blocked"]},
    "summary": {"type": "string", "maxLength": 1400},
    "evidence": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 250}},
    "files_changed": {"type": "array", "maxItems": 30, "items": {"type": "string"}},
    "blockers": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 250}}},
    "required": ["status", "summary", "evidence", "files_changed", "blockers"], "additionalProperties": False}

INSTRUCTIONS = """You are a local coding worker supervised by Dog Walker. Complete only the current step.
Inspect actual files before editing. Use shell tools to read, edit, and test in this workspace.
Return exactly the requested JSON object, with short evidence backed by actual tool results.
Use status=blocked and list blockers when you cannot complete the step. Do not invent command results.
Do not fetch internet resources, install packages, use cloud tools, or perform actions outside this workspace.
"""


def parse_result(text):
    """Accept bare JSON or one explicit JSON fence, always validating the schema.

    Some local Responses servers do not enforce output-schema formatting. Never
    extract arbitrary braces from prose or choose between multiple code blocks.
    """
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        fences = [m for m in re.finditer(r"(?m)^```(?:json)?[ \t]*\r?\n", text)
                  if text[m.end():].lstrip().startswith("{")]
        if len(fences) != 1 or text.count("```") > 2:
            raise
        body = text[fences[0].end():].lstrip()
        result, end = json.JSONDecoder().raw_decode(body)
        # Local tool templates sometimes leave closing tags instead of a fence.
        # Only a complete JSON value plus known envelope closers is accepted.
        tail = body[end:].strip()
        if not re.fullmatch(r"(?:```[ \t]*(?:\r?\n|$))?(?:</(?:parameter|function|tool_call)>[ \t\r\n]*)*", tail):
            raise json.JSONDecodeError("Unexpected text after fenced JSON", text, fences[0].end() + end)
    validate(result, SCHEMA)
    return result


def environment():
    env = dict(os.environ)
    for key in list(env):
        if any(x in key.upper() for x in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN")) or key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            env.pop(key)
    env.update(CODEX_HOME=str(DATA / "codex-home"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", NO_PROXY="127.0.0.1,localhost", USE_TF="0")
    return env


def configure():
    home = DATA / "codex-home"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    instructions = home / "instructions.md"
    instructions.write_text(INSTRUCTIONS)
    # JSON-escaped strings are also valid TOML basic strings for these paths.
    model, instructions_path, catalog, endpoint = map(json.dumps, (MODEL_PATH, str(instructions), CATALOG, ENDPOINT))
    config = f'''model = {model}
model_provider = "ornith_local"
model_reasoning_effort = "none"
model_context_window = 32768
model_auto_compact_token_limit = 24000
model_instructions_file = {instructions_path}
model_catalog_json = {catalog}
approval_policy = "never"
sandbox_mode = "workspace-write"
web_search = "disabled"
check_for_update_on_startup = false

[model_providers.ornith_local]
name = "Dog Walker Local Ornith"
base_url = {endpoint}
wire_api = "responses"
requires_openai_auth = false
stream_idle_timeout_ms = 1800000
request_max_retries = 0
stream_max_retries = 0

[features]
goals = false
apps = false
browser_use = false
computer_use = false
multi_agent = false
hooks = false
plugins = false
memories = false
shell_snapshot = false
skip_host_skill_discovery = true

[analytics]
enabled = false

[otel]
exporter = "none"
'''
    (home / "config.toml").write_text(config)
    return home


def model_ready():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ENDPOINT.rsplit("/v1", 1)[0] + "/props", timeout=3) as response:
        metadata = json.load(response)
    if Path(metadata.get("model_path", "")).resolve() != Path(MODEL_PATH).resolve():
        raise WalkerError("The local endpoint is serving a different or unidentified model")
    return metadata


async def stop_process(proc):
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), 5)
    except asyncio.TimeoutError:
        os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
    except ProcessLookupError:
        await proc.wait()


class CodexWorker:
    def __init__(self, store, emit, no_start=False):
        self.store, self.emit, self.no_start = store, emit, no_start
        self.proc = None

    async def ready(self):
        if not shutil.which("codex"):
            raise WalkerError("codex command is missing")
        configure()
        if not self.no_start and START_COMMAND:
            self.emit("Starting/reusing local Ornith…")
            self.proc = await asyncio.create_subprocess_exec(*START_COMMAND, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            try:
                async with asyncio.timeout(700):
                    while line := await self.proc.stdout.readline():
                        self.emit(line.decode(errors="replace").rstrip())
                    code = await self.proc.wait()
                    if code:
                        raise WalkerError(f"Ornith startup failed (exit {code})")
            finally:
                await stop_process(self.proc)
        await asyncio.to_thread(model_ready)

    async def turn(self, prompt, timeout):
        state = self.store.state
        number = state["turns"]
        turn_dir = self.store.path / "turns" / f"{number:03d}"
        turn_dir.mkdir(parents=True, exist_ok=True)
        schema = turn_dir / "schema.json"
        atomic_json(schema, SCHEMA)
        answer_file = turn_dir / "answer.json"
        argv = [shutil.which("codex"), "--no-daemon", "exec"]
        if state["session"]:
            argv += ["resume", state["session"]]
        else:
            argv += ["--sandbox", "workspace-write", "--cd", state["root"]]
        argv += ["--json", "--output-schema", str(schema), "--output-last-message", str(answer_file), "-"]
        self.store.event("prompt", turn=number, step=state["step"], prompt=prompt)
        commands, messages, errors = [], [], []
        completed = False
        self.proc = await asyncio.create_subprocess_exec(*argv, cwd=state["root"], env=environment(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True, limit=8 * 1024 * 1024)

        async def stdout():
            nonlocal completed
            while line := await self.proc.stdout.readline():
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise WalkerError("Codex emitted malformed JSONL; run paused") from exc
                self.store.event("codex", turn=number, event=event)
                typ = event.get("type")
                if typ == "thread.started":
                    session = event.get("thread_id")
                    if not isinstance(session, str) or not session:
                        raise WalkerError("Codex did not supply a valid session identifier")
                    if state["session"] and state["session"] != session:
                        raise WalkerError("Codex resumed a different session; refusing to advance")
                    self.store.save(session=session)
                elif typ == "turn.completed":
                    completed = True
                elif typ in {"error", "turn.failed"}:
                    errors.append(event)
                    self.emit(str(event))
                elif typ in {"item.started", "item.completed"}:
                    item = event.get("item", {})
                    if item.get("type") == "command_execution":
                        self.emit(f"$ {item.get('command', '')}" if typ == "item.started" else f"Command exit: {item.get('exit_code')}\n{item.get('aggregated_output', '')[-3000:]}")
                        if typ == "item.completed":
                            commands.append(item)
                    elif item.get("type") == "agent_message" and typ == "item.completed":
                        messages.append(item.get("text", ""))
                        self.emit(item.get("text", ""))
                    elif item.get("type") == "file_change":
                        self.emit(f"Files: {item.get('changes', [])}")

        async def stderr():
            while line := await self.proc.stderr.readline():
                text = line.decode(errors="replace").rstrip()
                self.store.event("codex_stderr", turn=number, message=text)
                self.emit(text)

        try:
            async with asyncio.timeout(timeout):
                self.proc.stdin.write(prompt.encode())
                await self.proc.stdin.drain()
                self.proc.stdin.close()
                async with asyncio.TaskGroup() as group:
                    group.create_task(stdout())
                    group.create_task(stderr())
                code = await self.proc.wait()
        except TimeoutError as exc:
            raise WalkerError(f"Worker exceeded {timeout} seconds; review partial work before retrying") from exc
        finally:
            await stop_process(self.proc)
        if code or not completed or not state["session"] or errors:
            raise WalkerError(f"Incomplete Codex turn (exit={code}, completed={completed}); see event log")
        try:
            result = parse_result(answer_file.read_text() if answer_file.is_file() else messages[-1])
        except (OSError, json.JSONDecodeError, ValidationError, IndexError) as exc:
            raise WalkerError(f"Worker result did not match StepResult: {exc}") from exc
        self.store.event("worker_result", turn=number, result=result, commands=commands)
        return result, commands
