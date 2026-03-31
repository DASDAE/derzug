"""
Testing utilities for DerZug.

Provides helpers for instantiating Orange widgets.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import ClassVar

import pytest
from AnyQt.QtCore import Qt
from AnyQt.QtTest import QTest
from AnyQt.QtWidgets import QApplication
from Orange.widgets.tests.base import (
    DummySignalManager,
    WidgetTest,
    open_widget_classes,
)
from Orange.widgets.widget import OWWidget
from orangecanvas.registry import WidgetRegistry

from derzug.core import ZugWidget
from derzug.core.patchdimwidget import PatchDimWidget
from derzug.workflow import Pipe, Task


def wait_for_widget_idle(widget: OWWidget, timeout: float = 5.0) -> None:
    """Pump Qt events until a widget finishes all active background tasks.

    Handles widgets that chain tasks (e.g. spool-load followed by a deferred
    emit task started via QTimer.singleShot): after each task completes, one
    extra processEvents() call flushes any pending singleShot(0, ...) timers
    that might start a follow-on task before declaring the widget idle.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if getattr(widget, "_async_teardown_started", False):
            QApplication.processEvents()
            return
        has_orange_task = getattr(widget, "task", None) is not None
        has_async_task = getattr(widget, "_active_execution_token", None) is not None
        if not has_orange_task and not has_async_task:
            # Double-check is intentional: Spool chains two tasks (load-index
            # then read-patch) via QTimer.singleShot(0, ...).  The first
            # processEvents() above fires on_done for task-1 and queues the
            # singleShot callback; this second call executes that callback and
            # starts task-2.  Without it we'd declare the widget idle while
            # task-2 is still pending, causing races in tests.
            QApplication.processEvents()
            has_orange_task = getattr(widget, "task", None) is not None
            has_async_task = (
                getattr(widget, "_active_execution_token", None) is not None
            )
            if not has_orange_task and not has_async_task:
                QApplication.processEvents()
                return
        time.sleep(0.01)
    raise AssertionError(
        f"{type(widget).__name__} did not become idle within {timeout}s"
    )


def capture_output(output_slot, monkeypatch) -> list:
    """Intercept sends on an Orange output slot; return the collected values list."""
    received: list = []
    monkeypatch.setattr(output_slot, "send", received.append)
    return received


def wait_for_output(qtbot, received: list, count: int = 1, timeout: int = 3000) -> None:
    """Block until `received` holds at least `count` values."""
    qtbot.waitUntil(lambda: len(received) >= count, timeout=timeout)


def wait_for_window_close(window: OWWidget, poll_interval: float = 0.01) -> None:
    """Keep processing events until the user closes an interactive test window."""
    while window.isVisible():
        QApplication.processEvents()
        time.sleep(poll_interval)


@dataclass
class BuiltWorkflow:
    """Container for a test workflow built in an Orange scheme."""

    scheme: object
    nodes_by_title: dict[str, object]
    widgets_by_title: dict[str, OWWidget]
    descriptions_by_name: dict[str, object]


@contextmanager
def widget_context[T: OWWidget](cls: type[T], stored_settings: dict | None = None):
    """
    Context manager for safely creating and cleaning up an OWidget in tests.

    Replicates the essential parts of Orange's WidgetTest.create_widget
    without requiring unittest-style test class inheritance.

    Parameters
    ----------
    cls : type[T]
        The OWidget subclass to instantiate.
    stored_settings : dict, optional
        Settings to restore on the widget, passed directly to __new__.

    Yields
    ------
    T
        The instantiated widget, ready for assertions.

    Examples
    --------
    >>> with widget_context(MyWidget) as w:
    ...     assert w is not None
    """
    signal_manager = DummySignalManager()

    # Rebind the settings handler and clear any defaults cached from disk so
    # the widget always starts from a known state, matching what
    # WidgetTest.create_widget does via reset_default_settings.
    handler = getattr(cls, "settingsHandler", None)
    if handler is not None:
        handler.bind(cls)
        handler.defaults = {}
        handler.global_contexts = []

    # open_widget_classes suppresses Orange's subclassing deprecation guard,
    # which fires when __new__ creates the internal tracking subclass.
    with open_widget_classes():
        widget = cls.__new__(
            cls,
            signal_manager=signal_manager,
            stored_settings=stored_settings,
        )
        widget.__init__()

    # Flush any singleShot timers queued during __init__.
    QApplication.processEvents()
    wait_for_widget_idle(widget)

    try:
        yield widget
    finally:
        # Mirror WidgetTest teardown: notify the widget, close, then schedule
        # deletion so Qt can reclaim resources on the next event loop tick.
        widget.onDeleteWidget()
        widget.close()
        widget.deleteLater()
        QApplication.processEvents()


