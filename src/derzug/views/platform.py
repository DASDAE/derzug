"""Platform integration and process-level setup for the DerZug canvas app.

These helpers are independent of the Orange main-window classes and have no
dependency on :mod:`derzug.views.orange`; that module imports and re-exports
them for the application startup path.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path

from AnyQt.QtGui import QOffscreenSurface, QOpenGLContext
from AnyQt.QtWidgets import QApplication
from orangecanvas.application.outputview import ExceptHook

from derzug.views.orange_errors import handle_derzug_exception


def install_derzug_exception_handler() -> None:
    """Route unhandled GUI exceptions to DerZug's custom dialog."""
    if not isinstance(sys.excepthook, ExceptHook):
        return
    with suppress((TypeError, RuntimeError)):
        sys.excepthook.handledException.disconnect()
    with suppress((TypeError, RuntimeError)):
        sys.excepthook.handledException.connect(handle_derzug_exception)


def _linux_desktop_entry_contents(exec_path: str, icon_path: str) -> str:
    """Return the desktop entry content installed for Linux launchers."""
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            "Name=DerZug",
            "GenericName=DAS Visualization",
            "Comment=Interactive DAS workflow visualization and review",
            f"Exec={exec_path} %f",
            f"Icon={icon_path}",
            "Terminal=false",
            "Categories=Science;Education;DataVisualization;Qt;",
            "Keywords=DAS;Distributed Acoustic Sensing;Visualization;Workflow;",
            "MimeType=application/x-derzug-workflow;",
            "StartupNotify=true",
            "StartupWMClass=derzug",
            "",
        ]
    )


def ensure_linux_desktop_entry() -> None:
    """Install/update a per-user desktop launcher on Linux."""
    if not sys.platform.startswith("linux"):
        return

    icon_path = (Path(__file__).parent.parent / "static" / "icon.png").resolve()
    exec_path = shutil.which("derzug")
    if exec_path is None:
        argv0 = Path(sys.argv[0]).expanduser()
        if argv0.is_absolute():
            exec_path = str(argv0.resolve())
        else:
            candidate = (Path.cwd() / argv0).resolve()
            exec_path = str(candidate)

    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    applications_dir = data_home / "applications"
    desktop_path = applications_dir / "derzug.desktop"
    content = _linux_desktop_entry_contents(exec_path, str(icon_path))

    with suppress(OSError):
        applications_dir.mkdir(parents=True, exist_ok=True)
        if (
            desktop_path.exists()
            and desktop_path.read_text(encoding="utf-8") == content
        ):
            return
        desktop_path.write_text(content, encoding="utf-8")


def configure_linux_desktop_integration(application: QApplication) -> None:
    """Expose the desktop file name so Linux docks can match the launcher."""
    if not sys.platform.startswith("linux"):
        return

    set_desktop_file_name = getattr(application, "setDesktopFileName", None)
    if set_desktop_file_name is None:
        return

    with suppress(Exception):
        set_desktop_file_name("derzug")


def configure_pyqtgraph_gpu_rendering() -> bool:
    """
    Enable OpenGL-backed pyqtgraph rendering when a context is available.

    Returns
    -------
    bool
        True when OpenGL rendering was enabled, otherwise False.
    """
    try:
        import pyqtgraph as pg
    except Exception:
        return False

    surface = None
    context = None
    has_gl = False
    try:
        surface = QOffscreenSurface()
        surface.create()
        if not surface.isValid():
            return False

        context = QOpenGLContext()
        if not context.create():
            return False

        has_gl = context.makeCurrent(surface)
    except Exception:
        has_gl = False
    finally:
        if context is not None:
            try:
                context.doneCurrent()
            except Exception:
                pass
        if surface is not None:
            try:
                surface.destroy()
            except Exception:
                pass

    try:
        pg.setConfigOptions(useOpenGL=bool(has_gl))
        return bool(pg.getConfigOption("useOpenGL"))
    except Exception:
        return False
