"""Tests for the asynchronous Conductor lifecycle orchestrator."""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

from derzug.conductor.lifecycle import ConductorLifecycle


class _FakeService:
    """Duck-type of ``ConductorService`` with scriptable state transitions."""

    def __init__(self, port: int, *, status: str = "running") -> None:
        self.host = "127.0.0.1"
        self.port = port
        self.server_id = f"fake{port:04d}"
        self.url = f"http://127.0.0.1:{port}/mcp"
        self.launch_calls = 0
        self.stop_calls = 0
        self.stoppable = True
        self._status = status

    def launch(self) -> None:
        self.launch_calls += 1

    def status(self) -> str:
        return self._status

    def request_stop(self) -> None:
        pass

    def is_stopped(self) -> bool:
        return self.stoppable

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_calls += 1
        self._status = "idle"


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    """Keep discovery-registry writes inside the test's tmp directory."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))


@pytest.fixture()
def fake_mcp_server(monkeypatch):
    """Install a fake ``mcp_server`` module whose services are scriptable."""
    module = types.ModuleType("derzug.conductor.mcp_server")
    module.services = []
    module.next_status = "running"

    def create_service(window, *, port, allow_code, **_kwargs):
        service = _FakeService(port, status=module.next_status)
        module.services.append(service)
        return service

    module.create_service = create_service
    monkeypatch.setitem(sys.modules, "derzug.conductor.mcp_server", module)
    return module


@pytest.fixture()
def lifecycle(qtbot):
    """A lifecycle owned by the test, shut down at exit."""
    lifecycle = ConductorLifecycle()
    yield lifecycle
    lifecycle.shutdown()


def test_start_emits_started_and_writes_client_config(
    lifecycle, fake_mcp_server, tmp_path, qtbot
):
    """A ready server reports its URL and lands the .mcp.json for agents."""
    with qtbot.waitSignal(lifecycle.started) as blocker:
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    (service,) = fake_mcp_server.services
    assert blocker.args == [service.url]
    assert lifecycle.phase == "running"
    assert lifecycle.url == service.url
    assert lifecycle.agent_cwd == str(tmp_path)
    config = json.loads((tmp_path / ".mcp.json").read_text())
    assert config["mcpServers"]["derzug-conductor"]["url"] == service.url


def test_request_start_is_ignored_while_a_service_exists(
    lifecycle, fake_mcp_server, tmp_path, qtbot
):
    """A second start request cannot race the owned service."""
    with qtbot.waitSignal(lifecycle.started):
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    lifecycle.request_start(object(), port=9999, allow_code=True, config_dir=tmp_path)
    assert len(fake_mcp_server.services) == 1


def test_start_polls_until_the_server_becomes_ready(
    lifecycle, fake_mcp_server, tmp_path, qtbot
):
    """The transient starting phase resolves once the service reports ready."""
    fake_mcp_server.next_status = "starting"
    lifecycle.request_start(object(), port=4321, allow_code=False, config_dir=tmp_path)
    (service,) = fake_mcp_server.services
    assert lifecycle.phase == "starting"
    assert lifecycle.url is None
    with qtbot.waitSignal(lifecycle.started):
        service._status = "running"
    assert lifecycle.phase == "running"


def test_start_failure_when_the_server_exits(
    lifecycle, fake_mcp_server, tmp_path, qtbot
):
    """A server thread that dies during startup reports a failed start."""
    fake_mcp_server.next_status = "exited"
    with qtbot.waitSignal(lifecycle.start_failed) as blocker:
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    assert "exited" in blocker.args[0]
    assert lifecycle.service is None
    assert lifecycle.phase == "idle"
    assert fake_mcp_server.services[0].stop_calls == 1


def test_start_failure_on_readiness_timeout(
    lifecycle, fake_mcp_server, tmp_path, qtbot, monkeypatch
):
    """A server that never reports ready fails the start after the deadline."""
    monkeypatch.setattr("derzug.conductor.lifecycle.START_TIMEOUT", 0.05)
    fake_mcp_server.next_status = "starting"
    with qtbot.waitSignal(lifecycle.start_failed) as blocker:
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    assert "not ready" in blocker.args[0]
    assert lifecycle.service is None
    assert fake_mcp_server.services[0].stop_calls == 1


def test_start_failure_when_client_config_write_fails(
    lifecycle, fake_mcp_server, tmp_path, qtbot, monkeypatch
):
    """Failure after readiness must not leave an orphan listening server."""

    def fail_write(*_args, **_kwargs):
        raise OSError("config is not writable")

    monkeypatch.setattr("derzug.conductor.lifecycle.write_mcp_config", fail_write)
    with qtbot.waitSignal(lifecycle.start_failed) as blocker:
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    assert "not writable" in blocker.args[0]
    assert lifecycle.service is None
    assert fake_mcp_server.services[0].stop_calls == 1


def test_start_and_stop_maintain_the_discovery_record(
    lifecycle, fake_mcp_server, tmp_path, qtbot
):
    """A ready server is advertised for discovery; a stopped one is not."""
    from derzug.conductor import registry

    with qtbot.waitSignal(lifecycle.started):
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    (service,) = fake_mcp_server.services
    (record,) = registry.list_records()
    assert record.server_id == service.server_id
    assert record.mcp_url == service.url
    assert record.pid == os.getpid()
    with qtbot.waitSignal(lifecycle.stopped):
        lifecycle.request_stop()
    assert registry.list_records() == []


def test_stop_emits_stopped_and_releases_the_service(
    lifecycle, fake_mcp_server, tmp_path, qtbot
):
    """A clean stop finalizes the service and clears the agent directory."""
    with qtbot.waitSignal(lifecycle.started):
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    with qtbot.waitSignal(lifecycle.stopped):
        lifecycle.request_stop()
    assert lifecycle.service is None
    assert lifecycle.phase == "idle"
    assert lifecycle.agent_cwd is None
    assert fake_mcp_server.services[0].stop_calls == 1


def test_stop_timeout_keeps_the_service_for_retry(
    lifecycle, fake_mcp_server, tmp_path, qtbot, monkeypatch
):
    """A hung shutdown keeps the port-owning service; a retry can succeed."""
    monkeypatch.setattr("derzug.conductor.lifecycle.STOP_TIMEOUT", 0.05)
    with qtbot.waitSignal(lifecycle.started):
        lifecycle.request_start(
            object(), port=4321, allow_code=False, config_dir=tmp_path
        )
    (service,) = fake_mcp_server.services
    service.stoppable = False
    with qtbot.waitSignal(lifecycle.stop_failed) as blocker:
        lifecycle.request_stop()
    assert "did not stop" in blocker.args[0]
    assert lifecycle.service is service
    assert lifecycle.phase == "running"

    service.stoppable = True
    with qtbot.waitSignal(lifecycle.stopped):
        lifecycle.request_stop()
    assert lifecycle.service is None


def test_shutdown_during_starting_stops_the_service_without_signals(
    lifecycle, fake_mcp_server, tmp_path, qtbot
):
    """Teardown mid-start discards the service and emits no lifecycle signals."""
    fake_mcp_server.next_status = "starting"
    lifecycle.request_start(object(), port=4321, allow_code=False, config_dir=tmp_path)
    outcomes = []
    lifecycle.started.connect(lambda *_: outcomes.append("started"))
    lifecycle.start_failed.connect(lambda *_: outcomes.append("start_failed"))
    lifecycle.shutdown()
    assert lifecycle.service is None
    assert fake_mcp_server.services[0].stop_calls == 1
    qtbot.wait(120)  # any stray timer tick would fire a signal here
    assert outcomes == []
