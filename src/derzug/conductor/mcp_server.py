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
import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from derzug.conductor.controller import CanvasController
from derzug.conductor.dispatch import MainThreadDispatcher

log = logging.getLogger(__name__)

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
        widget_type: str,
        title: str | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> str:
        """Add a node (display or qualified type name); returns its id.

        Omit x/y to auto-place it compactly to the right of existing nodes.
        Undoable.
        """
        position = (x, y) if x is not None and y is not None else None
        return call(controller.add_node, widget_type, title=title, position=position)

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

    @mcp.tool()
    def show_node(node_id: str, x: float | None = None, y: float | None = None) -> None:
        """Pop up a node's widget window (show/raise/focus), optionally at (x, y)."""
        call(controller.show_node, node_id, x=x, y=y)

    @mcp.tool()
    def move_node_window(node_id: str, x: float, y: float) -> None:
        """Move a node's widget window to screen coordinates (x, y)."""
        call(controller.move_node_window, node_id, x, y)

    @mcp.tool()
    def hide_node(node_id: str) -> None:
        """Hide (close) a node's widget window."""
        call(controller.hide_node, node_id)

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


# Agents we know how to auto-launch. The command runs in the config directory.
_AGENT_COMMANDS = {
    "claude": ["claude"],  # reads the .mcp.json we drop in the launch cwd
    "codex": ["codex"],  # needs an mcp-remote bridge entry (written below)
}


def _write_codex_config(host: str, port: int, name: str = "derzug-conductor") -> None:
    """Add an mcp-remote bridge for the server to ``~/.codex/config.toml``.

    Codex speaks stdio MCP, so it reaches our HTTP server through ``mcp-remote``.
    Appends the section only when absent (best effort; needs ``npx`` at runtime).
    """
    path = Path.home() / ".codex" / "config.toml"
    section = f"[mcp_servers.{name}]"
    existing = path.read_text() if path.exists() else ""
    if section in existing:
        return
    url = f"http://{host}:{port}/mcp"
    block = (
        f"\n{section}\n" 'command = "npx"\n' f'args = ["-y", "mcp-remote", "{url}"]\n'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing + block)
    log.info("Wrote Codex MCP bridge for %s to %s", url, path)


def _open_in_terminal(command: list[str], cwd: str) -> bool:
    """Best-effort: open a new terminal window running ``command`` in ``cwd``."""
    joined = " ".join(shlex.quote(part) for part in command)

    def _spawn(argv: list[str], spawn_cwd: str | None = None) -> bool:
        try:
            subprocess.Popen(argv, cwd=spawn_cwd)
            return True
        except Exception:
            log.error("Failed to launch terminal: %s", argv, exc_info=True)
            return False

    if sys.platform == "darwin":
        script = (
            f'tell application "Terminal" to do script '
            f'"cd {shlex.quote(cwd)} && exec {joined}"'
        )
        return _spawn(["osascript", "-e", script])
    if os.name == "nt":
        if shutil.which("wt"):
            return _spawn(["wt", "-d", cwd, *command])
        return _spawn(["cmd", "/c", "start", "", "cmd", "/k", joined], spawn_cwd=cwd)
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        exe = shutil.which(term)
        if exe is None:
            continue
        if term == "gnome-terminal":
            return _spawn([exe, "--working-directory", cwd, "--", *command])
        return _spawn([exe, "-e", joined], spawn_cwd=cwd)
    log.error("No terminal emulator found; run '%s' in %s yourself", joined, cwd)
    return False


def launch_agent_in_terminal(
    agent: str, cwd: str, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> bool:
    """Wire the named agent's MCP config and launch it in a new terminal in ``cwd``."""
    command = _AGENT_COMMANDS.get(agent, [agent])
    if shutil.which(command[0]) is None:
        log.error("Agent %r not found on PATH; run it yourself in %s", agent, cwd)
        return False
    if agent == "codex":
        _write_codex_config(host, port)
    return _open_in_terminal(command, cwd)


def start_conductor(
    window: Any,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    config_path: str | Path | None = None,
    agent: str | None = None,
) -> tuple[threading.Thread, str]:
    """Wire and start the in-app Conductor MCP server for ``window``.

    Builds a ``CanvasController`` + ``MainThreadDispatcher``, serves the MCP tools
    over streamable-http in a daemon thread (which keeps them alive), and
    optionally writes an ``.mcp.json`` so a client auto-connects. When ``agent``
    is given (e.g. ``"claude"`` / ``"codex"``), it is launched in a new terminal
    in the config directory. Returns the server thread and its URL.
    """
    controller = CanvasController(window)
    dispatcher = MainThreadDispatcher()
    mcp = build_conductor_mcp(controller, dispatcher, host=host, port=port)
    thread = serve_in_thread(mcp)
    url = f"http://{host}:{port}/mcp"
    cwd = os.getcwd()
    if config_path is not None:
        write_mcp_config(config_path, host=host, port=port)
        cwd = str(Path(config_path).resolve().parent)
        log.info("Conductor MCP server at %s (client config: %s)", url, config_path)
    else:
        log.info("Conductor MCP server at %s", url)
    if agent:
        launch_agent_in_terminal(agent, cwd, host=host, port=port)
    return thread, url
