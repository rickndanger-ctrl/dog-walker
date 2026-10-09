import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import yaml
from .storage import APP_ROOT, DATA, Store, git
from .workflow import WalkerError, load_workflow
from .judge import LocalJudge, MODEL_DIR, prepare
from .worker import MODEL_PATH, model_ready, configure


def fixture():
    demos = DATA / "demos"
    demos.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="coding-", dir=demos))
    for f in (APP_ROOT / "examples/fixture").iterdir():
        if f.is_file():
            shutil.copy2(f, root / f.name)
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=Dog Walker Demo", "-c", "user.email=demo@localhost", "commit", "-qm", "Disposable fixture")
    return root


def new_workflow(folder):
    root = Path(folder).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "steps").mkdir()
    (root / "steps/01-task.md").write_text("Complete the following task in ${project_root}.\n\nREPLACE THIS WITH YOUR TASK.\n")
    (root / "steps/01-retry.md").write_text("Continue the same task. Correct these failed checks:\n${failed_checks}\n\nPrevious result:\n${previous_result}\n")
    (root / "workflow.yaml").write_text(yaml.safe_dump({"version": 1, "name": root.name, "entry": "task", "steps": [{"id": "task", "prompt": "steps/01-task.md", "retry_prompt": "steps/01-retry.md", "max_retries": 2, "checks": [], "questions": {}}]}, sort_keys=False))
    return root


def doctor():
    report = {"offline": True, "cloud_fallback": False, "python": sys.version.split()[0],
              "codex": shutil.which("codex"), "worker_weights": Path(MODEL_PATH).is_file(),
              "judge_cached": (MODEL_DIR / "dog-walker-manifest.json").is_file(), "data_folder": str(DATA)}
    try:
        model_ready()
        report["worker"] = "ready"
    except Exception as exc:
        report["worker"] = f"not started / unavailable: {exc}"
    try:
        judge = LocalJudge()
        answer = judge.decide("The job completed successfully. All tests passed. There are no blockers.", {"done": {"type": "noul", "instructions": "Has the job completed successfully?"}})
        report["judge_smoke"] = answer["answers"]
    except Exception as exc:
        report["judge_error"] = str(exc)
    print(json.dumps(report, indent=2))
    return 0 if report["codex"] and report["worker_weights"] and "judge_error" not in report else 1


async def plain(store, no_start):
    from .engine import Engine

    async def ask(reason, passed):
        if not sys.stdin.isatty():
            return "pause"
        print(reason)
        choice = await asyncio.to_thread(input, "[a]pprove, [r]etry, [s]kip, [p]ause, [x]abort: ")
        return {"a": "approve", "r": "retry", "s": "skip", "x": "abort"}.get(choice.lower(), "pause")

    await Engine(store, lambda x: print(x, flush=True), ask, no_start).run()


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Dog Walker — offline prompt-sequence supervisor for local models. With no arguments, open the native desktop when Quickshell is installed.")
    sub = parser.add_subparsers(dest="command")
    desktop = sub.add_parser("desktop", help="Open the native desktop app")
    desktop.add_argument("file", nargs="?", default="")
    form = sub.add_parser("validate-form", help="Validate an official single-file job form without running it")
    form.add_argument("file")
    run = sub.add_parser("run", help="Run a Markdown workflow")
    run.add_argument("workflow")
    run.add_argument("--root", required=True)
    run.add_argument("--in-place", action="store_true", help="Edit the current working tree instead of creating a separate worktree")
    resume = sub.add_parser("resume", help="Continue a paused run")
    resume.add_argument("run_id")
    demo = sub.add_parser("demo", help="Create a disposable coding project and walk Ornith through its repair")
    for command in (run, resume, demo):
        command.add_argument("--auto", action="store_true", help="Advance verified steps and use bounded authored retries automatically")
        command.add_argument("--plain", action="store_true", help="Plain text instead of terminal dashboard")
        command.add_argument("--no-start", action="store_true", help="Use an already running loopback model server")
        command.add_argument("--offline", action="store_true", help="Explicit reminder: all runs are always offline")
    validate = sub.add_parser("validate")
    validate.add_argument("workflow")
    new = sub.add_parser("new", help="Create an editable workflow folder")
    new.add_argument("folder")
    sub.add_parser("setup-local-judge", help="One-time download of pinned open judge weights")
    doc = sub.add_parser("doctor", help="Check local prerequisites and run the judge smoke test")
    doc.add_argument("--offline", action="store_true")
    sub.add_parser("runs", help="List saved runs")
    args = parser.parse_args(argv)
    try:
        if args.command == "desktop" or args.command is None and shutil.which("quickshell"):
            return subprocess.call(["bash", str(APP_ROOT / "scripts/launch-desktop.sh"), getattr(args, "file", "")])
        if args.command == "validate-form":
            from .forms import compile_form
            data, workflow = compile_form(Path(args.file).read_text())
            print(f"Valid: {data['name']} ({len(workflow.steps)} steps). No commands were run.")
            return 0
        if args.command == "setup-local-judge":
            print(f"Downloading the offline judge once…\n{prepare()}")
            return 0
        if args.command == "doctor":
            return doctor()
        if args.command == "validate":
            w = load_workflow(args.workflow)
            print(f"Valid: {w.name} ({len(w.steps)} steps)")
            return 0
        if args.command == "new":
            print(f"Workflow created: {new_workflow(args.folder)}\nEdit steps/01-task.md and workflow.yaml, then use dog-walker run FOLDER --root PROJECT.")
            return 0
        if args.command == "runs":
            for path in sorted((DATA / "runs").glob("*/state.json"), reverse=True):
                s = json.loads(path.read_text())
                print(f"{s['id']}  {s['status']:10}  {s['name']}  step={s['step']}")
            return 0
        if args.command == "resume":
            store = Store.open(args.run_id)
            if args.auto:
                # Changing mode must not overwrite a run controlled elsewhere.
                store.acquire()
                try:
                    store.state = Store.open(args.run_id).state
                    store.save(auto=True)
                finally:
                    store.release()
        else:
            w = load_workflow(args.workflow if args.command == "run" else APP_ROOT / "examples/coding")
            root = args.root if args.command == "run" else fixture()
            store = Store.create(w, root, getattr(args, "auto", False), getattr(args, "in_place", False))
        configure()
        if getattr(args, "plain", False) or not sys.stdout.isatty():
            asyncio.run(plain(store, getattr(args, "no_start", False)))
        else:
            from .ui import Dashboard
            Dashboard(store, getattr(args, "no_start", False)).run()
        return 0 if store.state["status"] == "completed" else 2
    except (WalkerError, OSError, ValueError) as exc:
        print(f"Dog Walker: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nPaused. Run dog-walker runs to find the saved run.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
