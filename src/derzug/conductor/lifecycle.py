"""Asynchronous, GUI-side orchestration of the Conductor server lifecycle.

Owns a ``ConductorService`` and polls its state transitions from a ``QTimer``
so the Qt main thread never blocks on a server start (readiness wait) or stop
(thread join); outcomes are reported through Qt signals. The optional ``mcp``
dependency is imported only inside ``request_start``, so this module is safe
to import whether or not the extra is installed.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from AnyQt.QtCore import QObject, QTimer, Signal

from derzug.conductor.client_config import write_mcp_config

log = logging.getLogger(__name__)

#: Poll cadence for service state transitions (matches the dispatcher slice).
_POLL_INTERVAL_MS = 50
#: Longest wait for the server to report ready before the start fails.
START_TIMEOUT = 15.0
#: Longest wait for the server thread to exit before the stop fails.
STOP_TIMEOUT = 5.0


class ConductorLifecycle(QObject):
    """Start and stop the Conductor service without blocking the GUI thread."""

    started = Signal(str)
    start_failed = Signal(str)
    stopped = Signal()
    stop_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service: Any | None = None
        self._phase = "idle"  # idle | starting | running | stopping
        self._deadline = 0.0
        self._config_dir: Path | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def service(self) -> Any | None:
        """The owned service, if any (starting, running, or stop-failed)."""
        return self._service

    @property
    def phase(self) -> str:
        """One of ``"idle"``, ``"starting"``, ``"running"``, ``"stopping"``."""
        return self._phase

    @property
    def url(self) -> str | None:
        """The ready server's MCP endpoint URL."""
        if self._service is None or self._phase != "running":
            return None
        return self._service.url

    @property
    def agent_cwd(self) -> str | None:
        """The directory agents launch from (where the client config lives)."""
        return None if self._config_dir is None else str(self._config_dir)

    def request_start(
        self,
        window: Any,
        *,
        port: int,
        allow_code: bool,
        config_dir: str | Path,
    ) -> None:
        """Launch the service and poll for readiness in the background.

        Import and bind errors raise synchronously — a missing optional
        dependency or a taken port fails fast on the calling thread — and
        everything later is reported through ``started``/``start_failed``.
        """
        from derzug.conductor.mcp_server import create_service

        if self._service is not None:
            return
        service = create_service(window, port=port, allow_code=allow_code)
        service.launch()
        self._service = service
        self._config_dir = Path(config_dir)
        self._phase = "starting"
        self._deadline = time.monotonic() + START_TIMEOUT
        self._timer.start()

    def request_stop(self) -> None:
        """Ask the running service to shut down and poll for completion."""
        if self._service is None or self._phase != "running":
            return
        self._phase = "stopping"
        self._service.request_stop()
        self._deadline = time.monotonic() + STOP_TIMEOUT
        self._timer.start()

    def shutdown(self) -> None:
        """Stop synchronously (bounded) for application or window teardown."""
        self._timer.stop()
        service = self._service
        self._service = None
        self._config_dir = None
        self._phase = "idle"
        if service is None:
            return
        try:
            service.stop()
        except Exception:
            log.error("Failed to stop the Conductor MCP server", exc_info=True)

    def _tick(self) -> None:
        """Advance whichever transition is in flight."""
        if self._phase == "starting":
            self._tick_starting()
        elif self._phase == "stopping":
            self._tick_stopping()
        else:
            self._timer.stop()

    def _tick_starting(self) -> None:
        service = self._service
        status = service.status()
        if status == "running":
            self._timer.stop()
            try:
                self._finish_start(service)
            except Exception as exc:
                log.error("Conductor post-start setup failed", exc_info=True)
                self._discard_service()
                self.start_failed.emit(str(exc) or type(exc).__name__)
                return
            self._phase = "running"
            self.started.emit(service.url)
            return
        if status == "exited":
            self._timer.stop()
            self._discard_service()
            self.start_failed.emit("The Conductor server exited during startup.")
            return
        if time.monotonic() > self._deadline:
            self._timer.stop()
            self._discard_service()
            self.start_failed.emit(
                f"The Conductor server was not ready after {START_TIMEOUT:.0f} seconds."
            )

    def _tick_stopping(self) -> None:
        service = self._service
        if service.is_stopped():
            self._timer.stop()
            service.stop()  # finalize: joins the dead thread, releases the socket
            self._service = None
            self._config_dir = None
            self._phase = "idle"
            self.stopped.emit()
            return
        if time.monotonic() > self._deadline:
            self._timer.stop()
            # The port may still be bound, so keep the service to retry a stop
            # rather than letting a restart race the old server for it.
            self._phase = "running"
            self.stop_failed.emit(
                f"The Conductor server did not stop within {STOP_TIMEOUT:.0f} "
                "seconds; it may still hold its port. Stopping can be retried."
            )

    def _finish_start(self, service: Any) -> None:
        """Run the post-ready side effects (client config for agents)."""
        config_path = self._config_dir / ".mcp.json"
        write_mcp_config(config_path, host=service.host, port=service.port)
        log.info("Conductor client config written to %s", config_path)

    def _discard_service(self) -> None:
        """Drop a service that failed to become ready, stopping its remains."""
        service = self._service
        self._service = None
        self._config_dir = None
        self._phase = "idle"
        try:
            service.stop()
        except Exception:
            log.error("Failed to stop the Conductor MCP server", exc_info=True)


__all__ = ("START_TIMEOUT", "STOP_TIMEOUT", "ConductorLifecycle")
