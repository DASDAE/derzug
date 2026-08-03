"""Tests for the Conductor MCP server (requires the optional ``mcp`` extra)."""

from __future__ import annotations

import asyncio
import time

import pytest

pytest.importorskip("mcp")

from derzug.conductor import CanvasController, MainThreadDispatcher  # noqa: E402
from derzug.conductor.mcp_server import (  # noqa: E402
    build_conductor_mcp,
    create_service,
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


def test_service_reports_port_conflict_on_launch(blank_canvas):
    """A taken port raises immediately from launch() instead of dying silently."""
    import socket

    from derzug.conductor.mcp_server import ConductorService

    window, _ = blank_canvas
    mcp, _ = _server(window)
    with socket.create_server(("127.0.0.1", 0)) as sock:
        taken_port = sock.getsockname()[1]
        service = ConductorService(mcp, port=taken_port)
        with pytest.raises(OSError):
            service.launch()
    assert service.status() == "idle"


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
        assert service.status() == "running"
    finally:
        service.stop()
    assert service._thread is None
    assert service.status() == "idle"


def test_service_launch_polls_to_ready_and_stops_without_blocking(blank_canvas):
    """launch() returns before readiness; status/is_stopped drive the polling."""
    from derzug.conductor.mcp_server import ConductorService

    window, _ = blank_canvas
    mcp, _ = _server(window)
    service = ConductorService(mcp, port=0)
    service.launch()
    try:
        assert service.port > 0
        deadline = time.monotonic() + 30
        while service.status() == "starting":
            assert time.monotonic() < deadline, "server never became ready"
            time.sleep(0.02)
        assert service.status() == "running"
        service.request_stop()
        deadline = time.monotonic() + 10
        while not service.is_stopped():
            assert time.monotonic() < deadline, "server never stopped"
            time.sleep(0.02)
    finally:
        service.stop()
    assert service.status() == "idle"


def test_create_service_builds_a_fresh_dispatcher_per_service(blank_canvas):
    """Each service gets its own dispatcher (the stop latch is one-way)."""
    window, _ = blank_canvas
    first = create_service(window, port=0)
    second = create_service(window, port=0)
    assert first._dispatcher is not second._dispatcher
    assert first.server_id != second.server_id


def test_connect_tool_defaults_ports_to_patch(blank_canvas):
    """The connect tool links two nodes using the default 'Patch' ports."""
    window, _ = blank_canvas
    mcp, controller = _server(window)
    spool = controller.add_node("Spool", title="s")
    view = controller.add_node("Waterfall", title="v")
    asyncio.run(mcp.call_tool("connect", {"source_id": spool, "sink_id": view}))
    links = controller.get_canvas_state().links
    assert any(link.source_id == spool and link.sink_id == view for link in links)
