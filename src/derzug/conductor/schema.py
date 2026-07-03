"""JSON-serializable observation models for the DerZug Conductor.

These mirror the workflow layer's pydantic style and describe the live canvas in
a form an external agent can consume. They carry no Qt/Orange objects, only
plain data, so ``model_dump()`` yields agent-ready JSON.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PortInfo(BaseModel):
    """One input or output signal port on a node or widget type."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    kind: str  # "input" | "output"


class NodeState(BaseModel):
    """The observable state of one node on the canvas."""

    id: str
    type: str
    qualified_name: str
    title: str
    category: str
    position: tuple[float, float] | None
    settings: dict[str, Any]
    inputs: list[PortInfo]
    outputs: list[PortInfo]
    is_source: bool
    is_active_source: bool
    error: str | None


class LinkState(BaseModel):
    """One directed link between two node ports."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    source_port: str
    sink_id: str
    sink_port: str
    enabled: bool


class CanvasState(BaseModel):
    """A snapshot of the whole canvas: nodes, links, and the active source."""

    title: str | None
    nodes: list[NodeState]
    links: list[LinkState]
    active_source_id: str | None


class WidgetTypeInfo(BaseModel):
    """A registered widget type available to place on the canvas."""

    name: str
    qualified_name: str
    category: str
    description: str
    keywords: tuple[str, ...]
    inputs: list[PortInfo]
    outputs: list[PortInfo]


class NodeDetail(BaseModel):
    """A single node's full state plus a best-effort input-patch summary."""

    node: NodeState
    input_patch: dict[str, Any] | None


class CursorState(BaseModel):
    """Where the user's pointer is, for shared user/agent context."""

    screen_xy: tuple[int, int]
    over_node_id: str | None
    # Data-space position under the cursor (e.g. {"time": ..., "distance": ...,
    # "value": ...}), when the hovered widget exposes a cursor readout.
    data_position: dict[str, Any] | None


class FocusState(BaseModel):
    """What the user is currently looking at and pointing to."""

    focused_node_id: str | None
    focused_window_title: str | None
    cursor: CursorState
