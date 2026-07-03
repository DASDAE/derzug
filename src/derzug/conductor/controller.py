"""Read-only controller over a live DerZug canvas (Conductor Phase 1).

``CanvasController`` wraps a running ``DerZugMainWindow`` and exposes its
workflow as typed observations: the node/link graph, the placeable widget
types, per-node detail, and a compile check. It reuses the same primitives the
rest of the app uses to read the scheme (``scheme.nodes`` / ``scheme.links`` /
``scheme.widget_for_node``) and to compile it (``compile_workflow``).

Phase 1 is read-only and expected to be called on the Qt main thread. Off-thread
marshalling and mutation arrive in later phases.
"""

from __future__ import annotations

from typing import Any

import dascore as dc
from orangewidget.settings import Setting

from derzug.conductor.schema import (
    CanvasState,
    LinkState,
    NodeDetail,
    NodeState,
    PortInfo,
    WidgetTypeInfo,
)
from derzug.widgets.composite import NODE_ID_KEY
from derzug.workflow.compiler import compile_workflow

# Orange base-widget settings that are noise for an agent view.
_SETTINGS_BLOCKLIST = frozenset(
    {"savedWidgetGeometry", "controlAreaVisible", "widgetGeometry", "__version__"}
)


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


def _iter_setting_names(widget: object) -> list[str]:
    """Return the ordered, de-duplicated ``Setting`` names on a widget class."""
    names: list[str] = []
    seen: set[str] = set()
    for klass in type(widget).__mro__:
        for name, value in vars(klass).items():
            if isinstance(value, Setting) and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _read_settings(widget: object) -> dict[str, Any]:
    """Return the widget's current DerZug-relevant settings as JSON-safe data."""
    out: dict[str, Any] = {}
    for name in _iter_setting_names(widget):
        if name in _SETTINGS_BLOCKLIST:
            continue
        try:
            value = getattr(widget, name)
        except Exception:
            continue
        out[name] = _json_safe(value)
    return out


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
    """Read-only observation surface over one live ``DerZugMainWindow``."""

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
            settings=_read_settings(widget),
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

    def list_widget_types(self) -> list[WidgetTypeInfo]:
        """Return the placeable widget types from the window's registry."""
        registry = getattr(self._window, "widget_registry", None)
        if registry is None:
            return []
        types = [
            WidgetTypeInfo(
                name=description.name,
                qualified_name=description.qualified_name,
                category=getattr(description, "category", "") or "",
                description=getattr(description, "description", "") or "",
                keywords=tuple(getattr(description, "keywords", ()) or ()),
                inputs=_ports(getattr(description, "inputs", ()), "input"),
                outputs=_ports(getattr(description, "outputs", ()), "output"),
            )
            for description in registry.widgets()
        ]
        return sorted(
            types, key=lambda widget_type: (widget_type.category, widget_type.name)
        )

    def describe_node(self, node_id: str) -> NodeDetail:
        """Return one node's full state plus a best-effort input-patch summary."""
        scheme = self._scheme()
        for node in scheme.nodes:
            if _node_id(node) == node_id:
                widget = scheme.widget_for_node(node)
                state = self._node_state(node, widget, self._active_source_widget())
                return NodeDetail(
                    node=state,
                    input_patch=_patch_summary(getattr(widget, "_patch", None)),
                )
        raise KeyError(f"no node with id {node_id!r}")

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
