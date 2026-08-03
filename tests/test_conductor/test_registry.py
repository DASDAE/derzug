"""Tests for the Conductor discovery registry (no ``mcp`` dependency)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from derzug.conductor import registry
from derzug.conductor.registry import ServerRecord


def _record(server_id: str = "abc123", *, pid: int | None = None) -> ServerRecord:
    return ServerRecord(
        server_id=server_id,
        pid=os.getpid() if pid is None else pid,
        host="127.0.0.1",
        port=4319,
        base_url="http://127.0.0.1:4319",
        mcp_url="http://127.0.0.1:4319/mcp",
        started_at="2026-08-03T00:00:00+00:00",
        version="0.0.0",
    )


def test_state_dir_honors_xdg_state_home(monkeypatch, tmp_path):
    """The registry lives under the user's state directory."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert registry.state_dir() == tmp_path / "derzug" / "servers"


def test_write_list_and_remove_record_round_trip(tmp_path):
    """A record written atomically reads back equal and removes cleanly."""
    record = _record()
    path = registry.write_record(record, tmp_path)
    assert path == tmp_path / "abc123.json"
    assert json.loads(path.read_text())["mcp_url"] == record.mcp_url
    assert registry.list_records(tmp_path) == [record]
    registry.remove_record("abc123", tmp_path)
    assert registry.list_records(tmp_path) == []
    registry.remove_record("abc123", tmp_path)  # tolerated when already gone


def test_list_records_skips_malformed_files(tmp_path):
    """A corrupt record cannot break discovery of the healthy ones."""
    record = _record()
    registry.write_record(record, tmp_path)
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "wrong.json").write_text(json.dumps({"unexpected": "shape"}))
    assert registry.list_records(tmp_path) == [record]


def test_prune_removes_dead_pid_records(tmp_path, monkeypatch):
    """A record whose process is gone is deleted without a health probe."""
    if os.name != "posix":
        pytest.skip("pid liveness probing is POSIX-only")
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead = _record("deadbeef0000", pid=proc.pid)
    registry.write_record(dead, tmp_path)

    probes = []
    monkeypatch.setattr(
        registry, "_probe_health", lambda record: probes.append(record) or "live"
    )
    assert registry.prune_stale(tmp_path) == []
    assert probes == []  # short-circuited by the pid check
    assert registry.list_records(tmp_path) == []


def test_prune_health_checks_live_pids(tmp_path, monkeypatch):
    """A provably dead server is pruned; a healthy one stays advertised."""
    healthy = _record("healthy00001")
    silent = _record("silent000002")
    monkeypatch.setattr(
        registry,
        "_probe_health",
        lambda record: "live" if record.server_id == healthy.server_id else "stale",
    )
    registry.write_record(healthy, tmp_path)
    registry.write_record(silent, tmp_path)
    assert registry.discover(tmp_path) == [healthy]
    assert registry.list_records(tmp_path) == [healthy]


def test_prune_keeps_records_whose_probe_is_inconclusive(tmp_path, monkeypatch):
    """A timeout must not erase a live sibling; the record just isn't reported."""
    busy = _record("busy00000001")
    monkeypatch.setattr(registry, "_probe_health", lambda record: "unknown")
    registry.write_record(busy, tmp_path)
    assert registry.discover(tmp_path) == []
    assert registry.list_records(tmp_path) == [busy]


def test_pid_alive_reports_this_process_and_a_reaped_child():
    """The liveness probe distinguishes a running pid from an exited one."""
    if os.name != "posix":
        pytest.skip("pid liveness probing is POSIX-only")
    assert registry._pid_alive(os.getpid()) is True
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert registry._pid_alive(proc.pid) is False


def test_probe_health_requires_the_full_matching_identity(monkeypatch):
    """Only a 200 'healthy' answer naming this exact server counts as live."""
    record = _record()
    payloads = {}

    class _Response:
        status = 200

        def read(self):
            return json.dumps(payloads).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        registry.urllib.request, "urlopen", lambda url, timeout: _Response()
    )
    identity = {
        "status": "healthy",
        "server": "derzug-conductor",
        "server_id": record.server_id,
    }
    payloads.update(identity)
    assert registry._probe_health(record) == "live"
    # A reused port answering as someone (or something) else is stale.
    payloads.update(identity | {"server_id": "someone-else"})
    assert registry._probe_health(record) == "stale"
    payloads.update(identity | {"server": "another-app"})
    assert registry._probe_health(record) == "stale"
    payloads.clear()
    payloads.update({"status": "healthy", "server": "derzug-conductor"})
    assert registry._probe_health(record) == "stale"  # identity missing
    payloads.update(identity | {"status": "stopping"})
    assert registry._probe_health(record) == "stale"


def test_probe_health_distinguishes_refusal_from_timeout(monkeypatch):
    """Nothing-listening is provably stale; a slow answer stays inconclusive."""
    import urllib.error

    def _refuse(url, timeout):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(registry.urllib.request, "urlopen", _refuse)
    assert registry._probe_health(_record()) == "stale"

    def _hang(url, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(registry.urllib.request, "urlopen", _hang)
    assert registry._probe_health(_record()) == "unknown"
