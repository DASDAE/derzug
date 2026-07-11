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

Graph edits (add/remove nodes, connect/disconnect) are registered on the
document's undo stack, so the user can ``Ctrl+Z`` an agent's structural changes.
Widget parameter/view changes are not put on the stack (Orange's crash-recovery
swap file pickles the stack, and a widget-state command can't be cleanly
serialized); ``set_params`` / ``set_view`` instead return the prior state so the
caller can undo by re-applying it.

All methods are expected to be called on the Qt main thread; the MCP transport
marshals onto it via ``MainThreadDispatcher``. The ``Code`` widget (whose
parameters are executable Python) is excluded from the surface unless the
controller is built with ``allow_code=True``.
"""

from __future__ import annotations

import importlib
from typing import Any, get_args

import dascore as dc
from AnyQt.QtGui import QCursor
from AnyQt.QtWidgets import QApplication
from orangecanvas.scheme import SchemeLink, SchemeNode

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
from derzug.widgets.composite import ensure_node_id
from derzug.workflow.compiler import compile_workflow

# Horizontal gap (scheme units) between auto-placed nodes; keeps chains compact.
_NODE_GAP = 150.0

# Widget types whose parameters are executable Python. Excluded from the
# Conductor catalog and rejected on add/configure unless the user opts in
# (``--conductor-allow-code``): a connected agent must not gain arbitrary
# code execution through widget parameters.
UNSAFE_WIDGET_QNAMES = frozenset({"derzug.widgets.code.Code"})


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


def _widget_busy(widget: object) -> bool:
    """Return True while the widget's async execution is in flight."""
    return bool(getattr(widget, "_async_busy_state", False))


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

    def __init__(self, window: object, *, allow_code: bool = False) -> None:
        self._window = window
        self._allow_code = allow_code

    def _check_type_allowed(self, qualified_name: str) -> None:
        """Raise unless ``qualified_name`` may be authored/configured."""
        if not self._allow_code and qualified_name in UNSAFE_WIDGET_QNAMES:
            raise PermissionError(
                f"widget type {qualified_name!r} executes arbitrary Python and is "
                "disabled for agents; start DerZug with --conductor-allow-code "
                "to enable it"
            )

    def _check_widget_allowed(self, widget: object) -> None:
        """Raise unless ``widget``'s type may be configured by an agent."""
        widget_type = type(widget)
        self._check_type_allowed(f"{widget_type.__module__}.{widget_type.__name__}")

    def _document(self) -> Any:
        """Return the window's current document (undoable scheme editor)."""
        return self._window.current_document()

    def _scheme(self) -> Any:
        """Return the live scheme backing the window's current document."""
        return self._document().scheme()

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
            id=ensure_node_id(node),
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
            busy=_widget_busy(widget),
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
                    source_id=ensure_node_id(link.source_node),
                    source_port=link.source_channel.name,
                    sink_id=ensure_node_id(link.sink_node),
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
            self._widget_type_info(description)
            for description in registry.widgets()
            if self._allow_code
            or description.qualified_name not in UNSAFE_WIDGET_QNAMES
        ]
        return sorted(
            types, key=lambda widget_type: (widget_type.category, widget_type.name)
        )

    def _node_for_id(self, node_id: str) -> Any:
        """Return the scheme node with ``node_id``, or raise ``KeyError``."""
        for node in self._scheme().nodes:
            if ensure_node_id(node) == node_id:
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
        self._check_widget_allowed(widget)
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
        self._check_widget_allowed(widget)
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
                self._check_type_allowed(description.qualified_name)
                return description
        raise ValueError(f"unknown widget type: {widget_type!r}")

    def _auto_position(self) -> tuple[float, float]:
        """A compact spot for a new node: just right of the rightmost one."""
        nodes = list(self._scheme().nodes)
        if not nodes:
            return (0.0, 0.0)
        x, y = max((node.position or (0.0, 0.0) for node in nodes), key=lambda p: p[0])
        return (x + _NODE_GAP, y)

    def add_node(
        self,
        widget_type: str,
        *,
        title: str | None = None,
        position: tuple[float, float] | None = None,
    ) -> str:
        """Add a node of ``widget_type`` (display or qualified name); return its id.

        When ``position`` is omitted the node is auto-placed a compact gap to the
        right of the current rightmost node, so an agent building a chain gets a
        tidy left-to-right layout without computing coordinates.

        Undoable: registered on the document's undo stack, so the user can
        ``Ctrl+Z`` an agent's addition.
        """
        description = self._description_for(widget_type)
        placement = self._auto_position() if position is None else tuple(position)
        node = SchemeNode(
            description, title=title or description.name, position=placement
        )
        # Persist the id before the node enters the undo stack, so it survives
        # undo/redo cycles and save/reload.
        node_id = ensure_node_id(node)
        self._document().addNode(node)
        return node_id

    def remove_node(self, node_id: str) -> None:
        """Remove one node (and its links) from the canvas (undoable)."""
        self._document().removeNode(self._node_for_id(node_id))

    def connect(
        self, source_id: str, source_port: str, sink_id: str, sink_port: str
    ) -> None:
        """Link ``source_id:source_port`` to ``sink_id:sink_port`` (undoable)."""
        source = self._node_for_id(source_id)
        sink = self._node_for_id(sink_id)
        link = SchemeLink(
            source,
            source.output_channel(source_port),
            sink,
            sink.input_channel(sink_port),
        )
        self._document().addLink(link)

    def disconnect(
        self, source_id: str, source_port: str, sink_id: str, sink_port: str
    ) -> None:
        """Remove the link matching the given endpoints (undoable); else KeyError."""
        for link in list(self._scheme().links):
            if (
                ensure_node_id(link.source_node) == source_id
                and link.source_channel.name == source_port
                and ensure_node_id(link.sink_node) == sink_id
                and link.sink_channel.name == sink_port
            ):
                self._document().removeLink(link)
                return
        raise KeyError(f"no link {source_id}:{source_port} -> {sink_id}:{sink_port}")

    def run(self, node_id: str) -> None:
        """Re-run one node's widget; sources re-emit and propagate downstream.

        Execution is asynchronous: this schedules the run and returns. Poll
        :meth:`busy_nodes` (or the ``busy`` flag in node state) for completion.
        """
        self._widget_for_id(node_id).run()

    def busy_nodes(self) -> list[str]:
        """Return the ids of nodes whose widgets are currently executing."""
        scheme = self._scheme()
        return [
            ensure_node_id(node)
            for node in scheme.nodes
            if _widget_busy(scheme.widget_for_node(node))
        ]

    def show_node(
        self, node_id: str, *, x: float | None = None, y: float | None = None
    ) -> None:
        """Pop up (show, raise, focus) a node's widget window, optionally at (x, y).

        ``x``/``y`` are screen coordinates; when given, the window is moved there
        before it is shown.
        """
        widget = self._widget_for_id(node_id)
        if x is not None and y is not None:
            widget.move(int(x), int(y))
        widget.show()
        widget.raise_()
        widget.activateWindow()

    def move_node_window(self, node_id: str, x: float, y: float) -> None:
        """Move a node's widget window to screen coordinates ``(x, y)``."""
        self._widget_for_id(node_id).move(int(x), int(y))

    def hide_node(self, node_id: str) -> None:
        """Hide (close) a node's widget window."""
        self._widget_for_id(node_id).hide()

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
        return ensure_node_id(node) if node is not None else None

    def get_focus(self) -> FocusState:
        """Return what the user is looking at and pointing to (shared context)."""
        active = QApplication.activeWindow()
        focused_node = self._node_for_window(active)
        position = QCursor.pos()
        over_node = self._node_for_window(
            widget.window() if (widget := QApplication.widgetAt(position)) else None
        )
        return FocusState(
            focused_node_id=ensure_node_id(focused_node) if focused_node else None,
            focused_window_title=active.windowTitle() if active is not None else None,
            cursor=CursorState(
                screen_xy=(position.x(), position.y()),
                over_node_id=ensure_node_id(over_node) if over_node else None,
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
