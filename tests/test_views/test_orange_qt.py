"""Qt/Orange integration tests."""

from __future__ import annotations

import io
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import dascore as dc
import derzug.constants as constants
import pytest
from AnyQt.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRectF, Qt
from AnyQt.QtGui import (
    QAction,
    QCursor,
    QFont,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QTextCursor,
)
from AnyQt.QtTest import QTest
from AnyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QWidget,
)
from derzug.annotations_config import (
    AnnotationConfig,
    clear_annotation_config_cache,
    save_annotation_config,
)
from derzug.utils.display import format_display
from derzug.utils.testing import (
    build_window_workflow,
    wait_for_widget_idle,
    widget_context,
)
from derzug.views import orange as orange_view
from derzug.views.orange import (
    ActiveSourceManager,
    CodeWorkflowWarningDialog,
    DerZugConfig,
    DerZugErrorDialog,
    DerZugMain,
    ExperimentalWarningDialog,
    _ActiveSourceNavigator,
    _build_exception_report_data,
    _CanvasEscapeDefocuser,
    _CanvasZOrderToggler,
    _configure_linux_desktop_integration,
    _install_derzug_exception_handler,
    _linux_desktop_entry_contents,
    _TabWindowCycler,
    ensure_linux_desktop_entry,
)
from derzug.views.orange_errors import _build_issue_body, _build_issue_url
from derzug.widgets.spool import Spool
from derzug.widgets.table2annotation import Table2Annotation
from orangecanvas.application.canvastooldock import SplitterResizer
from orangecanvas.application.outputview import ExceptHook, TerminalTextDocument
from orangecanvas.document.interactions import RectangleSelectionAction
from orangecanvas.gui.windowlistmanager import WindowListManager


def _action_by_name(actions, name: str) -> QAction:
    """Return one QAction by objectName."""
    for action in actions:
        if action.objectName() == name:
            return action
    raise LookupError(name)


def _graph_signature(scheme) -> tuple[set[str], set[tuple[str, str, str, str]]]:
    """Return comparable node/link signatures for a workflow graph."""
    nodes = {node.title for node in scheme.nodes}
    links = {
        (
            link.source_node.title,
            link.source_channel.name,
            link.sink_node.title,
            link.sink_channel.name,
        )
        for link in scheme.links
    }
    return nodes, links


def _active_source_box_visible(window, node) -> bool:
    """Return True when the live node item shows the active-source title box."""
    item = window.current_document().scene().item_for_node(node)
    rect_item = getattr(item, "_derzug_active_source_rect", None)
    return bool(rect_item is not None and rect_item.isVisible())


def _assert_waterfall_control_text_fits(widget) -> None:
    """Assert that visible Waterfall control-area widgets fit their text hints."""
    assert widget.controlArea.width() >= widget.controlArea.sizeHint().width()

    text_widgets = widget.controlArea.findChildren((QPushButton, QLabel, QComboBox))
    visible_widgets = [child for child in text_widgets if child.isVisible()]
    assert visible_widgets

    for child in visible_widgets:
        if isinstance(child, QLabel) and child.wordWrap():
            continue
        target_width = max(child.sizeHint().width(), child.minimumSizeHint().width())
        assert child.width() >= target_width


def _patch_with_attrs(**attrs) -> dc.Patch:
    """Return an example patch with selected attrs replaced."""
    patch = dc.get_example_patch("example_event_2")
    payload = patch.attrs.model_dump()
    payload.update(attrs)
    return patch.update(attrs=payload)


def _select_test_spool() -> dc.BaseSpool:
    """Return a spool with predictable metadata for Select round-trip tests."""
    return dc.spool(
        [
            _patch_with_attrs(tag="bob", station="alpha"),
            _patch_with_attrs(tag="bob", station="beta"),
            _patch_with_attrs(tag="alice", station="beta"),
        ]
    )


def _select_canvas_nodes(window, *nodes) -> None:
    """Select the given workflow nodes in the live canvas scene."""
    scene = window.current_document().scene()
    scene.clearSelection()
    for node in nodes:
        scene.item_for_node(node).setSelected(True)


def _menu_labels(window, menu_name: str) -> list[str]:
    """Return visible non-separator labels from one top-level menu."""
    menu = next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text().replace("&", "") == menu_name
    )
    return [
        action.text().replace("&", "")
        for action in menu.actions()
        if action.isVisible() and not action.isSeparator()
    ]


def _clear_code_warning_setting() -> None:
    """Reset the persisted code-workflow warning preference for one test."""
    settings = orange_view._derzug_settings()
    settings.beginGroup("load")
    settings.remove("hide-code-widget-warning")
    settings.endGroup()


