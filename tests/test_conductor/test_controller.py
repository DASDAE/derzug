"""Tests for the read-only Conductor CanvasController (Phase 1)."""

from __future__ import annotations

import json

import pytest
from derzug.conductor import CanvasController, CanvasState, FocusState, NodeDetail
from derzug.conductor import controller as controller_module


def _description(window, name):
    """Return the registered widget description for one display name."""
    for description in window.widget_registry.widgets():
        if description.name == name:
            return description
    raise LookupError(f"no registered widget named {name!r}")


def _add_node(scheme, window, name, title, position):
    """Create one node of the named widget type on the scheme."""
    return scheme.new_node(_description(window, name), title=title, position=position)


@pytest.fixture
def blank_canvas(derzug_app):
    """Return (window, scheme) for an emptied canvas."""
    window = derzug_app.window
    scheme = window.current_document().scheme()
    for node in list(scheme.nodes):
        scheme.remove_node(node)
    return window, scheme


class TestObservations:
    """The controller reports the live canvas as typed observations."""

    def test_empty_canvas_state(self, blank_canvas):
        """An empty canvas reports no nodes, links, or active source."""
        window, _ = blank_canvas
        state = CanvasController(window).get_canvas_state()
        assert isinstance(state, CanvasState)
        assert state.nodes == []
        assert state.links == []
        assert state.active_source_id is None

    def test_list_widget_types(self, blank_canvas):
        """The registry surfaces placeable widget types with typed ports."""
        window, _ = blank_canvas
        types = CanvasController(window).list_widget_types()
        names = {widget_type.name for widget_type in types}
        assert {"Spool", "Waterfall", "Filter"} <= names

        waterfall = next(t for t in types if t.name == "Waterfall")
        assert waterfall.qualified_name == "derzug.widgets.waterfall.Waterfall"
        assert any(port.kind == "input" for port in waterfall.inputs)
        assert any(port.kind == "output" for port in waterfall.outputs)

    def test_nodes_settings_and_ports(self, blank_canvas):
        """Placed nodes report type, title, settings, and ports."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        _add_node(scheme, window, "Waterfall", "view", (300.0, 0.0))

        state = CanvasController(window).get_canvas_state()
        by_title = {node.title: node for node in state.nodes}
        assert set(by_title) == {"source", "view"}

        waterfall = by_title["view"]
        assert waterfall.type == "Waterfall"
        assert waterfall.category == "Visualize"
        # A known Waterfall Setting is surfaced in the settings dict.
        assert "colormap" in waterfall.settings
        assert any(port.name == "Patch" for port in waterfall.inputs)

        assert by_title["source"].is_source is True

    def test_describe_node_and_link(self, blank_canvas):
        """describe_node returns detail, and a link round-trips into the state."""
        window, scheme = blank_canvas
        spool = _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        waterfall = _add_node(scheme, window, "Waterfall", "view", (300.0, 0.0))
        scheme.new_link(
            spool,
            spool.output_channel("Patch"),
            waterfall,
            waterfall.input_channel("Patch"),
        )

        controller = CanvasController(window)
        state = controller.get_canvas_state()
        assert len(state.links) == 1
        link = state.links[0]
        assert link.source_port == "Patch"
        assert link.sink_port == "Patch"
        # Link endpoints reference real node ids in the state.
        node_ids = {node.id for node in state.nodes}
        assert {link.source_id, link.sink_id} <= node_ids

        detail = controller.describe_node(link.sink_id)
        assert isinstance(detail, NodeDetail)
        assert detail.node.title == "view"
        assert detail.input_patch is None  # no patch fed yet

    def test_describe_unknown_node_raises(self, blank_canvas):
        """Describing a missing node id raises a clear error."""
        window, _ = blank_canvas
        with pytest.raises(KeyError):
            CanvasController(window).describe_node("does-not-exist")

    def test_compile_check(self, blank_canvas):
        """compile_check returns a JSON-safe status dict for the canvas."""
        window, scheme = blank_canvas
        result = CanvasController(window).compile_check()
        assert set(result) == {"ok", "error", "task_count", "edge_count"}
        assert isinstance(result["ok"], bool)

    def test_state_is_json_serializable(self, blank_canvas):
        """The whole snapshot round-trips through JSON via model_dump."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        dumped = CanvasController(window).get_canvas_state().model_dump()
        json.dumps(dumped)  # must not raise
        assert dumped["nodes"][0]["title"] == "source"


class TestFocusAndPointer:
    """The controller reports what the user is looking at and pointing to."""

    def test_focus_maps_focused_widget_window(self, blank_canvas, monkeypatch):
        """A focused widget window resolves to its canvas node."""
        window, scheme = blank_canvas
        spool = _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        widget = scheme.widget_for_node(spool)
        monkeypatch.setattr(
            controller_module.QApplication,
            "activeWindow",
            staticmethod(lambda: widget),
        )
        monkeypatch.setattr(
            controller_module.QApplication, "widgetAt", staticmethod(lambda pos: None)
        )

        controller = CanvasController(window)
        source_id = next(
            node.id
            for node in controller.get_canvas_state().nodes
            if node.title == "source"
        )

        focus = controller.get_focus()
        assert isinstance(focus, FocusState)
        assert focus.focused_node_id == source_id
        assert controller.get_focused_node() == source_id
        json.dumps(focus.model_dump())  # must not raise

    def test_focus_none_when_canvas_focused(self, blank_canvas, monkeypatch):
        """Focus on the canvas window (not a widget) reports no focused node."""
        window, _ = blank_canvas
        monkeypatch.setattr(
            controller_module.QApplication,
            "activeWindow",
            staticmethod(lambda: window),
        )
        monkeypatch.setattr(
            controller_module.QApplication, "widgetAt", staticmethod(lambda pos: None)
        )
        focus = CanvasController(window).get_focus()
        assert focus.focused_node_id is None
        assert focus.cursor.over_node_id is None

    def test_cursor_over_node_and_data_readout(self, blank_canvas, monkeypatch):
        """The hovered node and its data-space cursor readout are reported."""
        window, scheme = blank_canvas
        waterfall = _add_node(scheme, window, "Waterfall", "view", (0.0, 0.0))
        widget = scheme.widget_for_node(waterfall)
        readout = {"time": "t0", "distance": 340.0, "value": 1.0}
        widget.conductor_cursor_readout = lambda: readout
        monkeypatch.setattr(
            controller_module.QApplication, "activeWindow", staticmethod(lambda: None)
        )
        monkeypatch.setattr(
            controller_module.QApplication,
            "widgetAt",
            staticmethod(lambda pos: widget),
        )

        controller = CanvasController(window)
        view_id = next(
            node.id
            for node in controller.get_canvas_state().nodes
            if node.title == "view"
        )
        focus = controller.get_focus()
        assert focus.cursor.over_node_id == view_id
        assert focus.cursor.data_position == readout
