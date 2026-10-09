from contextlib import contextmanager
import http.client
import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import pytest
from dog_walker.phone import Companion, server, credentials
from dog_walker.workflow import WalkerError

CONFIG = {"origin": "https://example.tailtest.ts.net", "owner": "owner@example.test"}
KEY = {"secret": "a" * 64, "pair_code": "ABCDEF123456"}


@contextmanager
def phone(tmp_path, call=None):
    calls = []
    def fake(method, *args):
        calls.append((method, args))
        if method == "companionSnapshot":
            return json.dumps({"connected": True, "review": True, "state": {"id": "run", "status": "running", "root": "/private/path", "hashes": {"private": "hash"}}, "review_id": "review"})
        if method == "companionControl": return "sent"
        if method == "companionReply": return json.dumps({"ok": True})
        raise AssertionError(method)
    httpd = server(CONFIG, KEY, 0, call=call or fake, data=tmp_path, secure=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    def request(path, method="GET", value=None, **headers):
        defaults = {"Host": "example.tailtest.ts.net", "Tailscale-User-Login": CONFIG["owner"], "Origin": CONFIG["origin"], "Content-Type": "application/json"}
        defaults.update(headers)
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
        body = value if isinstance(value, bytes) else json.dumps(value).encode() if value is not None else None
        connection.request(method, path, body=body, headers=defaults)
        response = connection.getresponse(); raw = response.read()
        data = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
        result = response.status, data, dict(response.getheaders())
        connection.close()
        return result
    try: yield request, calls
    finally: httpd.shutdown(); httpd.server_close(); thread.join(3)


def pair(request):
    status, _, headers = request("/api/pair", "POST", {"code": "ABCD-EF12-3456"})
    assert status == 200
    cookie = headers["Set-Cookie"].split(";")[0]
    status, state, _ = request("/api/state", Cookie=cookie)
    assert status == 200
    return cookie, state["csrf"]


def test_pairing_required_and_private_metadata_stays_private(tmp_path):
    with phone(tmp_path) as (request, calls):
        assert request("/api/state")[0] == 401 and not calls
        cookie, _ = pair(request)
        status, data, headers = request("/api/state", Cookie=cookie)
        assert status == 200 and data["current"]["state"]["id"] == "run"
        assert "root" not in data["current"]["state"] and "hashes" not in data["current"]["state"]
        assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("headers", [
    {"Tailscale-User-Login": "someone-else@example.test"},
    {"Tailscale-User-Login": ""}, {"Host": "attacker.example"},
])
def test_wrong_private_identity_or_host_cannot_read_or_pair(tmp_path, headers):
    with phone(tmp_path) as (request, calls):
        assert request("/api/state", **headers)[0] == 403
        assert request("/api/pair", "POST", {"code": KEY["pair_code"]}, **headers)[0] == 403
        assert not calls


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": ""}, {"Content-Type": "text/plain"}])
def test_cross_site_pairing_is_rejected(tmp_path, headers):
    with phone(tmp_path) as (request, calls):
        assert request("/api/pair", "POST", {"code": KEY["pair_code"]}, **headers)[0] == 403
        assert not calls


@pytest.mark.parametrize("extra", [{}, {"X-Dogwalker-CSRF": "forged"}, {"Cookie": "dogwalker=forged"}])
def test_unpaired_or_forged_actions_cannot_reach_desktop(tmp_path, extra):
    with phone(tmp_path) as (request, calls):
        command = {"action": "approve", "run_id": "run", "review_id": "review"}
        assert request("/api/control", "POST", command, **extra)[0] == 403
        assert not calls


def test_paired_action_requires_csrf_and_retains_context(tmp_path):
    with phone(tmp_path) as (request, calls):
        cookie, csrf = pair(request)
        command = {"action": "approve", "run_id": "run", "review_id": "review"}
        assert request("/api/control", "POST", command, Cookie=cookie)[0] == 403
        status, data, _ = request("/api/control", "POST", command, Cookie=cookie, **{"X-Dogwalker-CSRF": csrf})
        assert status == 200 and data["ok"]
        passed = json.loads(next(args[0] for method, args in calls if method == "companionControl"))
        assert all(passed[k] == v for k, v in command.items())


def test_stale_review_returns_conflict(tmp_path):
    def call(method, *args):
        if method == "companionSnapshot": return json.dumps({"state": None})
        assert method == "companionControl"
        return "stale"
    with phone(tmp_path, call) as (request, _):
        cookie, csrf = pair(request)
        assert request("/api/control", "POST", {"action": "approve", "run_id": "run", "review_id": "old"}, Cookie=cookie, **{"X-Dogwalker-CSRF": csrf})[0] == 409


def test_bad_pairing_is_rate_limited_and_sessions_expire(tmp_path):
    with phone(tmp_path) as (request, calls):
        for _ in range(5): assert request("/api/pair", "POST", {"code": "wrong"})[0] == 403
        assert request("/api/pair", "POST", {"code": KEY["pair_code"]})[0] == 409
        assert not calls
    app = Companion(CONFIG, KEY)
    old = f"{int(time.time())-50000}." + "1" * 32
    assert not app.valid_session(old + "." + app.signature(old))
    assert not app.valid_session("future.forged.signature")


def test_cookie_has_secure_flags_and_oversize_requests_are_rejected(tmp_path):
    app = Companion(CONFIG, KEY)
    assert app.secure is True
    with phone(tmp_path) as (request, calls):
        status, _, headers = request("/api/pair", "POST", {"code": KEY["pair_code"]})
        assert status == 200 and "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
        assert request("/api/pair", "POST", b"x" * 8193)[0] == 413
        assert request("/api/pair", "POST", b"{bad")[0] == 400


def test_credentials_are_private_and_not_overwritten(tmp_path):
    first = credentials(tmp_path)
    assert credentials(tmp_path) == first
    assert (tmp_path / "phone-secret.json").stat().st_mode & 0o777 == 0o600


def test_concurrent_setup_keeps_one_pairing_secret(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: credentials(tmp_path), range(16)))
    assert all(key == keys[0] for key in keys)


@pytest.mark.parametrize("origin", ["http://example.ts.net", "https://public.example", "https://user:pass@example.ts.net", "https://example.ts.net/other"])
def test_server_refuses_public_or_ambiguous_origins(origin):
    with pytest.raises(WalkerError): Companion({**CONFIG, "origin": origin}, KEY)