def _dispatch_mouse_event(
    widget,
    event_type: QEvent.Type,
    pos: QPoint,
    *,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    """Send one mouse event directly to a widget."""
    event = QMouseEvent(
        event_type,
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        button,
        buttons,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _visible_scene_rect(view) -> QRectF:
    """Return the current viewport coverage mapped into scene coordinates."""
    return view.mapToScene(view.viewport().rect()).boundingRect()


class _SipModuleWrongWrapper:
    """Stub SIP module that rejects one wrapper family."""

    @staticmethod
    def isdeleted(obj):
        raise TypeError(
            "isdeleted() argument 1 must be PyQt6.sip.simplewrapper, "
            f"not {type(obj).__name__}"
        )


class _SipModuleAlive:
    """Stub SIP module that accepts the wrapper and reports it alive."""

    @staticmethod
    def isdeleted(obj):
        return False


class _SipModuleDeleted:
    """Stub SIP module that accepts the wrapper and reports it deleted."""

    @staticmethod
    def isdeleted(obj):
        return True


@contextmanager
def _fresh_derzug_window(qapp, tmp_path):
    """Yield a freshly constructed DerZug main window for cold-reopen tests."""
    main = DerZugMain()
    old_cache_home = os.environ.get("XDG_CACHE_HOME")
    old_data_home = os.environ.get("XDG_DATA_HOME")
    cache_home = tmp_path / "fresh-cache"
    data_home = tmp_path / "fresh-data"
    cache_home.mkdir(parents=True, exist_ok=True)
    data_home.mkdir(parents=True, exist_ok=True)
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
    qapp.processEvents()
    try:
        yield window
    finally:
        window.hide()
        window.deleteLater()
        qapp.processEvents()
        QCoreApplication.sendPostedEvents()
        if old_cache_home is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = old_cache_home
        if old_data_home is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = old_data_home


@pytest.fixture
def orange_workflow(derzug_app, qapp):
    """Return a helper for building workflows in the DerZug main window."""
    window = derzug_app.window
    registry = derzug_app.main.registry

    def _build(widgets, links=(), *, clear=True):
        return build_window_workflow(
            window,
            registry,
            widgets,
            links,
            qapp=qapp,
            clear=clear,
        )

    return _build


class TestDerZugMainWindow:
    """Simple checks for DerZug Orange startup wiring."""

    @staticmethod
    def _clear_startup_warning_setting() -> None:
        """Reset the persisted startup warning preference for one test."""
        settings = orange_view._derzug_settings()
        settings.beginGroup("startup")
        settings.remove("hide-experimental-warning")
        settings.endGroup()

    @staticmethod
    def _clear_annotation_settings() -> None:
        """Reset persisted annotation preferences for one test."""
        clear_annotation_config_cache()
        save_annotation_config(AnnotationConfig())

    def test_annotation_settings_load_uses_cache_until_save(
        self, derzug_app, monkeypatch
    ):
        """Repeated default loads should reuse the cached config until a save."""
        self._clear_annotation_settings()
        calls: list[str] = []
        original_reader = orange_view.load_annotation_config.__globals__[
            "_read_annotation_config"
        ]

        def _wrapped_reader(settings):
            calls.append("read")
            return original_reader(settings)

        monkeypatch.setitem(
            orange_view.load_annotation_config.__globals__,
            "_read_annotation_config",
            _wrapped_reader,
        )

        first = orange_view.load_annotation_config(force_reload=True)
        second = orange_view.load_annotation_config()
        save_annotation_config(AnnotationConfig(annotator="alice"))
        third = orange_view.load_annotation_config()

        assert first.annotator == ""
        assert second.annotator == ""
        assert third.annotator == "alice"
        assert calls == ["read"]

    def test_help_menu_is_derzug_trimmed(self, derzug_app):
        """Help menu keeps only the curated DerZug actions."""
        window = derzug_app.window
        assert _menu_labels(window, "Help") == [
            "About",
            "Documentation",
            "Keyboard Shortcuts",
            "Example Workflow",
            "Donate to Orange",
        ]

    def test_splitter_resizer_ignores_generic_resize_events(self, qtbot):
        """Orange splitter resizer should not assert on generic resize events."""
        splitter = QSplitter()
        top = QWidget()
        bottom = QWidget()
        splitter.addWidget(top)
        splitter.addWidget(bottom)
        qtbot.addWidget(splitter)

        resizer = SplitterResizer()
        resizer.setSplitterAndWidget(splitter, bottom)

        event = QEvent(QEvent.Type.Resize)
        assert resizer.eventFilter(bottom, event) is False

    def test_shell_hides_inherited_orange_actions(self, derzug_app):
        """Menus should drop the inherited Orange-specific maintenance actions."""
        self._clear_annotation_settings()
        window = derzug_app.window

        assert all(label.strip() for label in _menu_labels(window, "File"))
        assert "Open Report..." not in _menu_labels(window, "File")
        assert "Window Groups" not in _menu_labels(window, "View")
        assert "Show report" not in _menu_labels(window, "View")
        assert "Add-ons..." not in _menu_labels(window, "Options")
        assert "Reset Widget Settings..." not in _menu_labels(window, "Options")
        assert "Annotation Settings..." in _menu_labels(window, "Options")
        assert "Settings" in _menu_labels(window, "Options")
        assert window.dock_help_action not in window.canvas_toolbar.actions()

    def test_annotation_settings_action_opens_dialog(self, derzug_app, monkeypatch):
        """The Options menu should expose the global annotation settings dialog."""
        self._clear_annotation_settings()
        window = derzug_app.window
        opened = []

        class _FakeAnnotationSettingsDialog:
            def __init__(self, *_args, **_kwargs):
                opened.append(True)

            def exec(self):
                return QDialog.DialogCode.Rejected

        monkeypatch.setattr(
            orange_view,
            "AnnotationSettingsDialog",
            _FakeAnnotationSettingsDialog,
        )

        window.annotation_settings_action.trigger()

        assert opened == [True]

    def test_annotation_settings_dialog_persists_values(self, derzug_app, monkeypatch):
        """Accepting the global annotation dialog should update QSettings."""
        self._clear_annotation_settings()
        window = derzug_app.window
        accepted = orange_view.AnnotationSettingsDialog(
            AnnotationConfig(
                annotator="alice",
                organization="DASDAE",
                label_names={"1": "p_pick"},
            ),
            window,
        )
        monkeypatch.setattr(accepted, "exec", lambda: QDialog.DialogCode.Accepted)
        monkeypatch.setattr(
            orange_view,
            "AnnotationSettingsDialog",
            lambda *_args, **_kwargs: accepted,
        )

        window.open_annotation_settings()

        settings = orange_view._derzug_settings()
        settings.beginGroup("annotations")
        try:
            assert settings.value("annotator", "", type=str) == "alice"
            assert settings.value("organization", "", type=str) == "DASDAE"
            assert settings.value("labels/1", "", type=str) == "p_pick"
        finally:
            settings.endGroup()

    def test_dev_controls_are_absent_by_default(self, derzug_app):
        """Normal mode should not expose development reload controls."""
        window = derzug_app.window

        assert window.hot_reload_action is None
        assert all(
            action.text().replace("&", "") != "Dev"
            for action in window.menuBar().actions()
        )

    def test_dev_controls_appear_in_dev_mode(self, derzug_app):
        """Dev mode should expose a top-level Dev menu and its actions."""
        window = derzug_app.window
        window.dev_mode = True

        window.install_dev_controls()

        assert window.hot_reload_action is not None
        assert window.edit_config_file_action is not None
        assert window.hot_reload_action.shortcut().toString() == "Ctrl+Shift+R"
        dev_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text().replace("&", "") == "Dev"
        )
        assert dev_menu is window.dev_menu
        assert [
            action.text().replace("&", "")
            for action in dev_menu.actions()
            if not action.isSeparator()
        ] == ["Hot Reload", "Edit Config File"]
        assert window.hot_reload_action not in window.canvas_toolbar.actions()

    def test_set_active_source_action_is_not_added_to_canvas_toolbar(self, derzug_app):
        """The active-source override should live in node menus, not the toolbar."""
        window = derzug_app.window

        assert all(
            action.text().replace("&", "") != "Set Active Source"
            for action in window.canvas_toolbar.actions()
        )

    def test_derzug_settings_use_dasdae_scope(self, derzug_app):
        """DerZug should store user settings under the dasdae namespace."""
        settings = orange_view._derzug_settings()

        assert settings.fileName().endswith("/dasdae/DerZug.ini")

    def test_edit_config_file_action_opens_derzug_config_file(
        self, derzug_app, monkeypatch, tmp_path
    ):
        """The dev action should open the DerZug config file path."""
        window = derzug_app.window
        window.dev_mode = True
        window.install_dev_controls()
        opened = []
        config_path = tmp_path / "dasdae" / "DerZug.ini"
        monkeypatch.setattr(window, "_config_file_path", lambda: str(config_path))
        monkeypatch.setattr(
            orange_view.QDesktopServices,
            "openUrl",
            lambda url: opened.append(url.toLocalFile()) or True,
        )

        window.edit_config_file_action.trigger()

        assert config_path.exists()
        assert [Path(item) for item in opened] == [config_path]

    def test_edit_config_file_action_reports_open_failure(
        self, derzug_app, monkeypatch, tmp_path
    ):
        """The dev action should surface an error if the config file cannot open."""
        window = derzug_app.window
        window.dev_mode = True
        window.install_dev_controls()
        shown = []
        config_path = tmp_path / "dasdae" / "DerZug.ini"
        monkeypatch.setattr(window, "_config_file_path", lambda: str(config_path))
        monkeypatch.setattr(orange_view.QDesktopServices, "openUrl", lambda _url: False)
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda _parent, title, text: shown.append((title, text)),
        )

        window.edit_config_file_action.trigger()

        assert shown == [
            (
                "Open Config File Failed",
                f"Could not open config file: {config_path}",
            )
        ]

    def test_documentation_action_opens_github(self, derzug_app, monkeypatch):
        """Documentation action should open the DerZug GitHub repository."""
        window = derzug_app.window
        opened = []

        monkeypatch.setattr(
            orange_view.QDesktopServices,
            "openUrl",
            lambda url: opened.append(url.toString()),
        )

        window.documentation_action.trigger()

        assert opened == ["https://github.com/dasdae/derzug"]

    def test_keyboard_shortcuts_action_opens_dialog(self, derzug_app, qapp):
        """Help menu should expose a keyboard shortcuts reference dialog."""
        window = derzug_app.window

        assert not any(
            widget.windowTitle() == "Keyboard Shortcuts"
            for widget in qapp.topLevelWidgets()
        )

        window.keyboard_shortcuts_action.trigger()
        qapp.processEvents()

        dialogs = [
            widget
            for widget in qapp.topLevelWidgets()
            if widget.windowTitle() == "Keyboard Shortcuts"
        ]

        assert dialogs
        assert dialogs[-1].isVisible()

    def test_startup_warning_dialog_has_expected_message_and_buttons(self, qtbot):
        """Startup warning dialog should expose the requested copy and actions."""
        dialog = ExperimentalWarningDialog()
        qtbot.addWidget(dialog)

        labels = [label.text() for label in dialog.findChildren(QLabel)]
        buttons = [button.text() for button in dialog.findChildren(QPushButton)]
        checkboxes = [box.text() for box in dialog.findChildren(QCheckBox)]

        assert dialog.windowTitle() == "🚨 Experimental Warning"
        assert "DerZug Is Experimental" in labels
        assert any("highly experimental proof of concept" in text for text in labels)
        assert buttons == ["OK"]
        assert checkboxes == ["Don't show this message again"]

    def test_startup_warning_ok_only_closes_for_now(self, qtbot):
        """OK should dismiss the warning without persisting the opt-out flag."""
        dialog = ExperimentalWarningDialog()
        qtbot.addWidget(dialog)
        ok_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "OK"
        )

        dialog.show()
        QTest.mouseClick(ok_button, Qt.MouseButton.LeftButton)

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.hide_future_warnings is False

    def test_startup_warning_checked_checkbox_persists_opt_out(self, qtbot):
        """Checking the opt-out box before OK should persist the suppression intent."""
        dialog = ExperimentalWarningDialog()
        qtbot.addWidget(dialog)
        checkbox = dialog.findChild(QCheckBox)
        ok_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "OK"
        )

        dialog.show()
        checkbox.setChecked(True)
        QTest.mouseClick(ok_button, Qt.MouseButton.LeftButton)

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.hide_future_warnings is True

    def test_code_warning_ok_keeps_future_warnings_enabled(self, qtbot):
        """Accepting the code warning without opt-out keeps future warnings on."""
        dialog = CodeWorkflowWarningDialog()
        qtbot.addWidget(dialog)
        ok_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Load Workflow"
        )

        dialog.show()
        QTest.mouseClick(ok_button, Qt.MouseButton.LeftButton)

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.hide_future_warnings is False

    def test_code_warning_checked_checkbox_persists_opt_out(self, qtbot):
        """Checking the opt-out box before load should persist suppression intent."""
        dialog = CodeWorkflowWarningDialog()
        qtbot.addWidget(dialog)
        checkbox = dialog.findChild(QCheckBox)
        ok_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Load Workflow"
        )

        dialog.show()
        checkbox.setChecked(True)
        QTest.mouseClick(ok_button, Qt.MouseButton.LeftButton)

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.hide_future_warnings is True

    def test_code_warning_cancel_rejects_without_opt_out(self, qtbot):
        """Canceling the code warning should reject without suppressing prompts."""
        dialog = CodeWorkflowWarningDialog()
        qtbot.addWidget(dialog)
        cancel_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Cancel"
        )

        dialog.show()
        QTest.mouseClick(cancel_button, Qt.MouseButton.LeftButton)

        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog.hide_future_warnings is False

    def test_about_dialog_is_derzug_led_with_orange_in_credits(self, qtbot):
        """About should lead with DerZug while keeping Orange as secondary credit."""
        dialog = orange_view.DerZugAboutDialog()
        qtbot.addWidget(dialog)

        labels = [label.text() for label in dialog.findChildren(QLabel)]
        rich_text = next(text for text in labels if "Version:" in text)

        assert "DerZug</b> is an interactive workspace" in rich_text
        assert "Built with" in rich_text
        assert "Orange</a>" in rich_text
        assert "Powered by:" not in rich_text

    def test_startup_warning_shows_on_first_window_show(
        self, derzug_app, monkeypatch, qapp
    ):
        """Showing the main window triggers the experimental warning by default."""
        self._clear_startup_warning_setting()
        window = derzug_app.window
        shown: list[object] = []

        class _FakeDialog:
            hide_future_warnings = False

            def __init__(self, parent=None) -> None:
                shown.append(parent)

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(orange_view, "ExperimentalWarningDialog", _FakeDialog)

        window.show()
        qapp.processEvents()

        assert shown == [window]
        assert window.should_show_experimental_warning() is True

    def test_startup_warning_dont_show_again_persists_opt_out(
        self, derzug_app, monkeypatch
    ):
        """Opting out of the startup warning should persist the preference."""
        self._clear_startup_warning_setting()
        window = derzug_app.window
        shown = []

        class _FakeDialog:
            hide_future_warnings = True

            def __init__(self, parent=None) -> None:
                shown.append(parent)

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(orange_view, "ExperimentalWarningDialog", _FakeDialog)

        window.maybe_show_experimental_warning()

        assert shown == [window]
        assert window.should_show_experimental_warning() is False

    def test_clear_startup_warning_setting_restores_warning_visibility(
        self, derzug_app
    ):
        """Clearing the stored opt-out should make the warning visible again."""
        window = derzug_app.window
        self._clear_startup_warning_setting()

        window.set_experimental_warning_hidden(True)
        assert window.should_show_experimental_warning() is False

        window.clear_experimental_warning_hidden()

        assert window.should_show_experimental_warning() is True

    def test_clear_code_warning_setting_restores_warning_visibility(self, derzug_app):
        """Clearing the stored opt-out should make code warnings visible again."""
        window = derzug_app.window
        _clear_code_warning_setting()

        window.set_code_widget_warning_hidden(True)
        assert window.should_show_code_widget_warning() is False

        window.clear_code_widget_warning_hidden()

        assert window.should_show_code_widget_warning() is True

    def test_startup_warning_ignores_other_settings_scopes(self, derzug_app):
        """DerZug should not read the warning flag from unrelated QSettings scopes."""
        window = derzug_app.window
        self._clear_startup_warning_setting()
        other = orange_view.QSettings(
            orange_view.QSettings.IniFormat,
            orange_view.QSettings.UserScope,
            "some.other.scope",
            "NotDerZug",
        )
        other.beginGroup("startup")
        other.setValue("hide-experimental-warning", True)
        other.endGroup()

        assert window.should_show_experimental_warning() is True

    def test_code_warning_ignores_other_settings_scopes(self, derzug_app):
        """DerZug should not read the code warning flag from unrelated scopes."""
        window = derzug_app.window
        _clear_code_warning_setting()
        other = orange_view.QSettings(
            orange_view.QSettings.IniFormat,
            orange_view.QSettings.UserScope,
            "some.other.scope",
            "NotDerZug",
        )
        other.beginGroup("load")
        other.setValue("hide-code-widget-warning", True)
        other.endGroup()

        assert window.should_show_code_widget_warning() is True

    def test_hot_reload_is_noop_outside_dev_mode(self, derzug_app, monkeypatch):
        """Non-dev hot reload attempts should not spawn a new process."""
        spawned: list[list[str]] = []
        monkeypatch.setattr(
            orange_view.subprocess, "Popen", lambda cmd: spawned.append(cmd)
        )

        derzug_app.window._trigger_hot_reload()

        assert spawned == []

    def test_linux_desktop_entry_avoids_orange_branding(self):
        """Desktop entry metadata should describe DerZug rather than Orange."""
        contents = _linux_desktop_entry_contents("/tmp/derzug", "/tmp/icon.png")

        assert "Orange workflows" not in contents
        assert "Orange;" not in contents
        assert "Comment=Interactive DAS workflow visualization and review" in contents
        assert (
            "Keywords=DAS;Distributed Acoustic Sensing;Visualization;Workflow;"
            in contents
        )

    def test_window_menu_actions_have_nonblank_titles(self, derzug_app, qapp):
        """Managed window-menu entries should always have visible titles."""
        window = derzug_app.window

        window.show()
        qapp.processEvents()

        labels = [
            action.text().replace("&", "").strip()
            for action in WindowListManager.instance().actions()
            if action.isVisible()
        ]

        assert labels
        assert all(labels), labels
        assert "DerZug" in labels

    def test_install_derzug_exception_handler_replaces_orange_handler(
        self, qapp, monkeypatch
    ):
        """The wiring helper should leave only DerZug's exception slot attached."""
        derzug_calls: list[tuple] = []
        orange_calls: list[tuple] = []
        hook = ExceptHook(stream=None)

        def _fake_derzug_handler(exc):
            derzug_calls.append(exc)

        def _fake_orange_handler(exc):
            orange_calls.append(exc)
            return None

        monkeypatch.setattr(sys, "excepthook", hook)
        monkeypatch.setattr(
            orange_view, "handle_derzug_exception", _fake_derzug_handler
        )
        monkeypatch.setattr(
            orange_view, "orange_handle_exception", _fake_orange_handler
        )
        hook.handledException.connect(orange_view.orange_handle_exception)

        _install_derzug_exception_handler()

        try:
            raise RuntimeError("unexpected dialog boom")
        except RuntimeError:
            exc = sys.exc_info()

        hook(*exc)

        assert derzug_calls
        assert not orange_calls
        assert derzug_calls[-1][0] is RuntimeError

    def test_spool_caption_decorates_when_patch_output_is_active(
        self, derzug_app, qapp, orange_workflow
    ):
        """Spool caption reflects active Patch output in both node and window titles."""
        workflow = orange_workflow((("Spool", "Spool"),))
        spool_widget = workflow.widgets_by_title["Spool"]
        spool_node = workflow.nodes_by_title["Spool"]

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget)

        assert spool_widget.captionTitle == "Spool ⚡"
        assert spool_widget.windowTitle() == "Spool ⚡"
        assert spool_node.title == "Spool ⚡"

    def test_build_hot_reload_command_preserves_dev_mode_and_workflow_path(
        self, derzug_app, tmp_path, monkeypatch
    ):
        """Hot reload should relaunch via the CLI with --dev and temp workflow path."""
        window = derzug_app.window
        window.dev_mode = True
        monkeypatch.setattr(orange_view.tempfile, "gettempdir", lambda: str(tmp_path))

        command = window._build_hot_reload_command(window._workflow_path_for_reload())

        assert command[:4] == [sys.executable, "-m", "derzug.cli", "--dev"]
        assert command[-1] == str(tmp_path / "derzug-hot-reload.ows")

    def test_hot_reload_saves_live_scheme_to_stable_temp_path(
        self, derzug_app, tmp_path, monkeypatch
    ):
        """Hot reload should snapshot the current scheme to temp without prompting."""
        window = derzug_app.window
        window.dev_mode = True
        window.install_dev_controls()
        document = window.current_document()
        document.setModified(True)

        spawned: list[list[str]] = []
        quits: list[bool] = []
        saved: list[tuple[object, str]] = []
        monkeypatch.setattr(
            orange_view.subprocess, "Popen", lambda cmd: spawned.append(cmd)
        )
        monkeypatch.setattr(
            orange_view.QTimer,
            "singleShot",
            lambda _delay, callback: (quits.append(True), callback()),
        )
        monkeypatch.setattr(orange_view.tempfile, "gettempdir", lambda: str(tmp_path))

        def _save_scheme_to(scheme, path):
            saved.append((scheme, path))
            return True

        monkeypatch.setattr(window, "save_scheme_to", _save_scheme_to)
        question_calls: list[tuple[tuple, dict]] = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: question_calls.append((args, kwargs)),
        )

        window._trigger_hot_reload()

        expected_path = str(tmp_path / "derzug-hot-reload.ows")
        assert saved == [(document.scheme(), expected_path)]
        assert spawned[-1][:4] == [sys.executable, "-m", "derzug.cli", "--dev"]
        assert spawned[-1][-1] == expected_path
        assert quits
        assert question_calls == []

    def test_hot_reload_uses_temp_path_even_when_document_has_saved_path(
        self, derzug_app, tmp_path, monkeypatch
    ):
        """Hot reload should relaunch the temp snapshot rather than the real .ows."""
        window = derzug_app.window
        window.dev_mode = True
        workflow_path = tmp_path / "saved.ows"
        window.current_document().setPath(str(workflow_path))
        monkeypatch.setattr(orange_view.tempfile, "gettempdir", lambda: str(tmp_path))

        reloaded_path = window._workflow_path_for_reload()

        assert reloaded_path == str(tmp_path / "derzug-hot-reload.ows")

    def test_hot_reload_temp_path_uses_os_temp_directory(
        self, derzug_app, tmp_path, monkeypatch
    ):
        """The hot reload temp file should live in the OS temp directory."""
        window = derzug_app.window
        monkeypatch.setattr(orange_view.tempfile, "gettempdir", lambda: str(tmp_path))

        path = window._hot_reload_temp_workflow_path()

        assert path == str(tmp_path / "derzug-hot-reload.ows")
        assert path.endswith(".ows")

    def test_open_widgets_flag_in_reload_command(self, derzug_app):
        """--open-widgets with node indices is included in the reload command."""
        window = derzug_app.window
        command = window._build_hot_reload_command(None, open_widget_ids=[0, 2])
        assert "--open-widgets" in command
        assert command[command.index("--open-widgets") + 1] == "0,2"

    def test_open_widgets_flag_absent_when_empty(self, derzug_app):
        """--open-widgets is omitted from the command when no widgets are open."""
        window = derzug_app.window
        command = window._build_hot_reload_command(None, open_widget_ids=[])
        assert "--open-widgets" not in command

    def test_collect_open_widget_node_ids_returns_visible_indices(self, derzug_app):
        """Only indices of already-created, visible widgets are collected."""
        window = derzug_app.window
        build_window_workflow(
            window,
            derzug_app.main.registry,
            (("Spool", "s0"), ("Spool", "s1")),
            qapp=None,
        )
        scheme = window.current_document().scheme()

        # Force-create both widgets so they appear in __item_for_node.
        nodes = list(scheme.nodes)
        w0 = scheme.widget_for_node(nodes[0])
        w1 = scheme.widget_for_node(nodes[1])
        assert w0 is not None and w1 is not None

        # Mark only the first widget visible.
        w0.show()
        assert w0.isVisible()
        assert not w1.isVisible()

        result = window._collect_open_widget_node_ids()
        assert result == [0]

    def test_hot_reload_spawn_failure_keeps_app_open(self, derzug_app, monkeypatch):
        """A restart spawn failure should report an error and not quit."""
        window = derzug_app.window
        window.dev_mode = True
        shown: list[tuple[str, str]] = []
        quits: list[bool] = []
        monkeypatch.setattr(
            orange_view.subprocess,
            "Popen",
            lambda _cmd: (_ for _ in ()).throw(OSError("boom")),
        )
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda _parent, title, text: shown.append((title, text)),
        )
        monkeypatch.setattr(
            orange_view.QTimer,
            "singleShot",
            lambda _delay, callback: (quits.append(True), callback()),
        )

        window._trigger_hot_reload()

        assert shown == [("Hot Reload Failed", "boom")]
        assert quits == []

    def test_hot_reload_temp_save_failure_keeps_app_open(self, derzug_app, monkeypatch):
        """A temp snapshot failure should report an error and not quit."""
        window = derzug_app.window
        window.dev_mode = True
        shown: list[tuple[str, str]] = []
        quits: list[bool] = []
        monkeypatch.setattr(
            window,
            "save_scheme_to",
            lambda _scheme, _path: False,
        )
        monkeypatch.setattr(
            QMessageBox,
            "critical",
            lambda _parent, title, text: shown.append((title, text)),
        )
        monkeypatch.setattr(
            orange_view.QTimer,
            "singleShot",
            lambda _delay, callback: (quits.append(True), callback()),
        )

        window._trigger_hot_reload()

        assert shown == [
            ("Hot Reload Failed", "Failed to save hot reload workflow snapshot.")
        ]
        assert quits == []

    def test_hot_reload_bypasses_save_prompt_during_quit(self, derzug_app):
        """Hot reload shutdown should skip the normal modified-workflow prompt."""
        window = derzug_app.window
        document = window.current_document()
        document.setModified(True)
        window._hot_reload_in_progress = True

        assert window.ask_save_changes() == QDialog.Accepted

    def test_spool_caption_does_not_overwrite_custom_node_titles(
        self, derzug_app, qapp, orange_workflow
    ):
        """Custom node titles remain stable when Spool caption is decorated."""
        workflow = orange_workflow((("Spool", "source-node"),))
        spool_widget = workflow.widgets_by_title["source-node"]
        spool_node = workflow.nodes_by_title["source-node"]

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget)

        assert spool_widget.captionTitle == "Spool ⚡"
        assert spool_widget.windowTitle() == "Spool ⚡"
        assert spool_node.title == "source-node"

    def test_spool_patch_can_feed_waterfall_example_event2(
        self, derzug_app, qapp, orange_workflow, qtbot
    ):
        """Direct Spool -> Waterfall flow should render example_event_2 cleanly."""
        workflow = orange_workflow(
            (("Spool", "Spool"), ("Waterfall", "Waterfall")),
            (("Spool", "Patch", "Waterfall", "Patch"),),
        )
        spool_widget = workflow.widgets_by_title["Spool"]
        waterfall_widget = workflow.widgets_by_title["Waterfall"]
        expected = dc.get_example_patch("example_event_2")

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget)
        qtbot.waitUntil(lambda: waterfall_widget._patch is not None, timeout=5000)

        assert not waterfall_widget.Error.invalid_patch.is_shown()
        assert waterfall_widget._patch is not None
        assert waterfall_widget._axes is not None
        assert waterfall_widget._axes.x_coord.dtype == expected.get_array("time").dtype
        assert waterfall_widget._axes.y_coord[0] == expected.get_array("distance")[0]

    def test_source_node_context_menu_offers_set_active_source(
        self, derzug_app, orange_workflow
    ):
        """Source nodes should expose Set Active Source on right-click."""
        window = derzug_app.window
        workflow = orange_workflow((("Spool", "Spool"), ("Code", "Code")))
        spool_node = workflow.nodes_by_title["Spool"]

        menu = window._canvas_composite_controller.context_menu_for_node(spool_node)

        assert menu is not None
        assert "Set Active Source" in [action.text() for action in menu.actions()]

    def test_non_source_node_context_menu_hides_set_active_source(
        self, derzug_app, orange_workflow
    ):
        """Non-source nodes should not expose Set Active Source."""
        window = derzug_app.window
        workflow = orange_workflow((("Code", "Code"),))
        code_node = workflow.nodes_by_title["Code"]

        menu = window._canvas_composite_controller.context_menu_for_node(code_node)
        labels = (
            [action.text() for action in menu.actions()] if menu is not None else []
        )

        assert "Set Active Source" not in labels

    def test_active_source_set_from_context_menu_keeps_title_stable(
        self, derzug_app, qapp, orange_workflow
    ):
        """Context-menu activation should promote the source without retitling it."""
        window = derzug_app.window
        manager = ActiveSourceManager()
        window.active_source_manager = manager
        workflow = orange_workflow((("Spool", "Spool"),))
        spool_widget = workflow.widgets_by_title["Spool"]
        spool_node = workflow.nodes_by_title["Spool"]

        wait_for_widget_idle(spool_widget)
        title_before = spool_node.title
        window._canvas_composite_controller._set_active_source_widget(spool_widget)
        qapp.processEvents()

        assert manager._active_widget is spool_widget
        assert spool_node.title == title_before

    def test_group_menu_can_coexist_with_set_active_source(
        self, derzug_app, orange_workflow
    ):
        """A source node in a groupable selection should show both actions."""
        window = derzug_app.window
        workflow = orange_workflow((("Spool", "Spool"), ("Code", "Code")))
        spool_node = workflow.nodes_by_title["Spool"]
        code_node = workflow.nodes_by_title["Code"]
        _select_canvas_nodes(window, spool_node, code_node)

        menu = window._canvas_composite_controller.context_menu_for_node(spool_node)
        labels = (
            [action.text() for action in menu.actions()] if menu is not None else []
        )

        assert "Group" in labels
        assert "Set Active Source" in labels

    def test_example_workflow_entrypoints_are_derzug_only(self):
        """Help-menu example workflows should come only from DerZug."""
        examples = list(DerZugConfig.examples_entry_points())
        loaded = [(ep.name, ep.group, ep.dist.name.lower()) for ep in examples]

        assert loaded, f"Loaded example workflows: {loaded}"
        assert all(
            group == "orange.widgets.tutorials" for _, group, _ in loaded
        ), loaded
        assert all(dist == constants.PKG_NAME for _, _, dist in loaded), loaded
        assert "000-Orange3" not in {name for name, _, _ in loaded}

    def test_create_new_window_allows_missing_notification_server(
        self, derzug_app, qapp
    ):
        """Opening example workflows should not crash without a notification server."""
        window = derzug_app.window
        assert window.notification_server is None

        created = window.create_new_window()
        qapp.processEvents()

        try:
            assert created is not None
            assert isinstance(created, orange_view.DerZugMainWindow)
        finally:
            created.hide()
            created.close()
            created.deleteLater()
            qapp.processEvents()

    def test_application_icon_loads_from_packaged_asset(self):
        """DerZug should expose a non-null application icon from static assets."""
        icon = DerZugConfig.application_icon()

        assert not icon.isNull()

    def test_linux_desktop_file_name_is_set_for_launcher_matching(self, qapp):
        """Linux launches should advertise the desktop file for dock matching."""
        original = qapp.desktopFileName() if hasattr(qapp, "desktopFileName") else None
        try:
            _configure_linux_desktop_integration(qapp)
            if sys.platform.startswith("linux") and hasattr(qapp, "desktopFileName"):
                assert qapp.desktopFileName() == "derzug"
        finally:
            if original is not None and hasattr(qapp, "setDesktopFileName"):
                qapp.setDesktopFileName(original)

    def test_linux_desktop_entry_is_written_to_user_applications_dir(
        self, monkeypatch, tmp_path
    ):
        """Linux startup should refresh a user launcher entry with the icon path."""
        if not sys.platform.startswith("linux"):
            pytest.skip("Linux desktop entry installation is Linux-specific.")

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(sys, "argv", ["/tmp/derzug"])

        ensure_linux_desktop_entry()

        desktop_file = tmp_path / "applications" / "derzug.desktop"
        assert desktop_file.exists()
        content = desktop_file.read_text(encoding="utf-8")
        assert "Name=DerZug" in content
        assert "StartupWMClass=derzug" in content
        assert "Icon=" in content

    def test_launch_shows_canvas_with_derzug_registry(self, derzug_app, qapp):
        """Fresh launch shows an empty canvas backed by DerZug widgets."""
        window = derzug_app.window
        registry = derzug_app.main.registry
        available = sorted(
            widget.name
            for widget in registry.widgets()
            if widget.package.startswith(constants.PKG_NAME)
        )

        window.show()
        qapp.processEvents()

        scheme = window.current_document().scheme()
        assert available
        assert list(scheme.nodes) == []
        assert window.isVisible()

    def test_loaded_widget_entrypoints(self, derzug_app):
        """
        Ensure the live registry actually contains required test_widgets.
        """
        registry = derzug_app.main.registry
        orange_widget_names = set(constants.ORANGE_WIDGETS_TO_LOAD)
        widgets = list(registry.widgets())
        loaded = [(widget.name, widget.id, widget.package) for widget in widgets]

        # Ensure no outlawed widgets got in.
        invalid = [
            item
            for item in loaded
            if not item[2].startswith(constants.PKG_NAME)
            and item[0] not in orange_widget_names
        ]
        assert not invalid, f"Loaded non-DerZug widgets: {invalid}"

        # Also make sure we have some widgets.
        assert len(widgets)

        # And that the explicitly flagged orange widgets got in.
        names = {x.name for x in widgets}
        assert orange_widget_names.issubset(names)

        # As well as some DerZug widgets.
        derzug_widgets = {
            x for x in widgets if x.package.startswith(constants.PKG_NAME)
        }
        assert len(derzug_widgets)

    def test_transform_category_follows_processing(self, derzug_app):
        """Canvas category ordering should place Transform after Processing."""
        registry = derzug_app.main.registry
        categories = sorted(registry.categories(), key=lambda cat: cat.priority)
        category_names = [category.name for category in categories]

        assert "Processing" in category_names
        assert "Transform" in category_names
        assert category_names.index("Processing") < category_names.index("Transform")

    def test_table_category_contains_table_to_annotations(self, derzug_app):
        """Table widgets should appear under the dedicated Table category."""
        registry = derzug_app.main.registry
        categories = sorted(registry.categories(), key=lambda cat: cat.priority)
        category_names = [category.name for category in categories]
        widget_by_name = {widget.name: widget for widget in registry.widgets()}

        assert "Table" in category_names
        assert category_names.index("IO") < category_names.index("Table")
        assert category_names.index("Table") < category_names.index("Processing")
        assert Table2Annotation.category == "Table"
        if "Table to Annotations" in widget_by_name:
            assert widget_by_name["Table to Annotations"].category == "Table"

    def test_launch_only_creates_derzug_workflow_nodes(self, derzug_app, qapp):
        """Startup workflow nodes should all map to DerZug widgets."""
        window = derzug_app.window
        registry = derzug_app.main.registry

        window.show()
        qapp.processEvents()

        scheme = window.current_document().scheme()
        widgets_by_name = {widget.name: widget for widget in registry.widgets()}
        loaded_nodes = sorted(node.title for node in scheme.nodes)
        non_derzug = [
            (node.title, widgets_by_name[node.title].package)
            for node in scheme.nodes
            if not widgets_by_name[node.title].package.startswith(constants.PKG_NAME)
        ]

        assert not non_derzug, f"Loaded non-DerZug workflow nodes: {non_derzug}"
        assert loaded_nodes == [
            node.title for node in scheme.nodes
        ], f"Startup loaded nodes: {loaded_nodes}"


