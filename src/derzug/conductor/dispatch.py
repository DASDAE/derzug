"""Marshal Conductor calls onto the Qt main thread.

``CanvasController`` must run on the Qt main thread (it touches the live scheme
and widgets), but the transport that drives it (the MCP server) runs off-thread.
``MainThreadDispatcher.run`` executes a callable on the main thread and blocks
the calling thread until it returns a result or raises — the inverse of the
worker-to-main marshalling in ``core/widget_runtime.py``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from AnyQt.QtCore import QObject, Qt, QThread, Signal
from AnyQt.QtWidgets import QApplication


class MainThreadDispatcher(QObject):
    """Run callables on the Qt main thread from any thread, blocking for result."""

    #: Carries a zero-arg callable to invoke on the main thread.
    _invoke = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())
        self._invoke.connect(self._run_on_main, Qt.QueuedConnection)

    @staticmethod
    def _run_on_main(func: Callable[[], None]) -> None:
        func()

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute ``func(*args, **kwargs)`` on the main thread; block for result.

        Runs directly when already on the main thread (so it never deadlocks on
        itself). Exceptions raised by ``func`` are re-raised on the caller.
        """
        app = QApplication.instance()
        if app is None or QThread.currentThread() is app.thread():
            return func(*args, **kwargs)

        outcome: dict[str, Any] = {}
        done = threading.Event()

        def _call() -> None:
            try:
                outcome["value"] = func(*args, **kwargs)
            except BaseException as exc:  # - re-raised on the caller
                outcome["error"] = exc
            finally:
                done.set()

        self._invoke.emit(_call)
        done.wait()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]
