"""Tests for shared ZugWidget behavior."""

from __future__ import annotations

import pytest
from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QWidget,
)
from derzug.core.zugwidget import ZugWidget
from derzug.utils.testing import widget_context
from derzug.views.orange_errors import DerZugErrorDialog
from derzug.widgets.aggregate import Aggregate
from derzug.widgets.analytic import Analytic
from derzug.widgets.calculus import Calculus
from derzug.widgets.code import Code
from derzug.widgets.coords import Coords
from derzug.widgets.detrend import Detrend
from derzug.widgets.fbe import FBE
from derzug.widgets.filter import Filter
from derzug.widgets.fourier import Fourier
from derzug.widgets.norm import Norm
from derzug.widgets.normalize import Normalize
from derzug.widgets.patchviewer import PatchViewer
from derzug.widgets.playaudio import PlayAudio
from derzug.widgets.resample import Resample
from derzug.widgets.rolling import Rolling
from derzug.widgets.select import Select
from derzug.widgets.spool import Spool
from derzug.widgets.stft import Stft
from derzug.widgets.ufunc import UFuncOperator
from derzug.widgets.waterfall import Waterfall
from derzug.widgets.wiggle import Wiggle
from Orange.widgets import gui
from Orange.widgets.widget import Msg

ALL_WIDGET_CLASSES = (
    Aggregate,
    Analytic,
    Calculus,
    Code,
    Coords,
    Detrend,
    FBE,
    Filter,
    Fourier,
    Normalize,
    Norm,
    PatchViewer,
    PlayAudio,
    Resample,
    Rolling,
    Select,
    Spool,
    Stft,
    UFuncOperator,
    Waterfall,
    Wiggle,
)


class _ShortcutWidget(ZugWidget):
    """Concrete test widget used to verify base keyboard shortcuts."""

    name = "Shortcut Widget"
    description = "Test widget for base shortcuts"
    category = "Test"

    def __init__(self):
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Inputs")
        self.input_edit = QLineEdit(box)
        box.layout().addWidget(self.input_edit)
        self.input_combo = QComboBox(box)
        self.input_combo.addItems(["one", "two"])
        box.layout().addWidget(self.input_combo)

    def widget_shortcuts(self) -> list[tuple[str, str]]:
        """Return a widget-specific shortcut for dialog coverage."""
        return [("Ctrl+R", "Run widget")]


class _FailingWidget(ZugWidget):
    """Concrete test widget whose run path raises an exception."""

    name = "Failing Widget"
    description = "Test widget for traceback popup"
    category = "Test"

    class Error(ZugWidget.Error):
        general = Msg("{}")

    def _run(self):
        raise RuntimeError("boom")


class _HandledFailingWidget(ZugWidget):
    """Concrete test widget that catches an exception into a named error slot."""

    name = "Handled Failing Widget"
    description = "Test widget for caught-exception traceback popup"
    category = "Test"

    class Error(ZugWidget.Error):
        specific = Msg("Specific failure: {}")
        general = Msg("{}")

    def trigger_handled_failure(self) -> None:
        """Raise and catch an error so the banner uses a named slot."""
        try:
            raise ValueError("handled boom")
        except Exception as exc:
            self._show_exception("specific", exc)

    def trigger_plain_message(self) -> None:
        """Show a non-exception message that should clear stored traceback state."""
        self._show_error_message("specific", "plain problem")


class _RefreshWidget(ZugWidget):
    """Concrete test widget used to verify deferred UI refresh behavior."""

    name = "Refresh Widget"
    description = "Test widget for deferred UI refresh"
    category = "Test"

    def __init__(self):
        super().__init__()
        self.refresh_count = 0

    def _refresh_ui(self) -> None:
        """Count how many visible refreshes the base class triggers."""
        self.refresh_count += 1


class _SidebarGrowthWidget(ZugWidget):
    """Concrete test widget whose sidebar widens during refresh."""

    name = "Sidebar Growth Widget"
    description = "Test widget for control-area sizing"
    category = "Test"

    def __init__(self):
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Parameters")
        self.action_button = gui.button(box, self, "Short")
        self._request_ui_refresh()

    def _refresh_ui(self) -> None:
        """Widen the button label to simulate late sidebar content changes."""
        self.action_button.setText("A much longer control label")


class _HiddenSidebarWidthWidget(ZugWidget):
    """Concrete test widget with hidden wide content in the sidebar."""

    name = "Hidden Sidebar Width Widget"
    description = "Test widget for hidden control-area sizing"
    category = "Test"

    def __init__(self):
        super().__init__()
        box = gui.widgetBox(self.controlArea, "Parameters")
        self.visible_label = QLabel("Short", box)
        box.layout().addWidget(self.visible_label)
        self.hidden_label = QLabel("A very long hidden control label", box)
        box.layout().addWidget(self.hidden_label)
        self.hidden_label.hide()