class TestUnexpectedErrorDialog:
    """Tests for DerZug's unexpected-error reporting helpers."""

    def test_build_exception_report_data_without_widget(self):
        """Non-widget exceptions should still produce key details and traceback."""
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc = sys.exc_info()

        details, traceback_text = _build_exception_report_data(exc)

        assert details["Exception"] == "RuntimeError: boom"
        assert details["Location"] != "Unknown"
        assert details["Widget"] == "Unknown"
        assert "RuntimeError: boom" in traceback_text

    def test_build_exception_report_data_with_widget(self):
        """Widget exceptions should report widget name and widget module location."""

        def _raise_from_widget(self):
            raise ValueError("widget boom")

        with widget_context(Spool) as widget:
            try:
                _raise_from_widget(widget)
            except ValueError:
                exc = sys.exc_info()

        details, traceback_text = _build_exception_report_data(exc)

        assert details["Exception"] == "ValueError: widget boom"
        assert details["Widget"] == "Spool"
        assert "derzug.widgets.spool" in details["Widget Location"]
        assert "ValueError: widget boom" in traceback_text

    def test_error_dialog_copy_traceback(self, qapp):
        """Copy Traceback should write the traceback text to the clipboard."""
        dialog = DerZugErrorDialog(
            details={"Exception": "ValueError: boom", "Location": "x.py:12"},
            traceback_text="traceback text",
        )

        dialog.copy_traceback()

        assert QApplication.clipboard().text() == "traceback text"

    def test_error_dialog_colorizes_traceback_lines(self, qapp):
        """The traceback viewer should attach syntax highlighting to key lines."""
        dialog = DerZugErrorDialog(
            details={"Exception": "ValueError: boom", "Location": "x.py:12"},
            traceback_text=(
                "Traceback (most recent call last):\n"
                '  File "x.py", line 12, in explode\n'
                "    raise ValueError('boom')\n"
                "ValueError: boom"
            ),
        )

        dialog._traceback_highlighter.rehighlight()
        document = dialog._traceback_edit.document()
        header_formats = document.findBlockByLineNumber(0).layout().formats()
        exception_formats = document.findBlockByLineNumber(3).layout().formats()

        assert header_formats
        assert exception_formats

    def test_error_dialog_exposes_submit_bug_report_button(self, qapp):
        """The dialog should offer a GitHub bug-report button."""
        dialog = DerZugErrorDialog(
            details={"Exception": "ValueError: boom", "Location": "x.py:12"},
            traceback_text="traceback text",
        )

        assert dialog._submit_bug_button.text() == "Submit Bug Report"

    def test_build_issue_body_includes_details_and_traceback(self):
        """The prefilled issue body should contain dialog details and traceback."""
        body = _build_issue_body(
            {"Exception": "ValueError: boom", "Widget": "Spool"},
            "Traceback text",
        )

        assert "Generated from the DerZug unexpected error dialog." in body
        assert "- **Exception**: ValueError: boom" in body
        assert "- **Widget**: Spool" in body
        assert "```text" in body
        assert "Traceback text" in body

    def test_build_issue_url_prefills_body_and_leaves_title_blank(self):
        """The issue URL should prefill only the GitHub body field."""
        issue_url = _build_issue_url(
            {"Exception": "ValueError: boom"},
            "Traceback text",
        )
        parsed = urlparse(issue_url)
        params = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.netloc == "github.com"
        assert parsed.path == "/dasdae/derzug/issues/new"
        assert "body" in params
        assert "title" not in params
        assert "ValueError: boom" in params["body"][0]
        assert "Traceback text" in params["body"][0]

    def test_submit_bug_report_opens_browser_with_issue_url(self, monkeypatch):
        """Clicking the button should open the prefilled GitHub issue URL."""
        opened_urls: list[str] = []

        def _fake_open(url):
            opened_urls.append(url.toString())
            return True

        monkeypatch.setattr(
            "derzug.views.orange_errors.QDesktopServices.openUrl", _fake_open
        )
        dialog = DerZugErrorDialog(
            details={"Exception": "ValueError: boom", "Location": "x.py:12"},
            traceback_text="traceback text",
        )

        dialog.submit_bug_report()

        assert len(opened_urls) == 1
        parsed = urlparse(opened_urls[0])
        params = parse_qs(parsed.query)
        assert parsed.path == "/dasdae/derzug/issues/new"
        assert "title" not in params
        assert "traceback text" in params["body"][0]
        assert not dialog._status_label.isVisible()

    def test_submit_bug_report_shows_message_when_browser_open_fails(self, monkeypatch):
        """Show a visible failure message when browser launch fails."""
        monkeypatch.setattr(
            "derzug.views.orange_errors.QDesktopServices.openUrl",
            lambda _url: False,
        )
        dialog = DerZugErrorDialog(
            details={"Exception": "ValueError: boom", "Location": "x.py:12"},
            traceback_text="traceback text",
        )

        dialog.submit_bug_report()

        assert not dialog._status_label.isHidden()
        assert "Could not open the browser" in dialog._status_label.text()

    def test_error_dialog_ctrl_q_closes_dialog(self, qapp, qtbot):
        """Ctrl+Q should close the traceback dialog."""
        dialog = DerZugErrorDialog(
            details={"Exception": "ValueError: boom", "Location": "x.py:12"},
            traceback_text="traceback text",
        )
        dialog.show()
        qtbot.wait(10)

        assert dialog.isVisible()

        qtbot.keyClick(dialog, Qt.Key_Q, modifier=Qt.ControlModifier)
        qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=1000)
        assert dialog.result() == dialog.DialogCode.Rejected


