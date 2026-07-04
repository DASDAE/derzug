"""End-to-end: the agent tool sequence builds a compilable pipeline.

Exercises the same calls an agent issues over MCP (discover -> author ->
configure -> compile/run) against a live canvas, proving the loop works without
needing a real agent client.
"""

from __future__ import annotations

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