@pytest.fixture
def shortcut_widget(qtbot):
    """Return a live widget instance for shortcut tests."""
    with widget_context(_ShortcutWidget) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget


class TestZugWidgetShortcuts:
    """Tests for common keyboard shortcuts implemented on ZugWidget."""

    def test_f_toggles_fullscreen(self, shortcut_widget, qtbot):
        """Pressing f toggles fullscreen on the widget window."""
        assert not shortcut_widget.window().isFullScreen()

        qtbot.keyClick(shortcut_widget, Qt.Key_F)
        assert shortcut_widget.window().isFullScreen()

        qtbot.keyClick(shortcut_widget, Qt.Key_F)
        assert not shortcut_widget.window().isFullScreen()

    def test_f_ignored_while_typing(self, shortcut_widget, qtbot):
        """Pressing f in a text input keeps text behavior and skips fullscreen."""
        shortcut_widget.input_edit.setFocus()
        qtbot.wait(10)
        assert not shortcut_widget.window().isFullScreen()

        qtbot.keyClick(shortcut_widget.input_edit, Qt.Key_F)

        assert shortcut_widget.input_edit.text() == "f"
        assert not shortcut_widget.window().isFullScreen()

    def test_modified_f_does_not_toggle(self, shortcut_widget, qtbot):
        """Modified f shortcuts should not trigger fullscreen toggling."""
        assert not shortcut_widget.window().isFullScreen()

        qtbot.keyClick(shortcut_widget, Qt.Key_F, modifier=Qt.ControlModifier)

        assert not shortcut_widget.window().isFullScreen()

    def test_ctrl_q_closes_window(self, shortcut_widget, qtbot):
        """Pressing Ctrl+Q closes the widget window."""
        assert shortcut_widget.window().isVisible()

        qtbot.keyClick(shortcut_widget, Qt.Key_Q, modifier=Qt.ControlModifier)
        qtbot.waitUntil(lambda: not shortcut_widget.window().isVisible(), timeout=1000)

    def test_q_ignored_while_typing(self, shortcut_widget, qtbot):
        """Pressing plain q in a text input keeps text behavior and window open."""
        shortcut_widget.input_edit.setFocus()
        qtbot.wait(10)
        assert shortcut_widget.window().isVisible()

        qtbot.keyClick(shortcut_widget.input_edit, Qt.Key_Q)

        assert shortcut_widget.input_edit.text() == "q"
        assert shortcut_widget.window().isVisible()

    def test_ctrl_q_ignored_while_typing(self, shortcut_widget, qtbot):
        """Pressing Ctrl+Q in a text input should not close the widget."""
        shortcut_widget.input_edit.setFocus()
        qtbot.wait(10)
        assert shortcut_widget.window().isVisible()

        qtbot.keyClick(
            shortcut_widget.input_edit, Qt.Key_Q, modifier=Qt.ControlModifier
        )

        assert shortcut_widget.window().isVisible()

    def test_escape_does_not_close_window(self, shortcut_widget, qtbot):
        """Pressing Escape should leave the widget window open."""
        assert shortcut_widget.window().isVisible()

        qtbot.keyClick(shortcut_widget, Qt.Key_Escape)

        assert shortcut_widget.window().isVisible()

    def test_escape_clears_line_edit_focus_and_refocuses_widget(
        self, shortcut_widget, qtbot
    ):
        """Escape from a child line edit should return focus to the widget."""
        shortcut_widget.input_edit.setFocus()
        qtbot.wait(10)

        qtbot.keyClick(shortcut_widget.input_edit, Qt.Key_Escape)
        qtbot.wait(10)

        assert shortcut_widget.window().isVisible()
        assert not shortcut_widget.input_edit.hasFocus()
        assert shortcut_widget.hasFocus()

    def test_escape_clears_combo_box_focus_and_refocuses_widget(
        self, shortcut_widget, qtbot
    ):
        """Escape from a combo box should return focus to the widget."""
        shortcut_widget.input_combo.setFocus()
        qtbot.wait(10)

        qtbot.keyClick(shortcut_widget.input_combo, Qt.Key_Escape)
        qtbot.wait(10)

        assert shortcut_widget.window().isVisible()
        assert not shortcut_widget.input_combo.hasFocus()
        assert shortcut_widget.hasFocus()

    def test_help_menu_exposes_keyboard_shortcuts_action(self, shortcut_widget):
        """Widget Help menu should expose the DerZug keyboard shortcuts action."""
        assert shortcut_widget.menuBar().isVisible()
        help_menu = shortcut_widget.menuBar().findChild(QMenu, "help-menu")
        assert help_menu is not None

        labels = [
            action.text().replace("&", "")
            for action in help_menu.actions()
            if not action.isSeparator()
        ]

        assert "Keyboard Shortcuts" in labels

    def test_keyboard_shortcuts_dialog_includes_widget_specific_rows(
        self, shortcut_widget, qtbot
    ):
        """Widget shortcuts dialog should include both shared and widget rows."""
        shortcut_widget.open_keyboard_shortcuts()
        qtbot.wait(10)

        dialogs = [
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, QDialog)
            and widget.windowTitle() == "Shortcut Widget Keyboard Shortcuts"
        ]
        assert dialogs

        labels = dialogs[-1].findChildren(QLabel)
        assert labels
        rendered = "".join(label.text() for label in labels)

        assert "Ctrl+Q" in rendered
        assert "Ctrl+R" in rendered
        assert "F1" in rendered


