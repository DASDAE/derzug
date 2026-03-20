"""Pytest configuration for DerZug."""

from __future__ import annotations

import os
import sys
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pytest

_QT_NOISY_PLUGIN_MESSAGES = {
    "This plugin does not support propagateSizeHints()",
    "This plugin does not support raise()",
    "This plugin does not support grabbing the keyboard",
}


def _show_mode_requested(argv: list[str]) -> bool:
    """Return True when pytest was invoked to run interactive show tests."""
    if "--show" in argv:
        return True

    for index, arg in enumerate(argv):
        if arg == "-m" and index + 1 < len(argv) and "show" in argv[index + 1]:
            return True
        if arg.startswith("-m") and len(arg) > 2 and "show" in arg[2:]:
            return True
    return False


def _should_suppress_qt_message(message: str) -> bool:
    """Return True for known offscreen Qt platform-plugin noise."""
    return message in _QT_NOISY_PLUGIN_MESSAGES


def _install_headless_qt_message_filter() -> None:
    """Suppress known offscreen Qt plugin chatter in normal headless test runs."""
    from AnyQt.QtCore import QtMsgType, qInstallMessageHandler

    global _PREV_QT_MESSAGE_HANDLER
    if _PREV_QT_MESSAGE_HANDLER is not None:
        return

    previous = qInstallMessageHandler(None)

    def _handler(msg_type, context, message) -> None:
        if msg_type in (
            QtMsgType.QtWarningMsg,
            QtMsgType.QtInfoMsg,
        ) and _should_suppress_qt_message(message):
            return
        if previous is not None:
            previous(msg_type, context, message)

    _PREV_QT_MESSAGE_HANDLER = previous
    qInstallMessageHandler(_handler)


def _restore_qt_message_filter() -> None:
    """Restore the prior Qt message handler after tests finish."""
    from AnyQt.QtCore import qInstallMessageHandler

    global _PREV_QT_MESSAGE_HANDLER
    if _PREV_QT_MESSAGE_HANDLER is None:
        return
    qInstallMessageHandler(_PREV_QT_MESSAGE_HANDLER)
    _PREV_QT_MESSAGE_HANDLER = None


def pytest_addoption(parser):
    """Register custom pytest CLI options for DerZug tests."""
    parser.addoption(
        "--show",
        action="store_true",
        default=False,
        help="Run tests marked 'show' (GUI-visible tests).",
    )


def pytest_configure(config):
    """Initialize shared Qt state for tests."""
    config.addinivalue_line(
        "markers",
        "show: GUI-visible tests; skipped by default unless --show or -m show is used.",
    )
    config.addinivalue_line(
        "markers",
        "integration: widget-pipeline integration tests.",
    )
    from AnyQt.QtWidgets import QApplication

    # Ensure a QApplication exists before Orange's WidgetTest setUpClass runs.
    # Otherwise WidgetTest creates one with "-widgetcount", which emits:
    # "Widgets left: ... Max widgets: ..."
    global _TEST_QAPP
    _TEST_QAPP = QApplication.instance() or QApplication(["-"])
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and not _show_mode_requested(
        sys.argv
    ):
        _install_headless_qt_message_filter()


def pytest_collection_modifyitems(config, items):
    """Apply skip policy for tests marked as 'show'."""
    wants_show_only = "show" in (config.option.markexpr or "")
    show_enabled = config.getoption("--show")

    skip_show = pytest.mark.skip(
        reason="Skipping 'show' test by default. Use --show or -m show."
    )
    skip_non_show = pytest.mark.skip(
        reason="Skipping non-'show' test because -m show is active."
    )

    for item in items:
        is_show = item.get_closest_marker("show") is not None
        if wants_show_only and not is_show:
            item.add_marker(skip_non_show)
        elif not show_enabled and not wants_show_only and is_show:
            item.add_marker(skip_show)


# Apply filters now so they cover warnings emitted during the imports below,
# which happen before pytest calls pytest_configure.
warnings.filterwarnings("always", module=r"^derzug")
warnings.filterwarnings("ignore")

# Default to an offscreen Qt backend so normal pytest runs work headlessly.
# When show tests are requested, leave the platform unset so Qt can create
# real windows on the user's desktop.
if not _show_mode_requested(sys.argv):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Force AnyQt to use PyQt6 in tests.
os.environ.setdefault("QT_API", "pyqt6")

from AnyQt.QtCore import QCoreApplication  # noqa
import dascore.core.attrs as _dascore_attrs  # noqa
from derzug.views.orange import DerZugMain  # noqa
from derzug.widgets.spool import Spool  # noqa
from orangecanvas.application.outputview import TerminalTextDocument  # noqa

if not hasattr(_dascore_attrs, "Mapping"):
    _dascore_attrs.Mapping = Mapping

_PREV_BREAKPOINTHOOK: Callable[..., Any] | None = None
_PREV_QT_MESSAGE_HANDLER: Callable[..., Any] | None = None
_TEST_QAPP: Any | None = None


@pytest.fixture(scope="session", autouse=True)
def _warning_filters() -> None:
    """Filter warnings for the entire test session."""
    # Show any warning whose source module is inside the derzug package.
    warnings.filterwarnings("always", module=r"^derzug")
    # Suppress everything else (Qt, Orange, scipy, etc.).
    warnings.filterwarnings("ignore")
    yield
    _restore_qt_message_filter()


@dataclass
class DerZugAppContext:
    """Container for a fully initialized DerZug test app."""

    main: DerZugMain
    window: Any


@pytest.fixture()
def derzug_app(qapp, tmp_path_factory) -> DerZugAppContext:
    """
    Build a fully initialized DerZug app context for GUI tests.

    The fixture reuses pytest-qt's existing QApplication (`qapp`) and sets up
    config, widget discovery, and the main window for interaction tests.
    """
    main = DerZugMain()
    # Keep Orange cache writes inside a sandbox-writable location.
    cache_home = tmp_path_factory.mktemp("derzug-app-cache")
    data_home = tmp_path_factory.mktemp("derzug-app-data")
    os.environ["XDG_CACHE_HOME"] = str(cache_home)
    os.environ["XDG_DATA_HOME"] = str(data_home)
    main.parse_arguments(
        [sys.argv[0], "--no-splash", "--no-welcome", "--force-discovery"]
    )
    main.activate_default_config()
    main.application = qapp
    main.output = TerminalTextDocument()
    main.registry = main.run_discovery()
    window = main.setup_main_window()

    # Keep fixture setup headless-safe; tests can show explicitly when needed.
    qapp.processEvents()
    yield DerZugAppContext(main=main, window=window)

    # Clean up UI state.
    window.hide()
    window.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents()
