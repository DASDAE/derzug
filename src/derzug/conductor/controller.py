"""Controller over a live DerZug canvas (Conductor).

``CanvasController`` wraps a running ``DerZugMainWindow`` and exposes its
workflow as typed observations (the node/link graph, placeable widget types
with their param schemas, per-node detail, a compile check) plus a write surface
to configure nodes (``set_params`` / ``set_view``) and author the graph
(``add_node`` / ``remove_node`` / ``connect`` / ``disconnect`` / ``run``). It
reuses the same primitives the rest of the app uses to read the scheme
(``scheme.nodes`` / ``scheme.links`` / ``scheme.widget_for_node``), edit it
(``scheme.new_node`` / ``scheme.new_link`` / ...), compile it
(``compile_workflow``), and set widget state (``apply_params`` /
``apply_view``).

All methods are expected to be called on the Qt main thread. Undo-stack
integration, Code-widget safety gating, off-thread marshalling, and the MCP
transport arrive in later phases.
"""

from __future__ import annotations

import importlib
from typing import Any, get_args

import dascore as dc
from AnyQt.QtGui import QCursor
from AnyQt.QtWidgets import QApplication

from derzug.conductor.schema import (
    CanvasState,
    CursorState,
    FocusState,
    LinkState,
    NodeDetail,
    NodeState,
    PortInfo,
    WidgetTypeInfo,
)
from derzug.widgets.composite import NODE_ID_KEY
from derzug.workflow.compiler import compile_workflow


def _widget_class(qualified_name: str) -> type | None:
    """Load a widget class from its ``module.Class`` qualified name, or None."""
    try:
        module_name, class_name = qualified_name.rsplit(".", 1)
        return getattr(importlib.import_module(module_name), class_name)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    """Return a JSON-serializable view of one setting value."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _node_id(node: Any) -> str:
    """Return a stable id for one node (DerZug node id when present)."""
    properties = getattr(node, "properties", None) or {}
    node_id = str(properties.get(NODE_ID_KEY, "")).strip()
    return node_id or str(id(node))


def _model_field_names(model: object) -> set[str]:
    """All valid field names for a model, combining discriminated-union members."""
    fields = getattr(model, "model_fields", None)
    if fields is not None:
        return set(fields)
    names: set[str] = set()
    for arg in get_args(model):  # Annotated[Union[...], FieldInfo]
        for member in get_args(arg):  # the union members
            member_fields = getattr(member, "model_fields", None)
            if member_fields:
                names |= set(member_fields)
    return names


def _read_params(widget: object) -> dict[str, Any]:
    """Return the widget's typed parameters as JSON-safe data."""
    if getattr(type(widget), "params_model", None) is None:
        return {}
    try:
        return _json_safe(widget.get_params().model_dump())
    except Exception:
        return {}


def _read_view(widget: object) -> dict[str, Any] | None:
    """Return the widget's typed presentation state as JSON-safe data, or None."""
    if getattr(type(widget), "view_model", None) is None:
        return None
    try:
        return _json_safe(widget.get_view().model_dump())
    except Exception:
        return None


def _signal_type_name(signal: object) -> str:
    """Return a readable type name for one Orange input/output signal."""
    signal_type = getattr(signal, "type", None)
    if isinstance(signal_type, str):
        return signal_type
    if isinstance(signal_type, type):
        return signal_type.__name__
    return str(signal_type)


def _ports(signals: object, kind: str) -> list[PortInfo]:
    """Return typed ``PortInfo`` entries for a signal container."""
    return [
        PortInfo(name=getattr(sig, "name", ""), type=_signal_type_name(sig), kind=kind)
        for sig in (signals or ())
    ]


def _patch_summary(obj: object) -> dict[str, Any] | None:
    """Return a shape/dims summary for a patch-like object, else None."""
    if not isinstance(obj, dc.Patch):
        return None
    return {"shape": list(obj.shape), "dims": list(obj.dims)}