class TestDerZugCanvasWorkflow:
    """Workflow/window behavior tests for the DerZug canvas."""

    @staticmethod
    def _possible_selection_handler(window):
        """Return Orange's deferred empty-space selection handler, if any."""
        return getattr(
            window.scheme_widget, "_SchemeEditWidget__possibleSelectionHandler"
        )

    @staticmethod
    def _create_canvas_annotation(
        document,
        kind: str,
        qapp,
        *,
        start: QPoint | None = None,
        end: QPoint | None = None,
    ) -> object:
        """Create one real canvas text or arrow annotation through the toolbar tool."""
        view = document.view()
        scene = document.scene()
        viewport = view.viewport()
        before = len(document.scheme().annotations)

        action_name = {
            "text": "new-text-action",
            "arrow": "new-arrow-action",
        }[kind]
        start = QPoint(80, 80) if start is None else start
        end = QPoint(180, 130) if end is None else end
        action = _action_by_name(document.toolbarActions(), action_name)
        if not action.isChecked():
            action.trigger()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseMove,
            end,
            button=Qt.NoButton,
            buttons=Qt.LeftButton,
        )
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)
        scene.setFocusItem(None)
        qapp.processEvents()
        assert len(document.scheme().annotations) == before + 1
        return document.scheme().annotations[-1]

    @staticmethod
    def _select_canvas_annotation_via_viewport(document, annotation, qapp) -> None:
        """Select one rendered canvas annotation by clicking it in the viewport."""
        view = document.view()
        scene = document.scene()
        viewport = view.viewport()
        item = scene.item_for_annotation(annotation)
        scene.clearSelection()
        qapp.processEvents()
        target_scene_pos = item.sceneBoundingRect().center()
        target_viewport_pos = view.mapFromScene(target_scene_pos)
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, target_viewport_pos)
        qapp.processEvents()

    @staticmethod
    def _arrow_palette(window) -> QWidget:
        """Return the floating arrow color palette widget."""
        palette = window.findChild(QWidget, "canvas-arrow-color-palette")
        assert palette is not None
        return palette

    @staticmethod
    def _arrow_palette_button(window, color: str) -> QPushButton:
        """Return one arrow color swatch button by hex color."""
        button = window.findChild(
            QPushButton, f"canvas-arrow-color-{color.lstrip('#').lower()}"
        )
        assert button is not None
        return button

    @staticmethod
    def _text_palette(window) -> QWidget:
        """Return the floating text style palette widget."""
        palette = window.findChild(QWidget, "canvas-text-style-palette")
        assert palette is not None
        return palette

    @staticmethod
    def _text_size_box(window) -> QComboBox:
        """Return the floating text palette size combo box."""
        box = window.findChild(QComboBox, "canvas-text-size-box")
        assert box is not None
        return box

    @staticmethod
    def _text_align_box(window) -> QComboBox:
        """Return the floating text palette alignment combo box."""
        box = window.findChild(QComboBox, "canvas-text-align-box")
        assert box is not None
        return box

    @staticmethod
    def _text_style_button(window, name: str) -> QPushButton:
        """Return one floating text style toggle button."""
        button = window.findChild(QPushButton, f"canvas-text-{name}-button")
        assert button is not None
        return button

    def test_canvas_text_annotation_copy_paste_shortcuts_duplicate_selection(
        self, derzug_app, qapp
    ):
        """Ctrl/Cmd+C then Ctrl/Cmd+V should duplicate selected canvas text."""
        window = derzug_app.window
        document = window.current_document()
        view = document.view()
        scene = document.scene()
        viewport = view.viewport()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "text", qapp)
        scene.clearSelection()
        scene.item_for_annotation(annotation).setSelected(True)
        qapp.processEvents()
        assert document.selectedAnnotations() == [annotation]

        copy_action = _action_by_name(document.actions(), "copy-action")
        paste_action = _action_by_name(document.actions(), "paste-action")
        assert copy_action.shortcut().matches(QKeySequence.StandardKey.Copy)
        assert paste_action.shortcut().matches(QKeySequence.StandardKey.Paste)
        viewport.setFocus(Qt.OtherFocusReason)
        qapp.processEvents()

        QTest.keySequence(viewport, copy_action.shortcut())
        qapp.processEvents()
        QTest.keySequence(viewport, paste_action.shortcut())
        qapp.processEvents()

        assert len(document.scheme().annotations) == 2

    def test_canvas_arrow_annotation_copy_paste_shortcuts_duplicate_selection(
        self, derzug_app, qapp
    ):
        """Copy/paste should also duplicate selected canvas arrow annotations."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()
        viewport = document.view().viewport()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "arrow", qapp)
        scene.clearSelection()
        scene.item_for_annotation(annotation).setSelected(True)
        qapp.processEvents()
        assert document.selectedAnnotations() == [annotation]

        copy_action = _action_by_name(document.actions(), "copy-action")
        paste_action = _action_by_name(document.actions(), "paste-action")
        viewport.setFocus(Qt.OtherFocusReason)
        qapp.processEvents()

        QTest.keySequence(viewport, copy_action.shortcut())
        qapp.processEvents()
        QTest.keySequence(viewport, paste_action.shortcut())
        qapp.processEvents()

        assert len(document.scheme().annotations) == 2

    def test_canvas_arrow_shortcuts_work_after_viewport_click_selection(
        self, derzug_app, qapp
    ):
        """Arrow cut/copy/paste should work after viewport click-selection."""
        window = derzug_app.window
        document = window.current_document()
        viewport = document.view().viewport()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "arrow", qapp)
        self._select_canvas_annotation_via_viewport(document, annotation, qapp)
        assert document.selectedAnnotations() == [annotation]

        copy_action = _action_by_name(document.actions(), "copy-action")
        cut_action = _action_by_name(document.actions(), "cut-action")
        paste_action = _action_by_name(document.actions(), "paste-action")
        viewport.setFocus(Qt.OtherFocusReason)
        qapp.processEvents()

        QTest.keySequence(viewport, copy_action.shortcut())
        qapp.processEvents()
        QTest.keySequence(viewport, paste_action.shortcut())
        qapp.processEvents()
        assert len(document.scheme().annotations) == 2

        latest = document.scheme().annotations[-1]
        self._select_canvas_annotation_via_viewport(document, latest, qapp)
        assert document.selectedAnnotations() == [latest]
        QTest.keySequence(viewport, cut_action.shortcut())
        qapp.processEvents()
        assert len(document.scheme().annotations) == 1

    def test_canvas_text_annotation_cut_shortcut_removes_then_pastes_selection(
        self, derzug_app, qapp
    ):
        """Cut should remove a selected canvas annotation and allow standard paste."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()
        viewport = document.view().viewport()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "text", qapp)
        scene.clearSelection()
        scene.item_for_annotation(annotation).setSelected(True)
        qapp.processEvents()
        assert document.selectedAnnotations() == [annotation]

        cut_action = _action_by_name(document.actions(), "cut-action")
        paste_action = _action_by_name(document.actions(), "paste-action")
        assert cut_action is not None
        assert cut_action.shortcut().matches(QKeySequence.StandardKey.Cut)
        viewport.setFocus(Qt.OtherFocusReason)
        qapp.processEvents()

        QTest.keySequence(viewport, cut_action.shortcut())
        qapp.processEvents()
        assert len(document.scheme().annotations) == 0

        QTest.keySequence(viewport, paste_action.shortcut())
        qapp.processEvents()
        assert len(document.scheme().annotations) == 1

    def test_canvas_paste_places_text_annotation_near_mouse_position(
        self, derzug_app, qapp
    ):
        """Paste should place copied canvas annotations so the cursor touches them."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()
        view = document.view()
        viewport = view.viewport()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "text", qapp)
        scene.clearSelection()
        scene.item_for_annotation(annotation).setSelected(True)
        qapp.processEvents()

        copy_action = _action_by_name(document.actions(), "copy-action")
        paste_action = _action_by_name(document.actions(), "paste-action")
        viewport.setFocus(Qt.OtherFocusReason)
        qapp.processEvents()

        QTest.keySequence(viewport, copy_action.shortcut())
        qapp.processEvents()

        paste_viewport_pos = QPoint(240, 210)
        target_scene_pos = view.mapToScene(paste_viewport_pos)
        QCursor.setPos(viewport.mapToGlobal(paste_viewport_pos))
        qapp.processEvents()

        QTest.keySequence(viewport, paste_action.shortcut())
        qapp.processEvents()

        assert len(document.scheme().annotations) == 2
        pasted = document.scheme().annotations[-1]
        pasted_item = scene.item_for_annotation(pasted)
        assert pasted_item.sceneBoundingRect().contains(target_scene_pos)

    def test_arrow_palette_visibility_follows_tool_and_selection(
        self, derzug_app, qapp
    ):
        """The floating arrow palette should appear only for arrow states."""
        window = derzug_app.window
        document = window.current_document()
        palette = self._arrow_palette(window)
        arrow_action = _action_by_name(document.toolbarActions(), "new-arrow-action")

        window.show()
        qapp.processEvents()

        assert not palette.isVisible()
        arrow_action.trigger()
        qapp.processEvents()
        assert palette.isVisible()

        QTest.keyClick(document.view().viewport(), Qt.Key_Escape)
        qapp.processEvents()
        assert not palette.isVisible()

        arrow = self._create_canvas_annotation(document, "arrow", qapp)
        self._select_canvas_annotation_via_viewport(document, arrow, qapp)
        assert palette.isVisible()

        text = self._create_canvas_annotation(document, "text", qapp)
        document.scene().clearSelection()
        document.scene().item_for_annotation(text).setSelected(True)
        qapp.processEvents()
        assert not palette.isVisible()

    def test_arrow_palette_changes_active_color_for_new_arrows(self, derzug_app, qapp):
        """Clicking a swatch in arrow-create mode should set new-arrow color."""
        window = derzug_app.window
        document = window.current_document()
        arrow_action = _action_by_name(document.toolbarActions(), "new-arrow-action")
        target_color = "#1F9CDF"

        window.show()
        qapp.processEvents()

        arrow_action.trigger()
        qapp.processEvents()
        QTest.mouseClick(
            self._arrow_palette_button(window, target_color),
            Qt.LeftButton,
        )
        qapp.processEvents()

        start = QPoint(90, 90)
        end = QPoint(180, 120)
        viewport = document.view().viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseMove,
            end,
            button=Qt.NoButton,
            buttons=Qt.LeftButton,
        )
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)
        qapp.processEvents()

        arrow = document.scheme().annotations[-1]
        assert isinstance(arrow, orange_view.SchemeArrowAnnotation)
        assert arrow.color.lower() == target_color.lower()

    def test_arrow_palette_enlarges_selected_swatch(self, derzug_app, qapp):
        """The arrow palette should enlarge the active color swatch."""
        window = derzug_app.window
        document = window.current_document()
        arrow_action = _action_by_name(document.toolbarActions(), "new-arrow-action")
        active_button = self._arrow_palette_button(window, "#C1272D")
        inactive_button = self._arrow_palette_button(window, "#000")

        window.show()
        qapp.processEvents()

        arrow_action.trigger()
        qapp.processEvents()

        assert active_button.width() > inactive_button.width()

    def test_arrow_palette_recolors_selected_arrows_with_undo(self, derzug_app, qapp):
        """Clicking a swatch with an arrow selected should stay undoable."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()
        target_color = "#39B54A"

        window.show()
        qapp.processEvents()

        arrow = self._create_canvas_annotation(document, "arrow", qapp)
        assert isinstance(arrow, orange_view.SchemeArrowAnnotation)
        old_color = arrow.color
        self._select_canvas_annotation_via_viewport(document, arrow, qapp)

        QTest.mouseClick(
            self._arrow_palette_button(window, target_color),
            Qt.LeftButton,
        )
        qapp.processEvents()

        assert arrow.color.lower() == target_color.lower()
        assert (
            scene.item_for_annotation(arrow).color().name().lower()
            == target_color.lower()
        )

        document.undoStack().undo()
        qapp.processEvents()
        assert arrow.color == old_color

    def test_arrow_palette_recolors_selected_arrow_when_click_clears_selection(
        self,
        derzug_app,
        qapp,
    ):
        """Arrow recolor should survive a palette click clearing selection."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()
        target_color = "#39B54A"

        window.show()
        qapp.processEvents()

        arrow = self._create_canvas_annotation(document, "arrow", qapp)
        self._select_canvas_annotation_via_viewport(document, arrow, qapp)
        button = self._arrow_palette_button(window, target_color)
        button.pressed.connect(scene.clearSelection)

        QTest.mouseClick(button, Qt.LeftButton)
        qapp.processEvents()

        assert arrow.color.lower() == target_color.lower()

    def test_arrow_palette_recolors_live_arrow_item_for_each_swatch(
        self, derzug_app, qapp
    ):
        """Selecting swatches should repaint the selected arrow immediately."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()

        window.show()
        qapp.processEvents()

        arrow = self._create_canvas_annotation(document, "arrow", qapp)
        self._select_canvas_annotation_via_viewport(document, arrow, qapp)
        item = scene.item_for_annotation(arrow)

        for color in ("#000", "#C1272D", "#662D91", "#1F9CDF", "#39B54A"):
            QTest.mouseClick(self._arrow_palette_button(window, color), Qt.LeftButton)
            qapp.processEvents()
            assert arrow.color.lower() == color.lower()
            assert (
                item.color().name().lower() == orange_view.QColor(color).name().lower()
            )

    def test_shift_arrow_edit_snaps_to_octilinear_angles(
        self, derzug_app, qapp, monkeypatch
    ):
        """Shift-dragging an arrow endpoint should snap to 45-degree increments."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()

        window.show()
        qapp.processEvents()

        arrow = self._create_canvas_annotation(document, "arrow", qapp)
        item = scene.item_for_annotation(arrow)
        document._SchemeEditWidget__startControlPointEdit(item)
        handler = scene.user_interaction_handler
        control = handler.control
        point = control._ControlPointLine__points[1]

        monkeypatch.setattr(
            orange_view.QApplication,
            "keyboardModifiers",
            staticmethod(lambda: Qt.ShiftModifier),
        )

        control._ControlPointLine__setActiveControl(point)
        control._ControlPointLine__activeControlMoved(QPointF(200, 145))
        qapp.processEvents()

        line = control.line()
        dx = line.p2().x() - line.p1().x()
        dy = line.p2().y() - line.p1().y()
        rounded_abs = sorted((round(abs(dx), 3), round(abs(dy), 3)))

        assert rounded_abs[0] == 0 or rounded_abs[0] == rounded_abs[1]

    def test_shift_new_arrow_creation_snaps_to_octilinear_angles(
        self, derzug_app, qapp
    ):
        """Shift while drawing a new arrow should snap it to 45-degree increments."""
        window = derzug_app.window
        document = window.current_document()
        viewport = document.view().viewport()

        window.show()
        qapp.processEvents()

        _action_by_name(document.toolbarActions(), "new-arrow-action").trigger()
        qapp.processEvents()

        start = QPoint(90, 90)
        end = QPoint(180, 135)
        QTest.mousePress(viewport, Qt.LeftButton, Qt.ShiftModifier, start)
        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseMove,
            end,
            button=Qt.NoButton,
            buttons=Qt.LeftButton,
        )
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.ShiftModifier, end)
        qapp.processEvents()

        arrow = document.scheme().annotations[-1]
        assert isinstance(arrow, orange_view.SchemeArrowAnnotation)
        dx = arrow.end_pos[0] - arrow.start_pos[0]
        dy = arrow.end_pos[1] - arrow.start_pos[1]
        rounded_abs = sorted((round(abs(dx), 3), round(abs(dy), 3)))

        assert rounded_abs[0] == 0 or rounded_abs[0] == rounded_abs[1]

    def test_text_palette_visibility_follows_tool_and_selection(self, derzug_app, qapp):
        """The floating text palette should appear only for text states."""
        window = derzug_app.window
        document = window.current_document()
        palette = self._text_palette(window)
        text_action = _action_by_name(document.toolbarActions(), "new-text-action")

        window.show()
        qapp.processEvents()

        assert not palette.isVisible()
        text_action.trigger()
        qapp.processEvents()
        assert palette.isVisible()

        QTest.keyClick(document.view().viewport(), Qt.Key_Escape)
        qapp.processEvents()
        assert not palette.isVisible()

        text = self._create_canvas_annotation(document, "text", qapp)
        self._select_canvas_annotation_via_viewport(document, text, qapp)
        assert palette.isVisible()

        arrow = self._create_canvas_annotation(document, "arrow", qapp)
        document.scene().clearSelection()
        document.scene().item_for_annotation(arrow).setSelected(True)
        qapp.processEvents()
        assert not palette.isVisible()

    def test_text_palette_stays_visible_after_creating_text_annotation(
        self, derzug_app, qapp
    ):
        """Creating a text box should keep the text palette visible."""
        window = derzug_app.window
        document = window.current_document()
        palette = self._text_palette(window)

        window.show()
        qapp.processEvents()

        self._create_canvas_annotation(document, "text", qapp)
        qapp.processEvents()

        assert palette.isVisible()

    def test_text_palette_changes_active_style_for_new_text_annotations(
        self, derzug_app, qapp
    ):
        """Choosing text styles in text-create mode should affect new text."""
        window = derzug_app.window
        document = window.current_document()
        text_action = _action_by_name(document.toolbarActions(), "new-text-action")

        window.show()
        qapp.processEvents()

        text_action.trigger()
        qapp.processEvents()
        self._text_size_box(window).setCurrentText("24")
        self._text_align_box(window).setCurrentText("Center")
        qapp.processEvents()
        QTest.mouseClick(self._text_style_button(window, "bold"), Qt.LeftButton)
        QTest.mouseClick(self._text_style_button(window, "italic"), Qt.LeftButton)
        QTest.mouseClick(self._text_style_button(window, "underline"), Qt.LeftButton)
        qapp.processEvents()

        text = self._create_canvas_annotation(document, "text", qapp)
        assert isinstance(text, orange_view.SchemeTextAnnotation)
        assert text.font["size"] == 24
        assert text.font["weight"] == int(QFont.Weight.Bold)
        assert text.font["italic"] is True
        assert text.font["underline"] is True
        assert text.font["alignment"] == "center"

    def test_text_palette_restyles_only_selected_text_with_undo(self, derzug_app, qapp):
        """Formatting changes should affect only selected text and stay undoable."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()

        window.show()
        qapp.processEvents()

        first = self._create_canvas_annotation(
            document,
            "text",
            qapp,
            start=QPoint(70, 70),
            end=QPoint(190, 130),
        )
        second = self._create_canvas_annotation(
            document,
            "text",
            qapp,
            start=QPoint(240, 180),
            end=QPoint(360, 240),
        )
        first_before = dict(first.font)
        second_before = dict(second.font)

        self._select_canvas_annotation_via_viewport(document, first, qapp)
        assert document.selectedAnnotations() == [first]

        self._text_size_box(window).setCurrentText("28")
        qapp.processEvents()
        QTest.mouseClick(self._text_style_button(window, "italic"), Qt.LeftButton)
        qapp.processEvents()

        assert first.font["size"] == 28
        assert first.font["italic"] is True
        assert second.font == second_before

        item_font = scene.item_for_annotation(first).font()
        assert item_font.pixelSize() == 28
        assert item_font.italic() is True

        document.undoStack().undo()
        qapp.processEvents()
        document.undoStack().undo()
        qapp.processEvents()

        assert first.font == first_before
        assert second.font == second_before

    def test_text_palette_realigns_selected_text(self, derzug_app, qapp):
        """Changing alignment should affect only the selected text annotation."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()

        window.show()
        qapp.processEvents()

        first = self._create_canvas_annotation(
            document, "text", qapp, start=QPoint(70, 70), end=QPoint(190, 130)
        )
        second = self._create_canvas_annotation(
            document, "text", qapp, start=QPoint(240, 180), end=QPoint(360, 240)
        )

        self._select_canvas_annotation_via_viewport(document, first, qapp)
        self._text_align_box(window).setCurrentText("Right")
        qapp.processEvents()

        assert first.font["alignment"] == "right"
        assert second.font.get("alignment", "left") == "left"
        assert (
            scene.item_for_annotation(first).textCursor().blockFormat().alignment()
            & Qt.AlignmentFlag.AlignRight
        )

    def test_text_alignment_round_trips_through_ows_save_load(self, derzug_app):
        """Text alignment should persist through standard .ows serialization."""
        scheme = orange_view.Scheme()
        scheme.add_annotation(
            orange_view.SchemeTextAnnotation(
                (10.0, 20.0, 100.0, 50.0),
                "hello",
                "text/plain",
                {"family": "Arial", "size": 16, "alignment": "center"},
            )
        )
        buffer = io.BytesIO()

        scheme.save_to(buffer)
        loaded = orange_view.Scheme()
        loaded.load_from(io.BytesIO(buffer.getvalue()))

        assert len(loaded.annotations) == 1
        loaded_text = loaded.annotations[0]
        assert isinstance(loaded_text, orange_view.SchemeTextAnnotation)
        assert loaded_text.font["alignment"] == "center"

    def test_load_scheme_fits_view_to_all_widgets_and_annotations(
        self, derzug_app, qapp, orange_workflow, tmp_path
    ):
        """Loading a workflow should zoom out to show widgets and annotations."""
        window = derzug_app.window
        orange_workflow((("Spool", "spool-node"),))
        document = window.current_document()
        scheme = document.scheme()
        assert scheme is not None

        scheme.add_annotation(
            orange_view.SchemeTextAnnotation(
                (4200.0, 3100.0, 220.0, 120.0),
                "far away",
                "text/plain",
                {"family": "Arial", "size": 16},
            )
        )
        qapp.processEvents()

        workflow_path = tmp_path / "fit_all_contents.ows"
        with workflow_path.open("wb") as stream:
            scheme.save_to(stream)

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        QCoreApplication.sendPostedEvents()
        qapp.processEvents()

        view = window.current_document().view()
        scene = window.current_document().scene()
        visible = _visible_scene_rect(view)
        contents = scene.itemsBoundingRect()

        assert visible.contains(contents)

    def test_load_scheme_keeps_larger_existing_view_when_contents_already_fit(
        self, derzug_app, qapp, orange_workflow, tmp_path
    ):
        """
        Loading should not zoom in when the current view already contains
        contents.
        """
        window = derzug_app.window
        orange_workflow((("Spool", "spool-node"),))
        document = window.current_document()
        scheme = document.scheme()
        assert scheme is not None

        scheme.add_annotation(
            orange_view.SchemeTextAnnotation(
                (220.0, 180.0, 120.0, 60.0),
                "small",
                "text/plain",
                {"family": "Arial", "size": 16},
            )
        )
        qapp.processEvents()

        workflow_path = tmp_path / "keep_large_view.ows"
        with workflow_path.open("wb") as stream:
            scheme.save_to(stream)

        view = document.view()
        view.setSceneRect(QRectF(-2000.0, -1500.0, 5000.0, 4000.0))
        view.fitInView(view.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        qapp.processEvents()
        visible_before = _visible_scene_rect(view)

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        QCoreApplication.sendPostedEvents()
        qapp.processEvents()

        reloaded_view = window.current_document().view()
        reloaded_scene = window.current_document().scene()
        visible_after = _visible_scene_rect(reloaded_view)
        contents = reloaded_scene.itemsBoundingRect()

        assert visible_after.contains(contents)
        assert visible_after.width() >= visible_before.width()
        assert visible_after.height() >= visible_before.height()

    def test_text_palette_applies_inline_rich_text_to_active_editor(
        self, derzug_app, qapp
    ):
        """Formatting while editing should preserve mixed rich text."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "text", qapp)
        item = scene.item_for_annotation(annotation)
        item.setSelected(True)
        item.startEdit()
        qapp.processEvents()

        cursor = item.textCursor()
        cursor.insertText("alpha beta")
        item.setTextCursor(cursor)

        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left, n=2)
        item.setTextCursor(cursor)
        qapp.processEvents()

        QTest.mouseClick(self._text_style_button(window, "bold"), Qt.LeftButton)
        qapp.processEvents()
        item.endEdit()
        qapp.processEvents()

        assert annotation.content_type == "text/html"
        assert "alpha" in annotation.content
        assert "beta" in annotation.content
        assert "<" in annotation.content
        assert "font-weight" in annotation.content or "<b>" in annotation.content

    def test_text_style_buttons_have_tooltips_with_shortcuts(self, derzug_app, qapp):
        """Formatting buttons should advertise their standard shortcuts."""
        window = derzug_app.window

        window.show()
        qapp.processEvents()

        assert "Bold" in self._text_style_button(window, "bold").toolTip()
        assert "Italic" in self._text_style_button(window, "italic").toolTip()
        assert "Underline" in self._text_style_button(window, "underline").toolTip()

    def test_standard_text_shortcuts_apply_to_active_text_editor(
        self, derzug_app, qapp
    ):
        """Bold/italic/underline shortcuts should format the active editor."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()
        viewport = document.view().viewport()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "text", qapp)
        item = scene.item_for_annotation(annotation)
        item.setSelected(True)
        item.startEdit()
        qapp.processEvents()

        cursor = item.textCursor()
        cursor.insertText("alpha")
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        item.setTextCursor(cursor)
        viewport.setFocus(Qt.OtherFocusReason)
        qapp.processEvents()

        QTest.keySequence(viewport, QKeySequence.StandardKey.Bold)
        QTest.keySequence(viewport, QKeySequence.StandardKey.Italic)
        QTest.keySequence(viewport, QKeySequence.StandardKey.Underline)
        qapp.processEvents()

        item.endEdit()
        qapp.processEvents()

        assert annotation.content_type == "text/html"
        assert "font-weight" in annotation.content or "<b>" in annotation.content
        assert "font-style" in annotation.content or "<i>" in annotation.content
        assert "text-decoration" in annotation.content or "<u>" in annotation.content

    def test_middle_button_drag_pans_canvas_and_expands_scene(
        self, derzug_app, qapp, orange_workflow
    ):
        """Middle-button dragging should hand-pan the canvas into new whitespace."""
        window = derzug_app.window
        orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Waterfall", "waterfall-node"),
                ("Code", "code-node"),
            ),
            (
                ("spool-node", "Patch", "waterfall-node", "Patch"),
                ("waterfall-node", "Patch", "code-node", "Patch"),
            ),
        )
        window.show()
        qapp.processEvents()

        view = window.scheme_widget.view()
        scene = window.scheme_widget.scene()
        viewport = view.viewport()
        start = viewport.rect().center()
        end = start - QPoint(120, 90)
        initial_rect = view.sceneRect()
        initial_center = view.mapToScene(viewport.rect().center())
        initial_selection = scene.selectedItems()

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonPress,
            start,
            button=Qt.MiddleButton,
            buttons=Qt.MiddleButton,
        )
        qapp.processEvents()

        assert view.dragMode() == view.DragMode.ScrollHandDrag
        assert viewport.cursor().shape() == Qt.CursorShape.ClosedHandCursor
        assert self._possible_selection_handler(window) is None
        assert scene.user_interaction_handler is None

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseMove,
            end,
            button=Qt.NoButton,
            buttons=Qt.MiddleButton,
        )
        qapp.processEvents()

        expanded_rect = view.sceneRect()
        assert expanded_rect.width() > initial_rect.width()
        assert expanded_rect.height() > initial_rect.height()
        assert view.mapToScene(viewport.rect().center()) != initial_center
        assert self._possible_selection_handler(window) is None
        assert scene.user_interaction_handler is None
        assert scene.selectedItems() == initial_selection

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonRelease,
            end,
            button=Qt.MiddleButton,
            buttons=Qt.NoButton,
        )
        qapp.processEvents()

        assert view.dragMode() == view.DragMode.NoDrag
        assert viewport.cursor().shape() == Qt.CursorShape.ArrowCursor
        assert self._possible_selection_handler(window) is None
        assert scene.user_interaction_handler is None

    def test_text_palette_stays_pinned_during_middle_button_pan(self, derzug_app, qapp):
        """The floating text palette should stay fixed to the viewport during pan."""
        window = derzug_app.window
        document = window.current_document()
        view = document.view()
        viewport = view.viewport()

        window.show()
        qapp.processEvents()

        self._create_canvas_annotation(document, "text", qapp)
        palette = self._text_palette(window)
        assert palette.isVisible()
        initial_pos = palette.pos()

        start = viewport.rect().center()
        end = start - QPoint(120, 90)

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonPress,
            start,
            button=Qt.MiddleButton,
            buttons=Qt.MiddleButton,
        )
        qapp.processEvents()

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseMove,
            end,
            button=Qt.NoButton,
            buttons=Qt.MiddleButton,
        )
        qapp.processEvents()

        assert palette.isVisible()
        assert palette.pos() == initial_pos

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonRelease,
            end,
            button=Qt.MiddleButton,
            buttons=Qt.NoButton,
        )
        qapp.processEvents()

        assert palette.pos() == initial_pos

    def test_shift_drag_locks_text_annotation_to_one_axis(
        self, derzug_app, qapp, monkeypatch
    ):
        """Holding Shift while moving a text annotation should lock it to one axis."""
        window = derzug_app.window
        document = window.current_document()
        scene = document.scene()

        window.show()
        qapp.processEvents()

        annotation = self._create_canvas_annotation(document, "text", qapp)
        item = scene.item_for_annotation(annotation)
        start = QPointF(item.pos())

        monkeypatch.setattr(
            orange_view.QApplication,
            "keyboardModifiers",
            staticmethod(lambda: Qt.ShiftModifier),
        )
        item.setPos(start + QPointF(80, 20))
        qapp.processEvents()

        delta = item.pos() - start
        assert delta.x() == 0 or delta.y() == 0

    def test_shift_drag_locks_widget_to_one_axis(
        self, derzug_app, qapp, orange_workflow, monkeypatch
    ):
        """Holding Shift while moving a widget should lock it to one axis."""
        window = derzug_app.window
        workflow = orange_workflow((("Spool", "spool-node"),))
        node = workflow.nodes_by_title["spool-node"]
        item = window.current_document().scene().item_for_node(node)

        window.show()
        qapp.processEvents()

        start = QPointF(item.pos())
        monkeypatch.setattr(
            orange_view.QApplication,
            "keyboardModifiers",
            staticmethod(lambda: Qt.ShiftModifier),
        )
        item.setPos(start + QPointF(80, 20))
        qapp.processEvents()

        delta = item.pos() - start
        assert delta.x() == 0 or delta.y() == 0

    def test_left_drag_on_empty_canvas_still_uses_rectangle_selection(
        self, derzug_app, qapp, orange_workflow
    ):
        """Left-dragging empty canvas should still use Orange's rectangle selection."""
        window = derzug_app.window
        orange_workflow((("Spool", "spool-node"), ("Waterfall", "waterfall-node")))
        window.show()
        qapp.processEvents()

        view = window.scheme_widget.view()
        scene = window.scheme_widget.scene()
        viewport = view.viewport()
        start = viewport.rect().center()
        end = start - QPoint(80, 60)

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonPress,
            start,
            button=Qt.LeftButton,
            buttons=Qt.LeftButton,
        )
        qapp.processEvents()

        handler = self._possible_selection_handler(window)
        assert isinstance(handler, RectangleSelectionAction)
        assert scene.user_interaction_handler is None

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseMove,
            end,
            button=Qt.NoButton,
            buttons=Qt.LeftButton,
        )
        qapp.processEvents()

        assert self._possible_selection_handler(window) is None
        assert isinstance(scene.user_interaction_handler, RectangleSelectionAction)

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonRelease,
            end,
            button=Qt.LeftButton,
            buttons=Qt.NoButton,
        )
        qapp.processEvents()

        assert scene.user_interaction_handler is None

    def test_reset_view_recenters_widgets_after_middle_button_pan(
        self, derzug_app, qapp, orange_workflow
    ):
        """Reset view should bring workflow items back after panning into whitespace."""
        window = derzug_app.window
        orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Waterfall", "waterfall-node"),
                ("Code", "code-node"),
            ),
            (
                ("spool-node", "Patch", "waterfall-node", "Patch"),
                ("waterfall-node", "Patch", "code-node", "Patch"),
            ),
        )
        window.show()
        qapp.processEvents()

        view = window.scheme_widget.view()
        scene = window.scheme_widget.scene()
        viewport = view.viewport()
        contents_rect = scene.itemsBoundingRect()
        reset_action = view.findChild(QAction, "action-zoom-reset")

        assert reset_action is not None
        assert view.mapToScene(viewport.rect()).boundingRect().intersects(contents_rect)

        start = viewport.rect().center()
        end = start - QPoint(viewport.width() * 3, viewport.height() * 3)

        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonPress,
            start,
            button=Qt.MiddleButton,
            buttons=Qt.MiddleButton,
        )
        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseMove,
            end,
            button=Qt.NoButton,
            buttons=Qt.MiddleButton,
        )
        _dispatch_mouse_event(
            viewport,
            QEvent.Type.MouseButtonRelease,
            end,
            button=Qt.MiddleButton,
            buttons=Qt.NoButton,
        )
        qapp.processEvents()

        assert (
            not view.mapToScene(viewport.rect())
            .boundingRect()
            .intersects(contents_rect)
        )

        reset_action.trigger()
        qapp.processEvents()

        assert view.mapToScene(viewport.rect()).boundingRect().intersects(contents_rect)

    def test_double_click_canvas_error_icon_opens_traceback_dialog(
        self, derzug_app, qapp, qtbot, orange_workflow, monkeypatch
    ):
        """Double-clicking a node's red canvas error icon should open traceback."""
        window = derzug_app.window
        dialogs: list[DerZugErrorDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(DerZugErrorDialog, "exec", _fake_exec)

        workflow = orange_workflow((("Code", "code-node"),))
        code_widget = workflow.widgets_by_title["code-node"]
        code_node = workflow.nodes_by_title["code-node"]
        code_widget.show()
        qapp.processEvents()

        code_widget.set_patch(dc.get_example_patch("example_event_1"))
        code_widget._editor.setPlainText("raise ValueError('canvas boom')")
        code_widget._run_button.click()
        qapp.processEvents()

        node_item = window.current_document().scene().item_for_node(code_node)
        icon_center = node_item.errorItem.sceneBoundingRect().center()
        view = window.scheme_widget.view()
        viewport_pos = view.mapFromScene(icon_center)

        assert node_item.errorItem.isVisible()
        assert code_widget._last_error_exc is not None

        qtbot.mouseDClick(view.viewport(), Qt.LeftButton, pos=viewport_pos)

        assert dialogs
        assert "ValueError: canvas boom" in dialogs[0]._traceback_edit.toPlainText()

    def test_double_click_canvas_node_body_does_not_open_traceback_dialog(
        self, derzug_app, qapp, qtbot, orange_workflow, monkeypatch
    ):
        """Double-clicking the node body should keep normal canvas behavior."""
        window = derzug_app.window
        dialogs: list[DerZugErrorDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(DerZugErrorDialog, "exec", _fake_exec)

        workflow = orange_workflow((("Code", "code-node"),))
        code_widget = workflow.widgets_by_title["code-node"]
        code_node = workflow.nodes_by_title["code-node"]
        code_widget.show()
        qapp.processEvents()

        code_widget.set_patch(dc.get_example_patch("example_event_1"))
        code_widget._editor.setPlainText("raise ValueError('body boom')")
        code_widget._run_button.click()
        qapp.processEvents()

        node_item = window.current_document().scene().item_for_node(code_node)
        body_center = window.scheme_widget.view().mapFromScene(
            node_item.shapeItem.sceneBoundingRect().center()
        )

        qtbot.mouseDClick(
            window.scheme_widget.view().viewport(), Qt.LeftButton, pos=body_center
        )

        assert not dialogs

    def test_workflow_roundtrip_preserves_graph_and_key_setting(
        self, derzug_app, tmp_path, qapp, orange_workflow
    ):
        """Saving and loading a workflow preserves topology and a widget setting."""
        window = derzug_app.window
        workflow = orange_workflow(
            (
                ("Filter", "filter-node"),
                ("Rolling", "rolling-node"),
                ("Waterfall", "waterfall-node"),
            ),
            (
                ("filter-node", "Patch", "rolling-node", "Patch"),
                ("rolling-node", "Patch", "waterfall-node", "Patch"),
            ),
        )

        filter_widget = workflow.widgets_by_title["filter-node"]
        filter_widget.selected_filter = "median_filter"
        filter_widget._filter_combo.setCurrentText("median_filter")
        qapp.processEvents()

        original_nodes, original_links = _graph_signature(workflow.scheme)
        workflow_path = tmp_path / "roundtrip.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))
        assert workflow_path.exists()

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        loaded_scheme = window.current_document().scheme()
        loaded_nodes, loaded_links = _graph_signature(loaded_scheme)

        assert loaded_nodes == original_nodes
        assert loaded_links == original_links

        loaded_filter_node = next(
            node for node in loaded_scheme.nodes if node.title == "filter-node"
        )
        loaded_filter_widget = loaded_scheme.widget_for_node(loaded_filter_node)
        assert loaded_filter_widget.selected_filter == "median_filter"

    def test_load_scheme_without_code_widget_skips_security_warning(
        self, derzug_app, tmp_path, qapp, orange_workflow, monkeypatch
    ):
        """Loading a safe workflow should not show the code-widget warning."""
        window = derzug_app.window
        _clear_code_warning_setting()
        workflow = orange_workflow((("Spool", "spool-node"),))
        workflow_path = tmp_path / "safe.ows"
        shown: list[object] = []

        class _FakeDialog:
            hide_future_warnings = False

            def __init__(self, parent=None) -> None:
                shown.append(parent)

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(orange_view, "CodeWorkflowWarningDialog", _FakeDialog)

        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()

        assert shown == []

    def test_load_scheme_with_code_widget_shows_security_warning(
        self, derzug_app, tmp_path, qapp, orange_workflow, monkeypatch
    ):
        """Loading a workflow with a Code widget should show the warning."""
        window = derzug_app.window
        _clear_code_warning_setting()
        workflow = orange_workflow((("Code", "code-node"),))
        workflow_path = tmp_path / "code.ows"
        shown: list[object] = []

        class _FakeDialog:
            hide_future_warnings = False

            def __init__(self, parent=None) -> None:
                shown.append(parent)

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(orange_view, "CodeWorkflowWarningDialog", _FakeDialog)

        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()

        assert shown == [window]

    def test_code_warning_cancel_aborts_workflow_load(
        self, derzug_app, tmp_path, qapp, orange_workflow, monkeypatch
    ):
        """Canceling the code warning should leave the current workflow unchanged."""
        window = derzug_app.window
        _clear_code_warning_setting()
        initial = orange_workflow((("Spool", "spool-node"),))
        initial_signature = _graph_signature(initial.scheme)
        code_workflow = orange_workflow((("Code", "code-node"),), clear=False)
        workflow_path = tmp_path / "code-cancel.ows"

        class _FakeDialog:
            hide_future_warnings = False

            def __init__(self, parent=None) -> None:
                self.parent = parent

            def exec(self):
                return QDialog.DialogCode.Rejected

        monkeypatch.setattr(orange_view, "CodeWorkflowWarningDialog", _FakeDialog)

        assert window.save_scheme_to(code_workflow.scheme, str(workflow_path))
        orange_workflow((("Spool", "spool-node"),))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()

        assert _graph_signature(window.current_document().scheme()) == initial_signature

    def test_code_warning_opt_out_suppresses_later_load_prompt(
        self, derzug_app, tmp_path, qapp, orange_workflow, monkeypatch
    ):
        """Accepting with opt-out should suppress the prompt on later code loads."""
        window = derzug_app.window
        _clear_code_warning_setting()
        workflow = orange_workflow((("Code", "code-node"),))
        workflow_path = tmp_path / "code-optout.ows"
        shown: list[object] = []

        class _FakeDialog:
            hide_future_warnings = True

            def __init__(self, parent=None) -> None:
                shown.append(parent)

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(orange_view, "CodeWorkflowWarningDialog", _FakeDialog)

        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        window.load_scheme(str(workflow_path))
        qapp.processEvents()

        assert shown == [window]
        assert window.should_show_code_widget_warning() is False

    def test_load_scheme_warns_for_code_widget_inside_composite(
        self, derzug_app, tmp_path, qapp, orange_workflow, monkeypatch
    ):
        """Grouped composites with internal Code widgets should trigger the warning."""
        window = derzug_app.window
        _clear_code_warning_setting()
        workflow = orange_workflow((("Spool", "spool-node"), ("Code", "code-node")))
        composite = window._canvas_composite_controller.group_nodes(
            [
                workflow.nodes_by_title["spool-node"],
                workflow.nodes_by_title["code-node"],
            ]
        )
        workflow_path = tmp_path / "composite-code.ows"
        shown: list[object] = []

        class _FakeDialog:
            hide_future_warnings = False

            def __init__(self, parent=None) -> None:
                shown.append(parent)

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(orange_view, "CodeWorkflowWarningDialog", _FakeDialog)

        assert composite is not None
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()

        assert shown == [window]

    def test_workflow_roundtrip_preserves_waterfall_selection(
        self, derzug_app, tmp_path, qapp, orange_workflow
    ):
        """Saving and loading a workflow should preserve Waterfall ROI selection."""
        window = derzug_app.window
        workflow = orange_workflow((("Waterfall", "waterfall-node"),))
        patch = dc.get_example_patch("example_event_2")
        waterfall_widget = workflow.widgets_by_title["waterfall-node"]

        waterfall_widget.show()
        waterfall_widget.set_patch(patch)
        qapp.processEvents()
        axes = waterfall_widget._axes
        waterfall_widget._create_selection_roi(
            center_x=float((axes.x_plot[0] + axes.x_plot[-1]) / 2),
            center_y=float((axes.y_plot[0] + axes.y_plot[-1]) / 2),
        )
        original = waterfall_widget._selection_apply_to_patch(patch)

        workflow_path = tmp_path / "waterfall-selection.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        loaded_scheme = window.current_document().scheme()
        loaded_node = next(
            node for node in loaded_scheme.nodes if node.title == "waterfall-node"
        )
        loaded_widget = loaded_scheme.widget_for_node(loaded_node)
        loaded_widget.show()
        loaded_widget.set_patch(patch)
        qapp.processEvents()

        assert loaded_widget._roi is not None
        assert loaded_widget.saved_selection_basis == "absolute"
        restored = loaded_widget._selection_apply_to_patch(patch)
        assert restored.shape == original.shape

    def test_workflow_roundtrip_preserves_select_patch_values(
        self, derzug_app, tmp_path, qapp, orange_workflow
    ):
        """Saving and loading a workflow should preserve Select patch values."""
        window = derzug_app.window
        workflow = orange_workflow((("Select", "select-node"),))
        patch = dc.get_example_patch("example_event_2")
        select_widget = workflow.widgets_by_title["select-node"]
        distance = patch.get_array("distance")
        selected = (float(distance[100]), float(distance[200]))

        select_widget.show()
        select_widget.set_patch(patch)
        qapp.processEvents()
        select_widget._selection_update_patch_range("distance", *selected)
        qapp.processEvents()

        workflow_path = tmp_path / "select-patch-values.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        loaded_scheme = window.current_document().scheme()
        loaded_node = next(
            node for node in loaded_scheme.nodes if node.title == "select-node"
        )
        loaded_widget = loaded_scheme.widget_for_node(loaded_node)
        loaded_widget.show()
        loaded_widget.set_patch(patch)
        qapp.processEvents()

        assert loaded_widget._selection_current_patch_range(
            "distance"
        ) == pytest.approx(selected)
        low_edit, high_edit = loaded_widget._selection_patch_edits["distance"]
        assert low_edit.text() == format_display(selected[0])
        assert high_edit.text() == format_display(selected[1])

    def test_workflow_roundtrip_preserves_select_patch_basis_and_sample_values(
        self, derzug_app, tmp_path, qapp, orange_workflow
    ):
        """Saving and loading a workflow preserves non-default Select basis state."""
        window = derzug_app.window
        workflow = orange_workflow((("Select", "select-node"),))
        patch = dc.get_example_patch("example_event_2")
        select_widget = workflow.widgets_by_title["select-node"]

        select_widget.show()
        select_widget.set_patch(patch)
        qapp.processEvents()
        select_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")
        qapp.processEvents()
        select_widget._selection_update_patch_range("distance", 100, 200)
        qapp.processEvents()

        workflow_path = tmp_path / "select-patch-samples.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        loaded_scheme = window.current_document().scheme()
        loaded_node = next(
            node for node in loaded_scheme.nodes if node.title == "select-node"
        )
        loaded_widget = loaded_scheme.widget_for_node(loaded_node)
        loaded_widget.show()
        loaded_widget.set_patch(patch)
        qapp.processEvents()

        assert loaded_widget._selection_patch_basis == "samples"
        assert loaded_widget._selection_current_patch_range("distance") == (100, 200)
        assert (
            loaded_widget._selection_panel.patch_basis_combo.currentText() == "Samples"
        )
        low_edit, high_edit = loaded_widget._selection_patch_edits["distance"]
        assert low_edit.text() == "100"
        assert high_edit.text() == "200"

    def test_workflow_roundtrip_preserves_select_spool_filter_values(
        self, derzug_app, tmp_path, qapp, orange_workflow
    ):
        """Saving and loading a workflow should preserve Select spool filter rows."""
        window = derzug_app.window
        workflow = orange_workflow((("Select", "select-node"),))
        spool = _select_test_spool()
        select_widget = workflow.widgets_by_title["select-node"]

        select_widget.show()
        select_widget.set_spool(spool)
        qapp.processEvents()

        combo_1, _value_1, _remove_1 = select_widget._selection_panel.spool_rows[0]
        combo_1.setCurrentText("tag")
        qapp.processEvents()
        combo_1, value_1, _remove_1 = select_widget._selection_panel.spool_rows[0]
        value_1.setText("bob")
        value_1.editingFinished.emit()
        qapp.processEvents()

        select_widget._selection_panel.spool_add_button.click()
        qapp.processEvents()
        combo_2, _value_2, _remove_2 = select_widget._selection_panel.spool_rows[1]
        combo_2.setCurrentText("station")
        qapp.processEvents()
        combo_2, value_2, _remove_2 = select_widget._selection_panel.spool_rows[1]
        value_2.setText("alpha")
        value_2.editingFinished.emit()
        qapp.processEvents()

        workflow_path = tmp_path / "select-spool-values.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        loaded_scheme = window.current_document().scheme()
        loaded_node = next(
            node for node in loaded_scheme.nodes if node.title == "select-node"
        )
        loaded_widget = loaded_scheme.widget_for_node(loaded_node)
        loaded_widget.show()
        loaded_widget.set_spool(spool)
        qapp.processEvents()

        first, second = loaded_widget._selection_state.spool.filters[:2]
        assert (first.key, first.raw_value) == ("tag", "bob")
        assert (second.key, second.raw_value) == ("station", "alpha")
        combo_1, value_1, _remove_1 = loaded_widget._selection_panel.spool_rows[0]
        combo_2, value_2, _remove_2 = loaded_widget._selection_panel.spool_rows[1]
        assert combo_1.currentText() == "tag"
        assert value_1.text() == "bob"
        assert combo_2.currentText() == "station"
        assert value_2.text() == "alpha"
        filtered = loaded_widget._selection_apply_to_spool(spool)
        assert len(filtered) == 1
        assert next(iter(filtered)).attrs.tag == "bob"
        assert next(iter(filtered)).attrs.station == "alpha"

    def test_workflow_roundtrip_preserves_select_patch_values_from_spool_chain(
        self, derzug_app, tmp_path, qapp, qtbot, orange_workflow
    ):
        """Spool-fed Select patch ranges should survive a full .ows roundtrip."""
        window = derzug_app.window
        workflow = orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Select", "select-node"),
                ("Waterfall", "waterfall-node"),
            ),
            (
                ("spool-node", "Patch", "select-node", "Patch"),
                ("select-node", "Patch", "waterfall-node", "Patch"),
            ),
        )
        spool_widget = workflow.widgets_by_title["spool-node"]
        select_widget = workflow.widgets_by_title["select-node"]

        spool_widget.show()
        select_widget.show()
        qapp.processEvents()

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget, timeout=5.0)
        qtbot.waitUntil(lambda: select_widget._patch is not None, timeout=5000)

        selected = (500.0, 700.0)
        select_widget._selection_update_patch_range("distance", *selected)
        qapp.processEvents()

        workflow_path = tmp_path / "select-spool-chain-patch-values.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()

        loaded_scheme = window.current_document().scheme()
        loaded_spool_node = next(
            node for node in loaded_scheme.nodes if node.title == "spool-node"
        )
        loaded_select_node = next(
            node for node in loaded_scheme.nodes if node.title == "select-node"
        )
        loaded_spool_widget = loaded_scheme.widget_for_node(loaded_spool_node)
        loaded_select_widget = loaded_scheme.widget_for_node(loaded_select_node)

        wait_for_widget_idle(loaded_spool_widget, timeout=5.0)
        qtbot.waitUntil(lambda: loaded_select_widget._patch is not None, timeout=5000)
        qapp.processEvents()

        assert loaded_select_widget._selection_current_patch_range(
            "distance"
        ) == pytest.approx(selected)
        low_edit, high_edit = loaded_select_widget._selection_patch_edits["distance"]
        assert low_edit.text() == format_display(selected[0])
        assert high_edit.text() == format_display(selected[1])

    def test_fresh_reopen_restores_select_distance_values_from_spool_chain(
        self, derzug_app, tmp_path, qapp, qtbot, orange_workflow
    ):
        """Cold reopen should restore narrowed absolute distance ranges in Select."""
        window = derzug_app.window
        workflow = orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Select", "select-node"),
                ("Waterfall", "waterfall-node"),
            ),
            (
                ("spool-node", "Patch", "select-node", "Patch"),
                ("select-node", "Patch", "waterfall-node", "Patch"),
            ),
        )
        spool_widget = workflow.widgets_by_title["spool-node"]
        select_widget = workflow.widgets_by_title["select-node"]

        spool_widget.show()
        select_widget.show()
        qapp.processEvents()

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget, timeout=5.0)
        qtbot.waitUntil(lambda: select_widget._patch is not None, timeout=5000)

        selected = (500.0, 700.0)
        select_widget._selection_update_patch_range("distance", *selected)
        qapp.processEvents()

        workflow_path = tmp_path / "select-cold-reopen-absolute.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        with _fresh_derzug_window(qapp, tmp_path / "fresh-absolute") as fresh_window:
            fresh_window.load_scheme(str(workflow_path))
            qapp.processEvents()

            loaded_scheme = fresh_window.current_document().scheme()
            loaded_spool_node = next(
                node for node in loaded_scheme.nodes if node.title == "spool-node"
            )
            loaded_select_node = next(
                node for node in loaded_scheme.nodes if node.title == "select-node"
            )
            loaded_spool_widget = loaded_scheme.widget_for_node(loaded_spool_node)
            loaded_select_widget = loaded_scheme.widget_for_node(loaded_select_node)

            wait_for_widget_idle(loaded_spool_widget, timeout=5.0)
            qtbot.waitUntil(
                lambda: loaded_select_widget._patch is not None, timeout=5000
            )
            loaded_select_widget.show()
            qapp.processEvents()

            assert loaded_select_widget._selection_patch_basis == "absolute"
            assert loaded_select_widget._selection_current_patch_range(
                "distance"
            ) == pytest.approx(selected)
            low_edit, high_edit = loaded_select_widget._selection_patch_edits[
                "distance"
            ]
            assert low_edit.text() == format_display(selected[0])
            assert high_edit.text() == format_display(selected[1])

    def test_fresh_reopen_restores_relative_select_distance_values(
        self, derzug_app, tmp_path, qapp, qtbot, orange_workflow
    ):
        """Cold reopen should restore narrowed relative distance ranges in Select."""
        window = derzug_app.window
        workflow = orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Select", "select-node"),
            ),
            (("spool-node", "Patch", "select-node", "Patch"),),
        )
        spool_widget = workflow.widgets_by_title["spool-node"]
        select_widget = workflow.widgets_by_title["select-node"]

        spool_widget.show()
        select_widget.show()
        qapp.processEvents()

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget, timeout=5.0)
        qtbot.waitUntil(lambda: select_widget._patch is not None, timeout=5000)

        select_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")
        qapp.processEvents()
        selected = (100.0, 200.0)
        select_widget._selection_update_patch_range("distance", *selected)
        qapp.processEvents()

        workflow_path = tmp_path / "select-cold-reopen-relative.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        with _fresh_derzug_window(qapp, tmp_path / "fresh-relative") as fresh_window:
            fresh_window.load_scheme(str(workflow_path))
            qapp.processEvents()

            loaded_scheme = fresh_window.current_document().scheme()
            loaded_spool_node = next(
                node for node in loaded_scheme.nodes if node.title == "spool-node"
            )
            loaded_select_node = next(
                node for node in loaded_scheme.nodes if node.title == "select-node"
            )
            loaded_spool_widget = loaded_scheme.widget_for_node(loaded_spool_node)
            loaded_select_widget = loaded_scheme.widget_for_node(loaded_select_node)

            wait_for_widget_idle(loaded_spool_widget, timeout=5.0)
            qtbot.waitUntil(
                lambda: loaded_select_widget._patch is not None, timeout=5000
            )
            loaded_select_widget.show()
            qapp.processEvents()

            assert loaded_select_widget._selection_patch_basis == "relative"
            assert loaded_select_widget._selection_current_patch_range("distance") == (
                100.0,
                200.0,
            )
            low_edit, high_edit = loaded_select_widget._selection_patch_edits[
                "distance"
            ]
            assert low_edit.text() == "100"
            assert high_edit.text() == "200"

    def test_loading_workflow_reemits_selected_spool_patch(
        self, derzug_app, tmp_path, qapp, qtbot, orange_workflow
    ):
        """Loading a workflow should re-emit the persisted Spool row selection."""
        window = derzug_app.window
        workflow = orange_workflow(
            (("Spool", "spool-node"), ("Waterfall", "waterfall-node")),
            (("spool-node", "Patch", "waterfall-node", "Patch"),),
        )
        spool_widget = workflow.widgets_by_title["spool-node"]
        spool_dir = tmp_path / "reloadable_spool"
        spool_dir.mkdir()
        base = dc.get_example_patch()
        attrs = base.attrs.model_dump()
        first = base.update(attrs={**attrs, "tag": "reload_first"})
        second = base.update(attrs={**attrs, "tag": "reload_second"})
        dc.examples.spool_to_directory(dc.spool([first, second]), spool_dir)

        spool_widget.show()
        qapp.processEvents()
        spool_widget._set_file_input(str(spool_dir), trigger_run=False)
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget, timeout=5.0)

        model = spool_widget._table.model()
        if model is None or model.rowCount() < 2:
            pytest.fail("Expected the directory-backed spool to expose two rows.")

        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)
        qapp.processEvents()

        workflow_path = tmp_path / "spool-selected-row.ows"
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()

        loaded_scheme = window.current_document().scheme()
        loaded_spool_node = next(
            node for node in loaded_scheme.nodes if node.title == "spool-node"
        )
        loaded_waterfall_node = next(
            node for node in loaded_scheme.nodes if node.title == "waterfall-node"
        )
        loaded_spool_widget = loaded_scheme.widget_for_node(loaded_spool_node)
        loaded_waterfall_widget = loaded_scheme.widget_for_node(loaded_waterfall_node)
        wait_for_widget_idle(loaded_spool_widget, timeout=5.0)
        qapp.processEvents()
        qtbot.waitUntil(
            lambda: loaded_waterfall_widget._patch is not None, timeout=5000
        )

        assert loaded_spool_widget.selected_source_row == 0
        assert loaded_waterfall_widget._patch is not None
        assert loaded_waterfall_widget._patch.attrs.tag == first.attrs.tag

    def test_waterfall_widget_window_does_not_smoosh_selection_buttons(
        self, derzug_app, qapp, orange_workflow
    ):
        """Waterfall widget windows should give selection buttons full width."""
        window = derzug_app.window
        workflow = orange_workflow((("Waterfall", "waterfall-node"),))
        waterfall_widget = workflow.widgets_by_title["waterfall-node"]

        window.show()
        waterfall_widget.show()
        qapp.processEvents()

        buttons = (
            waterfall_widget._add_selection_button,
            waterfall_widget._selection_panel.reset_button,
        )
        assert buttons  # keep an explicit handle on the expected controls
        _assert_waterfall_control_text_fits(waterfall_widget)

    def test_double_click_opened_waterfall_window_does_not_smoosh_controls(
        self, derzug_app, qapp, qtbot, orange_workflow
    ):
        """Double-click opening a Waterfall node should size the sidebar correctly."""
        window = derzug_app.window
        workflow = orange_workflow(
            (("Spool", "spool-node"), ("Waterfall", "waterfall-node")),
            (("spool-node", "Patch", "waterfall-node", "Patch"),),
        )
        waterfall_widget = workflow.widgets_by_title["waterfall-node"]
        waterfall_node = workflow.nodes_by_title["waterfall-node"]
        node_item = window.current_document().scene().item_for_node(waterfall_node)
        body_center = window.scheme_widget.view().mapFromScene(
            node_item.shapeItem.sceneBoundingRect().center()
        )

        assert not waterfall_widget.isVisible()

        qtbot.mouseDClick(
            window.scheme_widget.view().viewport(), Qt.LeftButton, pos=body_center
        )
        qapp.processEvents()

        assert waterfall_widget.isVisible()
        _assert_waterfall_control_text_fits(waterfall_widget)

    def test_opening_and_closing_widget_window_does_not_reemit_patch(
        self, derzug_app, qapp, qtbot, orange_workflow, monkeypatch
    ):
        """Opening and closing a widget window should not resend unchanged patches."""
        window = derzug_app.window
        workflow = orange_workflow(
            (("Spool", "spool-node"), ("Waterfall", "waterfall-node")),
            (("spool-node", "Patch", "waterfall-node", "Patch"),),
        )
        spool_widget = workflow.widgets_by_title["spool-node"]
        waterfall_widget = workflow.widgets_by_title["waterfall-node"]
        waterfall_node = workflow.nodes_by_title["waterfall-node"]
        node_item = window.current_document().scene().item_for_node(waterfall_node)
        body_center = window.scheme_widget.view().mapFromScene(
            node_item.shapeItem.sceneBoundingRect().center()
        )

        emitted_patches: list[dc.Patch | None] = []
        original_send = spool_widget.Outputs.patch.send

        def _send_and_record(patch):
            emitted_patches.append(patch)
            return original_send(patch)

        monkeypatch.setattr(spool_widget.Outputs.patch, "send", _send_and_record)

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget)
        qtbot.waitUntil(lambda: waterfall_widget._patch is not None, timeout=5000)

        assert len(emitted_patches) == 1

        qtbot.mouseDClick(
            window.scheme_widget.view().viewport(), Qt.LeftButton, pos=body_center
        )
        qapp.processEvents()
        qtbot.wait(50)
        waterfall_widget.close()
        qapp.processEvents()
        qtbot.wait(50)

        assert len(emitted_patches) == 1

    def test_loaded_waterfall_widget_window_does_not_smoosh_selection_buttons(
        self, derzug_app, qapp
    ):
        """Saved workflow geometry should still leave Waterfall controls readable."""
        window = derzug_app.window
        workflow_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "derzug"
            / "workflows"
            / "01_Quick Start.ows"
        )

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        scheme = window.current_document().scheme()
        waterfall_nodes = [
            node for node in scheme.nodes if node.description.name == "Waterfall"
        ]
        assert waterfall_nodes

        for node in waterfall_nodes:
            widget = scheme.widget_for_node(node)
            widget.show()
            qapp.processEvents()

            _assert_waterfall_control_text_fits(widget)

    def test_load_scheme_replaces_current_workflow_graph(
        self, derzug_app, tmp_path, qapp, orange_workflow
    ):
        """Loading a workflow replaces the current document graph."""
        window = derzug_app.window
        initial = orange_workflow(
            (
                ("Spool", "source-new"),
                ("Waterfall", "view-new"),
            ),
            (("source-new", "Patch", "view-new", "Patch"),),
        )

        workflow_path = tmp_path / "replace.ows"
        assert window.save_scheme_to(initial.scheme, str(workflow_path))

        # Overwrite with a different graph, then load the saved one back.
        orange_workflow(
            (
                ("Filter", "filter-old"),
                ("Rolling", "rolling-old"),
            ),
            (("filter-old", "Patch", "rolling-old", "Patch"),),
        )

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        loaded_scheme = window.current_document().scheme()
        loaded_nodes, loaded_links = _graph_signature(loaded_scheme)

        assert loaded_nodes == {"source-new", "view-new"}
        assert loaded_links == {("source-new", "Patch", "view-new", "Patch")}

    def test_widgets_are_not_forced_above_canvas(self, derzug_app, orange_workflow):
        """Widget windows should not be forced on top of the canvas."""
        workflow = orange_workflow((("Filter", "filter-node"),))
        widget = workflow.widgets_by_title["filter-node"]

        assert not (widget.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_restack_float_widgets_is_noop(
        self, derzug_app, orange_workflow, monkeypatch, qapp
    ):
        """Canvas activation should not force widget windows to the front."""
        window = derzug_app.window

        workflow = orange_workflow((("Filter", "filter-node"),))
        widget = workflow.widgets_by_title["filter-node"]
        widget.show()
        qapp.processEvents()

        raised: list[str] = []
        monkeypatch.setattr(widget, "raise_", lambda: raised.append(widget.name))

        window._restack_float_widgets()

        assert raised == []

    def test_selected_widgets_offer_group_action(self, derzug_app, orange_workflow):
        """Valid multi-node selections should expose the Group action."""
        window = derzug_app.window
        workflow = orange_workflow((("Code", "code-1"), ("Code", "code-2")))
        node_1 = workflow.nodes_by_title["code-1"]
        node_2 = workflow.nodes_by_title["code-2"]
        _select_canvas_nodes(window, node_1, node_2)
        menu = window._canvas_composite_controller.context_menu_for_node(node_1)
        labels = (
            [action.text() for action in menu.actions()] if menu is not None else []
        )

        assert "Group" in labels

    def test_group_and_ungroup_restore_workflow_topology(
        self, derzug_app, qapp, orange_workflow
    ):
        """Grouping two nodes should replace them with one composite cleanly."""
        window = derzug_app.window
        workflow = orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Filter", "filter-node"),
                ("Detrend", "detrend-node"),
                ("Waterfall", "waterfall-node"),
            ),
            (
                ("spool-node", "Patch", "filter-node", "Patch"),
                ("filter-node", "Patch", "detrend-node", "Patch"),
                ("detrend-node", "Patch", "waterfall-node", "Patch"),
            ),
        )
        code_1 = workflow.nodes_by_title["filter-node"]
        code_2 = workflow.nodes_by_title["detrend-node"]
        original = _graph_signature(workflow.scheme)

        composite = window._canvas_composite_controller.group_nodes([code_1, code_2])
        qapp.processEvents()

        assert composite is not None
        grouped_nodes, grouped_links = _graph_signature(workflow.scheme)
        assert "Composite" in grouped_nodes
        assert "filter-node" not in grouped_nodes
        assert "detrend-node" not in grouped_nodes
        assert len(workflow.scheme.nodes) == 3
        assert len(composite.input_channels()) == 1
        assert len(composite.output_channels()) == 1

        restored = window._canvas_composite_controller.ungroup_node(composite)
        qapp.processEvents()

        assert len(restored) == 2
        assert _graph_signature(workflow.scheme) == original
        assert grouped_links != original[1]

    def test_grouped_composite_forwards_patch_outputs(
        self, derzug_app, qapp, qtbot, orange_workflow
    ):
        """A grouped composite should behave like a real widget in the signal path."""
        window = derzug_app.window
        workflow = orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Filter", "filter-node"),
                ("Detrend", "detrend-node"),
                ("Waterfall", "waterfall-node"),
            ),
            (
                ("spool-node", "Patch", "filter-node", "Patch"),
                ("filter-node", "Patch", "detrend-node", "Patch"),
                ("detrend-node", "Patch", "waterfall-node", "Patch"),
            ),
        )
        spool_widget = workflow.widgets_by_title["spool-node"]
        waterfall_widget = workflow.widgets_by_title["waterfall-node"]
        code_1 = workflow.nodes_by_title["filter-node"]
        code_2 = workflow.nodes_by_title["detrend-node"]

        composite = window._canvas_composite_controller.group_nodes([code_1, code_2])
        qapp.processEvents()
        assert composite is not None

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget)
        qtbot.waitUntil(lambda: waterfall_widget._patch is not None, timeout=5000)

        assert waterfall_widget._patch is not None
        assert (
            waterfall_widget._patch.shape
            == dc.get_example_patch("example_event_2").shape
        )

    def test_grouped_workflow_roundtrip_loads_and_can_ungroup(
        self, derzug_app, tmp_path, qapp, orange_workflow
    ):
        """Composite workflows should save, reload, and still support Ungroup."""
        window = derzug_app.window
        workflow = orange_workflow(
            (
                ("Spool", "spool-node"),
                ("Filter", "filter-node"),
                ("Detrend", "detrend-node"),
                ("Waterfall", "waterfall-node"),
            ),
            (
                ("spool-node", "Patch", "filter-node", "Patch"),
                ("filter-node", "Patch", "detrend-node", "Patch"),
                ("detrend-node", "Patch", "waterfall-node", "Patch"),
            ),
        )
        composite = window._canvas_composite_controller.group_nodes(
            [
                workflow.nodes_by_title["filter-node"],
                workflow.nodes_by_title["detrend-node"],
            ]
        )
        workflow_path = tmp_path / "grouped-composite.ows"

        assert composite is not None
        assert window.save_scheme_to(workflow.scheme, str(workflow_path))

        window.load_scheme(str(workflow_path))
        qapp.processEvents()
        loaded_scheme = window.current_document().scheme()
        loaded_composite = next(
            node for node in loaded_scheme.nodes if node.title == "Composite"
        )

        restored = window._canvas_composite_controller.ungroup_node(loaded_composite)
        qapp.processEvents()

        assert len(restored) == 2
        assert {node.title for node in loaded_scheme.nodes} == {
            "spool-node",
            "filter-node",
            "detrend-node",
            "waterfall-node",
        }


