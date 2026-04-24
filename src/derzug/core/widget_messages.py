"""Orange message-bar and traceback helpers for DerZug widgets."""

from __future__ import annotations

from AnyQt.QtCore import QEvent, QPoint, Qt
from AnyQt.QtWidgets import QApplication, QLabel, QMenu, QWidget, QWidgetAction

from derzug.views.orange_errors import DerZugErrorDialog, _build_exception_report_data


class WidgetMessageMixin:
    """Shared Orange message-bar behavior for widgets."""

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

    def _open_last_error_dialog(self) -> None:
        """Show the stored traceback for the most recent unhandled widget error."""
        if self._last_error_exc is None:
            return
        details, traceback_text = _build_exception_report_data(self._last_error_exc)
        dialog = DerZugErrorDialog(details, traceback_text)
        dialog.exec()