def _widget_error(widget: object) -> str | None:
    """Return the widget's last unhandled error message, when tracked."""
    exc = getattr(widget, "_last_error_exc", None)
    if exc and len(exc) >= 2 and exc[1] is not None:
        return str(exc[1])
    return None


class CanvasController:
    """Observation + configure surface over one live ``DerZugMainWindow``.

    Wraps a running window and projects its workflow as JSON-serializable
    observations for an agent, and lets the agent configure existing nodes:

    - :meth:`get_canvas_state` — the whole node/link graph and active source.
    - :meth:`list_widget_types` — the placeable widget catalog + param schemas.
    - :meth:`describe_node` — one node's detail plus an input-patch summary.
    - :meth:`compile_check` — whether the canvas currently compiles.
    - :meth:`get_focused_node` / :meth:`get_focus` — what the user is looking at
      and pointing to, for shared user/agent context.
    - :meth:`set_params` / :meth:`set_view` — apply typed, validated state to a
      node, returning the prior state for undo.
    - :meth:`add_node` / :meth:`remove_node` / :meth:`connect` /
      :meth:`disconnect` / :meth:`run` — author and drive the graph.

    Must be called on the Qt main thread. Undo-stack integration and off-thread
    dispatch arrive in later phases.

    Examples
    --------
    >>> controller = CanvasController(main_window)
    >>> controller.get_canvas_state().model_dump()   # agent-ready JSON
    {'title': None, 'nodes': [...], 'links': [...], 'active_source_id': None}
    """

    def __init__(self, window: object) -> None:
        self._window = window

    def _scheme(self) -> Any:
        """Return the live scheme backing the window's current document."""
        return self._window.current_document().scheme()

    def _active_source_widget(self) -> object | None:
        """Return the current active-source widget, if any."""
        manager = getattr(self._window, "active_source_manager", None)
        return getattr(manager, "_active_widget", None) if manager else None

    def _node_state(
        self, node: Any, widget: object, active: object | None
    ) -> NodeState:
        """Build the observable state for one node."""
        description = getattr(node, "description", None)
        widget_type = type(widget)
        qualified_name = getattr(
            description,
            "qualified_name",
            f"{widget_type.__module__}.{widget_type.__name__}",
        )
        position = getattr(node, "position", None)
        return NodeState(
            id=_node_id(node),
            type=widget_type.__name__,
            qualified_name=qualified_name,
            title=getattr(node, "title", ""),
            category=getattr(description, "category", "") or "",
            position=tuple(position) if position else None,
            params=_read_params(widget),
            view=_read_view(widget),
            inputs=_ports(getattr(description, "inputs", ()), "input"),
            outputs=_ports(getattr(description, "outputs", ()), "output"),
            is_source=bool(getattr(widget, "is_source", False)),
            is_active_source=widget is active,
            error=_widget_error(widget),
        )

    def get_canvas_state(self) -> CanvasState:
        """Return a full snapshot of the current canvas graph."""
        scheme = self._scheme()
        active = self._active_source_widget()
        node_ids: dict[object, str] = {}
        nodes: list[NodeState] = []
        for node in scheme.nodes:
            widget = scheme.widget_for_node(node)
            state = self._node_state(node, widget, active)
            node_ids[widget] = state.id
            nodes.append(state)

        links: list[LinkState] = []
        for link in scheme.links:
            links.append(
                LinkState(
                    source_id=_node_id(link.source_node),
                    source_port=link.source_channel.name,
                    sink_id=_node_id(link.sink_node),
                    sink_port=link.sink_channel.name,
                    enabled=bool(getattr(link, "enabled", True)),
                )
            )

        return CanvasState(
            title=getattr(scheme, "title", None) or None,
            nodes=nodes,
            links=links,
            active_source_id=node_ids.get(active),
        )

    @staticmethod
    def _widget_type_info(description: Any) -> WidgetTypeInfo:
        """Build one WidgetTypeInfo, with param/view schemas when discoverable."""
        cls = _widget_class(getattr(description, "qualified_name", "") or "")
        params_schema = cls.params_schema() if hasattr(cls, "params_schema") else None
        view_schema = cls.view_schema() if hasattr(cls, "view_schema") else None
        return WidgetTypeInfo(
            name=description.name,
            qualified_name=description.qualified_name,
            category=getattr(description, "category", "") or "",
            description=getattr(description, "description", "") or "",
            keywords=tuple(getattr(description, "keywords", ()) or ()),
            inputs=_ports(getattr(description, "inputs", ()), "input"),
            outputs=_ports(getattr(description, "outputs", ()), "output"),
            params_schema=params_schema,
            view_schema=view_schema,
        )

    def list_widget_types(self) -> list[WidgetTypeInfo]:
        """Return the placeable widget types from the window's registry."""
        registry = getattr(self._window, "widget_registry", None)
        if registry is None:
            return []
        types = [
            self._widget_type_info(description) for description in registry.widgets()
        ]
        return sorted(
            types, key=lambda widget_type: (widget_type.category, widget_type.name)
        )

    def _node_for_id(self, node_id: str) -> Any:
        """Return the scheme node with ``node_id``, or raise ``KeyError``."""
        for node in self._scheme().nodes:
            if _node_id(node) == node_id:
                return node
        raise KeyError(f"no node with id {node_id!r}")

    def _widget_for_id(self, node_id: str) -> Any:
        """Return the widget for ``node_id``, or raise ``KeyError``."""
        return self._scheme().widget_for_node(self._node_for_id(node_id))

    def describe_node(self, node_id: str) -> NodeDetail:
        """Return one node's full state plus a best-effort input-patch summary."""
        node = self._node_for_id(node_id)
        widget = self._scheme().widget_for_node(node)
        state = self._node_state(node, widget, self._active_source_widget())
        return NodeDetail(
            node=state,
            input_patch=_patch_summary(getattr(widget, "_patch", None)),
        )

    # -- Write surface (Phase 2): configure existing nodes -------------------

    def _merge(self, model: object, kind: str, current: dict[str, Any], update: Any):
        """Merge a partial dict update onto current state, or take a full model.

        A dict is a partial update: unknown keys are rejected and the rest are
        layered onto the current values, so setting one field never silently
        resets the others to model defaults. A model instance replaces wholesale.
        """
        if not isinstance(update, dict):
            return update
        unknown = set(update) - _model_field_names(model)
        if unknown:
            raise ValueError(f"unknown {kind} field(s): {sorted(unknown)}")
        return {**current, **update}

    def set_params(
        self, node_id: str, params: Any, *, run: bool = True
    ) -> dict[str, Any]:
        """Apply typed parameters to one node; return its prior params.

        ``params`` is a ``params_model`` instance (full replacement) or a dict
        (a partial update merged onto current values, with unknown keys
        rejected). It is validated against the widget's model. Re-apply the
        returned prior dict to undo. Must be called on the Qt main thread.
        """
        widget = self._widget_for_id(node_id)
        model = getattr(type(widget), "params_model", None)
        if model is None:
            raise ValueError(f"node {node_id!r} has no params model")
        current = widget.get_params().model_dump()
        widget.apply_params(self._merge(model, "params", current, params), run=run)
        return _json_safe(current)

    def set_view(self, node_id: str, view: Any, *, run: bool = False) -> dict[str, Any]:
        """Apply presentation state to one node; return its prior view state.

        Like :meth:`set_params`, a dict is a partial update merged onto current.
        """
        widget = self._widget_for_id(node_id)
        model = getattr(type(widget), "view_model", None)
        if model is None:
            raise ValueError(f"node {node_id!r} has no view model")
        current = widget.get_view().model_dump()
        widget.apply_view(self._merge(model, "view", current, view), run=run)
        return _json_safe(current)

    # -- Write surface (Phase 2): author the graph ---------------------------

    def _description_for(self, widget_type: str) -> Any:
        """Return the registry description for a display or qualified name."""
        registry = getattr(self._window, "widget_registry", None)
        for description in registry.widgets() if registry else ():
            if widget_type in (description.name, description.qualified_name):
                return description
        raise ValueError(f"unknown widget type: {widget_type!r}")

    def add_node(
        self,
        widget_type: str,
        *,
        title: str | None = None,
        position: tuple[float, float] = (0.0, 0.0),
    ) -> str:
        """Add a node of ``widget_type`` (display or qualified name); return its id."""
        description = self._description_for(widget_type)
        node = self._scheme().new_node(
            description, title=title or description.name, position=tuple(position)
        )
        return _node_id(node)

    def remove_node(self, node_id: str) -> None:
        """Remove one node (and its links) from the canvas."""
        self._scheme().remove_node(self._node_for_id(node_id))

    def connect(
        self, source_id: str, source_port: str, sink_id: str, sink_port: str
    ) -> None:
        """Link ``source_id:source_port`` to ``sink_id:sink_port``."""
        scheme = self._scheme()
        source = self._node_for_id(source_id)
        sink = self._node_for_id(sink_id)
        scheme.new_link(
            source,
            source.output_channel(source_port),
            sink,
            sink.input_channel(sink_port),
        )

    def disconnect(
        self, source_id: str, source_port: str, sink_id: str, sink_port: str
    ) -> None:
        """Remove the link matching the given endpoints, or raise ``KeyError``."""
        scheme = self._scheme()
        for link in list(scheme.links):
            if (
                _node_id(link.source_node) == source_id
                and link.source_channel.name == source_port
                and _node_id(link.sink_node) == sink_id
                and link.sink_channel.name == sink_port
            ):
                scheme.remove_link(link)
                return
        raise KeyError(f"no link {source_id}:{source_port} -> {sink_id}:{sink_port}")

    def run(self, node_id: str) -> None:
        """Re-run one node's widget; sources re-emit and propagate downstream."""
        self._widget_for_id(node_id).run()

    def _node_for_window(self, window: object | None) -> Any | None:
        """Return the node whose widget owns ``window``, or None."""
        if window is None:
            return None
        scheme = self._scheme()
        for node in scheme.nodes:
            widget = scheme.widget_for_node(node)
            if widget is window or widget.window() is window:
                return node
        return None

    def _data_position(self, node: Any | None) -> dict[str, Any] | None:
        """Return the hovered widget's data-space cursor readout, if it exposes one.

        Plotting widgets can implement ``conductor_cursor_readout()`` returning a
        mapping like ``{"time": ..., "distance": ..., "value": ...}``; until they
        do, this is ``None``.
        """
        if node is None:
            return None
        widget = self._scheme().widget_for_node(node)
        hook = getattr(widget, "conductor_cursor_readout", None)
        if not callable(hook):
            return None
        try:
            readout = hook()
        except Exception:
            return None
        return dict(readout) if readout else None

    def get_focused_node(self) -> str | None:
        """Return the id of the node whose widget window is currently focused."""
        node = self._node_for_window(QApplication.activeWindow())
        return _node_id(node) if node is not None else None

    def get_focus(self) -> FocusState:
        """Return what the user is looking at and pointing to (shared context)."""
        active = QApplication.activeWindow()
        focused_node = self._node_for_window(active)
        position = QCursor.pos()
        over_node = self._node_for_window(
            widget.window() if (widget := QApplication.widgetAt(position)) else None
        )
        return FocusState(
            focused_node_id=_node_id(focused_node) if focused_node else None,
            focused_window_title=active.windowTitle() if active is not None else None,
            cursor=CursorState(
                screen_xy=(position.x(), position.y()),
                over_node_id=_node_id(over_node) if over_node else None,
                data_position=self._data_position(over_node),
            ),
        )

    def compile_check(self) -> dict[str, Any]:
        """Return whether the current canvas compiles, with a compact summary."""
        try:
            compiled = compile_workflow(self._scheme())
        except Exception as exc:
            return {"ok": False, "error": str(exc), "task_count": 0, "edge_count": 0}
        return {
            "ok": True,
            "error": None,
            "task_count": len(compiled.pipe.tasks),
            "edge_count": len(compiled.pipe.edges),
        }