class TestCanvasZOrderToggler:
    """Tests for Shift+~ canvas Z-order toggling behavior."""

    @pytest.fixture()
    def toggler(self):
        """Return a bare _CanvasZOrderToggler with no parent."""
        return _CanvasZOrderToggler()

    def _make_shift_tilde_event(self):
        """Return a synthetic Shift+~ key-press event."""
        return QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key_AsciiTilde,
            Qt.ShiftModifier,
        )

    def test_sends_canvas_back_when_canvas_is_active(
        self, toggler, derzug_app, qapp, orange_workflow, monkeypatch
    ):
        """Shift+~ should only raise OWWidget windows above the canvas."""
        window = derzug_app.window
        workflow = orange_workflow((("Filter", "filter-node"),))
        widget = workflow.widgets_by_title["filter-node"]
        widget.show()
        qapp.processEvents()

        raised_widgets: list[str] = []
        activated_widgets: list[str] = []
        monkeypatch.setattr(
            widget, "raise_", lambda: raised_widgets.append(widget.name)
        )
        monkeypatch.setattr(
            widget, "activateWindow", lambda: activated_widgets.append(widget.name)
        )

        # Simulate canvas being the active window.
        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: window),
        )
        monkeypatch.setattr(
            orange_view.QApplication,
            "focusWidget",
            staticmethod(lambda: None),
        )
        monkeypatch.setattr(toggler, "_find_main_window", lambda: window)

        event = self._make_shift_tilde_event()
        result = toggler.eventFilter(window, event)

        assert result is True
        assert raised_widgets == ["Filter"]
        # The topmost widget gets focus so Shift+~ can toggle back from it.
        assert activated_widgets == ["Filter"]

    def test_skips_non_owwidget_windows(self, toggler, derzug_app, qapp, monkeypatch):
        """Only OWWidget windows are raised; plain QWidgets are ignored."""
        window = derzug_app.window
        plain = QWidget()
        plain.show()
        qapp.processEvents()

        plain_raised: list[bool] = []
        monkeypatch.setattr(plain, "raise_", lambda: plain_raised.append(True))
        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: window),
        )
        monkeypatch.setattr(
            orange_view.QApplication,
            "focusWidget",
            staticmethod(lambda: None),
        )
        monkeypatch.setattr(toggler, "_find_main_window", lambda: window)

        event = self._make_shift_tilde_event()
        toggler.eventFilter(window, event)

        assert not plain_raised  # plain QWidget must not be raised

        plain.hide()
        plain.deleteLater()

    def test_does_not_lower_canvas_behind_unrelated_windows(
        self, toggler, derzug_app, qapp, orange_workflow, monkeypatch
    ):
        """Shift+~ should not lower the canvas in the global window stack."""
        window = derzug_app.window
        workflow = orange_workflow((("Filter", "filter-node"),))
        widget = workflow.widgets_by_title["filter-node"]
        widget.show()
        unrelated = QWidget()
        unrelated.show()
        qapp.processEvents()

        lowered: list[bool] = []
        raised_widgets: list[str] = []
        activated_widgets: list[str] = []
        unrelated_raised: list[bool] = []
        monkeypatch.setattr(window, "lower", lambda: lowered.append(True))
        monkeypatch.setattr(
            widget, "raise_", lambda: raised_widgets.append(widget.name)
        )
        monkeypatch.setattr(
            widget, "activateWindow", lambda: activated_widgets.append(widget.name)
        )
        monkeypatch.setattr(unrelated, "raise_", lambda: unrelated_raised.append(True))
        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: window),
        )
        monkeypatch.setattr(
            orange_view.QApplication,
            "focusWidget",
            staticmethod(lambda: None),
        )
        monkeypatch.setattr(toggler, "_find_main_window", lambda: window)

        result = toggler.eventFilter(window, self._make_shift_tilde_event())

        assert result is True
        assert not lowered
        assert raised_widgets == ["Filter"]
        assert activated_widgets == ["Filter"]
        assert not unrelated_raised

        unrelated.hide()
        unrelated.deleteLater()

    def test_returns_false_when_widget_is_active(
        self, toggler, derzug_app, qapp, orange_workflow, monkeypatch
    ):
        """Toggler yields control to ZugWidget when a widget window is active."""
        workflow = orange_workflow((("Filter", "filter-node"),))
        widget = workflow.widgets_by_title["filter-node"]

        # Simulate a widget window being active, not the canvas.
        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: widget),
        )

        event = self._make_shift_tilde_event()
        result = toggler.eventFilter(widget, event)

        assert result is False

    def test_ignores_tilde_without_shift(self, toggler, derzug_app, monkeypatch):
        """Plain tilde without Shift modifier must not trigger canvas lowering."""
        window = derzug_app.window
        lowered: list[bool] = []
        monkeypatch.setattr(window, "lower", lambda: lowered.append(True))
        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: window),
        )

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_AsciiTilde, Qt.NoModifier)
        toggler.eventFilter(window, event)

        assert not lowered

    def test_ignores_non_tilde_keys(self, toggler, derzug_app, monkeypatch):
        """Non-tilde keys with Shift must not trigger canvas lowering."""
        window = derzug_app.window
        lowered: list[bool] = []
        monkeypatch.setattr(window, "lower", lambda: lowered.append(True))
        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: window),
        )

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_A, Qt.ShiftModifier)
        toggler.eventFilter(window, event)

        assert not lowered


