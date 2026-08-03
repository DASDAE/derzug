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

import logging
import socket
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from mcp.server.fastmcp import FastMCP

from derzug.conductor.constants import DEFAULT_HOST, DEFAULT_PORT, SERVER_NAME
from derzug.conductor.controller import CanvasController
from derzug.conductor.dispatch import MainThreadDispatcher
from derzug.version import __version__

log = logging.getLogger(__name__)


def build_conductor_mcp(
    controller: CanvasController,
    dispatcher: MainThreadDispatcher,
    runtime_info: Callable[[], dict[str, Any]] | None = None,
) -> FastMCP:
    """Return a FastMCP server whose tools drive ``controller`` on the main thread.

    ``runtime_info`` late-binds facts that only exist once the service runs
    (resolved port, server id); it feeds the ``/health`` endpoint used by
    discovery.
    """
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

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Any) -> Any:
        """Answer discovery probes so stale registry records can be pruned."""
        from starlette.responses import JSONResponse

        info = {} if runtime_info is None else runtime_info()
        return JSONResponse(
            {
                "status": "healthy",
                "server": SERVER_NAME,
                "version": __version__,
                **info,
            }
        )

    return mcp


class ConductorService:
    """Owns the Conductor MCP server lifecycle: bind, serve, readiness, stop.

    ``launch`` pre-binds the listening socket on the calling thread — a port
    conflict raises immediately instead of dying silently inside a worker —
    then serves the streamable-http app on a background uvicorn server and
    returns at once; callers poll ``status`` for readiness. ``request_stop``
    halts the dispatcher (releasing any in-flight marshalled calls) and
    signals uvicorn to exit without blocking; ``is_stopped`` reports thread
    exit. The blocking ``start``/``stop`` pair remains for non-GUI callers
    (tests, teardown) that can afford to wait.
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
        self._sock: socket.socket | None = None
        self.server_id = uuid.uuid4().hex[:12]

    @property
    def host(self) -> str:
        """The interface the server binds (loopback by default)."""
        return self._host

    @property
    def port(self) -> int:
        """The bound port (resolved after ``launch`` when constructed with 0)."""
        return self._port

    @property
    def url(self) -> str:
        """The server's MCP endpoint URL."""
        return f"http://{self._host}:{self._port}/mcp"

    def launch(self) -> None:
        """Bind the port and serve in a background thread; return immediately.

        Raises ``OSError`` when the port is already taken. Poll ``status`` for
        readiness (``"running"``) or startup failure (``"exited"``).
        """
        import uvicorn

        from starlette.middleware.trustedhost import TrustedHostMiddleware

        if self._thread is not None:
            raise RuntimeError("Conductor MCP server already launched")
        sock = socket.create_server((self._host, self._port))
        try:
            self._port = sock.getsockname()[1]  # resolves an ephemeral port (0)
            app = self._mcp.streamable_http_app()
            # Loopback binding does not stop a hostile web page from steering a
            # browser at this port via DNS rebinding; validating Host does.
            app.add_middleware(
                TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"]
            )
            config = uvicorn.Config(
                app,
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
        except BaseException:
            self._server = None
            self._thread = None
            sock.close()
            raise
        self._sock = sock

    def status(self) -> str:
        """One of ``"idle"``, ``"starting"``, ``"running"``, or ``"exited"``."""
        thread = self._thread
        if thread is None:
            return "idle"
        server = self._server
        if server is not None and server.started and thread.is_alive():
            return "running"
        if not thread.is_alive():
            return "exited"
        return "starting"

    def request_stop(self) -> None:
        """Signal shutdown without blocking; poll ``is_stopped`` for completion."""
        if self._dispatcher is not None:
            self._dispatcher.stop()
        if self._server is not None:
            self._server.should_exit = True

    def is_stopped(self) -> bool:
        """Whether the server thread has exited (or never ran)."""
        return self._thread is None or not self._thread.is_alive()

    def start(self, timeout: float = 15.0) -> str:
        """Launch and block until ready; return the URL.

        A blocking convenience for callers off the GUI thread. Raises
        ``OSError`` when the port is already taken and ``RuntimeError`` when
        the server exits or is not ready within ``timeout`` seconds.
        """
        self.launch()
        deadline = time.monotonic() + timeout
        try:
            while (status := self.status()) != "running":
                if status == "exited":
                    raise RuntimeError("Conductor MCP server exited during startup")
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"Conductor MCP server not ready after {timeout:.0f}s"
                    )
                time.sleep(0.05)
        except BaseException:
            self.stop()
            raise
        log.info("Conductor MCP server ready at %s", self.url)
        return self.url

    def stop(self, timeout: float = 5.0) -> None:
        """Shut down: stop the dispatcher, signal uvicorn to exit, join the thread."""
        self.request_stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("Conductor MCP server thread did not stop cleanly")
        if self._sock is not None and self.is_stopped():
            with suppress(OSError):
                self._sock.close()
        self._sock = None
        self._server = None
        self._thread = None


def create_service(
    window: Any,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    allow_code: bool = False,
) -> ConductorService:
    """Wire an unstarted Conductor service for ``window``.

    Builds a fresh ``CanvasController`` + ``MainThreadDispatcher`` per service
    (the dispatcher's stop latch is one-way, so a service is never reused
    across starts). The caller owns the returned service: ``launch`` it, poll
    ``status``, and ``stop`` it on teardown.
    """
    controller = CanvasController(window, allow_code=allow_code)
    dispatcher = MainThreadDispatcher()
    holder: dict[str, Any] = {}

    def runtime_info() -> dict[str, Any]:
        service = holder.get("service")
        if service is None:
            return {}
        return {
            "server_id": service.server_id,
            "mcp_url": service.url,
            "allow_code": allow_code,
        }

    mcp = build_conductor_mcp(controller, dispatcher, runtime_info=runtime_info)
    service = ConductorService(mcp, host=host, port=port, dispatcher=dispatcher)
    holder["service"] = service
    return service
