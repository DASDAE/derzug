"""In-app MCP server exposing the Conductor over localhost.

Builds a FastMCP server whose tools drive a live ``CanvasController``. Every tool
marshals its call onto the Qt main thread via a ``MainThreadDispatcher``, so an
external agent client (e.g. Claude Code) can observe and drive the running canvas
over a localhost transport while DerZug's UI stays responsive.

``ConductorService`` owns the server lifecycle: it pre-binds the port (so a
conflict fails fast and loudly), serves in a background thread, reports
readiness, and shuts down cleanly on application teardown.

Trust model: the server binds loopback only and carries no authentication —
any local process may connect, so local clients are trusted by design. The
``Code`` widget (arbitrary Python via parameters) is additionally excluded from
the agent surface unless the user opts in with ``--conductor-allow-code``.

Requires the optional ``mcp`` dependency: ``pip install 'derzug[conductor]'``.
This module is imported only when the Conductor server is started, so the core
app never depends on ``mcp``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from derzug.conductor.controller import CanvasController
from derzug.conductor.dispatch import MainThreadDispatcher
from derzug.conductor.launch import SERVER_NAME, launch_agent_in_terminal

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4319


def build_conductor_mcp(
    controller: CanvasController, dispatcher: MainThreadDispatcher
) -> FastMCP:
    """Return a FastMCP server whose tools drive ``controller`` on the main thread."""
    mcp = FastMCP(
        "DerZug Conductor",
        instructions=(
            "Drive a live DerZug DAS (distributed acoustic sensing) workflow "
            "canvas of connected widget nodes.\n\n"
            "COMMON RECIPE (view data): add_node('Spool') -> "
            "set_params(spool_id, {'spool_input': 'example_event_1'}) -> "
            "add_node('Waterfall') -> connect(spool_id, waterfall_id) -> "
            "run(spool_id) -> wait_for_idle().\n\n"
            "CONVENTIONS:\n"
            "- Almost every node has one input port 'Patch' and one output port "
            "'Patch'; connect(source_id, sink_id) defaults to them, so you rarely "
            "need port names.\n"
            "- Omit x/y on add_node; nodes auto-place in a tidy left-to-right "
            "row.\n"
            "- set_params/set_view take PARTIAL updates, are validated against the "
            "node's schema, and return the prior value. They do NOT re-run the "
            "node by default: assemble and configure the graph first, then call "
            "run(source_id) once and wait_for_idle().\n"
            "- run() only schedules execution; wait_for_idle() blocks until no "
            "node is busy (each node also reports a 'busy' flag).\n"
            "- Structural edits (add/remove/connect) are undoable in the app "
            "(Ctrl+Z).\n"
            "- show_node pops up a node's widget window to display results.\n\n"
            "DISCOVERY: list_widget_types = the catalog with each type's "
            "params/view schema; get_canvas_state = the current graph; "
            "describe_node = one node's detail incl. its output patch shape.\n\n"
            "COMMON NODE TYPES: Spool (source; loads data/examples), Filter "
            "(bandpass etc.), Waterfall (2D image view), Wiggle (trace view), "
            "Detrend, Taper, Resample, Select, Aggregate. See list_widget_types "
            "for the full set and parameters."
        ),
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
        node_id: str, params: dict[str, Any], run: bool = False
    ) -> dict[str, Any]:
        """Apply a partial params update to a node; returns its prior params.

        Does not re-run the node unless ``run=True``: configure the graph fully,
        then call the ``run`` tool once and ``wait_for_idle``.
        """
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
    def connect(
        source_id: str,
        sink_id: str,
        source_port: str = "Patch",
        sink_port: str = "Patch",
    ) -> None:
        """Link source -> sink. Ports default to 'Patch' (the common case). Undoable."""
        call(controller.connect, source_id, source_port, sink_id, sink_port)

    @mcp.tool()
    def disconnect(
        source_id: str,
        sink_id: str,
        source_port: str = "Patch",
        sink_port: str = "Patch",
    ) -> None:
        """Remove the matching link (ports default to 'Patch'). Undoable."""
        call(controller.disconnect, source_id, source_port, sink_id, sink_port)

    @mcp.tool()
    def run(node_id: str) -> None:
        """Schedule a node re-run (async); follow with wait_for_idle to await it."""
        call(controller.run, node_id)

    @mcp.tool()
    def wait_for_idle(timeout_seconds: float = 30.0) -> dict[str, Any]:
        """Block until no node is executing; reports still-busy nodes on timeout.

        Polls from the server thread (brief main-thread hops), so the UI stays
        responsive while waiting.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            busy = call(controller.busy_nodes)
            if not busy:
                return {"idle": True, "busy_nodes": []}
            if time.monotonic() > deadline:
                return {"idle": False, "busy_nodes": busy}
            time.sleep(0.1)

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


