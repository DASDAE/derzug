"""DerZug Conductor: a programmatic, agent-facing view of a live canvas.

Phase 1 provides a read-only ``CanvasController`` over a running
``DerZugMainWindow`` plus JSON-serializable observation models. Mutation and the
MCP transport are added in later phases; this layer is intentionally a thin,
well-typed observation surface so its shape can be reviewed first.
"""

from derzug.conductor.controller import CanvasController
from derzug.conductor.schema import (
    CanvasState,
    LinkState,
    NodeDetail,
    NodeState,
    PortInfo,
    WidgetTypeInfo,
)

__all__ = (
    "CanvasController",
    "CanvasState",
    "LinkState",
    "NodeDetail",
    "NodeState",
    "PortInfo",
    "WidgetTypeInfo",
)
