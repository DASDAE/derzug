"""
Custom modifications to Orange for DerZug.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from copy import deepcopy
from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_dist_version
from pathlib import Path
from typing import ClassVar
from xml.sax.saxutils import escape

from AnyQt.QtCore import QDir, QEvent, QObject, QPointF, Qt, QTimer, QUrl
from AnyQt.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QIcon,
    QOffscreenSurface,
    QOpenGLContext,
    QPen,
    QPixmap,
)
from AnyQt.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsRectItem,
    QGraphicsView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from Orange.canvas.__main__ import OMain
from Orange.canvas.config import Config as OrangeConfig
from Orange.canvas.mainwindow import MainWindow as OrangeMainWindow
from orangecanvas.application.outputview import ExceptHook
from orangecanvas.canvas.items.nodeitem import NodeItem
from orangecanvas.gui.windowlistmanager import WindowListManager
from orangecanvas.scheme import readwrite
from orangecanvas.utils.settings import QSettings
from orangewidget.workflow.errorreporting import (
    handle_exception as orange_handle_exception,
)
from orangewidget.workflow.widgetsscheme import (
    OWWidgetManager,
    Scheme,
    WidgetsScheme,
    WidgetsSignalManager,
)

import derzug._anyqt_patch  # noqa: F401 - imported for side effects before AnyQt.QtGui
from derzug.annotations_config import (
    AnnotationSettingsDialog,
    load_annotation_config,
    save_annotation_config,
)
from derzug.core.zugwidget import ZugWidget
from derzug.utils.misc import (
    load_example_workflow_entrypoints,
    load_widget_entrypoints,
)
from derzug.utils.qt_runtime import install_sigint_handler
from derzug.views.orange_errors import (
    DerZugErrorDialog,
    _build_exception_report_data,
    handle_derzug_exception,
)
from derzug.views.orange_registry import filter_registry_for_das
from derzug.widgets.composite import (
    NODE_ID_KEY,
    composite_payload_from_properties,
    composite_properties,
    composite_widget_description,
    ensure_composite_widget_class,
    ensure_node_id,
    get_internal_node_id,
    get_node_id,
)

__all__ = (
    "ActiveSourceManager",
    "DerZugConfig",
    "DerZugErrorDialog",
    "DerZugMain",
    "DerZugMainWindow",
    "_build_exception_report_data",
    "filter_registry_for_das",
    "handle_derzug_exception",
)

_APP_ACTIVE_SOURCE_MANAGER = None
_APP_ACTIVE_SOURCE_MAIN_WINDOW = None
_EXPERIMENTAL_WARNING_GROUP = "startup"
_EXPERIMENTAL_WARNING_HIDE_KEY = "hide-experimental-warning"

try:
    sip = import_module("PyQt6.sip")
except ModuleNotFoundError:
    sip = import_module("sip")


def _derzug_settings() -> QSettings:
    """Return a settings object scoped to DerZug's real app identity."""
    organization = getattr(DerZugConfig, "OrganizationName", None) or getattr(
        DerZugConfig, "OrganizationDomain", ""
    )
    return QSettings(
        QSettings.IniFormat,
        QSettings.UserScope,
        str(organization),
        DerZugConfig.ApplicationName,
    )


def _reserved_node_metadata(properties: object) -> dict[str, object]:
    """Return the reserved DerZug node metadata subset from one properties dict."""
    if not isinstance(properties, dict):
        return {}
    keys = {NODE_ID_KEY}
    return {key: deepcopy(properties[key]) for key in keys if key in properties}


def _port_name_specs(boundary_specs: list[dict[str, object]]) -> list[str]:
    """Return stable public port names for boundary endpoint specs."""
    raw_names = [str(spec["channel_name"]) for spec in boundary_specs]
    unique = len(set(raw_names)) == len(raw_names)
    if unique:
        return raw_names
    return [f"{spec['node_title']}: {spec['channel_name']}" for spec in boundary_specs]


