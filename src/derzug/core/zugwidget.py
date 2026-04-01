"""
Base widget class for DerZug.
"""

from __future__ import annotations

from AnyQt.QtCore import QEvent, QPoint, Qt, QTimer
from AnyQt.QtGui import QKeyEvent, QKeySequence, QShortcut, QShowEvent
from AnyQt.QtWidgets import (
    QAbstractSpinBox,
    QAction,
    QApplication,
    QBoxLayout,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from Orange.widgets.widget import OWWidget

from derzug.core.widget_runtime import WidgetExecutionRequest, WidgetExecutionRuntime
from derzug.views.orange_errors import DerZugErrorDialog, _build_exception_report_data
from derzug.workflow import Pipe, Task


class _WidgetKeyboardShortcutsDialog(QDialog):
    """Keyboard shortcuts reference dialog for a single widget."""

    def __init__(
        self, title: str, sections: list[tuple[str, list[tuple[str, str]]]], parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(title)

        layout = QVBoxLayout(self)
        rows: list[str] = []
        for heading, items in sections:
            if not items:
                continue
            rows.append(f"<b>{heading}</b><br>")
            rows.extend(
                f"<b>{keys}</b>: {description}<br>" for keys, description in items
            )
            rows.append("<br>")

        text = QLabel("".join(rows).rstrip("<br>"), self)
        text.setTextFormat(Qt.RichText)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, Qt.Horizontal, self)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        layout.setSizeConstraint(QVBoxLayout.SetFixedSize)


class ZugWidget(OWWidget, openclass=True):
    """
    Thin OWWidget base class providing a consistent run/result lifecycle.

    Subclasses implement ``_run()`` to perform their core operation and
    optionally override ``_on_result()`` to update display areas after each run.
    """

    _FOCUS_EXCLUDE = (
        QLineEdit,
        QTextEdit,
        QPlainTextEdit,
        QAbstractSpinBox,
        QComboBox,
    )
    is_source = False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle shared shortcuts before deferring to Orange's default handling."""
        if self._should_toggle_fullscreen(event):
            self._toggle_fullscreen()
            event.accept()
            return
        if self._should_send_pending_state(event):
            if self._flush_pending_outputs():
                event.accept()
                return
        if self._should_close_window(event):
            self._close_window()
            event.accept()
            return
        if self._should_raise_canvas(event):
            self._raise_canvas()
            event.accept()
            return
        if self._should_consume_escape(event):
            self._handle_escape()
            event.accept()
            return
        super().keyPressEvent(event)

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the base widget and install shared window shortcuts."""
        super().__init__(*args, **kwargs)
        self._ui_refresh_pending = False
        self._control_area_width_check_pending = False
        self._dirty_delayed_outputs: set[str] = set()
        self._last_error_exc: (
            tuple[type[BaseException], BaseException, object] | None
        ) = None
        self._reported_error_during_run = False
        self._message_bar_click_timer = QTimer(self)
        self._message_bar_click_timer.setSingleShot(True)
        self._message_bar_click_timer.timeout.connect(
            self._show_pending_message_bar_popup
        )
        self._pending_message_bar_popup_pos: QPoint | None = None
        self._execution_runtime = WidgetExecutionRuntime(
            self,
            execute_request=self._execute_execution_request,
            apply_result=self._apply_async_result,
            apply_error=self._apply_async_error,
            apply_empty_result=self._apply_async_empty_result,
            handle_preflight_error=self._handle_async_preflight_error,
            handle_worker_unavailable=self._handle_async_worker_unavailable,
        )
        self._compact_control_area_layout()
        self.statusBar()
        if getattr(self, "message_bar", None) is not None:
            self._install_message_bar_event_filters()
        self._fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key_F), self)
        self._fullscreen_shortcut.setContext(Qt.WindowShortcut)
        self._fullscreen_shortcut.activated.connect(self._on_fullscreen_shortcut)
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._escape_shortcut.setContext(Qt.WindowShortcut)
        self._escape_shortcut.activated.connect(self._on_escape_shortcut)
        self._send_pending_shortcut = QShortcut(QKeySequence(Qt.Key_S), self)
        self._send_pending_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._send_pending_shortcut.activated.connect(self._on_send_pending_shortcut)
        self._close_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._close_shortcut.setContext(Qt.WindowShortcut)
        self._close_shortcut.activated.connect(self._on_close_shortcut)
        self._install_help_menu_actions()

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        """Open a traceback dialog when the message bar is double-clicked."""
        if self._is_message_bar_target(watched) and self._last_error_exc is not None:
            if (
                event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
            ):
                self._schedule_message_bar_popup(event.globalPos())
                event.accept()
                return True
            if (
                event.type() == QEvent.MouseButtonDblClick
                and event.button() == Qt.LeftButton
            ):
                self._cancel_message_bar_popup()
                self._open_last_error_dialog()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _install_message_bar_event_filters(self) -> None:
        """Install traceback-opening filters on the message bar and its children."""
        message_bar = getattr(self, "message_bar", None)
        if message_bar is None:
            return
        message_bar.installEventFilter(self)
        for child in message_bar.findChildren(QWidget):
            child.installEventFilter(self)

    def _is_message_bar_target(self, watched: QWidget | None) -> bool:
        """Return True when the watched object is the message bar or its child."""
        message_bar = getattr(self, "message_bar", None)
        if message_bar is None or watched is None:
            return False
        current = watched
        while current is not None:
            if current is message_bar:
                return True
            current = current.parentWidget()
        return False

    def _schedule_message_bar_popup(self, global_pos: QPoint) -> None:
        """Delay the default message popup long enough to allow a double-click."""
        self._pending_message_bar_popup_pos = QPoint(global_pos)
        interval = max(QApplication.doubleClickInterval(), 1)
        self._message_bar_click_timer.start(interval)

    def _cancel_message_bar_popup(self) -> None:
        """Cancel any pending single-click popup action."""
        self._message_bar_click_timer.stop()
        self._pending_message_bar_popup_pos = None

    def _show_pending_message_bar_popup(self) -> None:
        """Display Orange's full message popup after a completed single click."""
        message_bar = getattr(self, "message_bar", None)
        popup_pos = self._pending_message_bar_popup_pos
        self._pending_message_bar_popup_pos = None
        if message_bar is None or popup_pos is None:
            return
        message = getattr(message_bar, "message", None)
        if not message:
            return
        popup = QMenu(message_bar)
        label = QLabel(
            message_bar,
            textInteractionFlags=Qt.TextBrowserInteraction,
            openExternalLinks=message_bar.openExternalLinks(),
        )
        label.setContentsMargins(4, 4, 4, 4)
        label.setText(message_bar._styled(message.asHtml()))
        label.linkActivated.connect(message_bar.linkActivated)
        label.linkHovered.connect(message_bar.linkHovered)
        action = QWidgetAction(popup)
        action.setDefaultWidget(label)
        popup.addAction(action)
        popup.popup(popup_pos, action)

    def _error_slot(self, slot_name: str):
        """Return the named Error slot, falling back to Error.general when present."""
        slot = getattr(self.Error, slot_name, None)
        if slot is not None:
            return slot
        return getattr(self.Error, "general", None)

    def _show_error_message(self, slot_name: str, *fmt_args) -> None:
        """Show a non-exception error banner and clear any stored traceback."""
        self._cancel_message_bar_popup()
        self._reported_error_during_run = True
        self._last_error_exc = None
        slot = self._error_slot(slot_name)
        if slot is not None:
            slot(*fmt_args)
        if getattr(self, "message_bar", None) is not None:
            self._install_message_bar_event_filters()

    def _show_exception(
        self,
        slot_name: str,
        exc: BaseException,
        *fmt_args,
    ) -> None:
        """Show an exception-backed error banner and store traceback details."""
        self._cancel_message_bar_popup()
        self._reported_error_during_run = True
        self._last_error_exc = (type(exc), exc, exc.__traceback__)
        slot = self._error_slot(slot_name)
        if slot is not None:
            slot(*fmt_args, str(exc))
        if getattr(self, "message_bar", None) is not None:
            self._install_message_bar_event_filters()

    def _compact_control_area_layout(self) -> None:
        """Keep control-area content packed toward the top of the sidebar."""
        layout = getattr(self.controlArea, "layout", lambda: None)()
        if layout is None:
            return
        layout.setAlignment(Qt.AlignTop)

    def _help_menu(self) -> QMenu | None:
        """Return the widget-window Help menu, creating it when needed."""
        menu_bar = self.menuBar()
        if not isinstance(menu_bar, QMenuBar):
            return None
        help_menu = menu_bar.findChild(QMenu, "help-menu")
        if help_menu is not None:
            return help_menu
        help_menu = menu_bar.addMenu("Help")
        help_menu.setObjectName("help-menu")
        return help_menu

    def _install_help_menu_actions(self) -> None:
        """Add DerZug-specific help actions to the widget Help menu."""
        help_menu = self._help_menu()
        if help_menu is None:
            return
        if getattr(self, "_keyboard_shortcuts_action", None) is not None:
            return
        self._keyboard_shortcuts_action = QAction("Keyboard Shortcuts", self)
        self._keyboard_shortcuts_action.triggered.connect(self.open_keyboard_shortcuts)
        help_menu.addAction(self._keyboard_shortcuts_action)
        self._ensure_menu_bar_visible()

    def _ensure_menu_bar_visible(self) -> None:
        """Show the widget menu bar unless a native platform menu owns it."""
        menu_bar = self.menuBar()
        if not isinstance(menu_bar, QMenuBar):
            return
        if menu_bar.isNativeMenuBar():
            return
        menu_bar.setVisible(True)
        for action in self.actions():
            if action.objectName() == "action-show-menu-bar" and action.isCheckable():
                action.setChecked(True)
                break

    def shared_shortcuts(self) -> list[tuple[str, str]]:
        """Return shortcut rows shared by all DerZug widgets."""
        return [
            ("F", "Toggle fullscreen"),
            ("S", "Send unsent state"),
            ("Ctrl+Q", "Close window"),
            ("F1", "Open widget help"),
            ("Shift+~", "Raise canvas window"),
        ]

    def widget_shortcuts(self) -> list[tuple[str, str]]:
        """Return widget-specific shortcut rows. Subclasses can override this."""
        return []

    def keyboard_shortcut_sections(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """Return the shortcuts sections to show in the widget help dialog."""
        sections = [("Window", self.shared_shortcuts())]
        widget_specific = self.widget_shortcuts()
        if widget_specific:
            sections.append((self.name, widget_specific))
        return sections

    def open_keyboard_shortcuts(self) -> None:
        """Show the keyboard shortcuts reference dialog for this widget."""
        title = f"{self.name} Keyboard Shortcuts"
        dlg = _WidgetKeyboardShortcutsDialog(
            title=title,
            sections=self.keyboard_shortcut_sections(),
            parent=self,
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()
        dlg.raise_()

    def _should_toggle_fullscreen(self, event: QKeyEvent) -> bool:
        """Return True when an unmodified `f` should toggle fullscreen."""
        if event.key() != Qt.Key_F:
            return False
        if event.modifiers() != Qt.NoModifier:
            return False
        return not self._focus_should_keep_key_behavior(QApplication.focusWidget())

    def _should_send_pending_state(self, event: QKeyEvent) -> bool:
        """Return True when plain `s` should flush delayed outputs."""
        if event.key() != Qt.Key_S:
            return False
        if event.modifiers() != Qt.NoModifier:
            return False
        return not self._focus_should_keep_key_behavior(QApplication.focusWidget())

    def _delayed_output_names(self) -> tuple[str, ...]:
        """Return delayed output names for this widget."""
        return ()

    def _mark_output_dirty(self, name: str) -> None:
        """Mark one declared delayed output as having unsent local changes."""
        if name in self._delayed_output_names():
            self._dirty_delayed_outputs.add(name)

    def _clear_output_dirty(self, name: str) -> None:
        """Clear the pending flag for one delayed output."""
        self._dirty_delayed_outputs.discard(name)

    def _is_output_dirty(self, name: str) -> bool:
        """Return True when a delayed output currently has unsent changes."""
        return name in self._dirty_delayed_outputs

    def _flush_delayed_output(self, name: str) -> bool:
        """Flush one delayed output by name and return True if anything sent."""
        return False

    def _flush_pending_outputs(self) -> bool:
        """Flush all dirty delayed outputs declared by this widget."""
        sent_any = False
        for name in self._delayed_output_names():
            if not self._is_output_dirty(name):
                continue
            if self._flush_delayed_output(name):
                sent_any = True
        return sent_any

    def _focus_should_keep_key_behavior(self, widget: QWidget | None) -> bool:
        """
        Return True when the focused widget should keep normal text-entry behavior.
        """
        return isinstance(widget, self._FOCUS_EXCLUDE)

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen state on the top-level widget window."""
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
            return
        window.showFullScreen()

    def _on_fullscreen_shortcut(self) -> None:
        """Toggle fullscreen from the shared shortcut unless text input has focus."""
        if self._focus_should_keep_key_behavior(QApplication.focusWidget()):
            return
        self._toggle_fullscreen()

    def _on_escape_shortcut(self) -> None:
        """Cancel active interactions and restore focus to the widget window."""
        self._handle_escape()

    def _on_send_pending_shortcut(self) -> None:
        """Flush delayed outputs from a shared window shortcut."""
        if self._focus_should_keep_key_behavior(QApplication.focusWidget()):
            return
        self._flush_pending_outputs()

    def _should_raise_canvas(self, event: QKeyEvent) -> bool:
        """Return True when Shift+~ should raise the canvas window."""
        if event.key() != Qt.Key_AsciiTilde:
            return False
        if event.modifiers() != Qt.ShiftModifier:
            return False
        return not self._focus_should_keep_key_behavior(QApplication.focusWidget())

    def _raise_canvas(self) -> None:
        """Bring the DerZug canvas window to the front."""
        from derzug.views import orange as orange_view

        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, orange_view.DerZugMainWindow):
                widget.raise_()
                widget.activateWindow()
                return

    def _should_close_window(self, event: QKeyEvent) -> bool:
        """Return True when `Ctrl+Q` should close the widget window."""
        if event.key() != Qt.Key_Q:
            return False
        if event.modifiers() != Qt.ControlModifier:
            return False
        return not self._focus_should_keep_key_behavior(QApplication.focusWidget())

    def _should_consume_escape(self, event: QKeyEvent) -> bool:
        """Return True when plain Escape should be blocked from closing widgets."""
        return event.key() == Qt.Key_Escape and event.modifiers() == Qt.NoModifier

    def _handle_escape(self) -> None:
        """Cancel widget-specific interactions, then return focus to the window."""
        self._cancel_active_interactions()
        self._restore_window_focus()

    def _cancel_active_interactions(self) -> None:
        """Cancel any widget-specific transient interaction state."""
        return

    def _restore_window_focus(self) -> None:
        """Clear child focus and return keyboard focus to the top-level widget."""
        window = self.window()
        focus_widget = QApplication.focusWidget()
        if (
            focus_widget is not None
            and focus_widget is not self
            and focus_widget.window() is window
        ):
            focus_widget.clearFocus()
        if isinstance(window, QWidget):
            window.setFocus(Qt.ShortcutFocusReason)
            window.activateWindow()
        if self is not window:
            self.setFocus(Qt.ShortcutFocusReason)

    def _close_window(self) -> None:
        """Close the top-level widget window."""
        self.window().close()

    def _on_close_shortcut(self) -> None:
        """Close the window from the shared shortcut unless text input has focus."""
        if self._focus_should_keep_key_behavior(QApplication.focusWidget()):
            return
        self._close_window()

    def showEvent(self, event: QShowEvent) -> None:
        """Ensure newly shown source widgets can become active sources."""
        super().showEvent(event)
        self._ensure_menu_bar_visible()
        self._flush_pending_ui_refresh()

        # Let Qt finish laying out the Orange sidebar, then widen it if the
        # control-area contents need more room than the restored/default geometry.
        self._schedule_control_area_width_check()
        if not bool(getattr(self, "is_source", False)):
            return
        self._ensure_active_source_selection()
        # Delay one tick so WindowListManager sees the shown widget first.
        QTimer.singleShot(0, self._ensure_active_source_selection)

    def _is_ui_visible(self) -> bool:
        """Return True when the widget's top-level window is currently visible."""
        return bool(self.window().isVisible())

    def _request_ui_refresh(self) -> None:
        """Refresh UI immediately when visible, otherwise defer until shown."""
        if self._is_ui_visible():
            self._ui_refresh_pending = False
            self._refresh_ui()
            self._ensure_control_area_width()
            self._schedule_control_area_width_check()
            return
        self._ui_refresh_pending = True

    def _flush_pending_ui_refresh(self) -> None:
        """Apply one deferred UI refresh after the widget becomes visible."""
        if not self._ui_refresh_pending:
            return
        self._ui_refresh_pending = False
        self._refresh_ui()

    def _refresh_ui(self) -> None:
        """Override in subclasses to update visible widget state."""
        return

    def _schedule_control_area_width_check(self) -> None:
        """Re-check sidebar width after Qt applies pending layout updates."""
        if self._control_area_width_check_pending:
            return
        self._control_area_width_check_pending = True

        def _run() -> None:
            self._control_area_width_check_pending = False
            self._ensure_control_area_width()

        QTimer.singleShot(0, _run)

    def _ensure_control_area_width(self) -> None:
        """Expand the sidebar when control contents outgrow the current width."""
        if not bool(getattr(self, "controlAreaVisible", True)):
            return
        control_area = getattr(self, "controlArea", None)
        if control_area is None:
            return

        target_width = self._control_area_target_width(control_area)
        if target_width <= 0:
            return
        if control_area.minimumWidth() < target_width:
            control_area.setMinimumWidth(target_width)
        if control_area.width() >= target_width:
            return

        # Saved widget geometries can restore a sidebar that is narrower than the
        # current controls, so grow the top-level window just enough to fit.
        window = self.window()
        if window.isFullScreen() or window.isMaximized():
            return
        window.resize(
            window.width() + (target_width - control_area.width()), window.height()
        )

    def _control_area_target_width(self, control_area: QWidget) -> int:
        """Return the width needed by the currently visible sidebar contents."""
        layout = control_area.layout()
        if layout is None:
            return max(
                control_area.sizeHint().width(),
                control_area.minimumSizeHint().width(),
            )

        target_width = self._layout_target_width(layout)
        if target_width > 0:
            return target_width
        return max(
            control_area.sizeHint().width(),
            control_area.minimumSizeHint().width(),
        )

    def _layout_target_width(self, layout) -> int:
        """Return the horizontal width required by visible widgets in a layout."""
        visible_widths: list[int] = []
        child_layout_widths: list[int] = []
        visible_spacing = 0

        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                if widget.isHidden():
                    continue
                if isinstance(widget, QLabel) and widget.wordWrap():
                    # Word-wrapped labels don't constrain sidebar width; they
                    # wrap vertically.
                    visible_widths.append(widget.minimumSizeHint().width())
                else:
                    visible_widths.append(
                        max(widget.sizeHint().width(), widget.minimumSizeHint().width())
                    )
                continue
            if child_layout is not None:
                child_width = self._layout_target_width(child_layout)
                if child_width > 0:
                    child_layout_widths.append(child_width)

        direction = getattr(layout, "direction", lambda: None)()
        if isinstance(layout, QBoxLayout) and direction in (
            QBoxLayout.LeftToRight,
            QBoxLayout.RightToLeft,
        ):
            visible_count = len(visible_widths) + len(child_layout_widths)
            if visible_count > 1:
                visible_spacing = layout.spacing() * (visible_count - 1)
            target_width = (
                sum(visible_widths) + sum(child_layout_widths) + visible_spacing
            )
        else:
            target_width = max([0, *visible_widths, *child_layout_widths])

        margins = layout.contentsMargins()
        return target_width + margins.left() + margins.right()

    def _ensure_active_source_selection(self) -> None:
        """Ask the app-level manager to select an active source if needed."""
        from derzug.views import orange as orange_view

        manager = orange_view._APP_ACTIVE_SOURCE_MANAGER
        main_window = orange_view._APP_ACTIVE_SOURCE_MAIN_WINDOW
        if manager is not None and main_window is not None:
            try:
                if manager._active_widget is None:
                    manager._set_active_widget(main_window, self)
                    return
                current_sources = manager._source_widgets()
                if manager._active_widget not in current_sources:
                    manager._set_active_widget(main_window, self)
                else:
                    manager.ensure_active_source(main_window)
            except Exception:
                return
            return
        app = QApplication.instance()
        if app is None:
            return
        candidates = [*app.topLevelWidgets(), *app.allWidgets()]
        seen: set[int] = set()
        for top_level in candidates:
            key = id(top_level)
            if key in seen:
                continue
            seen.add(key)
            manager = getattr(top_level, "active_source_manager", None)
            if manager is None:
                continue
            try:
                if manager._active_widget is None:
                    manager._set_active_widget(top_level, self)
                    return
                # If no valid active source exists, promote this newly shown source.
                current_sources = manager._source_widgets()
                if manager._active_widget not in current_sources:
                    manager._set_active_widget(top_level, self)
                else:
                    manager.ensure_active_source(top_level)
            except Exception:
                return
            return

    def run(self) -> None:
        """
        Execute the widget's operation with consistent error handling.

        Clears all error and warning banners, calls ``_run()``, and passes the
        result to ``_on_result()``. Any unhandled exception is routed to
        ``Error.general`` if the subclass declares that slot.

        Examples
        --------
        >>> widget.run()  # typically triggered by input signals or control callbacks
        """
        self.Error.clear()
        self.Warning.clear()
        self._reported_error_during_run = False
        if self._async_teardown_started:
            return
        if self._supports_async_execution():
            self._run_async()
            return
        try:
            result = self._run()
        except Exception as exc:
            self._show_exception("general", exc)
            self._on_result(None)
            return
        self._cancel_message_bar_popup()
        if not self._reported_error_during_run:
            self._last_error_exc = None
        self._on_result(result)

    def _open_last_error_dialog(self) -> None:
        """Show the stored traceback for the most recent unhandled widget error."""
        if self._last_error_exc is None:
            return
        details, traceback_text = _build_exception_report_data(self._last_error_exc)
        dialog = DerZugErrorDialog(details, traceback_text)
        dialog.exec()

    def _supports_async_execution(self) -> bool:
        """Return True when this widget should dispatch execution off-thread."""
        return False

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Return a worker-safe execution request or None for an empty result."""
        return None

    def _build_task_execution_request(
        self,
        workflow_obj: Task | Pipe | None,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ) -> WidgetExecutionRequest | None:
        """Return a standard request for one canonical task-backed execution."""
        if workflow_obj is None:
            return None
        return WidgetExecutionRequest(
            workflow_obj=workflow_obj,
            input_values=input_values,
            output_names=output_names,
        )

    @staticmethod
    def _execute_execution_request(request: WidgetExecutionRequest):
        """Execute one captured request in a worker thread."""
        if request.execute is not None:
            return request.execute()
        return ZugWidget._execute_task_or_pipe_static(
            request.workflow_obj,
            input_values=request.input_values or {},
            output_names=request.output_names,
        )

    def _run_async(self) -> None:
        """Dispatch one execution request to the widget's worker thread."""
        self._execution_runtime.dispatch(
            self._build_execution_request,
        )

    def _apply_async_result(self, result) -> None:
        """Apply a worker result on the main thread."""
        self._cancel_message_bar_popup()
        if not self._reported_error_during_run:
            self._last_error_exc = None
        self._apply_async_completion_payload(result)

    def _apply_async_error(self, exc: Exception) -> None:
        """Apply a worker exception on the main thread."""
        self._handle_execution_exception(exc)
        self._apply_async_completion_payload(None)

    def _apply_async_empty_result(self) -> None:
        """Apply an empty async result without surfacing an error."""
        self._cancel_message_bar_popup()
        if not self._reported_error_during_run:
            self._last_error_exc = None
        self._apply_async_completion_payload(None)

    def _handle_async_preflight_error(self, exc: Exception) -> None:
        """Handle request-building failures before work reaches the worker."""
        if not self._reported_error_during_run:
            self._show_exception("general", exc)
        self._apply_async_completion_payload(None)

    def _handle_async_worker_unavailable(self) -> None:
        """Handle attempts to dispatch work after the runtime is unavailable."""
        self._show_error_message("general", "worker is unavailable")
        self._apply_async_completion_payload(None)

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Show one execution exception on the main thread."""
        self._show_exception("general", exc)

    def _apply_async_completion_payload(self, result) -> None:
        """Apply one async completion unless Qt teardown already won the race."""
        try:
            self._on_result(result)
        except RuntimeError as exc:
            if self._should_ignore_async_runtime_error(exc):
                return
            raise

    @staticmethod
    def _should_ignore_async_runtime_error(exc: RuntimeError) -> bool:
        """Return True for Qt wrapper teardown races during async result delivery."""
        text = str(exc)
        return "wrapped C/C++ object of type" in text and "has been deleted" in text

    def _execute_workflow_object(
        self,
        workflow_obj: Task | Pipe | None,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ):
        """Execute one validated workflow object and normalize widget outputs."""
        if workflow_obj is None:
            return None
        try:
            result = self._execute_task_or_pipe(
                workflow_obj,
                input_values=input_values,
                output_names=output_names,
            )
        except Exception as exc:
            self._handle_execution_exception(exc)
            return None
        return self._unwrap_execution_result(result, output_names)

    def _shutdown_async_executor(self) -> None:
        """Stop the per-widget worker pool."""
        self._execution_runtime.shutdown()

    def onDeleteWidget(self) -> None:
        """Release widget-owned worker resources before teardown."""
        self._shutdown_async_executor()
        super().onDeleteWidget()

    @property
    def _active_execution_token(self) -> int | None:
        """Compatibility view of the runtime's active execution token."""
        return self._execution_runtime.active_execution_token

    @property
    def _async_teardown_started(self) -> bool:
        """Compatibility view of the runtime teardown state."""
        return self._execution_runtime.teardown_started

    def _run(self):
        """Override to implement the widget's core computation; return the result."""
        return None

    def _on_result(self, result) -> None:
        """
        Called after each run() with the result, or None on error.

        Override to update the widget display.
        """

    def get_task(self) -> Task | Pipe:
        """Return the current workflow representation for this widget."""
        raise TypeError(f"{type(self).__name__} does not implement get_task()")

    def _execute_task_or_pipe(
        self,
        workflow_obj: Task | Pipe,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ):
        """Execute one task or sub-pipe for interactive widget use."""
        return self._execute_task_or_pipe_static(
            workflow_obj,
            input_values=input_values,
            output_names=output_names,
        )

    @staticmethod
    def _execute_task_or_pipe_static(
        workflow_obj: Task | Pipe,
        *,
        input_values: dict[str, object],
        output_names: tuple[str, ...],
    ):
        """Execute one task or sub-pipe without touching widget state."""
        if workflow_obj is None:
            raise TypeError("workflow_obj may not be None without request.execute")
        if isinstance(workflow_obj, Task):
            raw = workflow_obj.run(**input_values)
            return ZugWidget._normalize_task_outputs(workflow_obj, raw, output_names)
        if isinstance(workflow_obj, Pipe):
            results = workflow_obj.run(**input_values, output_keys=list(output_names))
            return {name: results.get(name) for name in output_names}
        raise TypeError(f"unsupported workflow object {workflow_obj!r}")

    @staticmethod
    def _unwrap_execution_result(result, output_names: tuple[str, ...]):
        """Return the single requested output value when possible."""
        if isinstance(result, dict) and len(output_names) == 1:
            return result.get(output_names[0])
        return result

    @staticmethod
    def _normalize_task_outputs(
        task: Task,
        raw: object,
        output_names: tuple[str, ...],
    ):
        """Normalize task return values for widget `_on_result()` handlers."""
        mapping = task.resolved_scalar_output_variables()
        if not mapping:
            return None
        if len(mapping) == 1:
            value = raw
            if len(output_names) == 1:
                return value
            return {output_names[0]: value}
        if isinstance(raw, dict):
            return {name: raw.get(name) for name in output_names}
        if isinstance(raw, tuple) and len(raw) == len(mapping):
            normalized = dict(zip(mapping.keys(), raw, strict=True))
            return {name: normalized.get(name) for name in output_names}
        raise ValueError(
            f"task {task.__class__.__name__} returned {raw!r} "
            f"but outputs are {tuple(mapping)}"
        )
