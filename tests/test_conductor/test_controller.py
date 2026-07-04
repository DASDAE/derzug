"""Tests for the read-only Conductor CanvasController (Phase 1)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import dascore as dc
import pytest
from derzug.conductor import CanvasController, CanvasState, FocusState, NodeDetail
from derzug.conductor import controller as controller_module
from derzug.conductor.controller import _json_safe
from derzug.widgets.composite import NODE_ID_KEY
from pydantic import ValidationError


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
        # Param/view schemas let an agent discover valid parameters up front.
        assert waterfall.params_schema and "properties" in waterfall.params_schema
        assert (
            waterfall.view_schema and "colormap" in waterfall.view_schema["properties"]
        )

        # Filter's discriminated-union schema comes through the same accessor.
        filter_type = next(t for t in types if t.name == "Filter")
        assert "oneOf" in filter_type.params_schema

    def test_nodes_params_view_and_ports(self, blank_canvas):
        """Placed nodes report type, title, typed params/view, and ports."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        _add_node(scheme, window, "Waterfall", "view", (300.0, 0.0))

        state = CanvasController(window).get_canvas_state()
        by_title = {node.title: node for node in state.nodes}
        assert set(by_title) == {"source", "view"}

        waterfall = by_title["view"]
        assert waterfall.type == "Waterfall"
        assert waterfall.category == "Visualize"
        # colormap is presentation state (view model); selection is a param.
        assert waterfall.view is not None and "colormap" in waterfall.view
        assert "saved_selection_basis" in waterfall.params
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

    def test_data_readout_hook_failure_is_safe(self, blank_canvas, monkeypatch):
        """A failing cursor-readout hook yields a null data position, not an error."""
        window, scheme = blank_canvas
        waterfall = _add_node(scheme, window, "Waterfall", "view", (0.0, 0.0))
        widget = scheme.widget_for_node(waterfall)

        def _boom():
            raise RuntimeError("no readout")

        widget.conductor_cursor_readout = _boom
        monkeypatch.setattr(
            controller_module.QApplication, "activeWindow", staticmethod(lambda: None)
        )
        monkeypatch.setattr(
            controller_module.QApplication,
            "widgetAt",
            staticmethod(lambda pos: widget),
        )
        focus = CanvasController(window).get_focus()
        assert focus.cursor.data_position is None


class TestNodeDetail:
    """Per-node detail: patch summaries, errors, active source, and stable ids."""

    def test_input_patch_summary(self, blank_canvas):
        """A node holding an input patch reports its shape and dims."""
        window, scheme = blank_canvas
        waterfall = _add_node(scheme, window, "Waterfall", "view", (0.0, 0.0))
        widget = scheme.widget_for_node(waterfall)
        widget._patch = dc.get_example_patch("example_event_1")

        controller = CanvasController(window)
        view_id = controller.get_canvas_state().nodes[0].id
        detail = controller.describe_node(view_id)
        assert set(detail.input_patch["dims"]) == {"distance", "time"}
        assert len(detail.input_patch["shape"]) == 2

    def test_node_error_is_surfaced(self, blank_canvas):
        """A widget's last unhandled error surfaces on its node state."""
        window, scheme = blank_canvas
        node = _add_node(scheme, window, "Waterfall", "view", (0.0, 0.0))
        widget = scheme.widget_for_node(node)
        widget._last_error_exc = (ValueError, ValueError("boom"), None)

        state = CanvasController(window).get_canvas_state()
        assert state.nodes[0].error == "boom"

    def test_active_source_is_reported(self, blank_canvas):
        """The active-source widget is flagged and named in the snapshot."""
        window, scheme = blank_canvas
        spool = _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        widget = scheme.widget_for_node(spool)
        window.active_source_manager = SimpleNamespace(_active_widget=widget)

        state = CanvasController(window).get_canvas_state()
        source = state.nodes[0]
        assert source.is_active_source is True
        assert state.active_source_id == source.id

    def test_stable_node_id_from_properties(self, blank_canvas):
        """A node's persisted DerZug id is preferred over its object id."""
        window, scheme = blank_canvas
        node = _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        node.properties[NODE_ID_KEY] = "stable-id"

        state = CanvasController(window).get_canvas_state()
        assert state.nodes[0].id == "stable-id"