class _CanvasCompositeController(QObject):
    """Implement composite group and ungroup actions on the canvas scene."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        document = main_window.current_document()
        document.scene().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle right-click group and ungroup actions for selected nodes."""
        document = self._main_window.current_document()
        if (
            obj is not document.scene()
            or event.type() != QEvent.GraphicsSceneContextMenu
        ):
            return False
        scene = document.scene()
        item = scene.item_at(event.scenePos(), NodeItem)
        if item is None:
            return False
        node = scene.node_for_item(item)
        menu = self.context_menu_for_node(node)
        if menu is not None:
            menu.popup(event.screenPos())
            event.accept()
            return True
        return False

    def context_menu_for_node(self, node):
        """Return the context menu for one clicked node, if any."""
        document = self._main_window.current_document()
        selected_nodes = list(document.selectedNodes())
        menu = None
        if (
            len(selected_nodes) == 1
            and selected_nodes[0] is node
            and self._is_composite_node(node)
        ):
            menu = QMenu(self._main_window)
            menu.addAction("Ungroup", lambda: self.ungroup_node(node))
        elif (
            len(selected_nodes) >= 2
            and node in selected_nodes
            and self._can_group(selected_nodes)
        ):
            menu = QMenu(self._main_window)
            menu.addAction("Group", lambda: self.group_nodes(selected_nodes))

        source_widget = self._source_widget_for_node(node)
        if source_widget is not None:
            if menu is None:
                menu = QMenu(self._main_window)
            menu.addAction(
                "Set Active Source",
                lambda: self._set_active_source_widget(source_widget),
            )
        return menu

    def _is_composite_node(self, node) -> bool:
        """Return True when the node stores one composite payload."""
        return composite_payload_from_properties(node.properties) is not None

    def _can_group(self, nodes: list[object]) -> bool:
        """Return True when the node selection can become one composite."""
        return all(not self._is_composite_node(node) for node in nodes)

    def _source_widget_for_node(self, node):
        """Return one source-capable widget for the given node, if available."""
        document = self._main_window.current_document()
        scheme = document.scheme()
        if scheme is None:
            return None
        widget = scheme.widget_for_node(node)
        if ActiveSourceManager._is_source_widget(widget):
            return widget
        return None

    def _set_active_source_widget(self, widget) -> None:
        """Promote the clicked source widget to the active source."""
        manager = self._main_window.active_source_manager
        if manager is None:
            return
        manager._set_active_widget(self._main_window, widget)

    def group_nodes(self, nodes: list[object]) -> object | None:
        """Replace a selected subgraph with one composite widget node."""
        if not self._can_group(nodes):
            return None
        document = self._main_window.current_document()
        scheme = document.scheme()
        selected = list(nodes)
        selected_set = set(selected)

        for node in selected:
            ensure_node_id(node)

        bounds = None
        scene = document.scene()
        for node in selected:
            rect = scene.item_for_node(node).sceneBoundingRect()
            bounds = rect if bounds is None else bounds.united(rect)
        if bounds is None:
            return None
        center = (float(bounds.center().x()), float(bounds.center().y()))

        incoming = []
        outgoing = []
        internal_links = []
        for link in tuple(scheme.links):
            source_inside = link.source_node in selected_set
            sink_inside = link.sink_node in selected_set
            if source_inside and sink_inside:
                internal_links.append(link)
            elif not source_inside and sink_inside:
                ensure_node_id(link.source_node)
                incoming.append(
                    {
                        "node_title": link.sink_node.title,
                        "channel_name": link.sink_channel.name,
                        "signal": link.sink_channel,
                        "internal_node_id": ensure_node_id(link.sink_node),
                        "internal_channel_name": link.sink_channel.name,
                        "external_node_id": get_node_id(link.source_node),
                        "external_channel_name": link.source_channel.name,
                    }
                )
            elif source_inside and not sink_inside:
                ensure_node_id(link.sink_node)
                outgoing.append(
                    {
                        "node_title": link.source_node.title,
                        "channel_name": link.source_channel.name,
                        "signal": link.source_channel,
                        "internal_node_id": ensure_node_id(link.source_node),
                        "internal_channel_name": link.source_channel.name,
                        "external_node_id": get_node_id(link.sink_node),
                        "external_channel_name": link.sink_channel.name,
                    }
                )

        incoming_by_endpoint: dict[tuple[str, str], dict[str, object]] = {}
        for spec in incoming:
            key = (spec["internal_node_id"], spec["internal_channel_name"])
            incoming_by_endpoint.setdefault(key, spec)
        outgoing_by_endpoint: dict[tuple[str, str], dict[str, object]] = {}
        for spec in outgoing:
            key = (spec["internal_node_id"], spec["internal_channel_name"])
            outgoing_by_endpoint.setdefault(key, spec)

        input_specs = list(incoming_by_endpoint.values())
        output_specs = list(outgoing_by_endpoint.values())
        for spec, port_name in zip(
            input_specs, _port_name_specs(input_specs), strict=True
        ):
            spec["port_name"] = port_name
        for spec, port_name in zip(
            output_specs, _port_name_specs(output_specs), strict=True
        ):
            spec["port_name"] = port_name

        internal_scheme = DerZugWidgetsScheme()
        internal_node_map = {}
        for node in selected:
            clone_properties = deepcopy(node.properties or {})
            clone_properties[NODE_ID_KEY] = get_node_id(node)
            clone_properties["__derzug_composite_internal_node_id"] = get_node_id(node)
            clone = internal_scheme.new_node(
                node.description,
                title=node.title,
                position=tuple(node.position),
                properties=clone_properties,
            )
            internal_node_map[node] = clone
        for link in internal_links:
            internal_scheme.new_link(
                internal_node_map[link.source_node],
                internal_node_map[link.source_node].output_channel(
                    link.source_channel.name
                ),
                internal_node_map[link.sink_node],
                internal_node_map[link.sink_node].input_channel(link.sink_channel.name),
            )

        buffer = io.BytesIO()
        readwrite.scheme_to_ows_stream(
            internal_scheme,
            buffer,
            pretty=True,
            pickle_fallback=True,
        )
        composite_id = f"{ensure_node_id(selected[0])}_{len(scheme.nodes)}"
        payload = {
            "version": 1,
            "composite_id": composite_id,
            "display_name": "Composite",
            "summary": f"{len(selected)} widgets grouped into one composite.",
            "internal_scheme_xml": buffer.getvalue().decode("utf-8"),
            "input_specs": input_specs,
            "output_specs": output_specs,
        }
        ensure_composite_widget_class(payload)
        desc = composite_widget_description(payload)
        composite_node = scheme.new_node(
            desc,
            title="Composite",
            position=center,
            properties=composite_properties(payload),
        )
        self._main_window._register_composite_description(payload)

        for node in selected:
            scheme.remove_node(node)

        for spec in incoming:
            external_node = self._node_by_id(scheme, spec["external_node_id"])
            if external_node is None:
                continue
            scheme.new_link(
                external_node,
                external_node.output_channel(spec["external_channel_name"]),
                composite_node,
                composite_node.input_channel(spec["port_name"]),
            )

        for spec in outgoing:
            external_node = self._node_by_id(scheme, spec["external_node_id"])
            if external_node is None:
                continue
            scheme.new_link(
                composite_node,
                composite_node.output_channel(spec["port_name"]),
                external_node,
                external_node.input_channel(spec["external_channel_name"]),
            )
        document.setModified(True)
        return composite_node

    def ungroup_node(self, node) -> list[object]:
        """Replace one composite node with its stored internal workflow."""
        payload = composite_payload_from_properties(node.properties)
        if payload is None:
            return []
        document = self._main_window.current_document()
        scheme = document.scheme()
        scheme.remove_node(node)

        temp_scheme = DerZugWidgetsScheme()
        readwrite.scheme_load(
            temp_scheme,
            io.BytesIO(str(payload["internal_scheme_xml"]).encode("utf-8")),
            registry=self._main_window.widget_registry,
        )
        loaded_nodes = list(temp_scheme.nodes)
        loaded_links = list(temp_scheme.links)
        node_map: dict[object, object] = {}
        for internal_node in loaded_nodes:
            properties = deepcopy(internal_node.properties)
            properties.pop("__derzug_composite_internal_node_id", None)
            restored = scheme.new_node(
                internal_node.description,
                title=internal_node.title,
                position=tuple(internal_node.position),
                properties=properties,
            )
            node_map[internal_node] = restored
        for link in loaded_links:
            scheme.new_link(
                node_map[link.source_node],
                node_map[link.source_node].output_channel(link.source_channel.name),
                node_map[link.sink_node],
                node_map[link.sink_node].input_channel(link.sink_channel.name),
            )

        restored_by_id = {
            get_internal_node_id(restored) or get_node_id(restored): restored
            for restored in node_map.values()
        }

        for spec in payload.get("input_specs", []):
            external_node = self._node_by_id(scheme, spec["external_node_id"])
            internal_node = restored_by_id.get(spec["internal_node_id"])
            if external_node is None or internal_node is None:
                continue
            scheme.new_link(
                external_node,
                external_node.output_channel(spec["external_channel_name"]),
                internal_node,
                internal_node.input_channel(spec["internal_channel_name"]),
            )

        for spec in payload.get("output_specs", []):
            external_node = self._node_by_id(scheme, spec["external_node_id"])
            internal_node = restored_by_id.get(spec["internal_node_id"])
            if external_node is None or internal_node is None:
                continue
            scheme.new_link(
                internal_node,
                internal_node.output_channel(spec["internal_channel_name"]),
                external_node,
                external_node.input_channel(spec["external_channel_name"]),
            )
        document.scene().clearSelection()
        for restored in node_map.values():
            document.scene().item_for_node(restored).setSelected(True)
        document.setModified(True)
        return list(node_map.values())

    @staticmethod
    def _node_by_id(scheme, node_id: str | None):
        """Return the scheme node with one persisted DerZug node id."""
        if not node_id:
            return None
        for node in scheme.nodes:
            if get_node_id(node) == node_id:
                return node
        return None


def _install_derzug_exception_handler() -> None:
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


def _configure_linux_desktop_integration(application: QApplication) -> None:
    """Expose the desktop file name so Linux docks can match the launcher."""
    if not sys.platform.startswith("linux"):
        return

    set_desktop_file_name = getattr(application, "setDesktopFileName", None)
    if set_desktop_file_name is None:
        return

    with suppress(Exception):
        set_desktop_file_name("derzug")


def _configure_pyqtgraph_gpu_rendering() -> bool:
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


class _TabWindowCycler(QObject):
    """Cycle managed Orange windows with Tab / Shift+Tab."""

    _FOCUS_EXCLUDE = (
        QLineEdit,
        QTextEdit,
        QPlainTextEdit,
        QAbstractSpinBox,
        QComboBox,
        QAbstractItemView,
    )

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.KeyPress:
            return False

        key = event.key()
        modifiers = event.modifiers()

        if key not in (Qt.Key_Tab, Qt.Key_Backtab):
            return False

        if modifiers not in (Qt.NoModifier, Qt.ShiftModifier):
            return False

        focus = QApplication.focusWidget()
        if self._focus_should_keep_tab_behavior(focus):
            return False

        step = -1 if (key == Qt.Key_Backtab or modifiers == Qt.ShiftModifier) else 1
        return self._cycle(step)

    def _focus_should_keep_tab_behavior(self, widget: QWidget | None) -> bool:
        return isinstance(widget, self._FOCUS_EXCLUDE)

    def _cycle(self, step: int) -> bool:
        actions = [
            action
            for action in WindowListManager.instance().actions()
            if (window := action.data()) is not None and window.isVisible()
        ]
        if not actions:
            return False

        active_window = QApplication.activeWindow()
        current = next(
            (
                index
                for index, action in enumerate(actions)
                if action.data() is active_window
            ),
            -1,
        )
        target = actions[(current + step) % len(actions)]
        target.setChecked(True)
        return True