class TestCanvasEscapeDefocuser:
    """Tests for Escape-based canvas refocus behavior."""

    @pytest.fixture()
    def defocuser(self):
        """Return a bare _CanvasEscapeDefocuser with no parent."""
        return _CanvasEscapeDefocuser()

    def test_escape_clears_focused_child_and_refocuses_canvas(
        self, defocuser, derzug_app, monkeypatch
    ):
        """Plain Escape should clear child focus and keep the canvas active."""
        window = derzug_app.window
        child = QLineEdit(window)
        child.show()

        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: window),
        )
        monkeypatch.setattr(
            orange_view.QApplication,
            "focusWidget",
            staticmethod(lambda: child),
        )
        monkeypatch.setattr(defocuser, "_find_main_window", lambda: window)

        activated: list[bool] = []
        cleared: list[bool] = []
        monkeypatch.setattr(window, "activateWindow", lambda: activated.append(True))
        monkeypatch.setattr(child, "clearFocus", lambda: cleared.append(True))

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)

        assert defocuser.eventFilter(window, event) is True
        assert cleared == [True]
        assert activated == [True]

    def test_escape_ignored_when_widget_window_is_active(
        self, defocuser, derzug_app, orange_workflow, monkeypatch
    ):
        """Canvas Escape handling should not steal events from active widgets."""
        window = derzug_app.window
        workflow = orange_workflow((("Filter", "filter-node"),))
        widget = workflow.widgets_by_title["filter-node"]

        monkeypatch.setattr(
            orange_view.QApplication,
            "activeWindow",
            staticmethod(lambda: widget),
        )
        monkeypatch.setattr(defocuser, "_find_main_window", lambda: window)

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)

        assert defocuser.eventFilter(window, event) is False


