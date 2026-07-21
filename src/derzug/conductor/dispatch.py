"""Marshal Conductor calls onto the Qt main thread.

``CanvasController`` must run on the Qt main thread (it touches the live scheme
and widgets), but the transport that drives it (the MCP server) runs off-thread.
``MainThreadDispatcher.run`` executes a callable on the main thread and blocks
the calling thread until it returns a result or raises — the inverse of the
worker-to-main marshalling in ``core/widget_runtime.py``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from AnyQt.QtCore import QObject, Qt, QThread, Signal
from AnyQt.QtWidgets import QApplication

#: How long one marshalled call may wait to start on the main thread before
#: failing. Once execution starts it is allowed to finish: returning a timeout
#: while a mutating call is still running would make retries unsafe.
DEFAULT_CALL_TIMEOUT = 30.0

#: Poll interval while waiting on the main thread; keeps stop() responsive.
_WAIT_SLICE = 0.05


class MainThreadDispatcher(QObject):
    """Run callables on the Qt main thread from any thread, blocking for result."""

    #: Carries a zero-arg callable to invoke on the main thread.
    _invoke = Signal(object)

    def __init__(self, *, timeout: float = DEFAULT_CALL_TIMEOUT) -> None:
        super().__init__()
        self._timeout = timeout
        self._stopped = threading.Event()
        app = QApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())
        self._invoke.connect(self._run_on_main, Qt.QueuedConnection)

    @staticmethod
    def _run_on_main(func: Callable[[], None]) -> None:
        func()

    def stop(self) -> None:
        """Refuse new calls and release any caller waiting on the main thread.

        Called at application teardown, when the main thread may never service
        another queued invocation.
        """
        self._stopped.set()

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute ``func(*args, **kwargs)`` on the main thread; block for result.

        Runs directly when already on the main thread (so it never deadlocks on
        itself). Exceptions raised by ``func`` are re-raised on the caller.
        Raises ``RuntimeError`` once stopped and ``TimeoutError`` when the main
        thread does not service the call within the dispatcher's timeout.
        """
        if self._stopped.is_set():
            raise RuntimeError("dispatcher is stopped (application shutting down)")
        app = QApplication.instance()
        if app is None or QThread.currentThread() is app.thread():
            return func(*args, **kwargs)

        outcome: dict[str, Any] = {}
        done = threading.Event()
        state_lock = threading.Lock()
        started = False
        cancelled = False

        def _cancel_if_queued() -> bool:
            """Cancel an invocation that has not started; report whether it won."""
            nonlocal cancelled
            with state_lock:
                if started:
                    return False
                cancelled = True
                return True

        def _call() -> None:
            nonlocal started
            with state_lock:
                if cancelled:
                    done.set()
                    return
                started = True
            try:
                outcome["value"] = func(*args, **kwargs)
            except BaseException as exc:  # - re-raised on the caller
                outcome["error"] = exc
            finally:
                done.set()

        self._invoke.emit(_call)
        deadline = time.monotonic() + self._timeout
        while not done.wait(_WAIT_SLICE):
            if self._stopped.is_set() and _cancel_if_queued():
                raise RuntimeError(
                    "dispatcher stopped while waiting on the main thread"
                )
            if time.monotonic() > deadline and _cancel_if_queued():
                raise TimeoutError(
                    f"main thread did not service the call within "
                    f"{self._timeout:.0f}s (busy or blocked)"
                )
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]
