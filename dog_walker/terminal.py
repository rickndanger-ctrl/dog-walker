"""Real terminal observation and interactive Claude/Codex operator sessions."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from .storage import APP_ROOT, DATA, Store, atomic_json, digest, project_inventory, scrub
from .workflow import WalkerError

SCRIPT = APP_ROOT / "scripts/walk-terminal.py"
MCP_SCRIPT = APP_ROOT / "scripts/helper-server.py"
PYTHON = APP_ROOT / ".venv/bin/python"


def clean_terminal(text):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(scrub(text)))
    return "".join(c for c in text if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))


def recent_events(run_path, limit=10):
    path = Path(run_path) / "events.jsonl"
    if not path.exists():
        return []
    with path.open("rb") as stream:
        stream.seek(0, 2)
        offset = max(0, stream.tell() - 256 * 1024)
        stream.seek(offset)
        if offset:
            stream.readline()
        lines = stream.read(256 * 1024).decode("utf-8", errors="replace").splitlines()
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
            if isinstance(value, dict) and render_event(value):
                rows.append(value)
        except ValueError:
            continue
    return rows[-limit:]


def render_event(event):
    typ = event.get("type")
    value = ""
    if typ == "codex":
        inner = event.get("event") or {}
        item = inner.get("item") or {}
        kind = item.get("type")
        if kind == "agent_message":
            value = item.get("text", "")
        elif kind == "command_execution":
            if inner.get("type") == "item.started":
                value = "$ " + item.get("command", "")
            else:
                value = "Exit " + str(item.get("exit_code")) + "\n" + item.get("aggregated_output", "")[-2500:]
        elif kind == "error":
            value = "Error: " + item.get("message", "")
        elif inner.get("type") in {"turn.failed", "error"}:
            value = json.dumps(inner)
    elif typ == "worker_result":
        value = (event.get("result") or {}).get("summary", "Worker reported a result")
    elif typ == "evaluation":
        value = "Verification: " + json.dumps(event.get("evaluation"))[:2500]
    elif typ in {"paused", "completed", "step_finished", "helper_file_edit", "helper_verification", "helper_guidance_used"}:
        value = json.dumps({k: v for k, v in event.items() if k != "time"})[:2500]
    elif typ == "prompt":
        value = "Step: " + str(event.get("step")) + " · turn " + str(event.get("turn"))
    elif typ == "codex_stderr":
        value = event.get("message", "")
    return clean_terminal(value)[:4000]


def watch(run_id):
    store = Store.open(run_id)
    print(clean_terminal("Handler · " + store.state["name"] + "\nRun: " + run_id))
    print("Live output. Closing this pane does not stop the walk.\n", flush=True)
    for event in recent_events(store.path):
        print(render_event(event), flush=True)
    path = store.path / "events.jsonl"
    while not path.exists():
        time.sleep(.25)
    with path.open() as stream:
        stream.seek(0, 2)
        last = None
        while True:
            state = Store.open(run_id).state
            status = (state["status"], state["phase"], state["step"])
            if status != last:
                print(clean_terminal("\n" + " · ".join(status)), flush=True)
                last = status
            position = stream.tell()
            line = stream.readline(256 * 1024 + 1)
            if len(line) > 256 * 1024:
                while line and not line.endswith("\n"):
                    line = stream.readline(256 * 1024)
                print("Large event omitted; inspect the saved run log for details.", flush=True)
                continue
            if not line or not line.endswith("\n"):
                stream.seek(position)
                time.sleep(.25)
                continue
            try:
                value = render_event(json.loads(line))
                if value:
                    print(value, flush=True)
            except ValueError:
                continue


def open_terminal(argv, cwd):
    if not shutil.which("omarchy"):
        raise WalkerError("Omarchy's terminal launcher is unavailable")
    # Without --, Omarchy can interpret "tmux" as its own terminal-tmux route.
    return subprocess.Popen(["omarchy", "launch", "terminal", "--", *map(str, argv)], cwd=cwd,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


def shell_rc(store):
    """Write shortcuts without starting a terminal or any helper inference."""
    folder = DATA / "terminals"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    rc = folder / (store.state["id"] + ".bashrc")
    command = [str(PYTHON), "-I", str(SCRIPT), "helper", "--attached", "--run-id", store.state["id"]]
    rc.write_text("if [[ -r ~/.bashrc ]]; then source ~/.bashrc; fi\n"
        + "check-model() { " + shlex.join(command) + ' --mode review --provider "${1:-codex}"; }\n'
        + "help-model() { " + shlex.join(command) + ' --mode drive --provider "${1:-codex}"; }\n'
        + "printf '%s\\n' 'Choose Claude or Codex above, or use this shell.' ''\n")
    rc.chmod(0o600)
    return rc


def ensure_live(store, embedded=False):
    if not shutil.which("tmux"):
        raise WalkerError("Install tmux to open the live terminal")
    rc = shell_rc(store)
    prefix = ["tmux", "-L", "handler"]
    session = "walk-" + store.state["id"] + ("-inside" if embedded else "")
    if subprocess.run([*prefix, "has-session", "-t", session], capture_output=True).returncode:
        subprocess.run([*prefix, "new-session", "-d", "-s", session, "-c", store.state["root"],
                        "-e", "DOG_WALKER_DATA=" + str(DATA),
                        str(PYTHON), "-I", str(SCRIPT), "watch", "--run-id", store.state["id"]], check=True, capture_output=True)
        subprocess.run([*prefix, "split-window", "-h", "-t", session, "-c", store.state["root"],
                        "bash", "--rcfile", str(rc), "-i"], check=True, capture_output=True)
        subprocess.run([*prefix, "select-layout", "-t", session, "even-horizontal"], check=True, capture_output=True)
    return session


def launch_live(store):
    session = ensure_live(store)
    open_terminal(["tmux", "-L", "handler", "attach-session", "-t", session], store.state["root"])
    return session


def embedded_terminal(store, kind="live", provider=None, mode="review", *, attach_only=False):
    """Prepare a persistent terminal, returning a native PTY attachment descriptor."""
    if kind not in {"live", "context", "shell", "helper"}:
        raise WalkerError("Choose a live terminal, shell, or model helper")
    if kind == "helper" and (provider not in {"claude", "codex"} or mode not in {"review", "drive"}):
        raise WalkerError("Choose Claude or Codex, in review or help mode")
    if kind == "helper" and not attach_only and not shutil.which(provider):
        raise WalkerError(provider.title() + " CLI is not installed")
    if not shutil.which("tmux"):
        raise WalkerError("Install tmux to open the embedded terminal")
    label, key = "Live", "live"
    if kind == "live":
        session = ensure_live(store, embedded=True)
    else:
        key = kind if kind in {"context", "shell"} else provider + "-" + mode
        label = "Live context" if kind == "context" else "Shell" if kind == "shell" else provider.title() + (" · Review" if mode == "review" else " · Help")
        session = "walk-" + store.state["id"] + "-" + key
        prefix = ["tmux", "-L", "handler"]
        if subprocess.run([*prefix, "has-session", "-t", session], capture_output=True).returncode:
            if attach_only:
                raise WalkerError("No saved agent terminal to reconnect")
            if kind == "context":
                argv = [str(PYTHON), "-I", str(SCRIPT), "watch", "--run-id", store.state["id"]]
            elif kind == "shell":
                argv = ["bash", "--rcfile", str(shell_rc(store)), "-i"]
            else:
                argv = [str(PYTHON), "-I", str(SCRIPT), "helper", "--attached", "--run-id",
                        store.state["id"], "--provider", provider, "--mode", mode]
            # remain-on-exit preserves CLI errors/results without killing another tab.
            subprocess.run([*prefix, "new-session", "-d", "-s", session, "-c", store.state["root"],
                            "-e", "DOG_WALKER_DATA=" + str(DATA),
                            *argv], check=True, capture_output=True)
            subprocess.run([*prefix, "set-option", "-t", session, "remain-on-exit", "on"], check=True, capture_output=True)
        # Handler supplies pane labels and agent tabs, so tmux's extra status
        # bar would duplicate them and take space from the small terminals.
        subprocess.run([*prefix, "set-option", "-t", session, "status", "off"], check=True, capture_output=True)
    return {"id": store.state["id"] + ":" + key, "run_id": store.state["id"], "label": label, "kind": kind,
            "session": session, "program": shutil.which("tmux"),
            "args": ["-L", "handler", "attach-session", "-t", session], "cwd": store.state["root"]}


def create_context(store, mode):
    """A bounded project copy and explicit instructions, with no config/secrets export."""
    from .helper import HelperServer, regular_path
    base = DATA / "helpers"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = Path(tempfile.mkdtemp(prefix=store.state["id"] + "-", dir=base))
    folder.chmod(0o700)
    project = folder / "project"
    project.mkdir(mode=0o700)
    root = Path(store.state["root"])
    copied, skipped = [], []
    total = 0
    for relative in sorted(project_inventory(root)):
        try:
            source = regular_path(root, relative)
            if (not source.is_file() or source.stat().st_size > 2 * 1024 * 1024
                or source.suffix in {".pem", ".key"} or len(copied) >= 200
                or total + source.stat().st_size > 8 * 1024 * 1024):
                skipped.append(relative); continue
            expected = digest(source)
            body = source.read_bytes()
            if len(body) > 2 * 1024 * 1024 or b"\0" in body or digest(source) != expected:
                skipped.append(relative); continue
            destination = project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
            destination.chmod(0o600)
            total += len(body); copied.append(relative)
        except (WalkerError, OSError):
            skipped.append(relative)
    status = HelperServer(store.state["id"], mode).execute("handler_status", {})
    (folder / "CONTEXT.md").write_text("# Handler helper context\n\n"
        + "You are assisting the selected local-model walk. Files in project/ are a snapshot, not the live workspace. "
          "Use handler_status and handler_read_file for fresh instructions and current hashes. "
          "Do not edit this snapshot or any files with ordinary shell/editor tools.\n\n"
        + ("Review only: inspect progress, identify bugs or stalls, and suggest a concise fix. Use handler_suggest "
           "to save advice; do not pause, edit, or advance the walk.\n\n" if mode == "review" else
           "Help mode: the walk is paused before launch. Use ONLY Handler MCP tools to edit allowlisted files, "
           "verify, queue guidance and resume/retry. Never edit protected tests, alter the plan or checks, install "
           "packages, switch the local model or approve completion. Rick owns final approval.\n\n")
        + "The selected Claude/Codex CLI uses its configured account and model. No fallback provider is enabled by Handler.\n\n"
        + "## Live state when opened\n\n```json\n" + json.dumps(scrub(status), indent=2, ensure_ascii=False)
        + "\n```\n\nSnapshot files: " + ", ".join(copied)
        + "\nSkipped files: " + ", ".join(skipped) + "\n")
    (folder / "CONTEXT.md").chmod(0o600)
    config = {"mcpServers": {"handler": {"command": str(PYTHON),
        "args": ["-I", str(MCP_SCRIPT), "--run-id", store.state["id"], "--mode", mode]}}}
    atomic_json(folder / "mcp.json", config)
    return folder


def helper_argv(provider, mode, folder, run_id):
    if provider not in {"claude", "codex"} or mode not in {"review", "drive"}:
        raise WalkerError("Choose Claude or Codex, in review or help mode")
    prompt = ("Read ../CONTEXT.md and use the Handler MCP tools for this selected walk. "
              + ("Check my local model's progress and code. Identify why it is slow or stuck and suggest focused fixes. "
                 "Keep the live walk running; do not edit files or control it." if mode == "review" else
                 "Help my local model finish this step. Inspect the current state, repair only allowed files via MCP, "
                 "run its authored checks, guide the model if needed, and resume/retry through Handler. "
                 "Keep all checks and final human approval intact."))
    if provider == "claude":
        return ["claude", "--strict-mcp-config", "--mcp-config", str(folder / "mcp.json"),
                "--setting-sources", "user", "--settings", '{"disableAllHooks":true,"autoMemoryEnabled":false}',
                "--disable-slash-commands", "--permission-mode", "plan" if mode == "review" else "manual",
                "--tools", "Read,Glob,Grep", "--", prompt]
    args = json.dumps(["-I", str(MCP_SCRIPT), "--run-id", run_id, "--mode", mode])
    env_vars = json.dumps(["PATH", "DOG_WALKER_DATA", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"])
    return ["codex", "--no-alt-screen", "--sandbox", "read-only", "--ask-for-approval", "on-request",
            "--cd", str(folder / "project"), "-c", "mcp_servers.handler.command=" + json.dumps(str(PYTHON)),
            "-c", "mcp_servers.handler.args=" + args, "-c", "mcp_servers.handler.env_vars=" + env_vars,
            "-c", "mcp_servers.handler.tool_timeout_sec=120", prompt]


def launch_helper(store, provider, mode):
    if provider not in {"claude", "codex"} or mode not in {"review", "drive"}:
        raise WalkerError("Choose Claude or Codex, in review or help mode")
    if not shutil.which(provider):
        raise WalkerError(provider.title() + " CLI is not installed")
    open_terminal([str(PYTHON), "-I", str(SCRIPT), "helper", "--run-id", store.state["id"],
                   "--provider", provider, "--mode", mode, "--attached"], store.state["root"])


def hold_error(attached):
    if attached and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this terminal.")
        except (EOFError, KeyboardInterrupt):
            pass


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Handler live terminal and scoped model helpers")
    parser.add_argument("action", choices=["live", "watch", "helper"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--provider", choices=["claude", "codex"], default="codex")
    parser.add_argument("--mode", choices=["review", "drive"], default="review")
    parser.add_argument("--attached", action="store_true")
    args = parser.parse_args(argv)
    try:
        store = Store.open(args.run_id)
        if args.action == "live":
            launch_live(store)
        elif args.action == "watch":
            watch(args.run_id)
        elif not args.attached:
            launch_helper(store, args.provider, args.mode)
        else:
            from .helper import HelperServer
            if args.mode == "drive":
                HelperServer(args.run_id, "drive").control("pause")
            store = Store.open(args.run_id)
            folder = create_context(store, args.mode)
            print("Review only · model keeps running" if args.mode == "review" else "Help mode · walk paused; changes go through Handler's scoped tools")
            print("Using your configured " + args.provider.title() + " CLI account and model.\n", flush=True)
            env = dict(os.environ)
            # Never send helpers through Handler's private local-worker profile.
            if env.get("CODEX_HOME") == str(DATA / "codex-home"):
                env.pop("CODEX_HOME")
            env.pop("CLAUDECODE", None)
            code = subprocess.call(helper_argv(args.provider, args.mode, folder, args.run_id),
                                   cwd=folder / "project", env=env)
            if code:
                print("Handler: " + args.provider.title() + " exited with code " + str(code), file=sys.stderr)
                hold_error(True)
            return code
        return 0
    except KeyboardInterrupt:
        return 0
    except (WalkerError, OSError, subprocess.SubprocessError) as exc:
        print(clean_terminal("Handler: " + str(exc)), file=sys.stderr)
        hold_error(args.attached)
        return 1
