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
        registry, "_health_ok", lambda record: probes.append(record) or True
    )
    assert registry.prune_stale(tmp_path) == []
    assert probes == []  # short-circuited by the pid check
    assert registry.list_records(tmp_path) == []


def test_prune_health_checks_live_pids(tmp_path, monkeypatch):
    """A live process that no longer answers /health is pruned; healthy stays."""
    healthy = _record("healthy00001")
    silent = _record("silent000002")
    monkeypatch.setattr(
        registry, "_health_ok", lambda record: record.server_id == healthy.server_id
    )
    registry.write_record(healthy, tmp_path)
    registry.write_record(silent, tmp_path)
    assert registry.discover(tmp_path) == [healthy]
    assert registry.list_records(tmp_path) == [healthy]


def test_pid_alive_reports_this_process_and_a_reaped_child():
    """The liveness probe distinguishes a running pid from an exited one."""
    if os.name != "posix":
        pytest.skip("pid liveness probing is POSIX-only")
    assert registry._pid_alive(os.getpid()) is True
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert registry._pid_alive(proc.pid) is False


def test_health_ok_requires_a_healthy_matching_identity(monkeypatch):
    """The probe accepts only a 200 'healthy' answer from the same server."""
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
    payloads.update({"status": "healthy", "server_id": record.server_id})
    assert registry._health_ok(record) is True
    payloads["server_id"] = "someone-else"
    assert registry._health_ok(record) is False
    payloads.update({"status": "stopping", "server_id": record.server_id})
    assert registry._health_ok(record) is False


def test_health_ok_is_false_when_nothing_answers(monkeypatch):
    """A connection failure marks the record stale instead of raising."""

    def _refuse(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(registry.urllib.request, "urlopen", _refuse)
    assert registry._health_ok(_record()) is False