class _CanvasTracebackIconFilter(QObject):
    """Open traceback dialogs when canvas node state icons are double-clicked."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Intercept double-clicks on node error icons before Orange activates nodes."""
        if (
            event.type() != QEvent.MouseButtonDblClick
            or event.button() != Qt.LeftButton
        ):
            return False
        return self._main_window._open_traceback_from_canvas_icon(event.position())


class _CanvasMiddleButtonPanFilter(QObject):
    """Enable middle-button hand panning on the Orange canvas view."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._active = False
        self._last_position: QPointF | None = None
        self._previous_drag_mode = QGraphicsView.DragMode.NoDrag

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Pan directly on middle-button drag without triggering left-drag tools."""
        viewport = self._viewport()
        if viewport is None or obj is not viewport:
            return False
        event_type = event.type()
        if (
            event_type in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick)
            and event.button() == Qt.MiddleButton
        ):
            self._begin_pan(event)
            return True
        if not self._active:
            return False
        if event_type == QEvent.MouseMove:
            self._pan_to(event.position())
            return True
        if (
            event_type == QEvent.MouseButtonRelease
            and event.button() == Qt.MiddleButton
        ):
            self._end_pan()
            return True
        return False

    def _begin_pan(self, event) -> None:
        """Activate temporary hand-drag mode for one middle-button gesture."""
        if self._active:
            return
        view = self._view()
        viewport = self._viewport()
        if view is None or viewport is None:
            return
        self._active = True
        self._last_position = QPointF(event.position())
        self._previous_drag_mode = view.dragMode()
        view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._expand_scene_rect()
        viewport.setCursor(Qt.ClosedHandCursor)

    def _end_pan(self) -> None:
        """Restore the canvas view after a middle-button drag finishes."""
        view = self._view()
        viewport = self._viewport()
        if view is not None:
            view.setDragMode(self._previous_drag_mode)
        if viewport is not None:
            viewport.unsetCursor()
        self._active = False
        self._last_position = None

    def _pan_to(self, position: QPointF) -> None:
        """Scroll the canvas by the latest middle-button drag delta."""
        view = self._view()
        if view is None:
            return
        if self._last_position is None:
            self._last_position = QPointF(position)
            return
        delta = QPointF(position) - self._last_position
        if delta.isNull():
            return
        self._expand_scene_rect()
        horizontal = view.horizontalScrollBar()
        vertical = view.verticalScrollBar()
        horizontal.setValue(horizontal.value() - round(delta.x()))
        vertical.setValue(vertical.value() - round(delta.y()))
        self._last_position = QPointF(position)

    def _expand_scene_rect(self) -> None:
        """Grow the scene rect around the visible area so panning reveals whitespace."""
        view = self._view()
        scene = view.scene() if view is not None else None
        if view is None or scene is None:
            return
        visible = view.mapToScene(view.viewport().rect()).boundingRect()
        margin_x = max(float(visible.width()), 400.0)
        margin_y = max(float(visible.height()), 400.0)
        expanded = visible.adjusted(-margin_x, -margin_y, margin_x, margin_y)
        scene.setSceneRect(scene.sceneRect().united(expanded))

    def _view(self):
        """Return the live canvas view."""
        scheme_widget = getattr(self._main_window, "scheme_widget", None)
        try:
            view = getattr(scheme_widget, "view", lambda: None)()
        except RuntimeError:
            return None
        if view is None or sip.isdeleted(view):
            return None
        return view

    def _viewport(self):
        """Return the live canvas viewport widget."""
        view = self._view()
        try:
            viewport = getattr(view, "viewport", lambda: None)()
        except RuntimeError:
            return None
        if viewport is None or sip.isdeleted(viewport):
            return None
        return viewport


class ActiveSourceManager:
    """Track and route global iteration events to the selected source widget."""

    def __init__(self):
        self._active_widget = None
        self._active_node = None

    def ensure_active_source(self, main_window) -> object | None:
        """Ensure an active source exists, auto-selecting the first source if needed."""
        if self._is_source_widget(self._active_widget) and bool(
            getattr(self._active_widget, "isVisible", lambda: False)()
        ):
            self.refresh_active_marker(main_window)
            return self._active_widget

        sources = self._source_widgets()
        if self._active_widget in sources:
            self.refresh_active_marker(main_window)
            return self._active_widget

        self._clear_active_marker()
        if not sources:
            self._active_widget = None
            self._active_node = None
            return None

        self._set_active_widget(main_window, sources[0])
        return self._active_widget

    def set_active_source_from_selection(self, main_window) -> bool:
        """Set active source from the currently selected canvas node."""
        document = main_window.current_document()
        selected = document.selectedNodes()
        if not selected:
            self._show_status_message(main_window, "Select one source node first.")
            return False
        node = selected[0]
        scheme = document.scheme()
        widget = scheme.widget_for_node(node)
        if not self._is_source_widget(widget):
            self._show_status_message(
                main_window, "Selected node is not a source widget."
            )
            return False
        self._set_active_widget(main_window, widget)
        return True

    def step(self, main_window, direction: int) -> bool:
        """Step active source selection forward/backward."""
        widget = self.ensure_active_source(main_window)
        if widget is None:
            self._show_status_message(main_window, "No active source available.")
            return False

        if direction > 0:
            handler = getattr(widget, "step_next_item", None)
        else:
            handler = getattr(widget, "step_previous_item", None)

        if handler is None:
            self._show_status_message(
                main_window, "Active source does not support stepping."
            )
            return False

        ok = bool(handler())
        if not ok:
            self._show_status_message(
                main_window, "Active source has no iterable items."
            )
        return ok

    def _set_active_widget(self, main_window, widget) -> None:
        """Activate one source widget and update its canvas marker."""
        if not self._is_source_widget(widget):
            return

        self._clear_active_marker()
        node = self._node_for_widget(widget)
        self._active_widget = widget
        self._active_node = node
        if node is None:
            return

        self._apply_active_marker(main_window, node)
        self._show_status_message(main_window, f"Active source set: {node.title}")

    def _clear_active_marker(self) -> None:
        """Remove the active-source marker from the previously active node."""
        node = self._active_node
        if node is None:
            return
        self._remove_active_marker(node)

    def refresh_active_marker(self, main_window) -> None:
        """Refresh the active-source box after a node title changes."""
        node = self._active_node
        if node is None:
            return
        self._apply_active_marker(main_window, node)

    @staticmethod
    def _is_source_widget(widget) -> bool:
        """Return True for widgets that opt in as active sources."""
        return isinstance(widget, ZugWidget) and bool(
            getattr(widget, "is_source", False)
        )

    def _source_widgets(self) -> list:
        """Return all currently open source widgets."""
        output = []
        seen: set[int] = set()

        def _append_if_source(widget) -> None:
            if widget is None:
                return
            key = id(widget)
            if key in seen:
                return
            if not bool(getattr(widget, "isVisible", lambda: False)()):
                return
            if not self._is_source_widget(widget):
                return
            seen.add(key)
            output.append(widget)

        for action in WindowListManager.instance().actions():
            _append_if_source(action.data())

        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                _append_if_source(widget)

        return output

    @staticmethod
    def _node_for_widget(widget):
        """Return the scheme node for a widget, if available."""
        signal_manager = getattr(widget, "signalManager", None)
        if signal_manager is None:
            return None
        scheme_getter = getattr(signal_manager, "scheme", None)
        if scheme_getter is None:
            return None
        scheme = scheme_getter()
        if scheme is None:
            return None
        return scheme.node_for_widget(widget)

    @staticmethod
    def _node_item_for_node(main_window, node):
        """Return the live canvas item for a scheme node, if present."""
        if main_window is None or node is None:
            return None
        document = getattr(main_window, "current_document", lambda: None)()
        if document is None:
            return None
        scene = getattr(document, "scene", lambda: None)()
        if scene is None:
            return None
        item_for_node = getattr(scene, "item_for_node", None)
        if item_for_node is None:
            return None
        with suppress(Exception):
            return item_for_node(node)
        return None

    def _apply_active_marker(self, main_window, node) -> None:
        """Draw a filled title-background box for the active source node."""
        item = self._node_item_for_node(main_window, node)
        if item is None or not hasattr(item, "captionTextItem"):
            return

        caption = item.captionTextItem
        rect_item = getattr(item, "_derzug_active_source_rect", None)
        if rect_item is None:
            rect_item = QGraphicsRectItem(item)
            rect_item.setPen(QPen(QColor("#7CB8F8"), 1.5))
            rect_item.setBrush(QBrush(QColor("#D9ECFF")))
            rect_item.setZValue(caption.zValue() - 1)
            setattr(item, "_derzug_active_source_rect", rect_item)

            def _update_rect():
                r = caption.mapRectToParent(caption.boundingRect())
                rect_item.setRect(r)

            caption.document().contentsChanged.connect(_update_rect)
            setattr(item, "_derzug_active_source_update", _update_rect)

        text_rect = caption.mapRectToParent(caption.boundingRect())
        rect_item.setRect(text_rect)
        rect_item.show()

    def _remove_active_marker(self, node) -> None:
        """Hide the active-source title box for one scheme node."""
        item = self._node_item_for_node(_APP_ACTIVE_SOURCE_MAIN_WINDOW, node)
        rect_item = getattr(item, "_derzug_active_source_rect", None) if item else None
        if rect_item is not None:
            rect_item.hide()

    @staticmethod
    def _show_status_message(main_window, message: str) -> None:
        """Display a short non-blocking message in the main window status bar."""
        status_bar = main_window.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message, 2500)


