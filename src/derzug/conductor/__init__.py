"""DerZug Conductor: a programmatic, agent-facing control surface over a live canvas.

``CanvasController`` wraps a running ``DerZugMainWindow`` to observe the workflow
(typed, JSON-serializable state + widget schemas), configure nodes
(``set_params`` / ``set_view``), and author the graph (``add_node`` / ``connect``
/ ...), with structural edits registered on the undo stack.
``MainThreadDispatcher`` marshals those calls onto the Qt main thread for the
off-thread MCP transport. The MCP server itself is added in a later phase.
"""

from derzug.conductor.controller import CanvasController
from derzug.conductor.dispatch import MainThreadDispatcher
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

__all__ = (
    "CanvasController",
    "CanvasState",
    "CursorState",
    "FocusState",
    "LinkState",
    "MainThreadDispatcher",
    "NodeDetail",
    "NodeState",
    "PortInfo",
    "WidgetTypeInfo",
)
