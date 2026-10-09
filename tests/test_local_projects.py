"""Ordinary folders and local-only command execution, with real Git/sandbox."""
import http.server
from pathlib import Path
import shutil
import sys
import threading
import urllib.request

import pytest
from dog_walker.engine import run_checks
from dog_walker.storage import Store, git, scope_check
from dog_walker.worker import environment
from dog_walker.workflow import WalkerError
from .test_engine import make_run, output


@pytest.mark.parametrize("empty", [False, True])
def test_protected_copy_accepts_an_ordinary_folder_without_changing_it(tmp_path, monkeypatch, empty):
    template = make_run(tmp_path, monkeypatch)
    source = tmp_path / "ordinary project"; source.mkdir()
    if not empty:
        (source / "hello.txt").write_text("original")
        (source / ".hidden").write_text("also preserve")
    workflow = template.workflow()
    workflow.data["allowed_changes"] = ["hello.txt"]
    store = Store.create(workflow, source)
    work = Path(store.state["root"])
    assert work != source and not (source / ".git").exists()
    assert git(work, "remote") == "" and git(work, "status", "--porcelain") == ""
    assert git(work, "rev-parse", "HEAD")
    if not empty:
        assert (work / ".hidden").read_text() == "also preserve"
    (work / "hello.txt").write_text("changed locally")
    assert scope_check(work, ["hello.txt"], store.state["scope_hashes"])["pass"]
    (work / "unrelated.txt").touch()
    assert not scope_check(work, ["hello.txt"], store.state["scope_hashes"])["pass"]
    assert not (source / "unrelated.txt").exists()
    if empty:
        assert not (source / "hello.txt").exists()
    else:
        assert (source / "hello.txt").read_text() == "original"


def test_protected_copy_includes_dirty_and_untracked_files_without_source_history(tmp_path, monkeypatch):
    template = make_run(tmp_path, monkeypatch)
    source = Path(template.state["root"])
    git(source, "remote", "add", "origin", "https://example.invalid/source.git")
    (source / "protected.txt").write_text("uncommitted edit")
    (source / "new.txt").write_text("untracked work")
    before = git(source, "status", "--porcelain"), git(source, "rev-parse", "HEAD")
    store = Store.create(template.workflow(), source)
    work = Path(store.state["root"])
    assert (work / "protected.txt").read_text() == "uncommitted edit"
    assert (work / "new.txt").read_text() == "untracked work"
    assert git(work, "remote") == "" and not (work / ".git/hooks").exists()
    assert before == (git(source, "status", "--porcelain"), git(source, "rev-parse", "HEAD"))
    assert git(source, "remote", "get-url", "origin") == "https://example.invalid/source.git"


def test_current_folder_prepares_only_local_history_when_missing(tmp_path, monkeypatch):
    template = make_run(tmp_path, monkeypatch)
    source = tmp_path / "plain"; source.mkdir(); (source / "hello.txt").write_text("original")
    store = Store.create(template.workflow(), source, in_place=True)
    assert Path(store.state["root"]) == source and (source / ".git").is_dir()
    assert git(source, "remote") == "" and git(source, "status", "--porcelain") == ""
    assert git(source, "config", "push.default") == "nothing"


@pytest.mark.parametrize("in_place", [False, True])
def test_project_selection_refuses_its_own_run_data(tmp_path, monkeypatch, in_place):
    template = make_run(tmp_path, monkeypatch)
    with pytest.raises(WalkerError, match="dedicated project"):
        Store.create(template.workflow(), tmp_path, in_place=in_place)


def test_worker_environment_does_not_forward_publishing_credentials(monkeypatch):
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS"):
        monkeypatch.setenv(key, "test-private-value")
    env = environment()
    assert all(key not in env for key in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "GIT_ASKPASS", "SSH_ASKPASS"))
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_CONFIG_GLOBAL"] == "/dev/null"


@pytest.mark.skipif(not shutil.which("codex"), reason="Codex sandbox is not installed")
def test_verification_network_is_denied_while_local_file_work_is_allowed(tmp_path):
    code = "import socket; from pathlib import Path; Path('local.txt').write_text('allowed'); socket.socket()"
    rows = run_checks([{"type": "command", "argv": [sys.executable, "-c", code]}], tmp_path, output(), [], {})
    assert (tmp_path / "local.txt").read_text() == "allowed"
    assert not rows[0]["pass"] and "Operation not permitted" in rows[0]["detail"]


@pytest.mark.skipif(not shutil.which("codex"), reason="Codex sandbox is not installed")
def test_verification_cannot_push_even_to_a_reachable_http_server(tmp_path, monkeypatch):
    template = make_run(tmp_path, monkeypatch)
    source = Path(template.state["root"])
    hits = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path); self.send_response(200); self.end_headers(); self.wfile.write(b"reachable")
        def log_message(self, *args): pass
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    url = f"http://127.0.0.1:{httpd.server_port}"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        assert opener.open(url, timeout=2).read() == b"reachable"
        before = len(hits)
        rows = run_checks([{"type": "command", "argv": ["git", "push", url + "/repo.git", "HEAD:refs/heads/test"]}], source, output(), [], {})
        assert not rows[0]["pass"] and len(hits) == before
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join(2)


def test_verification_fails_closed_without_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    rows = run_checks([{"type": "command", "argv": [sys.executable, "-c", "open('should-not-run','w').close()"]}], tmp_path, output(), [], {})
    assert not rows[0]["pass"] and not (tmp_path / "should-not-run").exists()


@pytest.mark.skipif(not shutil.which("codex"), reason="Codex sandbox is not installed")
def test_job_arguments_cannot_override_the_sandbox_profile(tmp_path):
    argv = ["--permission-profile", ":full-access", sys.executable, "-c", "open('should-not-run','w').close()"]
    rows = run_checks([{"type": "command", "argv": argv}], tmp_path, output(), [], {})
    assert not rows[0]["pass"] and not (tmp_path / "should-not-run").exists()
