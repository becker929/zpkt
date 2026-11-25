"""Ask's keys when the harness is not installed, and the desk taking a burst of page loads (25 Nov 2026)."""

from __future__ import annotations

import subprocess
import threading
import urllib.request
from types import SimpleNamespace

from zpkt.app.adapters import agents
from zpkt.app.adapters.api import ApiServer
from zpkt.app.web import DeskHTTPServer


def test_the_keychain_lookup_reads_the_harnesss_item_and_the_environment_comes_first(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="k\n")

    monkeypatch.delenv("HARNESS_GEMINI", raising=False)
    assert agents.keychain_secret("gemini", run=run) == "k"
    assert calls[0][:4] == ["security", "find-generic-password", "-s", "zpkt-gemini-api-key"]
    monkeypatch.setenv("HARNESS_GEMINI", "from-env")
    assert agents.keychain_secret("gemini", run=run) == "from-env" and len(calls) == 1
    assert agents.keychain_secret("unknown", run=run) is None


def test_a_missing_item_or_a_failed_lookup_is_no_key(monkeypatch):
    monkeypatch.delenv("HARNESS_OAUTH", raising=False)
    assert agents.keychain_secret("oauth", run=lambda *a, **k: SimpleNamespace(returncode=44, stdout="")) is None

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("security", 10)

    assert agents.keychain_secret("oauth", run=boom) is None


def test_the_servers_keep_a_backlog_for_a_burst_of_module_loads():
    assert DeskHTTPServer.request_queue_size >= 64 and ApiServer.request_queue_size >= 64


def test_forty_requests_at_once_all_get_answers(rig):
    codes: list[int] = []

    def get():
        with urllib.request.urlopen(rig.url + "/app/", timeout=10) as r:
            codes.append(r.status)

    threads = [threading.Thread(target=get) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 40
