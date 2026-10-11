"""Preliminary paired benchmark for Dog Walker's optional local coder.

The benchmark always drives the normal Engine/Store/worker path. Its generated
fixture projects are disposable, and hidden acceptance checks live outside the
workspace given to the coding worker.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import statistics
import time
from contextlib import contextmanager

from .workflow import WalkerError, load_workflow

TURN_BUDGET = 4
TRIAL_SECONDS = 600
CONDITIONS = ("main", "helper")


def _case_data():
    # Files in `tests` are ordinary, visible baseline checks. The additional
    # checks below are kept in the benchmark controller, outside worker roots.
    return {
        "bug": {
            "category": "bug",
            "task": "Fix apply_discount so it returns the final price after a percentage discount. Preserve the public function name and reject percentages outside 0..100 with ValueError.",
            "files": {
                "price.py": "def apply_discount(price, percent):\n    return price * percent / 100\n",
                "tests/test_basic.py": "import unittest\nfrom price import apply_discount\nclass Basic(unittest.TestCase):\n def test_discount(self): self.assertEqual(apply_discount(100, 20), 80)\nif __name__ == '__main__': unittest.main()\n",
            },
            "allowed": ["price.py"],
            "hidden": "import sys\nsys.path.insert(0, sys.argv[1])\nfrom price import apply_discount\nassert apply_discount(19.99, 0) == 19.99\nassert apply_discount(19.99, 100) == 0\nassert apply_discount(100, 12.5) == 87.5\nfor bad in (-1, 101):\n try: apply_discount(10, bad)\n except ValueError: pass\n else: raise AssertionError('invalid percentage accepted')\n",
        },
        "boundary": {
            "category": "boundary",
            "task": "Make chunk_items return consecutive chunks. It must return [] for empty input and raise ValueError when size is zero or negative.",
            "files": {
                "chunks.py": "def chunk_items(items, size):\n    return [items[i:i + size] for i in range(0, len(items), size)]\n",
                "tests/test_basic.py": "import unittest\nfrom chunks import chunk_items\nclass Basic(unittest.TestCase):\n def test_chunks(self): self.assertEqual(chunk_items([1,2,3], 2), [[1,2],[3]])\nif __name__ == '__main__': unittest.main()\n",
            },
            "allowed": ["chunks.py"],
            "hidden": "import sys\nsys.path.insert(0, sys.argv[1])\nfrom chunks import chunk_items\nassert chunk_items([], 2) == []\nassert chunk_items([1,2,3,4], 2) == [[1,2],[3,4]]\nfor size in (0, -1):\n try: chunk_items([1], size)\n except ValueError: pass\n else: raise AssertionError('invalid size accepted')\n",
        },
        "multifile": {
            "category": "multifile",
            "task": "Consolidate title formatting in the shared text module and make both CLI entry points use it. Keep the existing output format, including empty and mixed-case titles.",
            "files": {
                "text.py": "# Shared text helpers will live here.\n",
                "cli.py": "def title_for_cli(value):\n    return value.strip().title()\n",
                "admin/cli.py": "def title_for_admin(value):\n    return value.strip().title()\n",
                "tests/test_basic.py": "import unittest\nfrom cli import title_for_cli\nclass Basic(unittest.TestCase):\n def test_title(self): self.assertEqual(title_for_cli(' hello world '), 'Hello World')\nif __name__ == '__main__': unittest.main()\n",
            },
            "allowed": ["text.py", "cli.py", "admin/cli.py"],
            "hidden": "import ast, pathlib, sys\nsys.path.insert(0, sys.argv[1])\nfrom cli import title_for_cli\nfrom admin.cli import title_for_admin\nfor value, expected in [(' hello world ', 'Hello World'), ('', ''), ('mIXed Case', 'Mixed Case')]:\n assert title_for_cli(value) == expected\n assert title_for_admin(value) == expected\ndef imported_shared_call(path, function_name):\n tree=ast.parse(path.read_text())\n imported={}\n for node in ast.walk(tree):\n  if isinstance(node, ast.ImportFrom) and node.module == 'text':\n   for alias in node.names: imported[alias.asname or alias.name]=alias.name\n fn=next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name)\n return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in imported for n in ast.walk(fn))\nroot=pathlib.Path(sys.argv[1])\nassert imported_shared_call(root/'cli.py', 'title_for_cli'), 'CLI must call a helper imported from text.py'\nassert imported_shared_call(root/'admin/cli.py', 'title_for_admin'), 'admin CLI must call a helper imported from text.py'\n",
        },
        "regressiontest": {
            "category": "regressiontest",
            "task": "Fix is_enabled so None, empty text, and whitespace-only text are disabled, while case-insensitive 'true' is enabled. Add a focused regression test in tests/test_regression.py that asserts whitespace-only text is disabled.",
            "files": {
                "flags.py": "def is_enabled(value):\n    return bool(value)\n",
                "tests/test_basic.py": "import unittest\nfrom flags import is_enabled\nclass Basic(unittest.TestCase):\n def test_true(self): self.assertTrue(is_enabled('true'))\nif __name__ == '__main__': unittest.main()\n",
            },
            "allowed": ["flags.py", "tests/test_basic.py", "tests/test_regression.py"],
            "hidden": "import pathlib, shutil, subprocess, sys, tempfile\nroot=pathlib.Path(sys.argv[1])\nsys.path.insert(0, str(root))\nfrom flags import is_enabled\nassert is_enabled(None) is False\nassert is_enabled('') is False\nassert is_enabled('  \\t') is False\nassert is_enabled('TRUE') is True\nassert is_enabled('false') is False\ntest=root/'tests/test_regression.py'\nassert test.is_file(), 'tests/test_regression.py is required'\nwith tempfile.TemporaryDirectory() as tmp:\n d=pathlib.Path(tmp); (d/'tests').mkdir(); shutil.copy2(test, d/'tests/test_regression.py')\n (d/'flags.py').write_text(\"def is_enabled(value):\\n    return bool(value)\\n\")\n buggy=subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_regression.py'], cwd=d, capture_output=True, text=True)\n assert buggy.returncode != 0, 'regression test does not catch the original whitespace bug'\n fixed=subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_regression.py'], cwd=root, capture_output=True, text=True)\n assert fixed.returncode == 0, 'regression test fails against the fixed implementation: '+fixed.stderr\n",
        },
        "navigation": {
            "category": "navigation",
            "task": "Find normalize_name in the nested package and make it collapse all internal whitespace to one space while trimming both ends. Preserve the existing case conversion.",
            "files": {
                "app/__init__.py": "",
                "app/people/__init__.py": "",
                "app/people/names.py": "def normalize_name(value):\n    return value.strip().title()\n",
                "tests/test_basic.py": "import unittest\nfrom app.people.names import normalize_name\nclass Basic(unittest.TestCase):\n def test_name(self): self.assertEqual(normalize_name('  ada lovelace '), 'Ada Lovelace')\nif __name__ == '__main__': unittest.main()\n",
            },
            "allowed": ["app/people/names.py"],
            "hidden": "import sys\nsys.path.insert(0, sys.argv[1])\nfrom app.people.names import normalize_name\nassert normalize_name('  ada   van\\trossum ') == 'Ada Van Rossum'\nassert normalize_name('ONE') == 'One'\nassert normalize_name('') == ''\n",
        },
        "refactor": {
            "category": "refactor",
            "task": "Refactor the repeated clamping logic into one private helper used by both functions. Preserve behavior for normal, negative, and above-maximum inputs.",
            "files": {
                "ranges.py": "def percent(value):\n    if value < 0:\n        return 0\n    if value > 100:\n        return 100\n    return value\n\ndef ratio(value):\n    if value < 0:\n        return 0\n    if value > 1:\n        return 1\n    return value\n",
                "tests/test_basic.py": "import unittest\nfrom ranges import percent, ratio\nclass Basic(unittest.TestCase):\n def test_values(self): self.assertEqual(percent(50), 50); self.assertEqual(ratio(.5), .5)\nif __name__ == '__main__': unittest.main()\n",
            },
            "allowed": ["ranges.py"],
            "hidden": "import ast, pathlib, sys\nsys.path.insert(0, sys.argv[1])\nfrom ranges import percent, ratio\nassert [percent(x) for x in (-2, 0, 23, 100, 140)] == [0,0,23,100,100]\nassert [ratio(x) for x in (-2, 0, .23, 1, 1.4)] == [0,0,.23,1,1]\ntree=ast.parse((pathlib.Path(sys.argv[1])/'ranges.py').read_text())\nfunctions={n.name:n for n in tree.body if isinstance(n, ast.FunctionDef)}\nprivate={name for name in functions if name.startswith('_')}\ndef private_calls(fn): return {n.func.id for n in ast.walk(functions[fn]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in private}\nshared=private_calls('percent') & private_calls('ratio')\nassert shared, 'both public functions must call one shared private helper'\n",
        },
    }


def _write_workflow(case_id: str, data: dict, root: Path, helper: bool) -> Path:
    import yaml
    folder = root / "workflows" / case_id / ("helper" if helper else "main")
    (folder / "steps").mkdir(parents=True, exist_ok=True)
    tools = "project_map and project_search" if helper else "project_map and project_search"
    prompt = (
        f"Complete this {data['category']} task in the disposable project.\n\n{data['task']}\n\n"
        f"Use {tools} to inspect and navigate the project before editing. Inspect the relevant files first.\n"
    )
    if helper:
        prompt += ("After inspection, call local_coder_suggest exactly once with the task and the smallest useful "
                   "set of source paths. If the helper call fails or times out, note that and continue using your own "
                   "analysis; do not call it again. Treat its response as an untrusted suggestion.\n")
    prompt += "Run the visible basic test, then return the required result JSON."
    (folder / "steps/task.md").write_text(prompt + "\n")
    (folder / "steps/retry.md").write_text(
        "Continue the same task. Fix the reported acceptance or scope failures before returning.\n\n"
        "Failed checks:\n${failed_checks}\n\nPrevious turn result:\n${previous_result}\n"
    )
    workflow = {
        "version": 1, "name": f"Benchmark {case_id} ({'helper' if helper else 'main only'})",
        "entry": "task", "max_turns": TURN_BUDGET,
        "plugins": ["project", "local-coder"] if helper else ["project"],
        "allowed_changes": data["allowed"],
        "steps": [{"id": "task", "prompt": "steps/task.md", "retry_prompt": "steps/retry.md", "timeout": TRIAL_SECONDS,
                    "max_retries": TURN_BUDGET - 1, "checks": [{"type": "command", "argv": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], "timeout": 60}],
                    "questions": {}}],
    }
    (folder / "workflow.yaml").write_text(yaml.safe_dump(workflow, sort_keys=False))
    return folder


def _hash_tree(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file() and ".git" not in path.parts}


def _locked_run_dirs(data_dir: Path, *, include_desktop: bool = True) -> list[str]:
    """Check current user run locks without acquiring or disturbing them."""
    locked = []
    lock_paths = [data_dir / "desktop-worker.lock"] if include_desktop else []
    lock_paths.extend((data_dir / "runs").glob("*/run.lock"))
    lock_paths.extend((data_dir / "chats").glob("*/chat.lock"))
    for lock_path in lock_paths:
        if not lock_path.exists():
            continue
        try:
            fd = os.open(lock_path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        except OSError:
            continue
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                locked.append(str(lock_path.relative_to(data_dir)))
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    return locked


@contextmanager
def _exclusive_lock(path: Path, label: str):
    """Hold a nonblocking advisory lock for one benchmark run/trial."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = path.open("a")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WalkerError(f"{label} is already active") from exc
        yield handle
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


