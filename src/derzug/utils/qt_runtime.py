"""Shared Qt application runtime helpers."""

from __future__ import annotations

import signal
from contextlib import suppress

from AnyQt.QtCore import QTimer
from AnyQt.QtWidgets import QApplication


def _quit_application(app: QApplication) -> None:
    """Close DerZug windows and stop the Qt event loop."""
    with suppress(RuntimeError):
        app.closeAllWindows()
    with suppress(RuntimeError):
        app.quit()


def install_sigint_handler(
    app: QApplication | None = None,
    *,
    interval_ms: int = 100,
) -> QApplication | None:
    """Install Ctrl+C support for a Qt application."""
    app = app or QApplication.instance()
    if app is None:
        return None
    if bool(getattr(app, "_derzug_sigint_installed", False)):
        return app

    def _handle_sigint(_signum, _frame) -> None:
        QTimer.singleShot(0, lambda: _quit_application(app))

    signal.signal(signal.SIGINT, _handle_sigint)

    timer = QTimer(app)
    timer.setInterval(interval_ms)
    timer.timeout.connect(lambda: None)
    timer.start()

    app._derzug_sigint_timer = timer
    app._derzug_sigint_installed = True
    return app
