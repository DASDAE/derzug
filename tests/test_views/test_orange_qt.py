"""Qt/Orange integration tests."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import dascore as dc
import derzug.constants as constants
import pytest
from AnyQt.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from AnyQt.QtGui import QAction, QKeyEvent, QMouseEvent
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
    DerZugConfig,
    DerZugErrorDialog,
    DerZugMain,
    ExperimentalWarningDialog,
    _build_exception_report_data,
    _CanvasEscapeDefocuser,
    _CanvasZOrderToggler,
    _configure_linux_desktop_integration,
    _install_derzug_exception_handler,
    _linux_desktop_entry_contents,
    ensure_linux_desktop_entry,
)
from derzug.views.orange_errors import _build_issue_body, _build_issue_url
from derzug.widgets.spool import Spool
from derzug.widgets.table2annotation import Table2Annotation
from orangecanvas.application.outputview import ExceptHook, TerminalTextDocument
from orangecanvas.document.interactions import RectangleSelectionAction
from orangecanvas.gui.windowlistmanager import WindowListManager


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
        assert opened == [str(config_path)]

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
        first = base.update(attrs={**attrs, "tag": "reload-first"})
        second = base.update(attrs={**attrs, "tag": "reload-second"})
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
        delivered_patches: list[dc.Patch | None] = []
        original_send = spool_widget.Outputs.patch.send
        original_set_patch = waterfall_widget.set_patch

        def _send_and_record(patch):
            emitted_patches.append(patch)
            return original_send(patch)

        def _set_patch_and_record(patch):
            delivered_patches.append(patch)
            return original_set_patch(patch)

        monkeypatch.setattr(spool_widget.Outputs.patch, "send", _send_and_record)
        monkeypatch.setattr(waterfall_widget, "set_patch", _set_patch_and_record)

        spool_widget.spool_input = "example_event_2"
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget)
        qtbot.waitUntil(lambda: waterfall_widget._patch is not None, timeout=5000)

        assert len(emitted_patches) == 1
        assert len(delivered_patches) == 1

        qtbot.mouseDClick(
            window.scheme_widget.view().viewport(), Qt.LeftButton, pos=body_center
        )
        qapp.processEvents()
        qtbot.wait(50)
        waterfall_widget.close()
        qapp.processEvents()
        qtbot.wait(50)

        assert len(emitted_patches) == 1
        assert len(delivered_patches) == 1

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
            / "020_basic_dss.ows"
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
