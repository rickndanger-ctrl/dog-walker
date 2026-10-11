import json
import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest

from dog_walker import benchmark
from dog_walker.engine import Engine
from dog_walker.storage import Store
from dog_walker.workflow import load_workflow


def test_prepare_creates_six_disposable_paired_workflows_without_inference(tmp_path):
    output = tmp_path / "pilot"
    manifest = benchmark.prepare(output)

    assert manifest["pilot"] == "preliminary"
    assert manifest["tasks"] == ["bug", "boundary", "multifile", "regressiontest", "navigation", "refactor"]
    assert len(manifest["cases"]) == 6
    for task, case in manifest["cases"].items():
        assert (output / "fixtures" / task).is_dir()
        for condition in benchmark.CONDITIONS:
            workflow = output / case["workflows"][condition]
            text = (workflow / "steps/task.md").read_text()
            assert "project_map and project_search" in text
            assert ("local_coder_suggest exactly once" in text) is (condition == "helper")
            assert (workflow / "steps/retry.md").is_file()
            parsed = benchmark.load_workflow(workflow)
            assert parsed.steps["task"]["retry_prompt"] == "steps/retry.md"
            if condition == "helper":
                assert "local-coder" in (workflow / "workflow.yaml").read_text()
                assert "If the helper call fails or times out" in text
                assert "do not call it again" in text
        # The private acceptance program is not placed in either worker workspace.
        assert (output / "private-checks" / f"{task}.py").is_file()
        assert not list((output / "fixtures" / task).rglob("*hidden*"))
    assert json.loads((output / "results.json").read_text())["trials"] == []


