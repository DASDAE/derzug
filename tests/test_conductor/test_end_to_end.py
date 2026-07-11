"""End-to-end: the agent tool sequence builds a compilable pipeline.

Two layers: the controller-level test exercises the agent call sequence
(discover -> author -> configure -> compile/run) directly on the main thread;
the HTTP test drives the same canvas through a real MCP client over
streamable-http, exercising the server thread and the cross-thread dispatcher.
"""

from __future__ import annotations

import asyncio
import threading
import time

from derzug.conductor import CanvasController


def test_agent_builds_spool_filter_waterfall_pipeline(blank_canvas, qtbot):
    """Discover -> add -> connect -> configure yields a compilable workflow."""
    window, _ = blank_canvas
    conductor = CanvasController(window)

    # Discover the available node types (and their param schemas).
    types = {info.name for info in conductor.list_widget_types()}
    assert {"Spool", "Filter", "Waterfall"} <= types

    # Author: Spool -> Filter -> Waterfall.
    spool = conductor.add_node("Spool", title="src")
    bandpass = conductor.add_node("Filter", title="bandpass", position=(200.0, 0.0))
    view = conductor.add_node("Waterfall", title="view", position=(400.0, 0.0))
    conductor.connect(spool, "Patch", bandpass, "Patch")
    conductor.connect(bandpass, "Patch", view, "Patch")

    # Configure: load an example and set a 5-40 Hz bandpass.
    conductor.set_params(spool, {"spool_input": "example_event_1"})
    conductor.set_params(
        bandpass,
        {
            "kind": "pass_filter",
            "dim": "time",
            "low_bound": "5 Hz",
            "high_bound": "40 Hz",
        },
    )

    # The pipeline the agent built is a valid, compilable workflow.
    check = conductor.compile_check()
    assert check["ok"], check.get("error")
    assert check["task_count"] >= 3
    assert check["edge_count"] >= 2

    # The configured filter reads back through the typed params.
    bandpass_params = conductor.describe_node(bandpass).node.params
    assert bandpass_params["kind"] == "pass_filter"
    assert bandpass_params["high_bound"] == "40 Hz"

    # Running the source executes cleanly (no widget errors).
    conductor.run(spool)
    qtbot.wait(20)
    by_title = {node.title: node for node in conductor.get_canvas_state().nodes}
    assert by_title["src"].error is None
    assert by_title["bandpass"].error is None


def test_agent_drives_canvas_over_http(blank_canvas):
    """A real MCP client over streamable-http drives the live canvas.

    Exercises the full transport path — HTTP server thread, MCP session, and
    the cross-thread dispatch onto the Qt main thread — which the direct
    controller test above cannot. The client runs in a worker thread while
    this (main) thread pumps the Qt event loop to service dispatched calls.
    """
    import pytest

    pytest.importorskip("mcp")
    from AnyQt.QtWidgets import QApplication
    from derzug.conductor import MainThreadDispatcher
    from derzug.conductor.mcp_server import ConductorService, build_conductor_mcp

    window, _ = blank_canvas
    controller = CanvasController(window)
    dispatcher = MainThreadDispatcher()
    service = ConductorService(
        build_conductor_mcp(controller, dispatcher), port=0, dispatcher=dispatcher
    )
    url = service.start(timeout=30.0)
    outcome: dict[str, object] = {}

    async def drive() -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                added = await session.call_tool(
                    "add_node", {"widget_type": "Detrend", "title": "over-http"}
                )
                assert not added.isError
                state = await session.call_tool("get_canvas_state", {})
                assert not state.isError
                outcome["ok"] = True

    def client() -> None:
        try:
            asyncio.run(drive())
        except BaseException as exc:  # surfaced in the main-thread assert below
            outcome["error"] = exc

    thread = threading.Thread(target=client)
    thread.start()
    deadline = time.monotonic() + 60
    while thread.is_alive() and time.monotonic() < deadline:
        QApplication.processEvents()  # service the dispatched main-thread calls
        time.sleep(0.01)
    try:
        assert not thread.is_alive(), "MCP client did not finish in time"
        assert "error" not in outcome, outcome.get("error")
        assert outcome.get("ok") is True
        # The tool call landed on the live canvas.
        titles = [node.title for node in controller.get_canvas_state().nodes]
        assert "over-http" in titles
    finally:
        service.stop()