class _CanvasZOrderToggler(QObject):
    """Raise DerZug widget windows in front of the canvas with Shift+~.

    Only handles the canvas-is-active direction.  When a widget window is
    active the widget's own keyPressEvent raises the canvas instead.
    """

    _FOCUS_EXCLUDE = _TabWindowCycler._FOCUS_EXCLUDE

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Raise widget windows when Shift+~ is pressed and the canvas is active."""
        if event.type() != QEvent.KeyPress:
            return False
        if event.key() != Qt.Key_AsciiTilde:
            return False
        if event.modifiers() != Qt.ShiftModifier:
            return False
        if self._focus_should_keep_key_behavior(QApplication.focusWidget()):
            return False
        # Delegate to ZugWidget keyPressEvent when a widget window owns focus.
        main_window = self._find_main_window()
        if main_window is None or QApplication.activeWindow() is not main_window:
            return False
        self._send_canvas_back(main_window)
        return True

    def _focus_should_keep_key_behavior(self, widget: QWidget | None) -> bool:
        return isinstance(widget, self._FOCUS_EXCLUDE)

    @staticmethod
    def _send_canvas_back(main_window) -> None:
        """Raise DerZug widget windows in front of the canvas and focus the topmost."""
        from Orange.widgets.widget import OWWidget

        widget_windows = [
            window
            for action in WindowListManager.instance().actions()
            if (window := action.data()) is not None
            and window is not main_window
            and window.isVisible()
            and isinstance(window, OWWidget)
        ]
        if not widget_windows:
            widget_windows = [
                w
                for w in QApplication.topLevelWidgets()
                if w is not main_window and w.isVisible() and isinstance(w, OWWidget)
            ]
        for w in widget_windows:
            w.raise_()
        # Activate the topmost widget so Shift+~ can toggle back from it.
        if widget_windows:
            widget_windows[-1].activateWindow()

    @staticmethod
    def _find_main_window():
        """Return the running DerZugMainWindow, or None."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, DerZugMainWindow):
                return widget
        return None


class _CanvasEscapeDefocuser(QObject):
    """Handle Escape on the canvas by clearing child focus and refocusing it."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Consume plain Escape while the main canvas window is active."""
        if event.type() != QEvent.KeyPress:
            return False
        if event.key() != Qt.Key_Escape:
            return False
        if event.modifiers() != Qt.NoModifier:
            return False
        main_window = self._find_main_window()
        if main_window is None or QApplication.activeWindow() is not main_window:
            return False
        focus_widget = QApplication.focusWidget()
        if (
            focus_widget is not None
            and focus_widget is not main_window
            and focus_widget.window() is main_window
        ):
            focus_widget.clearFocus()
        main_window.setFocus(Qt.ShortcutFocusReason)
        main_window.activateWindow()
        event.accept()
        return True

    @staticmethod
    def _find_main_window():
        """Return the running DerZugMainWindow, or None."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, DerZugMainWindow):
                return widget
        return None


class _ActiveSourceNavigator(QObject):
    """Global hotkeys for stepping active-source contents."""

    _FOCUS_EXCLUDE = _TabWindowCycler._FOCUS_EXCLUDE

    def __init__(self, manager: ActiveSourceManager):
        super().__init__()
        self._manager = manager

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.KeyPress:
            return False

        if self._focus_should_keep_key_behavior(QApplication.focusWidget()):
            return False

        key = event.key()
        modifiers = event.modifiers()
        direction = 0
        if key == Qt.Key_A and modifiers == Qt.ControlModifier:
            direction = 1
        elif key == Qt.Key_A and modifiers == (Qt.ControlModifier | Qt.ShiftModifier):
            direction = -1
        if direction == 0:
            return False

        main_window = self._find_main_window()
        if main_window is None:
            return False
        self._manager.step(main_window, direction)
        return True

    def _focus_should_keep_key_behavior(self, widget: QWidget | None) -> bool:
        return isinstance(widget, self._FOCUS_EXCLUDE)

    @staticmethod
    def _find_main_window():
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, DerZugMainWindow):
                return widget
        return None


class DerZugAboutDialog(QDialog):
    """About dialog for DerZug."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About DerZug")
        from derzug.version import __version__

        layout = QVBoxLayout(self)

        icon_path = Path(__file__).parent.parent / "static" / "logo_v1.png"
        pixmap = QPixmap(str(icon_path)).scaledToWidth(256, Qt.SmoothTransformation)
        img_label = QLabel(self)
        img_label.setPixmap(pixmap)
        img_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(img_label)

        def _pkg_version(name: str) -> str:
            with suppress(PackageNotFoundError):
                return _pkg_dist_version(name)
            return "n/a"

        qt_binding_name = next(
            (name for name in ("PyQt6", "PyQt5") if _pkg_version(name) != "n/a"),
            "Qt Binding",
        )
        deps = [
            ("Orange3", "orange3"),
            ("DASCore", "dascore"),
            (qt_binding_name, qt_binding_name),
            ("pyqtgraph", "pyqtgraph"),
            ("tiledb", "tiledb"),
            ("duckdb", "duckdb"),
        ]
        rows = "".join(
            f"<tr><td>{label}</td><td>{escape(_pkg_version(pkg))}</td></tr>"
            for label, pkg in deps
        )
        text = (
            "<center>"
            "<p><b>DerZug</b> is an interactive workspace for DAS workflows"
            " and visualization.</p>"
            "<p>"
            'Built with <a href="https://dascore.org/">DASCore</a>, '
            '<a href="https://pyqtgraph.readthedocs.io/">PyQtGraph</a>, '
            'and <a href="https://orangedatamining.com/">Orange</a>.'
            "</p>"
            f"<p>Version: {escape(__version__)}</p>"
            "</center>"
            f"<table>{rows}</table>"
        )
        text_label = QLabel(text, self)
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setOpenExternalLinks(True)
        layout.addWidget(text_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, self)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        layout.setSizeConstraint(QVBoxLayout.SetFixedSize)