class TestZugWidgetHelpMenuCoverage:
    """Tests for base Help menu coverage across DerZug widgets."""

    @pytest.mark.parametrize("widget_cls", ALL_WIDGET_CLASSES)
    def test_every_widget_has_help_menu(self, widget_cls, qtbot):
        """Each widget window should expose the shared Help menu."""
        with widget_context(widget_cls) as widget:
            widget.show()
            qtbot.wait(10)
            assert widget.menuBar().isVisible()
            help_menu = widget.menuBar().findChild(QMenu, "help-menu")
            assert help_menu is not None

            labels = [
                action.text().replace("&", "")
                for action in help_menu.actions()
                if not action.isSeparator()
            ]
            assert "Keyboard Shortcuts" in labels


class TestZugWidgetErrors:
    """Tests for shared traceback behavior on widget errors."""

    @staticmethod
    def _get_visible_message_label(widget) -> QWidget:
        """Return the actual visible message-label target from Orange's bar."""
        return next(
            child
            for child in widget.message_bar.findChildren(QWidget)
            if type(child).__name__ == "ElidingLabel" and child.isVisible()
        )

    def test_double_click_visible_error_label_opens_traceback_dialog(
        self, qtbot, monkeypatch
    ):
        """Double-clicking the visible error label should show the traceback dialog."""
        dialogs: list[DerZugErrorDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(DerZugErrorDialog, "exec", _fake_exec)

        with widget_context(_FailingWidget) as widget:
            widget.show()
            qtbot.wait(10)

            widget.run()

            assert widget.Error.general.is_shown()
            target = self._get_visible_message_label(widget)
            qtbot.mouseDClick(target, Qt.LeftButton)

        assert dialogs
        assert "RuntimeError: boom" in dialogs[0]._traceback_edit.toPlainText()

    def test_single_click_visible_error_label_shows_default_message_popup(
        self, qtbot, monkeypatch
    ):
        """A normal single click should still open Orange's full message popup."""
        popups: list[tuple[object, object]] = []

        def _fake_popup(menu, pos, action=None):
            popups.append((pos, action))

        monkeypatch.setattr("AnyQt.QtWidgets.QMenu.popup", _fake_popup)

        with widget_context(_FailingWidget) as widget:
            widget.show()
            qtbot.wait(10)

            widget.run()

            assert widget.Error.general.is_shown()
            target = self._get_visible_message_label(widget)
            qtbot.mouseClick(target, Qt.LeftButton)
            qtbot.wait(QApplication.doubleClickInterval() + 50)

        assert len(popups) == 1

    def test_double_click_named_error_label_opens_traceback_dialog(
        self, qtbot, monkeypatch
    ):
        """Named Error slots should still open tracebacks on double-click."""
        dialogs: list[DerZugErrorDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(DerZugErrorDialog, "exec", _fake_exec)

        with widget_context(_HandledFailingWidget) as widget:
            widget.show()
            qtbot.wait(10)

            widget.trigger_handled_failure()

            assert widget.Error.specific.is_shown()
            target = self._get_visible_message_label(widget)
            qtbot.mouseDClick(target, Qt.LeftButton)

        assert dialogs
        assert "ValueError: handled boom" in dialogs[0]._traceback_edit.toPlainText()

    def test_plain_message_clears_stored_traceback_state(self, qtbot, monkeypatch):
        """Non-exception banners must not keep an earlier traceback attached."""
        dialogs: list[DerZugErrorDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(DerZugErrorDialog, "exec", _fake_exec)

        with widget_context(_HandledFailingWidget) as widget:
            widget.show()
            qtbot.wait(10)

            widget.trigger_handled_failure()
            assert widget._last_error_exc is not None

            widget.trigger_plain_message()
            assert widget.Error.specific.is_shown()
            assert widget._last_error_exc is None

            target = self._get_visible_message_label(widget)
            qtbot.mouseDClick(target, Qt.LeftButton)

        assert not dialogs


class TestZugWidgetDeferredRefresh:
    """Tests for visibility-gated UI refreshes on ZugWidget."""

    def test_request_ui_refresh_defers_while_hidden(self):
        """Hidden widgets should mark one pending refresh instead of drawing."""
        with widget_context(_RefreshWidget) as widget:
            widget._request_ui_refresh()

            assert widget.refresh_count == 0
            assert widget._ui_refresh_pending is True

    def test_show_event_flushes_pending_refresh_once(self, qtbot):
        """Showing the widget should flush one deferred refresh."""
        with widget_context(_RefreshWidget) as widget:
            widget._request_ui_refresh()
            widget.show()
            qtbot.wait(10)

            assert widget.refresh_count == 1
            assert widget._ui_refresh_pending is False

    def test_hidden_refresh_requests_coalesce(self, qtbot):
        """Repeated hidden requests should still produce one visible refresh."""
        with widget_context(_RefreshWidget) as widget:
            widget._request_ui_refresh()
            widget._request_ui_refresh()
            widget._request_ui_refresh()

            widget.show()
            qtbot.wait(10)

            assert widget.refresh_count == 1


class TestZugWidgetCanvasRaise:
    """Tests for Shift+~ canvas-raise behavior on ZugWidget."""

    def test_shift_tilde_calls_raise_canvas(self, qtbot, monkeypatch):
        """Shift+~ from a widget window calls _raise_canvas."""
        called: list[bool] = []
        with widget_context(_ShortcutWidget) as widget:
            monkeypatch.setattr(widget, "_raise_canvas", lambda: called.append(True))
            widget.show()
            qtbot.wait(10)
            qtbot.keyClick(widget, Qt.Key_AsciiTilde, modifier=Qt.ShiftModifier)
        assert called

    def test_shift_tilde_ignored_while_typing(self, qtbot, monkeypatch):
        """Shift+~ inside a text input does not call _raise_canvas."""
        called: list[bool] = []
        with widget_context(_ShortcutWidget) as widget:
            monkeypatch.setattr(widget, "_raise_canvas", lambda: called.append(True))
            widget.show()
            widget.input_edit.setFocus()
            qtbot.wait(10)
            qtbot.keyClick(
                widget.input_edit, Qt.Key_AsciiTilde, modifier=Qt.ShiftModifier
            )
        assert not called

    def test_raise_canvas_raises_main_window(self, derzug_app, monkeypatch):
        """_raise_canvas calls raise_ and activateWindow on the DerZugMainWindow."""
        window = derzug_app.window
        raised: list[bool] = []
        activated: list[bool] = []
        monkeypatch.setattr(window, "raise_", lambda: raised.append(True))
        monkeypatch.setattr(window, "activateWindow", lambda: activated.append(True))

        with widget_context(_ShortcutWidget) as widget:
            widget._raise_canvas()

        assert raised
        assert activated

    def test_shift_tilde_in_shared_shortcuts(self):
        """Shift+~ should appear in every widget's shared shortcut list."""
        with widget_context(_ShortcutWidget) as widget:
            keys = [key for key, _ in widget.shared_shortcuts()]
        assert "Shift+~" in keys


class TestZugWidgetSizing:
    """Tests for shared control-area sizing behavior."""

    def test_control_area_expands_for_late_wider_contents(self, qtbot):
        """Shown widgets should widen the sidebar to fit refreshed controls."""
        with widget_context(_SidebarGrowthWidget) as widget:
            widget.show()
            qtbot.wait(10)

            hint_width = max(
                widget.controlArea.sizeHint().width(),
                widget.controlArea.minimumSizeHint().width(),
            )

            assert widget.controlArea.width() >= hint_width

    def test_hidden_controls_do_not_force_initial_sidebar_width(self, qtbot):
        """Hidden controls should not inflate the initial sidebar width."""
        with widget_context(_HiddenSidebarWidthWidget) as widget:
            widget.show()
            qtbot.wait(10)

            visible_width = max(
                widget.visible_label.sizeHint().width(),
                widget.visible_label.minimumSizeHint().width(),
            )
            hidden_width = max(
                widget.hidden_label.sizeHint().width(),
                widget.hidden_label.minimumSizeHint().width(),
            )

            assert hidden_width > visible_width
            assert widget.controlArea.width() < hidden_width