def build_window_workflow(
    window,
    registry: WidgetRegistry,
    widgets: tuple[tuple[str, str], ...],
    links: tuple[tuple[str, str, str, str], ...] = (),
    *,
    qapp=None,
    clear: bool = True,
) -> BuiltWorkflow:
    """
    Build a workflow in the current window scheme from widget and link specs.

    Parameters
    ----------
    window
        The Orange main window whose current scheme should be populated.
    registry
        The widget registry used to resolve widget descriptions by name.
    widgets
        Tuples of ``(registry_name, title)`` for each node to create.
    links
        Tuples of ``(source_title, output_name, sink_title, input_name)`` for links.
    qapp
        Optional QApplication used to flush events after building.
    clear
        If True, clear all existing nodes from the current scheme before building.

    Returns
    -------
    BuiltWorkflow
        A container with the scheme, created nodes, widgets, and descriptions.
    """
    scheme = window.current_document().scheme()
    if clear:
        for node in list(scheme.nodes):
            scheme.remove_node(node)

    descriptions_by_name = {widget.name: widget for widget in registry.widgets()}
    nodes_by_title: dict[str, object] = {}

    for registry_name, title in widgets:
        desc = descriptions_by_name[registry_name]
        nodes_by_title[title] = scheme.new_node(desc, title=title)

    for source_title, output_name, sink_title, input_name in links:
        source_node = nodes_by_title[source_title]
        sink_node = nodes_by_title[sink_title]
        scheme.new_link(
            source_node,
            source_node.output_channel(output_name),
            sink_node,
            sink_node.input_channel(input_name),
        )

    if qapp is not None:
        qapp.processEvents()

    widgets_by_title = {
        title: scheme.widget_for_node(node) for title, node in nodes_by_title.items()
    }

    if qapp is not None:
        qapp.processEvents()

    return BuiltWorkflow(
        scheme=scheme,
        nodes_by_title=nodes_by_title,
        widgets_by_title=widgets_by_title,
        descriptions_by_name=descriptions_by_name,
    )


class TestWidgetDefaults(WidgetTest):
    """
    DerZug's default widget test suite.
    """

    __test__ = False

    widget: ClassVar[type[ZugWidget]]

    # The inputs needed to init the test Widget of the form:
    # ((input_name, input_value), ...)
    inputs: ClassVar[tuple[tuple[str, object], ...]] = ()
    stored_settings: ClassVar[dict | None] = None

    def create_default_widget(self):
        """Create the configured widget and apply any default input signals."""
        widget = self.create_widget(self.widget, stored_settings=self.stored_settings)
        for input_name, value in self.inputs:
            sig = getattr(widget.Inputs, input_name)
            self.send_signal(sig, value, widget=widget)
        widget.show()
        self.process_events()
        wait_for_widget_idle(widget)
        return widget

    @pytest.fixture()
    def widget_object(self):
        """Yield the default widget instance for tests that need a live widget."""
        widget = self.create_default_widget()
        yield widget
        self.process_events()

    def test_widget_instantiates(self):
        """Widget instantiates with shared metadata and signal definitions."""
        widget_object = self.create_default_widget()
        assert isinstance(widget_object, self.widget)
        assert isinstance(widget_object, ZugWidget)
        assert bool(getattr(widget_object, "name", "").strip())
        assert bool(getattr(widget_object, "description", "").strip())
        assert bool(getattr(widget_object, "category", "").strip())
        assert hasattr(widget_object, "Inputs")
        assert hasattr(widget_object, "Outputs")
        error_general = getattr(widget_object.Error, "general", None)
        if error_general is not None:
            assert not error_general.is_shown()

    def test_widget_exposes_workflow_object(self):
        """Widget returns a workflow `Task` or `Pipe` for compilation."""
        widget_object = self.create_default_widget()
        workflow_obj = widget_object.get_task()

        assert isinstance(workflow_obj, Task | Pipe)

    def test_minimum_size(self):
        """Widget meets Orange minimum-size expectations."""
        self.check_minimum_size(self.create_default_widget())

    def test_image_export(self):
        """Widget supports Orange's image export smoke check."""
        self.check_export_image(self.create_default_widget())

    def test_msg_base_class(self):
        """Widget message groups inherit from the expected base class."""
        self.check_msg_base_class(self.create_default_widget())

    def test_control_area_items_are_top_aligned(self):
        """Control-area content stays packed toward the top of the sidebar."""
        widget_object = self.create_default_widget()
        layout = widget_object.controlArea.layout()

        assert layout is not None
        assert bool(layout.alignment() & Qt.AlignTop)

    def test_ctrl_q_closes_window(self):
        """Pressing Ctrl+Q closes the shown widget window."""
        widget_object = self.create_default_widget()
        widget_object.show()
        self.process_events()
        window = widget_object.window()
        window.activateWindow()
        window.raise_()
        self.process_events()
        assert window.isVisible()

        QTest.keyClick(window, Qt.Key_Q, Qt.ControlModifier)
        deadline = time.monotonic() + 1.0
        while window.isVisible() and time.monotonic() < deadline:
            self.process_events()
            time.sleep(0.01)
        assert not window.isVisible()

    def test_f_enters_fullscreen(self):
        """Pressing f makes main-area widgets enter fullscreen."""
        widget_object = self.create_default_widget()
        if not bool(getattr(widget_object, "want_main_area", True)):
            pytest.skip("Widget does not use a main area")

        widget_object.show()
        self.process_events()
        window = widget_object.window()
        window.activateWindow()
        window.raise_()
        self.process_events()
        assert not window.isFullScreen()

        QTest.keyClick(window, Qt.Key_F)
        deadline = time.monotonic() + 1.0
        while not window.isFullScreen() and time.monotonic() < deadline:
            self.process_events()
            time.sleep(0.01)
        assert window.isFullScreen()
        window.showNormal()
        self.process_events()

    @pytest.mark.show
    def test_show_widget_window(self):
        """Show the widget window and keep it open for manual interaction."""
        widget_object = self.create_default_widget()
        self.show(widget_object)
        window = widget_object.window()
        window.activateWindow()
        window.raise_()
        self.process_events()

        # Interactive show-mode runs are intentionally blocking so a developer
        # can inspect and manipulate the live widget before closing it.
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            wait_for_window_close(window)


