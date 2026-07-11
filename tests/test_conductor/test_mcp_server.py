"""Tests for the Conductor MCP server (requires the optional ``mcp`` extra)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp")

from derzug.conductor import CanvasController, MainThreadDispatcher  # noqa: E402
from derzug.conductor.mcp_server import (  # noqa: E402
    build_conductor_mcp,
    start_conductor,
    write_mcp_config,
)

_EXPECTED_TOOLS = {
    "get_canvas_state",
    "list_widget_types",
    "describe_node",
    "compile_check",
    "get_focus",
    "set_params",
    "set_view",
    "add_node",
    "remove_node",
    "connect",
    "disconnect",
    "run",
    "wait_for_idle",
    "show_node",
    "move_node_window",
    "hide_node",
}


def _server(window):
    controller = CanvasController(window)
    mcp = build_conductor_mcp(controller, MainThreadDispatcher())
    return mcp, controller


def test_tools_are_registered(blank_canvas):
    """The server exposes the full observe/configure/author tool surface."""
    window, _ = blank_canvas
    mcp, _ = _server(window)
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert _EXPECTED_TOOLS <= names


def test_add_node_tool_drives_the_controller(blank_canvas):
    """Calling the add_node tool authors a node on the live canvas."""
    window, _ = blank_canvas
    mcp, controller = _server(window)
    asyncio.run(mcp.call_tool("add_node", {"widget_type": "Detrend", "title": "dt"}))
    titles = [node.title for node in controller.get_canvas_state().nodes]
    assert "dt" in titles


def test_write_mcp_config(tmp_path):
    """The generated MCP config points a client at the server's endpoint."""
    path = tmp_path / ".mcp.json"
    url = write_mcp_config(path, port=4321)
    config = json.loads(path.read_text())
    assert url == "http://127.0.0.1:4321/mcp"
    assert config["mcpServers"]["derzug-conductor"]["url"] == url
    assert config["mcpServers"]["derzug-conductor"]["type"] == "http"


def test_write_mcp_config_merges_existing_entries(tmp_path):
    """An existing .mcp.json keeps its other servers; only ours is replaced."""
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"type": "stdio", "command": "other-server"},
                    "derzug-conductor": {"type": "http", "url": "http://stale"},
                }
            }
        )
    )
    url = write_mcp_config(path, port=4321)
    config = json.loads(path.read_text())
    assert config["mcpServers"]["other"]["command"] == "other-server"
    assert config["mcpServers"]["derzug-conductor"]["url"] == url


def test_write_mcp_config_leaves_invalid_json_untouched(tmp_path):
    """A hand-edited config that fails to parse is never clobbered."""
    path = tmp_path / ".mcp.json"
    path.write_text("{not json")
    write_mcp_config(path, port=4321)
    assert path.read_text() == "{not json"


def test_service_reports_port_conflict_on_start(blank_canvas):
    """A taken port raises immediately from start() instead of dying silently."""
    import socket

    from derzug.conductor.mcp_server import ConductorService

    window, _ = blank_canvas
    mcp, _ = _server(window)
    with socket.create_server(("127.0.0.1", 0)) as sock:
        taken_port = sock.getsockname()[1]
        service = ConductorService(mcp, port=taken_port)
        with pytest.raises(OSError):
            service.start()


def test_service_start_ready_and_stop(blank_canvas):
    """The service binds an ephemeral port, reports ready, and stops cleanly."""
    from derzug.conductor.mcp_server import ConductorService

    window, _ = blank_canvas
    mcp, _ = _server(window)
    service = ConductorService(mcp, port=0)
    url = service.start(timeout=30.0)
    try:
        assert service.port > 0
        assert url == f"http://127.0.0.1:{service.port}/mcp"
    finally:
        service.stop()
    assert service._thread is None


def test_start_conductor_stops_service_when_config_write_fails(
    blank_canvas, tmp_path, monkeypatch
):
    """Failure after bind/readiness must not leave an orphan listening server."""
    from derzug.conductor.mcp_server import ConductorService

    window, _ = blank_canvas
    stopped: list[ConductorService] = []
    original_stop = ConductorService.stop

    def track_stop(self, timeout=5.0):
        stopped.append(self)
        original_stop(self, timeout)

    def fail_write(*args, **kwargs):
        raise OSError("config is not writable")

    monkeypatch.setattr(ConductorService, "stop", track_stop)
    monkeypatch.setattr("derzug.conductor.mcp_server.write_mcp_config", fail_write)

    with pytest.raises(OSError, match="not writable"):
        start_conductor(window, port=0, config_path=tmp_path / ".mcp.json")

    assert len(stopped) == 1
    assert stopped[0]._thread is None


def test_connect_tool_defaults_ports_to_patch(blank_canvas):
    """The connect tool links two nodes using the default 'Patch' ports."""
    window, _ = blank_canvas
    mcp, controller = _server(window)
    spool = controller.add_node("Spool", title="s")
    view = controller.add_node("Waterfall", title="v")
    asyncio.run(mcp.call_tool("connect", {"source_id": spool, "sink_id": view}))
    links = controller.get_canvas_state().links
    assert any(link.source_id == spool and link.sink_id == view for link in links)
