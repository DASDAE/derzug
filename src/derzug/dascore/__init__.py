"""Dascore namespace integrations for DerZug."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

from AnyQt.QtCore import QEvent, QEventLoop, QObject, QTimer, Qt
from AnyQt.QtWidgets import QApplication, QWidget
try:
    from dascore.utils.namespace import PatchNameSpace, SpoolNameSpace
except ModuleNotFoundError as exc:  # pragma: no cover - compatibility guard
    _NAMESPACE_IMPORT_ERROR = exc

    class PatchNameSpace:  # type: ignore[no-redef]
        """Fallback stub used when the installed dascore lacks namespaces."""

    class SpoolNameSpace:  # type: ignore[no-redef]
        """Fallback stub used when the installed dascore lacks namespaces."""

else:
    _NAMESPACE_IMPORT_ERROR = None

from orangecanvas.application.outputview import TerminalTextDocument

from derzug.utils.qt_runtime import install_sigint_handler

if TYPE_CHECKING:
    from derzug.views.orange import DerZugMainWindow
    from derzug.widgets.waterfall import Waterfall
    from derzug.widgets.wiggle import Wiggle

_APP: QApplication | None = None
_LIVE_WIDGETS: dict[int, QWidget] = {}


class _CloseEventFilter(QObject):
    """Quit an event loop when a widget is closed or hidden."""

    def __init__(self, loop: QEventLoop) -> None:
        super().__init__()
        self._loop = loop

    def eventFilter(self, _obj, event) -> bool:
        """Stop the loop once the widget begins closing."""
        if event.type() in (QEvent.Type.Close, QEvent.Type.Hide):
            QTimer.singleShot(0, self._loop.quit)
        return False


def _ensure_qapplication() -> QApplication:
    """Return the active QApplication, creating one if needed."""
    global _APP
    app = QApplication.instance()
    if app is not None:
        _APP = app
        install_sigint_handler(_APP)
        return app
    _APP = QApplication(["derzug"])
    install_sigint_handler(_APP)
    return _APP


def _track_widget(widget: QWidget) -> QWidget:
    """Keep launched widgets alive until Qt destroys them."""
    key = id(widget)
    widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _LIVE_WIDGETS[key] = widget
    widget.destroyed.connect(lambda *_args, key=key: _LIVE_WIDGETS.pop(key, None))
    return widget


def _collapse_control_area(widget: QWidget) -> None:
    """Collapse Orange's left control panel when launching standalone viewers."""
    set_visible = getattr(widget, "_OWBaseWidget__setControlAreaVisible", None)
    if callable(set_visible):
        set_visible(False)


def _block_until_closed(widget: QWidget) -> None:
    """Block until the launched widget is closed."""
    if not widget.isVisible():
        return
    loop = QEventLoop()
    event_filter = _CloseEventFilter(loop)
    destroyed = False

    def _mark_destroyed(*_args) -> None:
        nonlocal destroyed
        destroyed = True

    widget.installEventFilter(event_filter)
    widget.destroyed.connect(_mark_destroyed)
    widget.destroyed.connect(loop.quit)
    loop.exec()
    if destroyed:
        return
    try:
        widget.removeEventFilter(event_filter)
    except RuntimeError:
        # Qt may already have destroyed the underlying C++ widget by the time
        # the close loop returns.
        return


def _launch_patch_widget(
    widget_cls: type[QWidget],
    patch,
    *,
    show: bool,
) -> QWidget:
    """Instantiate a DerZug widget, load a patch, and optionally show it."""
    if _NAMESPACE_IMPORT_ERROR is not None:  # pragma: no cover - compatibility guard
        raise RuntimeError(
            "DerZug Patch namespaces require a dascore build with "
            "dascore.utils.namespace support."
        ) from _NAMESPACE_IMPORT_ERROR
    _ensure_qapplication()
    widget = _track_widget(widget_cls())
    _collapse_control_area(widget)
    widget.set_patch(patch)
    if show:
        widget.show()
        _block_until_closed(widget)
    return widget