class TestCompileCheckAndHelpers:
    """compile_check over real graphs, and the settings JSON coercion helper."""

    def test_compile_check_reports_graph(self, blank_canvas):
        """A connected Spool->Waterfall compiles with the expected task/edge counts."""
        window, scheme = blank_canvas
        spool = _add_node(scheme, window, "Spool", "source", (0.0, 0.0))
        waterfall = _add_node(scheme, window, "Waterfall", "view", (300.0, 0.0))
        scheme.new_link(
            spool,
            spool.output_channel("Patch"),
            waterfall,
            waterfall.input_channel("Patch"),
        )

        result = CanvasController(window).compile_check()
        assert result["ok"] is True
        assert result["error"] is None
        assert result["task_count"] == 2
        assert result["edge_count"] == 1

    def test_json_safe_coercion(self):
        """Settings values are coerced to JSON-safe data, deeply."""
        assert _json_safe(None) is None
        assert _json_safe("x") == "x"
        assert _json_safe(3) == 3
        assert _json_safe(1.5) == 1.5
        assert _json_safe(True) is True
        assert _json_safe((1, "a")) == [1, "a"]  # tuples become lists
        assert _json_safe({"k": [1, 2]}) == {"k": [1, 2]}
        # Non-JSON values fall back to their string form.
        coerced = _json_safe({"obj": object()})
        assert isinstance(coerced["obj"], str)
        json.dumps(coerced)  # must not raise


class TestWriteSurface:
    """The controller configures existing nodes through the typed interface."""

    def _first_node_id(self, window):
        return CanvasController(window).get_canvas_state().nodes[0].id

    def test_set_params_applies_and_returns_prior(self, blank_canvas):
        """set_params validates + applies params and returns the prior (for undo)."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Detrend", "detrend", (0.0, 0.0))
        controller = CanvasController(window)
        node_id = self._first_node_id(window)

        prior = controller.set_params(
            node_id, {"dim": "time", "detrend_type": "constant"}, run=False
        )
        params = controller.describe_node(node_id).node.params
        assert params["detrend_type"] == "constant"

        # Re-applying the returned prior undoes the change.
        controller.set_params(node_id, prior, run=False)
        assert (
            controller.describe_node(node_id).node.params["detrend_type"]
            == prior["detrend_type"]
        )

    def test_set_params_rejects_invalid(self, blank_canvas):
        """An out-of-schema value is rejected by model validation."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Detrend", "detrend", (0.0, 0.0))
        controller = CanvasController(window)
        node_id = self._first_node_id(window)
        with pytest.raises(ValidationError):
            controller.set_params(node_id, {"detrend_type": "not_a_type"}, run=False)

    def test_set_view_applies_presentation_state(self, blank_canvas):
        """set_view updates a visual widget's view model."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Waterfall", "wf", (0.0, 0.0))
        controller = CanvasController(window)
        node_id = self._first_node_id(window)

        controller.set_view(node_id, {"colormap": "viridis"})
        assert controller.describe_node(node_id).node.view["colormap"] == "viridis"

    def test_set_view_without_view_model_raises(self, blank_canvas):
        """A widget with no view model rejects set_view."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Detrend", "detrend", (0.0, 0.0))
        controller = CanvasController(window)
        node_id = self._first_node_id(window)
        with pytest.raises(ValueError):
            controller.set_view(node_id, {"anything": 1})

    def test_partial_update_preserves_other_fields(self, blank_canvas):
        """A partial dict merges onto current state, not model defaults."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Detrend", "detrend", (0.0, 0.0))
        controller = CanvasController(window)
        node_id = self._first_node_id(window)

        controller.set_params(node_id, {"dim": "time"}, run=False)
        # Setting only detrend_type must not reset the dim set above.
        controller.set_params(node_id, {"detrend_type": "constant"}, run=False)
        params = controller.describe_node(node_id).node.params
        assert params["dim"] == "time"
        assert params["detrend_type"] == "constant"

    def test_set_params_rejects_unknown_field(self, blank_canvas):
        """An unknown field name is rejected (agent typo feedback)."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Detrend", "detrend", (0.0, 0.0))
        controller = CanvasController(window)
        node_id = self._first_node_id(window)
        with pytest.raises(ValueError, match="unknown params"):
            controller.set_params(node_id, {"not_a_field": 1}, run=False)

    def test_set_params_switches_discriminated_type(self, blank_canvas):
        """A partial update can switch a discriminated-union (Filter) type."""
        window, scheme = blank_canvas
        _add_node(scheme, window, "Filter", "filter", (0.0, 0.0))
        controller = CanvasController(window)
        node_id = self._first_node_id(window)

        controller.set_params(
            node_id,
            {"kind": "notch_filter", "frequency": "60 Hz", "q": 30.0},
            run=False,
        )
        params = controller.describe_node(node_id).node.params
        assert params["kind"] == "notch_filter"
        assert params["frequency"] == "60 Hz"