class ConductorService:
    """Owns the Conductor MCP server lifecycle: bind, serve, readiness, stop.

    ``start`` pre-binds the listening socket on the calling thread — a port
    conflict raises immediately instead of dying silently inside a worker —
    then serves the streamable-http app on a background uvicorn server and
    blocks until it reports ready (or raises on startup failure). ``stop``
    halts the dispatcher (releasing any in-flight marshalled calls), signals
    uvicorn to exit, and joins the thread.
    """

    def __init__(
        self,
        mcp: FastMCP,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        dispatcher: MainThreadDispatcher | None = None,
    ) -> None:
        self._mcp = mcp
        self._host = host
        self._port = port
        self._dispatcher = dispatcher
        self._server: Any | None = None
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        """The interface the server binds (loopback by default)."""
        return self._host

    @property
    def port(self) -> int:
        """The bound port (resolved after ``start`` when constructed with 0)."""
        return self._port

    @property
    def url(self) -> str:
        """The server's MCP endpoint URL."""
        return f"http://{self._host}:{self._port}/mcp"

    def start(self, timeout: float = 15.0) -> str:
        """Bind, serve in a background thread, and wait for readiness; return URL.

        Raises ``OSError`` when the port is already taken and ``RuntimeError``
        when the server exits or is not ready within ``timeout`` seconds.
        """
        import uvicorn

        sock = socket.create_server((self._host, self._port))
        try:
            self._port = sock.getsockname()[1]  # resolves an ephemeral port (0)
            config = uvicorn.Config(
                self._mcp.streamable_http_app(),
                host=self._host,
                port=self._port,
                log_level="warning",
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(
                target=self._server.run,
                kwargs={"sockets": [sock]},
                name="conductor-mcp",
                daemon=True,
            )
            self._thread.start()
            deadline = time.monotonic() + timeout
            while not self._server.started:
                if not self._thread.is_alive():
                    raise RuntimeError("Conductor MCP server exited during startup")
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"Conductor MCP server not ready after {timeout:.0f}s"
                    )
                time.sleep(0.05)
        except BaseException:
            self.stop()
            sock.close()
            raise
        log.info("Conductor MCP server ready at %s", self.url)
        return self.url

    def stop(self, timeout: float = 5.0) -> None:
        """Shut down: stop the dispatcher, signal uvicorn to exit, join the thread."""
        if self._dispatcher is not None:
            self._dispatcher.stop()
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("Conductor MCP server thread did not stop cleanly")
        self._server = None
        self._thread = None


def write_mcp_config(
    path: str | Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    name: str = SERVER_NAME,
) -> str:
    """Merge our server entry into the MCP client config at ``path``; return URL.

    The file is an ``.mcp.json`` a client such as Claude Code picks up. An
    existing config keeps its other entries — only ``mcpServers[name]`` is
    replaced — and the file is written atomically (temp file + rename). An
    existing file that is not valid JSON is left untouched (logged), so a
    user's hand-edited config is never clobbered.
    """
    url = f"http://{host}:{port}/mcp"
    path = Path(path)
    config: dict[str, Any] = {}
    if path.exists():
        try:
            config = json.loads(path.read_text())
        except ValueError:
            log.error(
                "Existing %s is not valid JSON; leaving it untouched. "
                "Add the server yourself: %s",
                path,
                url,
            )
            return url
        if not isinstance(config, dict):
            config = {}
    servers = config.setdefault("mcpServers", {})
    servers[name] = {"type": "http", "url": url}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    os.replace(tmp, path)
    return url


def start_conductor(
    window: Any,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    config_path: str | Path | None = None,
    agent: str | None = None,
    allow_code: bool = False,
) -> ConductorService:
    """Wire and start the in-app Conductor MCP server for ``window``.

    Builds a ``CanvasController`` + ``MainThreadDispatcher``, starts a
    ``ConductorService`` and waits for readiness (raising on bind/startup
    failure). Only after the server is ready is the client config written and,
    when ``agent`` is given (e.g. ``"claude"`` / ``"codex"``), the agent
    launched in a new terminal in the config directory. The caller owns the
    returned service and should ``stop()`` it on application teardown.
    """
    controller = CanvasController(window, allow_code=allow_code)
    dispatcher = MainThreadDispatcher()
    mcp = build_conductor_mcp(controller, dispatcher)
    service = ConductorService(mcp, host=host, port=port, dispatcher=dispatcher)
    try:
        url = service.start()
        cwd = os.getcwd()
        if config_path is not None:
            write_mcp_config(config_path, host=service.host, port=service.port)
            cwd = str(Path(config_path).resolve().parent)
            log.info("Conductor client config written to %s", config_path)
        if agent:
            launch_agent_in_terminal(agent, cwd, url)
    except BaseException:
        service.stop()
        raise
    return service