class TestDerZugMainTeardown:
    """Tests for DerZugMain app-global teardown behavior."""

    def test_application_filter_teardown_removes_filters_and_clears_globals(
        self, qapp, monkeypatch
    ):
        """DerZug should uninstall app event filters and clear globals on teardown."""
        main = DerZugMain()
        main.application = qapp
        manager = ActiveSourceManager()
        main.active_source_manager = manager
        main._tab_window_cycler = _TabWindowCycler(qapp)
        main._active_source_navigator = _ActiveSourceNavigator(manager)
        main._canvas_z_order_toggler = _CanvasZOrderToggler(qapp)
        main._canvas_escape_defocuser = _CanvasEscapeDefocuser(qapp)
        expected_filters = [
            main._tab_window_cycler,
            main._active_source_navigator,
            main._canvas_z_order_toggler,
            main._canvas_escape_defocuser,
        ]
        removed: list[object] = []

        monkeypatch.setattr(qapp, "removeEventFilter", removed.append)
        monkeypatch.setattr(orange_view, "_APP_ACTIVE_SOURCE_MANAGER", manager)
        monkeypatch.setattr(orange_view, "_APP_ACTIVE_SOURCE_MAIN_WINDOW", object())
        qapp.active_source_manager = manager
        qapp.active_source_main_window = object()

        main._tear_down_application_filters()

        assert removed == expected_filters
        assert main._tab_window_cycler is None
        assert main._active_source_navigator is None
        assert main._canvas_z_order_toggler is None
        assert main._canvas_escape_defocuser is None
        assert main.active_source_manager is None
        assert orange_view._APP_ACTIVE_SOURCE_MANAGER is None
        assert orange_view._APP_ACTIVE_SOURCE_MAIN_WINDOW is None
        assert qapp.active_source_manager is None
        assert qapp.active_source_main_window is None

    def test_tear_down_application_runs_filter_teardown_before_base(
        self, qapp, monkeypatch
    ):
        """DerZug should clean its app-global hooks before delegating to Orange."""
        main = DerZugMain()
        main.application = qapp
        calls: list[str] = []

        monkeypatch.setattr(
            DerZugMain,
            "_tear_down_application_filters",
            lambda self: calls.append("filters"),
        )
        monkeypatch.setattr(
            orange_view.OMain,
            "tear_down_application",
            lambda self: calls.append("base"),
        )

        main.tear_down_application()

        assert calls == ["filters", "base"]

    def test_tear_down_sys_redirections_is_idempotent(self, monkeypatch):
        """Repeated teardown should tolerate already-disconnected hook wiring."""
        main = DerZugMain()
        hook = ExceptHook(stream=None)
        monkeypatch.setattr(sys, "excepthook", hook)
        hook.handledException.connect(orange_view.handle_derzug_exception)

        main.tear_down_sys_redirections()
        main.tear_down_sys_redirections()


class TestQtWrapperCompatibility:
    """Regression tests for mixed SIP wrapper environments."""

    def test_qt_object_is_deleted_falls_back_after_wrapper_typeerror(self, monkeypatch):
        """A mismatched SIP wrapper type should not crash the deletion check."""
        monkeypatch.setattr(
            orange_view,
            "_SIP_MODULES",
            (_SipModuleWrongWrapper(), _SipModuleAlive()),
        )

        assert orange_view._qt_object_is_deleted(object()) is False

    def test_qt_object_is_deleted_detects_deleted_wrapper_after_fallback(
        self, monkeypatch
    ):
        """Fallback SIP modules should still report deleted wrappers as deleted."""
        monkeypatch.setattr(
            orange_view,
            "_SIP_MODULES",
            (_SipModuleWrongWrapper(), _SipModuleDeleted()),
        )

        assert orange_view._qt_object_is_deleted(object()) is True
