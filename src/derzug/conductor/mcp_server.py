"""In-app MCP server exposing the Conductor over localhost.

Builds a FastMCP server whose tools drive a live ``CanvasController``. Every tool
marshals its call onto the Qt main thread via a ``MainThreadDispatcher``, so an
external agent client (e.g. Claude Code) can observe and drive the running canvas
over a localhost transport while DerZug's UI stays responsive.

Requires the optional ``mcp`` dependency: ``pip install 'derzug[conductor]'``.
This module is imported only when the Conductor server is started, so the core
app never depends on ``mcp``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from derzug.conductor.controller import CanvasController
from derzug.conductor.dispatch import MainThreadDispatcher

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4319


def build_conductor_mcp(
    controller: CanvasController,
    dispatcher: MainThreadDispatcher,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> FastMCP:
    """Return a FastMCP server whose tools drive ``controller`` on the main thread."""
    mcp = FastMCP(
        "DerZug Conductor",
        instructions=(
            "Observe and drive a live DerZug DAS workflow canvas. Use "
            "list_widget_types to discover node types and their parameter "
            "schemas, get_canvas_state to see the graph, then add_node / connect "
            "/ set_params / run to build and drive a pipeline. Structural edits "
            "are undoable in the app."
        ),
        host=host,
        port=port,
    )

    def call(func: Any, *args: Any, **kwargs: Any) -> Any:
        return dispatcher.run(func, *args, **kwargs)

    @mcp.tool()
    def get_canvas_state() -> dict[str, Any]:
        """Return the whole canvas: nodes (typed params/view, ports) and links."""
        return call(controller.get_canvas_state).model_dump()

    @mcp.tool()
    def list_widget_types() -> list[dict[str, Any]]:
        """List placeable widget types with their params/view JSON schemas."""
        return [info.model_dump() for info in call(controller.list_widget_types)]

    @mcp.tool()
    def describe_node(node_id: str) -> dict[str, Any]:
        """Return one node's detail plus an input-patch shape/dims summary."""
        return call(controller.describe_node, node_id).model_dump()

    @mcp.tool()
    def compile_check() -> dict[str, Any]:
        """Report whether the current canvas compiles into a runnable workflow."""
        return call(controller.compile_check)

    @mcp.tool()
    def get_focus() -> dict[str, Any]:
        """What the user is looking at and pointing to (focused node + cursor)."""
        return call(controller.get_focus).model_dump()

    @mcp.tool()
    def set_params(
        node_id: str, params: dict[str, Any], run: bool = True
    ) -> dict[str, Any]:
        """Apply a partial params update to a node; returns its prior params."""
        return {"prior": call(controller.set_params, node_id, params, run=run)}

    @mcp.tool()
    def set_view(
        node_id: str, view: dict[str, Any], run: bool = False
    ) -> dict[str, Any]:
        """Apply a partial view update (colormap, range, ...); returns the prior."""
        return {"prior": call(controller.set_view, node_id, view, run=run)}

    @mcp.tool()
    def add_node(
        widget_type: str, title: str | None = None, x: float = 0.0, y: float = 0.0
    ) -> str:
        """Add a node (display or qualified type name); returns its id. Undoable."""
        return call(controller.add_node, widget_type, title=title, position=(x, y))

    @mcp.tool()
    def remove_node(node_id: str) -> None:
        """Remove a node and its links. Undoable."""
        call(controller.remove_node, node_id)

    @mcp.tool()
    def connect(source_id: str, source_port: str, sink_id: str, sink_port: str) -> None:
        """Link source_id:source_port -> sink_id:sink_port. Undoable."""
        call(controller.connect, source_id, source_port, sink_id, sink_port)

    @mcp.tool()
    def disconnect(
        source_id: str, source_port: str, sink_id: str, sink_port: str
    ) -> None:
        """Remove the matching link. Undoable."""
        call(controller.disconnect, source_id, source_port, sink_id, sink_port)

    @mcp.tool()
    def run(node_id: str) -> None:
        """Re-run a node; sources re-emit and propagate downstream."""
        call(controller.run, node_id)

    return mcp


def serve_in_thread(mcp: FastMCP) -> threading.Thread:
    """Run the MCP server (streamable-http) in a daemon thread; return the thread."""
    thread = threading.Thread(
        target=lambda: mcp.run(transport="streamable-http"),
        name="conductor-mcp",
        daemon=True,
    )
    thread.start()
    return thread


def write_mcp_config(
    path: str | Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    name: str = "derzug-conductor",
) -> str:
    """Write an MCP client config pointing at the running server; return its URL.

    The file is an ``.mcp.json`` a client such as Claude Code can pick up, so the
    user just launches their agent in that directory and it is wired to the live
    canvas with no manual endpoint entry.
    """
    url = f"http://{host}:{port}/mcp"
    config = {"mcpServers": {name: {"type": "http", "url": url}}}
    Path(path).write_text(json.dumps(config, indent=2))
    return url