def _get_canvas_spool_description(window):
    """Return the registered public Spool widget description."""
    registry = getattr(window, "widget_registry", None)
    if registry is None:
        raise RuntimeError("DerZug main window has no widget registry")
    for description in registry.widgets():
        if description.qualified_name == "derzug.widgets.spool.Spool":
            return description
    for description in registry.widgets():
        if description.name == "Spool":
            return description
    raise LookupError("Could not resolve Spool widget description from registry")


def _ensure_writable_xdg_dirs() -> None:
    """Point XDG cache/data homes at writable locations when needed."""
    for env_name, suffix in (
        ("XDG_CACHE_HOME", "derzug-cache"),
        ("XDG_DATA_HOME", "derzug-data"),
    ):
        current = os.environ.get(env_name)
        if current:
            try:
                os.makedirs(current, exist_ok=True)
                test_path = os.path.join(current, ".derzug-write-test")
                with open(test_path, "w", encoding="utf-8"):
                    pass
                os.remove(test_path)
                continue
            except OSError:
                pass
        os.environ[env_name] = tempfile.mkdtemp(prefix=f"{suffix}-")


def _create_main_window() -> DerZugMainWindow:
    """Create one configured DerZug main window without entering the app loop."""
    from derzug.views.orange import DerZugMain

    app = _ensure_qapplication()
    _ensure_writable_xdg_dirs()
    main = DerZugMain()
    main.parse_arguments(["derzug", "--no-splash", "--no-welcome", "--force-discovery"])
    main.activate_default_config()
    main.application = app
    main.output = TerminalTextDocument()
    main.registry = main.run_discovery()
    window = main.setup_main_window()
    window._derzug_main = main
    return window


def _seed_canvas_window(
    value,
    *,
    title: str = "Spool",
) -> DerZugMainWindow:
    """Create a new DerZug window seeded with one locked public Spool node."""
    from derzug.widgets.spool import Spool

    window = _track_widget(_create_main_window())
    scheme = window.current_document().scheme()
    for node in list(scheme.nodes):
        scheme.remove_node(node)

    description = _get_canvas_spool_description(window)
    node = scheme.new_node(description, title=title, position=(0, 0))
    widget = scheme.widget_for_node(node)
    if not isinstance(widget, Spool):
        raise TypeError("failed to create canvas spool widget")
    widget.set_canvas_source(value)
    return window


def _launch_canvas_window(
    value,
    *,
    show: bool,
) -> DerZugMainWindow:
    """Launch one DerZug canvas session seeded from a patch or spool."""
    if _NAMESPACE_IMPORT_ERROR is not None:  # pragma: no cover - compatibility guard
        raise RuntimeError(
            "DerZug Patch/Spool namespaces require a dascore build with "
            "dascore.utils.namespace support."
        ) from _NAMESPACE_IMPORT_ERROR
    window = _seed_canvas_window(value)
    if show:
        window.show()
        _block_until_closed(window)
    return window


class ZugPatchNameSpace(PatchNameSpace):
    """Patch namespace for launching DerZug viewers."""

    name = "zug"

    def waterfall(self, *, show: bool = True) -> Waterfall:
        """Launch the DerZug waterfall viewer for this patch."""
        from derzug.widgets.waterfall import Waterfall

        return _launch_patch_widget(Waterfall, self, show=show)

    def wiggle(self, *, show: bool = True) -> Wiggle:
        """Launch the DerZug wiggle viewer for this patch."""
        from derzug.widgets.wiggle import Wiggle

        return _launch_patch_widget(Wiggle, self, show=show)

    def canvas(self, *, show: bool = True) -> DerZugMainWindow:
        """Launch the full DerZug canvas seeded with this patch."""
        return _launch_canvas_window(self, show=show)


class ZugSpoolNameSpace(SpoolNameSpace):
    """Spool namespace for launching the DerZug canvas."""

    name = "zug"

    def canvas(self, *, show: bool = True) -> DerZugMainWindow:
        """Launch the full DerZug canvas seeded with this spool."""
        return _launch_canvas_window(self, show=show)


__all__ = [
    "ZugPatchNameSpace",
    "ZugSpoolNameSpace",
]