class DerZugKeyboardShortcutsDialog(QDialog):
    """Keyboard shortcuts reference dialog for DerZug."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")

        layout = QVBoxLayout(self)

        text = QLabel(
            (
                "<b>Canvas</b><br>"
                "<b>F</b>: Toggle fullscreen<br>"
                "<b>Tab</b>: Focus next visible window<br>"
                "<b>Shift+Tab</b>: Focus previous visible window<br>"
                "<b>Shift+~</b>: Bring widget windows forward / raise canvas<br>"
                "<b>Ctrl+A</b>: Step active source forward<br>"
                "<b>Ctrl+Shift+A</b>: Step active source backward<br>"
                "<br>"
                "<b>Widget Windows</b><br>"
                "<b>F</b>: Toggle fullscreen<br>"
                "<b>Ctrl+Q</b>: Close window<br>"
                "<br>"
                "<b>Canvas Editing</b><br>"
                "<b>Ctrl+C</b>: Copy selection<br>"
                "<b>Ctrl+V</b>: Paste selection<br>"
                "<b>Ctrl+D</b>: Duplicate selection<br>"
                "<b>Delete / Backspace</b>: Remove selection<br>"
                "<b>F1</b>: Open widget help"
            ),
            self,
        )
        text.setTextFormat(Qt.RichText)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, self)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        layout.setSizeConstraint(QVBoxLayout.SetFixedSize)


class DerZugConfig(OrangeConfig):
    """Application config for DerZug."""

    OrganizationDomain = "dasdae"
    OrganizationName = "dasdae"
    ApplicationName = "DerZug"
    AppUserModelID = "DASDAE.DerZug"

    @staticmethod
    def application_icon():
        """Return the application icon used by DerZug."""
        icon_path = Path(__file__).parent.parent / "static" / "icon.png"
        return QIcon(str(icon_path))

    @staticmethod
    def widgets_entry_points() -> Iterable[object]:
        """
        Return filtered widget entry points.
        """
        yield from load_widget_entrypoints()

    @staticmethod
    def examples_entry_points() -> Iterable[object]:
        """Return DerZug example workflow entry points only."""
        yield from load_example_workflow_entrypoints()

    @staticmethod
    def workflow_constructor(*args, **kwargs):
        """Create a DerZug workflow with owner-aware widget windows."""
        return DerZugWidgetsScheme(*args, **kwargs)


class DerZugOWWidgetManager(OWWidgetManager):
    """Widget manager for DerZug workflows."""

    def create_widget_instance(self, node):
        """Create the widget with Orange's default window behavior."""
        return super().create_widget_instance(node)


class DerZugWidgetsScheme(WidgetsScheme):
    """Orange workflow scheme with DerZug-specific widget window behavior."""

    def __init__(self, parent=None, title=None, description=None, env={}, **kwargs):
        Scheme.__init__(self, parent, title, description, env=env, **kwargs)
        self.widget_manager = DerZugOWWidgetManager()
        self.signal_manager = WidgetsSignalManager(self)
        self.widget_manager.set_scheme(self)
        self._WidgetsScheme__report_view = None

    def sync_node_properties(self):
        """Preserve DerZug node metadata while syncing widget settings."""
        changed = False
        for node in self.nodes:
            settings = self.widget_manager.widget_settings_for_node(node)
            merged = dict(settings)
            merged.update(_reserved_node_metadata(node.properties))
            if merged != node.properties:
                node.properties = merged
                changed = True
        return changed


# def get_app(app=None):
#     """Get or create the QApplication, with Ctrl+C (SIGINT) support."""
#     app = app or QApplication.instance() or QApplication(sys.argv)
#     signal.signal(signal.SIGINT, lambda *_: app.quit())
#     app._sigint_timer = QTimer()
#     app._sigint_timer.start(600)
#     app._sigint_timer.timeout.connect(lambda: None)
#     return app


class DerZugMain(OMain):
    """Orange main runner customized for DerZug."""

    DefaultConfig = "derzug.views.orange.DerZugConfig"
    gpu_rendering_enabled = False
    active_source_manager = None
    show_demo = False
    dev_mode = False
    startup_workflow_path: str | None = None
    startup_open_widget_ids: ClassVar[list[int]] = []

    def run(self, argv=None):
        """Run the Orange main loop for DerZug."""
        # self.app = get_app()
        return super().run(argv or [])

    def setup_application(self):
        """Apply DerZug-specific application setup."""
        super().setup_application()
        install_sigint_handler(self.application)
        self.gpu_rendering_enabled = _configure_pyqtgraph_gpu_rendering()
        self.active_source_manager = ActiveSourceManager()
        global _APP_ACTIVE_SOURCE_MANAGER
        _APP_ACTIVE_SOURCE_MANAGER = self.active_source_manager
        self.application.active_source_manager = self.active_source_manager
        _configure_linux_desktop_integration(self.application)
        self.application.setWindowIcon(DerZugConfig.application_icon())
        self._tab_window_cycler = _TabWindowCycler(self.application)
        self._active_source_navigator = _ActiveSourceNavigator(
            self.active_source_manager
        )
        self._canvas_z_order_toggler = _CanvasZOrderToggler(self.application)
        self._canvas_escape_defocuser = _CanvasEscapeDefocuser(self.application)
        self.application.installEventFilter(self._tab_window_cycler)
        self.application.installEventFilter(self._active_source_navigator)
        self.application.installEventFilter(self._canvas_z_order_toggler)
        self.application.installEventFilter(self._canvas_escape_defocuser)

    def setup_sys_redirections(self):
        """Install stdout/stderr redirection and DerZug's exception dialog hook."""
        super().setup_sys_redirections()
        _install_derzug_exception_handler()

    def tear_down_sys_redirections(self):
        """Remove DerZug's exception handler before restoring base redirections."""
        if isinstance(sys.excepthook, ExceptHook):
            with suppress((TypeError, RuntimeError)):
                sys.excepthook.handledException.disconnect(handle_derzug_exception)
            # Restore Orange's expected connection so the base teardown can
            # disconnect it without raising when shutting the app down.
            with suppress((TypeError, RuntimeError)):
                sys.excepthook.handledException.connect(orange_handle_exception)
        super().tear_down_sys_redirections()

    def splash_screen(self):
        """Disable splash screen for the DerZug app."""
        return None

    def show_welcome_screen(self, parent):
        """Disable Orange welcome screen for DerZug."""
        return None

    def create_main_window(self):
        """Create the main window instance for DerZug."""
        return DerZugMainWindow()

    def setup_main_window(self):
        """Configure the main window with the filtered widget registry."""
        window = super().setup_main_window()
        self.registry = filter_registry_for_das(self.registry)
        window.set_widget_registry(self.registry)
        window.active_source_manager = self.active_source_manager
        window.dev_mode = bool(self.dev_mode)
        window.startup_demo_mode = bool(self.show_demo)
        window.startup_workflow_path = self.startup_workflow_path
        window.startup_open_widget_ids = list(self.startup_open_widget_ids)
        global _APP_ACTIVE_SOURCE_MAIN_WINDOW
        _APP_ACTIVE_SOURCE_MAIN_WINDOW = window
        self.application.active_source_main_window = window
        window.install_dev_controls()
        if self.show_demo:
            QTimer.singleShot(0, window.examples_dialog)
        return window

    def main_window_stylesheet(self):
        """
        Load the local DerZug stylesheet by default.

        This mirrors Orange's default ``orange.qss`` but keeps a project-local
        copy so style fixes can be made without patching site-packages.
        """
        if self.options.stylesheet is not None:
            return super().main_window_stylesheet()

        qss_path = Path(__file__).parent.parent / "styles" / "orange.qss"
        if not qss_path.exists():
            return super().main_window_stylesheet()

        content = qss_path.read_text(encoding="utf-8")
        pattern = re.compile(
            r"^\s*@([a-zA-Z0-9_]+?)\s*:\s*([a-zA-Z0-9_/]+?);\s*$",
            flags=re.MULTILINE,
        )
        for prefix, subpath in pattern.findall(content):
            resolved = str((qss_path.parent / subpath).resolve())
            if resolved not in QDir.searchPaths(prefix):
                QDir.addSearchPath(prefix, resolved)
        return pattern.sub("", content)


