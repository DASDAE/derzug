"""Configuration for the Qt benchmark suite.

The whole tree is skipped when no usable Qt stack is installed, and Qt is
forced offscreen before anything imports it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from importlib.util import find_spec

import pytest

# Must be set before the first Qt import: AnyQt resolves QT_API at import time
# and Qt reads QT_QPA_PLATFORM when the QGuiApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyqt6")


def _has_qt_stack() -> bool:
    """Return True when a Qt binding, AnyQt, pyqtgraph, and Orange are present."""
    try:
        binding = any(
            find_spec(name) is not None for name in ("PyQt6", "PyQt5", "PySide6")
        )
        shims = all(
            find_spec(name) is not None for name in ("AnyQt", "pyqtgraph", "Orange")
        )
    except (ImportError, ValueError):
        return False
    return binding and shims


HAS_QT = _has_qt_stack()

# Skipping at collection time is what keeps the modules from being imported at
# all. A module-level skip would still execute their top-level Qt imports.
collect_ignore_glob = [] if HAS_QT else ["test_*.py"]


@pytest.fixture(scope="session")
def qapp():
    """Return the one process-wide offscreen QApplication.

    A missing platform plugin (no libEGL/libGL, for instance) is treated as a
    skip rather than a failure, so the suite degrades the same way a missing
    binding does.
    """
    try:
        from AnyQt.QtWidgets import QApplication
    except ImportError as error:  # pragma: no cover - guarded by collect_ignore
        pytest.skip(f"Qt is not importable: {error}")

    app = QApplication.instance()
    if app is None:
        try:
            app = QApplication(["-"])
        except Exception as error:  # pragma: no cover - platform dependent
            pytest.skip(f"could not create a QApplication: {error}")

    # PyQt destroys wrapped C++ objects at interpreter exit; if any top-level
    # Qt object outlives the QApplication that teardown segfaults. This mirrors
    # the same guard in tests/conftest.py.
    try:
        from PyQt6 import sip

        sip.setdestroyonexit(False)
    except Exception:  # pragma: no cover - binding dependent
        pass

    # No quit()/deleteLater(): final C++ cleanup is left to process teardown.
    return app


@pytest.fixture(scope="module")
def patch_small():
    """Return a 300x2000 example patch."""
    import dascore as dc

    return dc.get_example_patch("random_das", shape=(300, 2000))


@pytest.fixture(scope="module")
def patch_large():
    """Return a 1000x5000 example patch."""
    import dascore as dc

    return dc.get_example_patch("random_das", shape=(1000, 5000))


@pytest.fixture(scope="module")
def patch_large_copy(patch_large):
    """Return a distinct patch object holding identical data.

    Used to exercise the equality comparison in
    ``Waterfall._should_reset_view_for_new_patch``, which short-circuits on
    object identity.
    """
    return patch_large.new(data=patch_large.data.copy())


@pytest.fixture(scope="module")
def waterfall_widget(qapp) -> Iterator:
    """Yield one shown, offscreen Waterfall reused by every benchmark here.

    Construction and teardown stay outside the timed region. The widget must
    be shown: ``ZugWidget._request_ui_refresh`` is a no-op while the window is
    hidden, so a hidden widget never enters the render path at all.
    """
    from derzug.utils.testing import widget_context
    from derzug.widgets.waterfall import Waterfall

    with widget_context(Waterfall) as widget:
        widget.resize(800, 600)
        widget.show()
        qapp.processEvents()
        yield widget
        widget.hide()


@pytest.fixture(scope="module")
def wiggle_widget(qapp) -> Iterator:
    """Yield one shown, offscreen Wiggle reused by every benchmark here."""
    from derzug.utils.testing import widget_context
    from derzug.widgets.wiggle import Wiggle

    with widget_context(Wiggle) as widget:
        widget.resize(800, 600)
        widget.show()
        qapp.processEvents()
        yield widget
        widget.hide()