def test_prepare_refuses_to_overwrite_output(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        benchmark.prepare(output)


def test_live_benchmark_refuses_before_inference_or_output_creation(tmp_path, monkeypatch):
    output = tmp_path / "live-pilot"

    def inference_must_not_start():
        pytest.fail("live benchmark attempted model readiness")

    monkeypatch.setattr(benchmark, "_main_readiness", inference_must_not_start)
    with pytest.raises(benchmark.WalkerError, match="local coder has been retired"):
        benchmark.run_pilot(output)
    with pytest.raises(benchmark.WalkerError, match="local coder has been retired"):
        benchmark.run_pilot(output, resume=True)
    assert not output.exists()
    assert not list(tmp_path.glob(".*.benchmark.lock"))


def test_hidden_rubrics_accept_reference_solutions(tmp_path):
    output = tmp_path / "pilot"
    benchmark.prepare(output)
    solutions = {
        "bug": {"price.py": "def apply_discount(price, percent):\n    if not 0 <= percent <= 100: raise ValueError('bad percent')\n    return price * (1 - percent / 100)\n"},
        "boundary": {"chunks.py": "def chunk_items(items, size):\n    if size <= 0: raise ValueError('bad size')\n    return [items[i:i + size] for i in range(0, len(items), size)]\n"},
        "multifile": {"text.py": "def format_title(value): return value.strip().title()\n",
                      "cli.py": "from text import format_title\ndef title_for_cli(value): return format_title(value)\n",
                      "admin/cli.py": "from text import format_title\ndef title_for_admin(value): return format_title(value)\n"},
        "regressiontest": {"flags.py": "def is_enabled(value): return value.strip().lower() == 'true' if isinstance(value, str) else False\n",
                           "tests/test_regression.py": "import unittest\nfrom flags import is_enabled\nclass Regression(unittest.TestCase):\n def test_whitespace_only_is_disabled(self): self.assertFalse(is_enabled('  \\t'))\n"},
        "navigation": {"app/people/names.py": "import re\ndef normalize_name(value): return re.sub(r'\\s+', ' ', value).strip().title()\n"},
        "refactor": {"ranges.py": "def _clamp(value, minimum, maximum):\n    return max(minimum, min(maximum, value))\ndef percent(value): return _clamp(value, 0, 100)\ndef ratio(value): return _clamp(value, 0, 1)\n"},
    }
    for task, files in solutions.items():
        root = output / "fixtures" / task
        for name, body in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        proc = subprocess.run(
            [sys.executable, str(output / "private-checks" / f"{task}.py"), str(root)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"{task} reference solution rejected: {proc.stderr}"


def test_trial_order_alternates_by_task():
    assert benchmark._trial_order(0) == ["main", "helper"]
    assert benchmark._trial_order(1) == ["helper", "main"]
    assert benchmark._trial_order(2) == ["main", "helper"]


def test_scoring_uses_store_protected_copy_and_checks_scope_independently(tmp_path, monkeypatch):
    import dog_walker.storage as storage

    output = tmp_path / "pilot"
    manifest = benchmark.prepare(output)
    source = output / "fixtures/bug"
    monkeypatch.setattr(storage, "DATA", tmp_path / "private-data")
    workflow = benchmark.load_workflow(output / manifest["cases"]["bug"]["workflows"]["main"])
    store = Store.create(workflow, source, auto=True)
    workspace = Path(store.state["root"])
    (workspace / "price.py").write_text(
        "def apply_discount(price, percent):\n"
        "    if not 0 <= percent <= 100:\n        raise ValueError('percent out of range')\n"
        "    return price * (1 - percent / 100)\n"
    )
    case = benchmark._case_data()["bug"]
    score = benchmark._score("bug", workspace, output / "private-checks/bug.py",
                             input_project=source, baseline_hashes=manifest["cases"]["bug"]["baseline_hashes"],
                             allowed=case["allowed"], scope_baseline=store.state["scope_hashes"])

    assert score["hidden"]["pass"]
    assert score["scope"]["pass"]
    assert score["input_fixture_unchanged"]
    assert score["pass"]
    (workspace / "unlisted.txt").write_text("out of scope\n")
    bad_scope = benchmark._score("bug", workspace, output / "private-checks/bug.py",
                                 input_project=source, baseline_hashes=manifest["cases"]["bug"]["baseline_hashes"],
                                 allowed=case["allowed"], scope_baseline=store.state["scope_hashes"])
    assert not bad_scope["scope"]["pass"]
    assert not bad_scope["pass"]


def test_report_summarizes_conditions_helper_calls_and_null_tokens(tmp_path):
    output = tmp_path / "report"
    output.mkdir()
    trials = [
        {"task": "bug", "condition": "main", "status": "completed", "correct": True, "turns": 1,
         "seconds": 10, "helper_calls": 0, "helper_successes": 0, "helper_timeouts": 0,
         "checks_pass": True, "peak_sampled_rss_bytes": 1024**3, "tokens": None},
        {"task": "boundary", "condition": "helper", "status": "paused", "correct": False, "turns": 2,
         "seconds": 12, "helper_calls": 1, "helper_successes": 0, "helper_timeouts": 1,
         "checks_pass": True, "reason": "Final response had an unexpected closing tag",
         "peak_sampled_rss_bytes": 2 * 1024**3, "tokens": None},
    ]
    benchmark._write_report(output, {"created_at_unix": 1}, {"trials": trials, "updated_at_unix": 13})
    report = (output / "REPORT.md").read_text()
    assert "Main model" in report and "Main + helper" in report
    assert "Code + scope checks passing" in report and "Completed and correct" in report
    assert "| Main model | 1/1 | 1/1 |" in report
    assert "| Main + helper | 1/1 | 0/1 |" in report
    assert "A paused walk may have passing code and scope checks" in report
    assert "Final response had an unexpected closing tag" in report
    assert "| boundary | Main + helper | paused | yes | no |" in report
    assert "missed the exactly-one-call target" in report
    assert "2.00 GiB" in report and "n/a" in report


def test_sample_memory_deduplicates_same_pid_across_categories():
    sample = benchmark._sample_memory(os.getpid(), os.getpid())
    assert sample["benchmark"]["rss_bytes"] > 0
    assert sample["main_model"]["rss_bytes"] > 0
    assert sample["rss_bytes"] == sample["benchmark"]["rss_bytes"]


def test_token_usage_counts_completed_turns_once_and_stays_null_when_unavailable(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text("\n".join([
        json.dumps({"type": "codex", "event": {"type": "item.completed", "usage": {"input_tokens": 7}}}),
        json.dumps({"type": "codex", "event": {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4}}}),
    ]))
    assert benchmark._token_usage(events) == {"input_tokens": 10, "output_tokens": 4}
    events.write_text(json.dumps({"type": "codex", "event": {"type": "turn.completed", "usage": {}}}))
    assert benchmark._token_usage(events) is None


def test_desktop_lease_and_runner_lock_are_exclusive(tmp_path):
    data = tmp_path / "data"
    with benchmark._desktop_trial_lease(data):
        assert benchmark._locked_run_dirs(data) == ["desktop-worker.lock"]
    assert benchmark._locked_run_dirs(data) == []
    lock = tmp_path / ".pilot.lock"
    with benchmark._exclusive_lock(lock, "runner"):
        with pytest.raises(benchmark.WalkerError):
            with benchmark._exclusive_lock(lock, "runner"):
                pass


def test_timeout_cancels_fake_worker_and_leaves_no_process(tmp_path, monkeypatch):
    import dog_walker.settings as settings
    import dog_walker.storage as storage
    import dog_walker.worker as worker

    config = tmp_path / "worker.json"
    config.write_text(json.dumps({**settings.defaults(), "start_command": []}))
    monkeypatch.setattr(settings, "CONFIG", config)
    monkeypatch.setattr(storage, "DATA", tmp_path / "isolated-data")
    monkeypatch.setattr(worker, "DATA", tmp_path / "isolated-data")
    project = tmp_path / "project"
    project.mkdir()
    (project / "file.txt").write_text("initial\n")
    workflow = tmp_path / "workflow"
    (workflow / "steps").mkdir(parents=True)
    (workflow / "steps/task.md").write_text("wait\n")
    (workflow / "workflow.yaml").write_text(
        "version: 1\nname: Timeout\nentry: task\nsteps:\n  - id: task\n"
        "    prompt: steps/task.md\n    checks:\n      - type: file_exists\n        path: file.txt\n"
    )
    spawned = {}

    class HangingWorker:
        async def ready(self):
            return None

        async def turn(self, _prompt, _timeout):
            self.proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", "import time; time.sleep(30)", start_new_session=True
            )
            spawned["pid"] = self.proc.pid
            try:
                await asyncio.sleep(30)
            finally:
                await worker.stop_process(self.proc)

    data = tmp_path / "data"
    wdir = tmp_path / "codex-home"
    store, status, error, _duration, _events, _samples = benchmark._run_engine(
        workflow, project, data, wdir, 0.1, worker_factory_override=lambda *_args: HangingWorker()
    )

    assert status == "timeout"
    assert "exceeded" in error
    assert store.state["status"] == "paused"
    assert spawned["pid"]
    with pytest.raises(ProcessLookupError):
        os.kill(spawned["pid"], 0)


def test_helper_cleanup_runs_when_trial_is_interrupted(tmp_path, monkeypatch):
    stopped = []

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(benchmark, "_run_engine", interrupt)
    monkeypatch.setattr(benchmark, "_stop_owned_coder", lambda was_active: stopped.append(was_active))

    with pytest.raises(KeyboardInterrupt):
        benchmark._run_engine_with_helper_cleanup(
            tmp_path / "workflow", tmp_path / "project", tmp_path / "data", tmp_path / "home", 10,
            helper_enabled=True, helper_was_active=False,
        )

    assert stopped == [False]


def test_cli_reports_interrupt_with_checkpoint_resume_command(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(benchmark, "run_pilot", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    code = benchmark.main(["--run", "--output", str(tmp_path / "pilot")])

    captured = capsys.readouterr()
    assert code == 130
    assert "Completed walks remain checkpointed" in captured.err
    assert "--run --resume --output" in captured.err
    assert "Traceback" not in captured.err


def test_engine_trial_with_fake_worker_uses_authored_check_without_inference(tmp_path, monkeypatch):
    import dog_walker.storage as storage

    project = tmp_path / "project"
    project.mkdir()
    (project / "result.txt").write_text("before\n")
    workflow_root = tmp_path / "workflow"
    (workflow_root / "steps").mkdir(parents=True)
    (workflow_root / "steps/task.md").write_text("Write the expected result.\n")
    (workflow_root / "workflow.yaml").write_text(
        "version: 1\nname: Fake benchmark\nentry: task\nmax_turns: 4\n"
        "steps:\n  - id: task\n    prompt: steps/task.md\n    checks:\n"
        "      - type: file_contains\n        path: result.txt\n        text: after\n"
    )
    monkeypatch.setattr(storage, "DATA", tmp_path / "private-data")

    class FakeWorker:
        async def ready(self):
            return None

        async def turn(self, prompt, timeout):
            (store_root / "result.txt").write_text("after\n")
            return ({"status": "completed", "summary": "fake worker completed",
                     "evidence": ["result.txt contains after"], "files_changed": ["result.txt"],
                     "blockers": []}, [])

    async def ask(_reason, _passed):
        return "pause"

    store = Store.create(load_workflow(workflow_root), project, auto=True)
    store_root = Path(store.state["root"])
    asyncio.run(Engine(store, lambda _line: None, ask, no_start=True,
                       worker_factory=lambda *_args: FakeWorker()).run())

    assert store.state["status"] == "completed"
    assert store.state["turns"] == 1
    assert (store_root / "result.txt").read_text() == "after\n"