class DerZugMainWindow(OrangeMainWindow):
    """Orange main window customized for DerZug."""

    def __init__(self, *args, **kwargs):
        """Initialize the DerZug main window."""
        super().__init__(*args, **kwargs)
        self.setWindowTitle("DerZug")
        self.set_float_widgets_on_top_enabled(False)
        self.active_source_manager: ActiveSourceManager | None = None
        self.dev_mode = False
        self.startup_demo_mode = False
        self.startup_workflow_path: str | None = None
        self.startup_open_widget_ids: list[int] = []
        self.dev_menu: QMenu | None = None
        self.hot_reload_action: QAction | None = None
        self.edit_config_file_action: QAction | None = None
        self.annotation_settings_action: QAction | None = None
        self._hot_reload_in_progress = False
        self._startup_warning_shown = False
        self._canvas_composite_controller = _CanvasCompositeController(self)
        self._canvas_traceback_filter = _CanvasTracebackIconFilter(self)
        self._canvas_middle_button_pan_filter = _CanvasMiddleButtonPanFilter(self)
        self._apply_default_help_visibility()
        self._customize_shell()
        self._install_canvas_traceback_filter()
        self._install_canvas_middle_button_pan_filter()
        self._install_canvas_reset_view_handler()

    def _apply_default_help_visibility(self) -> None:
        """Default quick-help pane to hidden unless user has saved a preference."""
        settings = QSettings()
        settings.beginGroup("mainwindow")
        has_saved_visibility = settings.contains("quick-help/visible")
        settings.endGroup()
        if has_saved_visibility:
            return

        self.canvas_tool_dock.setQuickHelpVisible(False)
        if getattr(self, "dock_help_action", None) is not None:
            self.dock_help_action.setChecked(False)

    def _customize_shell(self) -> None:
        """Trim inherited Orange shell actions down to the DerZug UX."""
        self._customize_help_menu()
        self._remove_toolbar_help_action()
        self._prune_menu_actions("File", {"Open Report..."})
        self._prune_menu_actions("View", {"Window Groups", "Show report"})
        self._prune_menu_actions(
            "Options",
            {"Add-ons...", "Reset Widget Settings..."},
        )
        self._install_annotation_settings_action()

    def _remove_toolbar_help_action(self) -> None:
        """Remove the quick-help toggle from the canvas toolbar."""
        action = getattr(self, "dock_help_action", None)
        toolbar = getattr(self, "canvas_toolbar", None)
        if action is None or toolbar is None:
            return
        toolbar.removeAction(action)

    def _customize_help_menu(self) -> None:
        """Keep only the DerZug-relevant help actions."""
        help_menu = getattr(self, "help_menu", None)
        if help_menu is None:
            return

        with suppress((TypeError, RuntimeError)):
            self.documentation_action.triggered.disconnect()
        self.documentation_action.triggered.connect(self.open_documentation)
        self.examples_action.setText("Example Workflow")
        self.donate_action.setText("Donate to Orange")
        self.keyboard_shortcuts_action = QAction("Keyboard Shortcuts", self)
        self.keyboard_shortcuts_action.triggered.connect(self.open_keyboard_shortcuts)

        help_menu.clear()
        help_menu.addActions(
            [
                self.about_action,
                self.documentation_action,
                self.keyboard_shortcuts_action,
                self.examples_action,
                self.donate_action,
            ]
        )

    def _prune_menu_actions(self, menu_name: str, labels_to_remove: set[str]) -> None:
        """Remove inherited actions from one top-level menu."""
        menu = self._menu_by_name(menu_name)
        if menu is None:
            return
        for action in list(menu.actions()):
            label = action.text().replace("&", "")
            if label in labels_to_remove:
                menu.removeAction(action)
                action.setVisible(False)
        self._cleanup_menu_separators(menu)

    def _menu_by_name(self, menu_name: str) -> QMenu | None:
        """Return one top-level menu by visible title."""
        menu_bar = self.menuBar()
        if menu_bar is None:
            return None
        for action in menu_bar.actions():
            label = action.text().replace("&", "")
            if label == menu_name:
                return action.menu()
        return None

    def _install_annotation_settings_action(self) -> None:
        """Add the global annotation settings entry to the Options menu."""
        options_menu = self._menu_by_name("Options")
        if options_menu is None:
            return
        if self.annotation_settings_action is None:
            action = QAction("Annotation Settings...", self)
            action.setObjectName("annotation-settings-action")
            action.triggered.connect(self.open_annotation_settings)
            self.annotation_settings_action = action
        existing = [
            action
            for action in options_menu.actions()
            if action is self.annotation_settings_action
        ]
        if existing:
            return
        insert_before = next(
            (
                action
                for action in options_menu.actions()
                if action.text().replace("&", "") == "Settings"
            ),
            None,
        )
        if insert_before is None:
            options_menu.addAction(self.annotation_settings_action)
        else:
            options_menu.insertAction(insert_before, self.annotation_settings_action)
        self._cleanup_menu_separators(options_menu)

    @staticmethod
    def _cleanup_menu_separators(menu: QMenu) -> None:
        """Hide empty actions plus leading, trailing, and doubled separators."""
        actions = list(menu.actions())
        previous_was_separator = True
        for action in actions:
            label = action.text().replace("&", "").strip()
            if not action.isSeparator() and not label:
                action.setVisible(False)
                continue
            if action.isSeparator():
                keep = not previous_was_separator
                action.setVisible(keep)
                previous_was_separator = True
            else:
                action.setVisible(True)
                previous_was_separator = False
        trailing_separator = True
        for action in reversed(actions):
            if not action.isVisible():
                continue
            if action.isSeparator() and trailing_separator:
                action.setVisible(False)
            else:
                trailing_separator = False

    def event(self, event: QEvent) -> bool:
        """Delegate events to the base Orange main window."""
        return super().event(event)

    def showEvent(self, event) -> None:
        """Show the startup warning once when the main window first appears."""
        super().showEvent(event)
        if self._startup_warning_shown:
            return
        self._startup_warning_shown = True
        QTimer.singleShot(0, self.maybe_show_experimental_warning)

    def keyPressEvent(self, event) -> None:
        """Toggle fullscreen with F when no text input has focus."""
        if (
            event.key() == Qt.Key_F
            and event.modifiers() == Qt.NoModifier
            and not isinstance(
                QApplication.focusWidget(),
                QAbstractItemView
                | QAbstractSpinBox
                | QComboBox
                | QLineEdit
                | QPlainTextEdit
                | QTextEdit,
            )
        ):
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def _install_canvas_traceback_filter(self) -> None:
        """Install the canvas traceback handler on the current scheme viewport."""
        scheme_widget = getattr(self, "scheme_widget", None)
        view = getattr(scheme_widget, "view", lambda: None)()
        viewport = getattr(view, "viewport", lambda: None)()
        if viewport is not None:
            viewport.installEventFilter(self._canvas_traceback_filter)

    def _install_canvas_middle_button_pan_filter(self) -> None:
        """Install middle-button panning on the current scheme viewport."""
        scheme_widget = getattr(self, "scheme_widget", None)
        view = getattr(scheme_widget, "view", lambda: None)()
        viewport = getattr(view, "viewport", lambda: None)()
        if viewport is not None:
            viewport.installEventFilter(self._canvas_middle_button_pan_filter)

    def _install_canvas_reset_view_handler(self) -> None:
        """Extend Reset Zoom so it reframes workflow contents after panning."""
        scheme_widget = getattr(self, "scheme_widget", None)
        view = getattr(scheme_widget, "view", lambda: None)()
        if view is None:
            return
        action = view.findChild(QAction, "action-zoom-reset")
        if action is not None:
            action.triggered.connect(self._reset_canvas_view_to_contents)

    def _reset_canvas_view_to_contents(self) -> None:
        """Shrink the canvas scene rect back to workflow contents and recenter it."""
        scheme_widget = getattr(self, "scheme_widget", None)
        view = getattr(scheme_widget, "view", lambda: None)()
        scene = getattr(scheme_widget, "scene", lambda: None)()
        if view is None or scene is None:
            return
        contents = scene.itemsBoundingRect()
        if contents.isNull() or not contents.isValid():
            return
        padding_x = max(contents.width() * 0.15, 120.0)
        padding_y = max(contents.height() * 0.15, 120.0)
        framed = contents.adjusted(-padding_x, -padding_y, padding_x, padding_y)
        scene.setSceneRect(framed)
        view.centerOn(framed.center())

    def _register_composite_description(self, payload: dict[str, object]) -> None:
        """Ensure one dynamic composite description exists in the live registry."""
        desc = composite_widget_description(payload)
        if self.widget_registry is not None and not self.widget_registry.has_widget(
            desc.qualified_name
        ):
            self.widget_registry.register_widget(desc)

    def load_scheme(self, filename):
        """Pre-register dynamic composite widgets before Orange loads links."""
        try:
            with open(filename, "rb") as stream:
                parsed = readwrite.parse_ows_stream(stream)
        except Exception:
            parsed = None
        if parsed is not None:
            for node_desc in parsed.nodes:
                data = getattr(node_desc, "data", None)
                if data is None:
                    continue
                try:
                    properties = readwrite.loads(data.data, data.format)
                except Exception:
                    continue
                payload = composite_payload_from_properties(properties)
                if payload is None:
                    continue
                ensure_composite_widget_class(payload)
                self._register_composite_description(payload)
        super().load_scheme(filename)
        QTimer.singleShot(0, self._reemit_restored_source_widgets)
        if self.startup_open_widget_ids:
            QTimer.singleShot(0, self._open_startup_widgets)

    def _reemit_restored_source_widgets(self) -> None:
        """Re-emit restored source-widget outputs after workflow reload settles."""
        from derzug.widgets.spool import Spool

        document = self.current_document()
        scheme = getattr(document, "scheme", lambda: None)()
        if scheme is None:
            return
        for node in scheme.nodes:
            widget = scheme.widget_for_node(node)
            if isinstance(widget, Spool):
                if widget._source_spool is None:
                    widget.run()
                else:
                    widget._emit_current_output()

    def _collect_open_widget_node_ids(self) -> list[int]:
        """Return indices of nodes whose widget windows are currently visible.

        Only checks already-created widgets to avoid forcing instantiation of
        widgets that have never been opened.
        """
        document = self.current_document()
        if document is None:
            return []
        scheme = getattr(document, "scheme", lambda: None)()
        if scheme is None:
            return []
        wm = getattr(scheme, "widget_manager", None)
        if wm is None:
            return []
        created = getattr(wm, "_OWWidgetManager__item_for_node", {})
        return [
            idx
            for idx, node in enumerate(scheme.nodes)
            if node in created
            and (w := created[node].widget) is not None
            and w.isVisible()
        ]

    def _open_startup_widgets(self) -> None:
        """Open widget windows that were visible before hot reload."""
        document = self.current_document()
        if document is None:
            return
        scheme = getattr(document, "scheme", lambda: None)()
        if scheme is None:
            return
        wm = getattr(scheme, "widget_manager", None)
        if wm is None:
            return
        nodes = scheme.nodes
        for idx in self.startup_open_widget_ids:
            if 0 <= idx < len(nodes):
                widget = scheme.widget_for_node(nodes[idx])
                if widget is not None:
                    wm.activate_widget_for_node(nodes[idx], widget)

    def _node_item_from_canvas_pos(self, viewport_pos) -> NodeItem | None:
        """Return the node item under a viewport position, if any."""
        scheme_widget = getattr(self, "scheme_widget", None)
        view = getattr(scheme_widget, "view", lambda: None)()
        scene = getattr(scheme_widget, "scene", lambda: None)()
        if view is None or scene is None:
            return None
        scene_pos = view.mapToScene(viewport_pos.toPoint())
        item = scene.itemAt(scene_pos, view.transform())
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        return item

    def _widget_for_node_item(self, node_item: NodeItem):
        """Return the live widget for a canvas node item, if present."""
        document = self.current_document()
        scheme = getattr(document, "scheme", lambda: None)()
        scene = getattr(document, "scene", lambda: None)()
        if scheme is None or scene is None:
            return None
        for node in scheme.nodes:
            try:
                if scene.item_for_node(node) is node_item:
                    return scheme.widget_for_node(node)
            except Exception:
                continue
        return None

    def _clicked_state_icon(self, node_item: NodeItem, viewport_pos):
        """Return the visible state icon hit by the canvas click, if any."""
        scheme_widget = getattr(self, "scheme_widget", None)
        view = getattr(scheme_widget, "view", lambda: None)()
        if view is None:
            return None
        scene_pos = view.mapToScene(viewport_pos.toPoint())
        for icon_item in (
            getattr(node_item, "errorItem", None),
            getattr(node_item, "warningItem", None),
            getattr(node_item, "infoItem", None),
        ):
            if icon_item is None or not icon_item.isVisible():
                continue
            if icon_item.sceneBoundingRect().contains(scene_pos):
                return icon_item
        return None

    def _open_traceback_from_canvas_icon(self, viewport_pos) -> bool:
        """Open a traceback dialog when a visible node state icon is double-clicked."""
        node_item = self._node_item_from_canvas_pos(viewport_pos)
        if node_item is None:
            return False
        if self._clicked_state_icon(node_item, viewport_pos) is None:
            return False
        widget = self._widget_for_node_item(node_item)
        if not isinstance(widget, ZugWidget) or widget._last_error_exc is None:
            return False
        widget._open_last_error_dialog()
        return True

    def _restack_float_widgets(self) -> None:
        """No-op: DerZug no longer forces widget windows above the canvas."""
        return

    def install_dev_controls(self) -> None:
        """Install development-only hot-reload controls."""
        if not self.dev_mode:
            return
        if self.hot_reload_action is None:
            action = QAction("Hot Reload", self)
            action.setObjectName("hot-reload-action")
            action.setToolTip(
                "Restart DerZug in development mode and reopen the workflow"
            )
            action.setShortcut("Ctrl+Shift+R")
            action.triggered.connect(self._trigger_hot_reload)
            self.hot_reload_action = action
            self.addAction(action)
        if self.edit_config_file_action is None:
            action = QAction("Edit Config File", self)
            action.setObjectName("edit-config-file-action")
            action.setToolTip("Open the DerZug user config file")
            action.triggered.connect(self._open_config_file)
            self.edit_config_file_action = action
            self.addAction(action)
        if self.dev_menu is None:
            menu = QMenu("Dev", self)
            menu.setObjectName("dev-menu")
            menu.addAction(self.hot_reload_action)
            menu.addAction(self.edit_config_file_action)
            self.dev_menu = menu
        menu_bar = self.menuBar()
        if (
            menu_bar is not None
            and self.dev_menu.menuAction() not in menu_bar.actions()
        ):
            menu_bar.addMenu(self.dev_menu)

    def _trigger_hot_reload(self) -> None:
        """Restart the app in development mode from one temp workflow snapshot."""
        if not self.dev_mode:
            return
        open_widget_ids = self._collect_open_widget_node_ids()
        try:
            restart_workflow = self._workflow_path_for_reload()
            command = self._build_hot_reload_command(restart_workflow, open_widget_ids)
            subprocess.Popen(command)
        except Exception as exc:
            QMessageBox.critical(self, "Hot Reload Failed", str(exc))
            return
        self._hot_reload_in_progress = True
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def ask_save_changes(self):
        """Bypass the normal save prompt when quitting only for hot reload."""
        if self._hot_reload_in_progress:
            return QDialog.Accepted
        return super().ask_save_changes()

    def _current_document_path(self) -> str | None:
        """Return the current document path, if any."""
        document = self.current_document()
        if document is None:
            return None
        path = document.path()
        return str(path) if path else None

    def _workflow_path_for_reload(self) -> str | None:
        """Return the workflow path to reopen after a hot reload."""
        if self.current_document() is not None:
            return self._save_temp_workflow_for_reload()
        return self.startup_workflow_path

    def _hot_reload_temp_workflow_path(self) -> str:
        """Return the stable temp workflow path used for hot reload snapshots."""
        return str(Path(tempfile.gettempdir()) / "derzug-hot-reload.ows")

    def _save_temp_workflow_for_reload(self) -> str:
        """Serialize the current live workflow to the hot-reload temp path."""
        document = self.current_document()
        if document is None:
            raise RuntimeError("No current workflow is available for hot reload.")
        scheme = document.scheme()
        if scheme is None:
            raise RuntimeError(
                "No current workflow scheme is available for hot reload."
            )
        workflow_path = self._hot_reload_temp_workflow_path()
        if not self.save_scheme_to(scheme, workflow_path):
            raise RuntimeError("Failed to save hot reload workflow snapshot.")
        return workflow_path

    def _config_file_path(self) -> str:
        """Return the user config file path for DerZug."""
        return _derzug_settings().fileName()

    def _open_config_file(self) -> None:
        """Open the DerZug user config file in the OS default editor."""
        try:
            settings = _derzug_settings()
            path = Path(self._config_file_path())
            path.parent.mkdir(parents=True, exist_ok=True)
            settings.sync()
            path.touch(exist_ok=True)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            if not opened:
                raise RuntimeError(f"Could not open config file: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Open Config File Failed", str(exc))

    def _build_hot_reload_command(
        self,
        workflow_path: str | None,
        open_widget_ids: list[int] | None = None,
    ) -> list[str]:
        """Return the command used to restart DerZug in development mode."""
        command = [sys.executable, "-m", "derzug.cli", "--dev"]
        if workflow_path:
            command.append(workflow_path)
        elif self.startup_demo_mode:
            command.append("--demo")
        if open_widget_ids:
            command.extend(
                ["--open-widgets", ",".join(str(i) for i in open_widget_ids)]
            )
        return command

    def open_about(self):
        """Show the DerZug about dialog."""
        dlg = DerZugAboutDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()
        dlg.raise_()

    def open_documentation(self) -> None:
        """Open DerZug project documentation."""
        QDesktopServices.openUrl(QUrl("https://github.com/dasdae/derzug"))

    def open_keyboard_shortcuts(self) -> None:
        """Show the DerZug keyboard shortcuts dialog."""
        dlg = DerZugKeyboardShortcutsDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()
        dlg.raise_()

    def open_annotation_settings(self) -> None:
        """Show the global annotation settings dialog."""
        dialog = AnnotationSettingsDialog(load_annotation_config(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        save_annotation_config(dialog.config())

    def should_show_experimental_warning(self) -> bool:
        """Return True when the startup experimental warning is enabled."""
        settings = _derzug_settings()
        settings.beginGroup(_EXPERIMENTAL_WARNING_GROUP)
        hidden = settings.value(_EXPERIMENTAL_WARNING_HIDE_KEY, False, type=bool)
        settings.endGroup()
        return not bool(hidden)

    def set_experimental_warning_hidden(self, hidden: bool) -> None:
        """Persist whether the startup experimental warning should stay hidden."""
        settings = _derzug_settings()
        settings.beginGroup(_EXPERIMENTAL_WARNING_GROUP)
        settings.setValue(_EXPERIMENTAL_WARNING_HIDE_KEY, bool(hidden))
        settings.endGroup()

    def clear_experimental_warning_hidden(self) -> None:
        """Clear the persisted startup experimental warning preference."""
        settings = _derzug_settings()
        settings.beginGroup(_EXPERIMENTAL_WARNING_GROUP)
        settings.remove(_EXPERIMENTAL_WARNING_HIDE_KEY)
        settings.endGroup()

    def maybe_show_experimental_warning(self) -> None:
        """Show the startup experimental warning unless the user hid it."""
        if not self.should_show_experimental_warning():
            return
        dialog = ExperimentalWarningDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.hide_future_warnings:
            self.set_experimental_warning_hidden(True)


class ExperimentalWarningDialog(QDialog):
    """Modal startup warning for DerZug's experimental status."""

    TITLE = "🚨 Experimental Warning"
    HEADING = "DerZug Is Experimental"
    MESSAGE = (
        "Warning: Derzug is a highly experimental proof of concept. "
        "It should not be used for anything important. "
        "Expect bugs and breaking changes."
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.TITLE)
        self.setModal(True)
        self.resize(520, 230)
        self.hide_future_warnings = False
        self.setObjectName("experimental-warning-dialog")
        self.setStyleSheet(
            """
            QDialog#experimental-warning-dialog {
                background-color: #fff4f4;
            }
            QFrame#experimental-warning-panel {
                background-color: #fffafa;
                border: 1px solid #d7a1a1;
                border-left: 6px solid #b63a3a;
                border-radius: 10px;
            }
            QLabel#experimental-warning-heading {
                color: #7f1d1d;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#experimental-warning-body {
                color: #4a1f1f;
                font-size: 14px;
                line-height: 1.35;
            }
            QPushButton#experimental-warning-ok {
                background-color: #b63a3a;
                border: 1px solid #962f2f;
                border-radius: 6px;
                color: white;
                font-weight: 700;
                padding: 6px 16px;
            }
            QPushButton#experimental-warning-ok:hover {
                background-color: #c44343;
            }
            QPushButton#experimental-warning-hide {
                border-radius: 6px;
                padding: 6px 16px;
            }
            QCheckBox#experimental-warning-checkbox {
                color: #4a1f1f;
                font-size: 13px;
                spacing: 8px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        panel = QWidget(self)
        panel.setObjectName("experimental-warning-panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.setSpacing(8)

        heading = QLabel(self.HEADING, panel)
        heading.setObjectName("experimental-warning-heading")
        heading.setWordWrap(True)
        panel_layout.addWidget(heading)

        label = QLabel(self.MESSAGE, panel)
        label.setObjectName("experimental-warning-body")
        label.setWordWrap(True)
        panel_layout.addWidget(label)

        layout.addWidget(panel)

        self._hide_checkbox = QCheckBox("Don't show this message again", self)
        self._hide_checkbox.setObjectName("experimental-warning-checkbox")
        layout.addWidget(self._hide_checkbox)

        buttons = QDialogButtonBox(self)
        ok_button = QPushButton("OK", self)
        ok_button.setObjectName("experimental-warning-ok")
        buttons.addButton(ok_button, QDialogButtonBox.ButtonRole.AcceptRole)
        ok_button.clicked.connect(self._accept_for_now)
        layout.addWidget(buttons)

    def _accept_for_now(self) -> None:
        """Accept the dialog without suppressing future startup warnings."""
        self.hide_future_warnings = self._hide_checkbox.isChecked()
        self.accept()