class TestPatchDimWidgetDefaults(TestWidgetDefaults):
    """Shared defaults for PatchDimWidget subclasses with selected_dim state."""

    __test__ = False

    widget: ClassVar[type[PatchDimWidget]]
    compatible_patch: ClassVar[object]
    incompatible_patch: ClassVar[object]
    persisted_dim: ClassVar[str] = "time"

    def test_selected_dim_survives_none_then_compatible_patch(self):
        """`None` should not clear the stored dim before a compatible replacement."""
        widget_object = self.create_default_widget()
        assert isinstance(widget_object, PatchDimWidget)
        signal = getattr(widget_object.Inputs, "patch")

        self.send_signal(signal, self.compatible_patch, widget=widget_object)
        self.process_events()
        widget_object.selected_dim = self.persisted_dim

        self.send_signal(signal, None, widget=widget_object)
        self.process_events()
        assert widget_object.selected_dim == self.persisted_dim

        self.send_signal(signal, self.compatible_patch, widget=widget_object)
        self.process_events()
        assert widget_object.selected_dim == self.persisted_dim

    def test_selected_dim_resets_only_on_incompatible_replacement(self):
        """Stored dims should reset only when the next real patch cannot use them."""
        widget_object = self.create_default_widget()
        assert isinstance(widget_object, PatchDimWidget)
        signal = getattr(widget_object.Inputs, "patch")

        self.send_signal(signal, self.compatible_patch, widget=widget_object)
        self.process_events()
        widget_object.selected_dim = self.persisted_dim

        self.send_signal(signal, None, widget=widget_object)
        self.process_events()
        assert widget_object.selected_dim == self.persisted_dim

        self.send_signal(signal, self.incompatible_patch, widget=widget_object)
        self.process_events()
        assert widget_object.selected_dim in getattr(
            widget_object, "_available_dims", ()
        )
        assert widget_object.selected_dim != self.persisted_dim


class TestPatchInputStateDefaults(TestWidgetDefaults):
    """Shared defaults for patch widgets with custom persisted input state."""

    __test__ = False

    compatible_patch: ClassVar[object]
    incompatible_patch: ClassVar[object]
    input_signal_name: ClassVar[str] = "patch"

    def _resolve_input_value(self, value):
        """Materialize deferred test inputs when needed."""
        return value() if callable(value) else value

    def arrange_persisted_input_state(self, widget_object):
        """Install persisted widget state after a compatible patch arrives."""
        raise NotImplementedError

    def assert_persisted_input_state(self, widget_object, state_token) -> None:
        """Assert the arranged state survives a compatible replacement."""
        raise NotImplementedError

    def assert_reset_input_state(self, widget_object, state_token) -> None:
        """Assert incompatible replacement input resets invalid stored state."""
        raise NotImplementedError

    def test_input_state_survives_none_then_compatible_patch(self):
        """`None` should not clear persisted state before a compatible replacement."""
        widget_object = self.create_default_widget()
        signal = getattr(widget_object.Inputs, self.input_signal_name)
        compatible = self._resolve_input_value(self.compatible_patch)

        self.send_signal(signal, compatible, widget=widget_object)
        self.process_events()
        state_token = self.arrange_persisted_input_state(widget_object)
        self.process_events()

        self.send_signal(signal, None, widget=widget_object)
        self.process_events()
        self.assert_persisted_input_state(widget_object, state_token)

        self.send_signal(
            signal,
            self._resolve_input_value(self.compatible_patch),
            widget=widget_object,
        )
        self.process_events()
        self.assert_persisted_input_state(widget_object, state_token)

    def test_input_state_resets_only_on_incompatible_replacement(self):
        """Persisted state should reset only when a real replacement cannot use it."""
        widget_object = self.create_default_widget()
        signal = getattr(widget_object.Inputs, self.input_signal_name)
        compatible = self._resolve_input_value(self.compatible_patch)

        self.send_signal(signal, compatible, widget=widget_object)
        self.process_events()
        state_token = self.arrange_persisted_input_state(widget_object)
        self.process_events()

        self.send_signal(signal, None, widget=widget_object)
        self.process_events()
        self.assert_persisted_input_state(widget_object, state_token)

        self.send_signal(
            signal,
            self._resolve_input_value(self.incompatible_patch),
            widget=widget_object,
        )
        self.process_events()
        self.assert_reset_input_state(widget_object, state_token)
