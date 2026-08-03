"""Tests for the Conductor menu and settings UI."""

from __future__ import annotations

import pytest
from AnyQt.QtWidgets import QApplication, QDialog, QMainWindow
from derzug.conductor.constants import DEFAULT_HOST, DEFAULT_PORT
from derzug.views import conductor as conductor_view
from derzug.views.conductor import (
    ConductorMenuController,
    ConductorSettings,
    ConductorSettingsDialog,
    load_conductor_port,
    save_conductor_port,
)
from orangecanvas.utils.settings import QSettings

URL = "http://127.0.0.1:4319/mcp"


@pytest.fixture
def conductor_menu(qtbot):
    """Return a standalone main window and its Conductor menu controller."""
    window = QMainWindow()
    window.help_menu = window.menuBar().addMenu("Help")
    qtbot.addWidget(window)
    controller = ConductorMenuController(window)
    return window, controller


def test_conductor_settings_validate_port():
    """Conductor ports must be valid non-boolean TCP port numbers."""
    assert ConductorSettings().port == DEFAULT_PORT
    with pytest.raises(ValueError, match="port must be between"):
        ConductorSettings(port=0)
    with pytest.raises(ValueError, match="port must be between"):
        ConductorSettings(port=True)


def test_conductor_port_round_trip_and_invalid_fallback(tmp_path):
    """Only a valid port is persisted; bad stored values use the default."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    save_conductor_port(5432, settings)
    assert load_conductor_port(settings) == 5432

    settings.beginGroup("conductor")
    settings.setValue("port", "not-a-port")
    settings.endGroup()
    assert load_conductor_port(settings) == DEFAULT_PORT


def test_conductor_settings_dialog_exposes_safe_defaults(qtbot):
    """The dialog keeps the host local and returns edited session settings."""
    dialog = ConductorSettingsDialog(ConductorSettings(port=4321, allow_code=False))
    qtbot.addWidget(dialog)

    assert dialog.host_field.text() == DEFAULT_HOST
    assert dialog.host_field.isReadOnly()
    assert dialog.port_field.value() == 4321
    assert not dialog.allow_code_checkbox.isChecked()

    dialog.port_field.setValue(5432)
    dialog.allow_code_checkbox.setChecked(True)
    assert dialog.settings() == ConductorSettings(port=5432, allow_code=True)


def test_menu_is_inserted_before_help_and_starts_stopped(conductor_menu):
    """The always-visible menu starts with runtime actions disabled."""
    window, controller = conductor_menu
    labels = [action.text().replace("&", "") for action in window.menuBar().actions()]

    assert labels == ["Conductor", "Help"]
    assert controller.status_action.text() == "Status: Stopped"
    assert controller.start_action.isEnabled()
    assert not controller.stop_action.isEnabled()
    assert not controller.restart_action.isEnabled()
    assert not controller.copy_url_action.isEnabled()
    assert not controller.agent_menu.menuAction().isEnabled()


def test_menu_emits_lifecycle_requests_with_current_settings(conductor_menu, qtbot):
    """Start and restart requests carry the currently configured values."""
    _, controller = conductor_menu
    settings = ConductorSettings(port=4321, allow_code=True)
    controller.set_settings(settings)

    with qtbot.waitSignal(controller.start_requested) as started:
        controller.start_action.trigger()
    assert started.args == [4321, True]

    controller.set_running(URL, settings)
    with qtbot.waitSignal(controller.restart_requested) as restarted:
        controller.restart_action.trigger()
    assert restarted.args == [4321, True]

    with qtbot.waitSignal(controller.stop_requested):
        controller.stop_action.trigger()


def test_running_state_enables_runtime_actions_and_copies_url(conductor_menu, qtbot):
    """A ready server enables its URL and agent controls."""
    _, controller = conductor_menu
    controller.set_running(URL, controller.settings)

    assert controller.status_action.text() == f"Status: Running at {URL}"
    assert not controller.start_action.isEnabled()
    assert controller.stop_action.isEnabled()
    assert controller.restart_action.isEnabled()
    assert controller.copy_url_action.isEnabled()
    assert controller.agent_menu.menuAction().isEnabled()

    controller.copy_url_action.trigger()
    assert QApplication.clipboard().text() == URL
    with qtbot.waitSignal(controller.launch_agent_requested) as launched:
        controller.open_codex_action.trigger()
    assert launched.args == ["codex"]

    controller.set_stopped()
    assert controller.status_action.text() == "Status: Stopped"
    assert controller.start_action.isEnabled()


def test_accepted_settings_mark_running_server_for_restart(
    conductor_menu, monkeypatch, qtbot
):
    """Accepted changes are retained and identify when restart is required."""
    _, controller = conductor_menu
    controller.set_running(URL, controller.settings)

    class _AcceptedSettingsDialog:
        def __init__(self, settings, parent):
            assert settings == ConductorSettings()
            assert parent is not None

        def exec(self):
            return QDialog.DialogCode.Accepted

        def settings(self):
            return ConductorSettings(port=5432, allow_code=True)

    monkeypatch.setattr(
        conductor_view,
        "ConductorSettingsDialog",
        _AcceptedSettingsDialog,
    )
    with qtbot.waitSignal(controller.port_changed) as changed:
        controller.settings_action.trigger()

    assert changed.args == [5432]
    assert controller.settings == ConductorSettings(port=5432, allow_code=True)
    assert controller.restart_action.text() == "Restart Server (Apply Settings)"


def test_code_permission_is_not_part_of_persisted_settings(tmp_path):
    """The arbitrary-code opt-in must be chosen again in each app session."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    save_conductor_port(5432, settings)

    restored = ConductorSettings(port=load_conductor_port(settings))

    assert restored == ConductorSettings(port=5432, allow_code=False)