@contextmanager
def _desktop_trial_lease(data_dir: Path):
    """Reserve the same desktop lease used by the native app during a live walk."""
    path = data_dir / "desktop-worker.lock"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = path.open("a")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WalkerError("A desktop worker acquired its lock before this trial") from exc
        yield handle
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def _coder_service_active() -> bool | None:
    """Read the named local-coder unit state without changing it."""
    try:
        proc = subprocess.run(["systemctl", "--user", "show", "dog-walk-coder.service",
                               "--property=ActiveState", "--value", "--no-pager"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode:
        return None
    return proc.stdout.strip() in {"active", "activating", "reloading"}


def _stop_owned_coder(was_active: bool | None) -> str | None:
    """Stop only the helper service that was inactive before this pilot arm."""
    if was_active is not False or _coder_service_active() is not True:
        return None
    try:
        proc = subprocess.run(["systemctl", "--user", "stop", "dog-walk-coder.service"],
                              capture_output=True, text=True, timeout=65)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Could not stop benchmark-started local coder: {exc}"
    if proc.returncode:
        return "Could not stop benchmark-started local coder: " + (proc.stderr.strip() or proc.stdout.strip())[-1200:]
    return None


def prepare(output: Path) -> dict:
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name in ("fixtures", "workflows", "trials", "private-checks", "isolated-data", "codex-home"):
        (output / name).mkdir(mode=0o700)
    cases = _case_data()
    manifest = {"pilot": "preliminary", "created_at_unix": time.time(), "turn_budget": TURN_BUDGET,
                "trial_timeout_seconds": TRIAL_SECONDS, "tasks": list(cases), "cases": {}}
    for task, data in cases.items():
        fixture = output / "fixtures" / task
        fixture_files = {**data["files"], ".gitignore": "__pycache__/\n*.py[cod]\n"}
        for relative, body in fixture_files.items():
            path = fixture / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        data["baseline_hashes"] = _hash_tree(fixture)
        # Controller-only scoring material is deliberately outside every trial
        # workspace and never referenced from the generated workflow.
        (output / "private-checks" / f"{task}.py").write_text(data["hidden"])
        main_workflow = _write_workflow(task, data, output, False)
        helper_workflow = _write_workflow(task, data, output, True)
        manifest["cases"][task] = {"category": data["category"], "baseline_hashes": data["baseline_hashes"],
                                    "workflows": {"main": str(main_workflow.relative_to(output)),
                                                  "helper": str(helper_workflow.relative_to(output))}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "results.json").write_text(json.dumps({"pilot": "preliminary", "trials": []}, indent=2) + "\n")
    return manifest


def _pid_tree(root_pid: int) -> set[int]:
    parents = {}
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return {root_pid}
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            # The comm field is parenthesized but may itself contain spaces.
            fields = stat[stat.rfind(")") + 2:].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    found = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, ppid in parents.items():
            if ppid in found and pid not in found:
                found.add(pid)
                changed = True
    return found


def _systemd_main_pid() -> int | None:
    try:
        proc = subprocess.run(["systemctl", "--user", "show", "dog-walk-coder.service",
                               "--property=MainPID", "--value", "--no-pager"],
                              capture_output=True, text=True, timeout=3)
        pid = int(proc.stdout.strip()) if proc.returncode == 0 else 0
        return pid if pid > 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _tree_memory(pids: set[int]) -> tuple[set[int], int, int]:
    rss = swap = 0
    found = set()
    for pid in pids:
        try:
            values = {}
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                key, sep, rest = line.partition(":")
                fields = rest.split()
                if sep and key in {"VmRSS", "VmSwap"} and fields and fields[0].isdigit():
                    values[key] = int(fields[0]) * 1024
            if "VmRSS" in values:
                rss += values["VmRSS"]
                swap += values.get("VmSwap", 0)
                found.add(pid)
        except OSError:
            continue
    return found, rss, swap


def _sample_memory(root_pid: int, model_pid: int | None = None, coder_pid: int | None = None) -> dict:
    groups = {
        "benchmark": _pid_tree(root_pid),
        "main_model": _pid_tree(model_pid) if model_pid else set(),
        "local_coder": _pid_tree(coder_pid) if coder_pid else set(),
    }
    details = {}
    all_pids = set()
    for name, pids in groups.items():
        found, rss, swap = _tree_memory(pids)
        details[name] = {"process_count": len(found), "rss_bytes": rss if found else None,
                         "swap_bytes": swap if found else None}
        all_pids.update(found)
    # Union the PID sets so a service that is also a child is counted once.
    found, rss, swap = _tree_memory(all_pids)
    return {"process_count": len(found), "rss_bytes": rss if found else None,
            "swap_bytes": swap if found else None, **details}


def _token_usage(events_path: Path):
    if not events_path.is_file():
        return None
    totals = {"input_tokens": 0, "output_tokens": 0}
    found = False
    for line in events_path.read_text().splitlines():
        try:
            event = json.loads(line)
            # Codex may repeat intermediate item usage. Count only a completed
            # turn's usage object once, avoiding recursive double-counting.
            if event.get("event", {}).get("type") != "turn.completed":
                continue
            usage = event["event"].get("usage")
            if not isinstance(usage, dict):
                continue
            incoming = usage.get("input_tokens", usage.get("prompt_tokens"))
            outgoing = usage.get("output_tokens", usage.get("completion_tokens"))
            if isinstance(incoming, (int, float)):
                totals["input_tokens"] += int(incoming); found = True
            if isinstance(outgoing, (int, float)):
                totals["output_tokens"] += int(outgoing); found = True
        except (ValueError, OSError): pass
    return totals if found else None


def _run_engine(workflow: Path, project: Path, data_dir: Path, codex_home: Path, timeout: int,
                worker_factory_override=None):
    # Point the ordinary Store and worker at private benchmark state before
    # constructing them. The CodexWorker/Engine path still owns every check.
    import dog_walker.storage as storage
    import dog_walker.worker as worker
    import dog_walker.settings as settings
    from .engine import Engine
    from .storage import Store
    configured = settings.load_settings()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path = data_dir / "worker.json"
    config_path.write_text(json.dumps({**configured, "start_command": []}, indent=2) + "\n")
    config_path.chmod(0o600)
    settings.CONFIG = config_path
    storage.DATA = data_dir
    worker.DATA = data_dir
    worker.reload_settings()
    w = load_workflow(workflow)
    store = Store.create(w, project, auto=True)
    def make_worker(*args):
        return worker.CodexWorker(*args, home=codex_home)
    worker_factory = worker_factory_override or make_worker
    memory_samples = []
    async def run():
        engine = Engine(store, lambda _line: None, lambda _reason, _passed: asyncio.sleep(0, result="pause"),
                        no_start=True, worker_factory=worker_factory)
        async def sampler():
            while True:
                try:
                    from .runtime import find_runtime_pid
                    main_pid, _reason = find_runtime_pid(worker.MODEL_PATH, worker.ENDPOINT)
                except Exception:
                    main_pid = None
                coder_pid = _systemd_main_pid()
                sample = _sample_memory(os.getpid(), main_pid, coder_pid)
                memory_samples.append({"elapsed_seconds": round(time.monotonic() - started, 2), **sample})
                await asyncio.sleep(1)
        task = asyncio.create_task(sampler())
        try:
            await asyncio.wait_for(engine.run(), timeout=timeout)
        finally:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    started = time.monotonic()
    try:
        asyncio.run(run())
        status = store.state.get("status")
        error = None
    except asyncio.TimeoutError:
        status, error = "timeout", f"Trial exceeded {timeout} seconds"
        # Engine.run's worker owns and terminates its process group. Never touch
        # the separately running main or helper model service here.
    except Exception as exc:
        status, error = "error", f"{type(exc).__name__}: {exc}"
    duration = time.monotonic() - started
    events_path = store.path / "events.jsonl"
    return store, status, error, duration, events_path, memory_samples


def _run_engine_with_helper_cleanup(workflow: Path, project: Path, data_dir: Path,
                                    codex_home: Path, timeout: int, *,
                                    helper_enabled: bool, helper_was_active: bool | None):
    """Always release a helper service this trial may have started."""
    cleanup_error = None
    try:
        result = _run_engine(workflow, project, data_dir, codex_home, timeout)
    finally:
        if helper_enabled:
            cleanup_error = _stop_owned_coder(helper_was_active)
    return (*result, cleanup_error)


def _score(task: str, workspace: Path, checker: Path, *, input_project: Path,
           baseline_hashes: dict[str, str], allowed: list[str], scope_baseline: dict) -> dict:
    from .storage import scope_check
    hidden = {"pass": False, "detail": "Hidden acceptance checks did not run"}
    try:
        proc = subprocess.run([sys.executable, str(checker), str(workspace)], capture_output=True,
                              text=True, timeout=20, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        hidden = {"pass": proc.returncode == 0, "detail": (proc.stdout + proc.stderr)[-3000:]}
    except subprocess.TimeoutExpired:
        hidden = {"pass": False, "detail": "Hidden acceptance checks timed out"}
    scope = scope_check(workspace, allowed, scope_baseline)
    input_unchanged = _hash_tree(input_project) == baseline_hashes
    return {"pass": bool(hidden["pass"] and scope["pass"] and input_unchanged),
            "hidden": hidden, "scope": scope, "input_fixture_unchanged": input_unchanged}


def _trial_order(task_index: int) -> list[str]:
    return ["main", "helper"] if task_index % 2 == 0 else ["helper", "main"]


def _main_readiness() -> dict:
    from .runtime import verify_runtime
    from .settings import load_settings
    configured = load_settings()
    return verify_runtime(configured["model_path"], configured["endpoint"], timeout=3)


def _wait_main_idle(timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    readiness = {"ready": False, "reason": "runtime has not returned to idle"}
    while time.monotonic() < deadline:
        try:
            readiness = _main_readiness()
        except Exception as exc:
            readiness = {"ready": False, "reason": str(exc)}
        if readiness.get("ready"):
            return readiness
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    return readiness


def run_pilot(output: Path, resume: bool = False) -> dict:
    raise WalkerError("Live benchmark runs are disabled because the optional local coder has been retired. Use --dry-run to create the disposable fixtures without inference.")
    output = output.expanduser().resolve()
    lock = output.parent / f".{output.name}.benchmark.lock"
    with _exclusive_lock(lock, "Another benchmark runner"):
        return _run_pilot_locked(output, resume)


def _run_pilot_locked(output: Path, resume: bool = False) -> dict:
    if not (output / "manifest.json").is_file():
        if resume:
            raise WalkerError("Cannot resume: this output has no benchmark manifest")
        prepare(output)
    manifest = json.loads((output / "manifest.json").read_text())
    result_path = output / "results.json"
    results = json.loads(result_path.read_text()) if result_path.exists() else {"pilot": "preliminary", "trials": []}
    if results["trials"] and not resume:
        raise WalkerError("This pilot already has checkpoints; pass --resume to continue without replacing them")
    results.setdefault("run_started_at_unix", time.time())
    _atomic_write(result_path, results)
    completed = {(t["task"], t["condition"]) for t in results["trials"]}
    default_data = Path(os.environ.get("DOG_WALKER_DATA", Path.home() / ".local/share/dog-walker")).expanduser()
    for i, task in enumerate(manifest["tasks"]):
        data = _case_data()[task]
        base = output / "fixtures" / task
        if _hash_tree(base) != manifest["cases"][task]["baseline_hashes"]:
            raise WalkerError(f"Fixture {task} changed from its recorded baseline")
        for condition in _trial_order(i):
            if (task, condition) in completed:
                continue
            locked = _locked_run_dirs(default_data)
            if locked:
                raise WalkerError("An existing Dog Walker run is locked; benchmark paused before a trial: " + ", ".join(locked[:8]))
            # Each arm gets a fresh byte-for-byte project and isolated config.
            project = output / "trials" / task / condition / "input-project"
            project.parent.mkdir(parents=True, exist_ok=True)
            if project.exists():
                shutil.rmtree(project)
            shutil.copytree(base, project)
            if _hash_tree(project) != manifest["cases"][task]["baseline_hashes"]:
                raise WalkerError("A fresh trial fixture failed its baseline hash check")
            helper_was_active = _coder_service_active() if condition == "helper" else None
            data_dir = output / "isolated-data" / task / condition
            # Worker environment() derives CODEX_HOME from the isolated data root.
            home = data_dir / "codex-home"
            data_dir.mkdir(parents=True, exist_ok=True)
            home.mkdir(parents=True, exist_ok=True)
            workflow = output / manifest["cases"][task]["workflows"][condition]
            readiness = _main_readiness()
            if not readiness.get("ready"):
                results["paused_reason"] = "Main model is not healthy and idle; no trial was started. " + str(readiness.get("reason", "runtime check failed"))
                results["updated_at_unix"] = time.time()
                _atomic_write(result_path, results)
                _write_report(output, manifest, results)
                raise WalkerError(results["paused_reason"])
            started_at = time.time()
            with _desktop_trial_lease(default_data):
                raced_locks = _locked_run_dirs(default_data, include_desktop=False)
                if raced_locks:
                    raise WalkerError("A user run/chat acquired a lock before the benchmark trial: " + ", ".join(raced_locks[:8]))
                store, status, error, duration, events, memory_samples, helper_stop_error = _run_engine_with_helper_cleanup(
                    workflow, project, data_dir, home, TRIAL_SECONDS,
                    helper_enabled=condition == "helper", helper_was_active=helper_was_active)
            state = store.state
            rows = []
            try:
                rows = [json.loads(line) for line in events.read_text().splitlines()]
            except OSError:
                pass
            coder_calls = [e for e in rows if e.get("type") == "plugin_tool" and e.get("tool") == "local_coder_suggest"]
            successful_calls = [e for e in coder_calls if e.get("result", {}).get("isError") is False]
            workspace = Path(state["root"])
            score = _score(task, workspace, output / "private-checks" / f"{task}.py",
                           input_project=project, baseline_hashes=manifest["cases"][task]["baseline_hashes"],
                           allowed=data["allowed"], scope_baseline=state["scope_hashes"])
            trial = {
                "task": task, "category": data["category"], "condition": condition,
                "status": status, "engine_status": state.get("status"), "error": error,
                "reason": state.get("reason"), "checks_pass": bool(score["pass"]),
                "correct": bool(score["pass"] and status == "completed"), "scoring": score,
                "seconds": round(duration, 3), "turns": state.get("turns", 0),
                "helper_calls": len(coder_calls), "helper_successes": len(successful_calls),
                "helper_call_seconds": round(sum(e.get("duration_ms", 0) for e in coder_calls) / 1000, 3),
                "helper_timeouts": sum("timed out" in json.dumps(e.get("result", {})).lower() for e in coder_calls),
                "helper_server_was_active": helper_was_active if condition == "helper" else None,
                "helper_cleanup_error": helper_stop_error,
                "process_memory_samples": memory_samples,
                "peak_sampled_rss_bytes": max((s["rss_bytes"] for s in memory_samples if s["rss_bytes"] is not None), default=None),
                "peak_main_model_rss_bytes": max((s["main_model"]["rss_bytes"] for s in memory_samples if s["main_model"]["rss_bytes"] is not None), default=None),
                "peak_local_coder_rss_bytes": max((s["local_coder"]["rss_bytes"] for s in memory_samples if s["local_coder"]["rss_bytes"] is not None), default=None),
                "tokens": _token_usage(events), "run_id": state.get("id"), "started_at_unix": started_at,
                "order": _trial_order(i),
            }
            results["trials"].append(trial)
            results["updated_at_unix"] = time.time()
            _atomic_write(result_path, results)
            _write_report(output, manifest, results)
            completed_count = len(results["trials"])
            outcome = "passed" if trial["correct"] else "needs review"
            print(f"[{completed_count}/12] {task} / {'main model' if condition == 'main' else 'main + helper'}: {outcome} in {trial['seconds']:.1f}s; {trial['turns']} turns; helper calls {trial['helper_calls']}/{trial['helper_successes']}", flush=True)
            if _hash_tree(base) != manifest["cases"][task]["baseline_hashes"]:
                raise WalkerError(f"Original fixture {task} changed during a trial")
            if status == "timeout":
                idle = _wait_main_idle(60)
                if not idle.get("ready"):
                    results["paused_reason"] = "The main model did not return to healthy idle state within 60 seconds after a timed-out trial; no later trial was started. " + str(idle.get("reason", "runtime check failed"))
                    results["updated_at_unix"] = time.time()
                    _atomic_write(result_path, results)
                    _write_report(output, manifest, results)
                    raise WalkerError(results["paused_reason"])
    results["pilot"] = "preliminary"
    results["complete"] = len(results["trials"]) == 12
    results.pop("paused_reason", None)
    _atomic_write(result_path, results)
    _write_report(output, manifest, results)
    return results


def _atomic_write(path: Path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def _write_report(output: Path, manifest: dict, results: dict):
    trials = results.get("trials", [])
    runtime = max(0, (results.get("updated_at_unix") or time.time()) - results.get("run_started_at_unix", time.time()))
    aliases = {"main": "Main model", "helper": "Main + helper"}
    lines = ["# Dog Walker helper benchmark (preliminary)", "",
             "This is a preliminary pilot with six disposable tasks. Each task gets one main model walk and one main plus helper walk, with order alternating by task. A walk uses Dog Walker's regular Engine, a four-turn limit, a ten-minute cap, and isolated trial data. The runner checks that the main model is healthy and idle before each walk, and never starts or restarts it.", "",
             f"Completed {len(trials)} of 12 walks. Total pilot time so far: {runtime / 60:.1f} minutes.", "",
             "| Condition | Code + scope checks passing | Completed and correct | Median time | Peak sampled memory |",
             "|---|---:|---:|---:|---:|"]
    for condition in CONDITIONS:
        rows = [t for t in trials if t["condition"] == condition]
        checks_passed = sum(_trial_checks_pass(t) for t in rows)
        completed_correct = sum(bool(t.get("correct")) for t in rows)
        med = statistics.median(t["seconds"] for t in rows) if rows else None
        peaks = [t.get("peak_sampled_rss_bytes") for t in rows if t.get("peak_sampled_rss_bytes") is not None]
        peak = max(peaks) if peaks else None
        med_text = f"{med:.1f}s" if med is not None else "n/a"
        peak_text = f"{peak / 1024**3:.2f} GiB" if peak is not None else "n/a"
        lines.append(f"| {aliases[condition]} | {checks_passed}/{len(rows)} | {completed_correct}/{len(rows)} | {med_text} | {peak_text} |")
    helper_rows = [t for t in trials if t["condition"] == "helper"]
    missed = sum(t.get("helper_calls", 0) != 1 for t in helper_rows)
    errors = sum(max(0, t.get("helper_calls", 0) - t.get("helper_successes", 0)) for t in helper_rows)
    timeouts = sum(t.get("helper_timeouts", 0) for t in helper_rows)
    lines += ["", f"Helper calls: {missed} of {len(helper_rows)} helper walks missed the exactly-one-call target; {errors} errors; {timeouts} timeouts.", "",
             "Code + scope checks mean the hidden acceptance checks passed, changes stayed within the allowed files, and the original fixture stayed unchanged. Completed and correct also requires Dog Walker to complete the workflow. A paused walk may have passing code and scope checks while still needing a workflow or response-format review; a pause alone does not mean the code is wrong. Each workflow also runs its visible baseline test.", "",
             "| Task | Condition | Walk result | Code + scope checks | Completed and correct | Turns | Time | Helper calls / successful | Peak memory | Tokens | Review reason |",
             "|---|---|---:|:---:|:---:|---:|---:|---:|---:|---:|---|"]
    for t in trials:
        mem = t.get("peak_sampled_rss_bytes")
        tokens = t.get("tokens")
        token_text = f"{tokens['input_tokens']} in / {tokens['output_tokens']} out" if tokens else "n/a"
        mem_text = f"{mem / 1024**3:.2f} GiB" if mem is not None else "n/a"
        reason = _report_cell(t.get("reason") or t.get("error"), 180)
        lines.append(f"| {t['task']} | {aliases[t['condition']]} | {t['status']} | {'yes' if _trial_checks_pass(t) else 'no'} | {'yes' if t.get('correct') else 'no'} | {t['turns']} | {t['seconds']:.1f}s | {t['helper_calls']} / {t['helper_successes']} | {mem_text} | {token_text} | {reason} |")
    lines += ["", "Memory is sampled once per second across the benchmark worker, main model process, and local helper service when process IDs are available. Samples can miss brief peaks. Token totals stay unavailable (`n/a`) unless the Codex event stream reports completed-turn usage. A helper error or timeout is recorded separately; the main worker is instructed to continue from its own inspection.", ""]
    (output / "REPORT.md").write_text("\n".join(lines))


def _trial_checks_pass(trial: dict) -> bool:
    if "checks_pass" in trial:
        return bool(trial["checks_pass"])
    scoring = trial.get("scoring")
    if isinstance(scoring, dict) and "pass" in scoring:
        return bool(scoring["pass"])
    return bool(trial.get("correct"))


def _report_cell(value, limit: int) -> str:
    if not value:
        return "—"
    text = " ".join(str(value).split()).replace("|", "¦")
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Create disposable fixtures for the historical Dog Walker helper benchmark")
    parser.add_argument("--output", required=True, type=Path, help="New output directory; use --resume to continue an existing pilot")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Create disposable tasks/workflows and baseline hashes without model inference")
    mode.add_argument("--run", action="store_true", help="Retired: live runs are disabled because the local coder has been retired")
    parser.add_argument("--resume", action="store_true", help="Resume incomplete trials in an existing output directory")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            if args.resume:
                raise WalkerError("--resume applies only to --run")
            manifest = prepare(args.output)
            print(json.dumps({"created": str(args.output.resolve()), "pilot": "preliminary", "tasks": manifest["tasks"], "live_inference": False}, indent=2))
        else:
            result = run_pilot(args.output, resume=args.resume)
            print(f"Preliminary pilot: {len(result['trials'])}/12 walks checkpointed; report: {args.output.resolve() / 'REPORT.md'}")
        return 0
    except KeyboardInterrupt:
        print("Benchmark interrupted. Completed walks remain checkpointed.", file=sys.stderr)
        if args.run:
            print(f"Resume with: python scripts/benchmark-pilot.py --run --resume --output {args.output}", file=sys.stderr)
        return 130
    except (OSError, ValueError, WalkerError) as exc:
        print(f"Benchmark: {exc}", file=sys.stderr)
        return 1