class TestGraphAuthoring:
    """The controller can author the canvas graph (add/connect/remove/run)."""

    def test_add_node_returns_id_and_appears(self, blank_canvas):
        """add_node places a node reachable in the canvas state."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        node_id = controller.add_node("Detrend", title="dt", position=(10.0, 20.0))
        state = controller.get_canvas_state()
        node = next(n for n in state.nodes if n.id == node_id)
        assert node.type == "Detrend"
        assert node.title == "dt"
        assert node.position == (10.0, 20.0)

    def test_add_node_unknown_type_raises(self, blank_canvas):
        """An unregistered widget type is rejected."""
        window, _ = blank_canvas
        with pytest.raises(ValueError, match="unknown widget type"):
            CanvasController(window).add_node("NotAWidget")

    def test_connect_and_disconnect(self, blank_canvas):
        """Connect adds a typed link; disconnect removes it."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        src = controller.add_node("Spool", title="src")
        sink = controller.add_node("Waterfall", title="view", position=(300.0, 0.0))

        controller.connect(src, "Patch", sink, "Patch")
        links = controller.get_canvas_state().links
        assert any(
            link.source_id == src and link.sink_id == sink and link.sink_port == "Patch"
            for link in links
        )

        controller.disconnect(src, "Patch", sink, "Patch")
        assert controller.get_canvas_state().links == []

    def test_connect_invalid_port_raises(self, blank_canvas):
        """Connecting a non-existent port surfaces an error."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        src = controller.add_node("Spool", title="src")
        sink = controller.add_node("Waterfall", title="view", position=(300.0, 0.0))
        with pytest.raises(Exception):
            controller.connect(src, "NoSuchPort", sink, "Patch")

    def test_disconnect_missing_link_raises(self, blank_canvas):
        """Disconnecting an absent link is an explicit error."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        src = controller.add_node("Spool", title="src")
        sink = controller.add_node("Waterfall", title="view", position=(300.0, 0.0))
        with pytest.raises(KeyError):
            controller.disconnect(src, "Patch", sink, "Patch")

    def test_remove_node(self, blank_canvas):
        """remove_node deletes the node from the canvas."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        node_id = controller.add_node("Detrend", title="dt")
        assert any(n.id == node_id for n in controller.get_canvas_state().nodes)
        controller.remove_node(node_id)
        assert all(n.id != node_id for n in controller.get_canvas_state().nodes)

    def test_run_configured_source_is_clean(self, blank_canvas, qtbot):
        """Configuring and running a source executes without raising or erroring."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        spool = controller.add_node("Spool", title="src")
        controller.set_params(spool, {"spool_input": "example_event_1"})
        controller.run(spool)
        qtbot.wait(20)
        assert controller.describe_node(spool).node.error is None

    def test_add_node_is_undoable(self, blank_canvas):
        """An agent's add_node lands on the document undo stack (Ctrl+Z)."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        node_id = controller.add_node("Detrend")
        assert any(n.id == node_id for n in controller.get_canvas_state().nodes)

        window.current_document().undoStack().undo()
        assert all(n.id != node_id for n in controller.get_canvas_state().nodes)

    def test_connect_is_undoable(self, blank_canvas):
        """Connect is undoable via the document undo stack."""
        window, _ = blank_canvas
        controller = CanvasController(window)
        src = controller.add_node("Spool", title="src")
        sink = controller.add_node("Waterfall", title="view", position=(300.0, 0.0))
        controller.connect(src, "Patch", sink, "Patch")
        assert controller.get_canvas_state().links

        window.current_document().undoStack().undo()
        assert controller.get_canvas_state().links == []
