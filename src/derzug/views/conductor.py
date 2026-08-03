"""Conductor menu and settings UI with no optional MCP dependency."""

from __future__ import annotations

from dataclasses import dataclass

from AnyQt.QtCore import QObject, Signal
from AnyQt.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from orangecanvas.utils.settings import QSettings

from derzug.conductor.client_config import (
    claude_add_command,
    codex_cli_command,
    codex_config_toml,
    mcp_url,
)
from derzug.conductor.constants import DEFAULT_HOST, DEFAULT_PORT

_SETTINGS_GROUP = "conductor"
_PORT_KEY = "port"
_MIN_PORT = 1
_MAX_PORT = 65535


@dataclass(frozen=True)
class ConductorSettings:
    """Configuration used the next time the Conductor server starts."""

    port: int = DEFAULT_PORT
    allow_code: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not _MIN_PORT <= self.port <= _MAX_PORT
        ):
            raise ValueError(f"port must be between {_MIN_PORT} and {_MAX_PORT}")


def load_conductor_port(settings: QSettings) -> int:
    """Load the persisted Conductor port, falling back for invalid values."""
    settings.beginGroup(_SETTINGS_GROUP)
    try:
        raw_port = settings.value(_PORT_KEY, DEFAULT_PORT)
    finally:
        settings.endGroup()
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    if not _MIN_PORT <= port <= _MAX_PORT:
        return DEFAULT_PORT
    return port


def save_conductor_port(port: int, settings: QSettings) -> None:
    """Persist the validated Conductor port."""
    config = ConductorSettings(port=port)
    settings.beginGroup(_SETTINGS_GROUP)
    try:
        settings.setValue(_PORT_KEY, config.port)
    finally:
        settings.endGroup()


class ConductorSettingsDialog(QDialog):
    """Edit settings used for the next Conductor server start."""

    def __init__(
        self,
        settings: ConductorSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Conductor Settings")
        self.setModal(True)
        self.setObjectName("conductor-settings-dialog")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.host_field = QLineEdit(DEFAULT_HOST, self)
        self.host_field.setObjectName("conductor-host-field")
        self.host_field.setReadOnly(True)
        self.host_field.setToolTip("Conductor is restricted to this computer")
        form.addRow("Host", self.host_field)

        self.port_field = QSpinBox(self)
        self.port_field.setObjectName("conductor-port-field")
        self.port_field.setRange(_MIN_PORT, _MAX_PORT)
        self.port_field.setValue(settings.port)
        form.addRow("Port", self.port_field)

        self.allow_code_checkbox = QCheckBox(
            "Allow agents to add or configure Code widgets",
            self,
        )
        self.allow_code_checkbox.setObjectName("conductor-allow-code-checkbox")
        self.allow_code_checkbox.setChecked(settings.allow_code)
        layout.addWidget(self.allow_code_checkbox)

        warning = QLabel(
            "Code widgets execute arbitrary Python. This permission applies only "
            "to the current DerZug session.",
            self,
        )
        warning.setObjectName("conductor-code-warning")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> ConductorSettings:
        """Return the configuration currently entered in the dialog."""
        return ConductorSettings(
            port=self.port_field.value(),
            allow_code=self.allow_code_checkbox.isChecked(),
        )


class ConductorMenuController(QObject):
    """Own the Conductor menu and expose lifecycle requests as Qt signals."""

    start_requested = Signal(int, bool)
    stop_requested = Signal()
    restart_requested = Signal(int, bool)
    connect_agent_requested = Signal(str)
    port_changed = Signal(int)
    state_changed = Signal(str, str)

    def __init__(
        self,
        window: QMainWindow,
        settings: ConductorSettings | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._settings = settings or ConductorSettings()
        self._running_settings: ConductorSettings | None = None
        self._state = "stopped"
        self._url: str | None = None
        self._connect_dialog: ConductorConnectDialog | None = None

        self.menu = QMenu("Conductor", window)
        self.menu.setObjectName("conductor-menu")

        self.status_action = QAction("Status: Stopped", window)
        self.status_action.setObjectName("conductor-status-action")
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()

        self.connect_action = QAction("Connect Agent...", window)
        self.connect_action.setObjectName("conductor-connect-action")
        self.connect_action.triggered.connect(self.show_connect_dialog)
        self.menu.addAction(self.connect_action)
        self.menu.addSeparator()

        self.start_action = QAction("Start Server", window)
        self.start_action.setObjectName("conductor-start-action")
        self.start_action.triggered.connect(self._request_start)
        self.menu.addAction(self.start_action)

        self.stop_action = QAction("Stop Server", window)
        self.stop_action.setObjectName("conductor-stop-action")
        self.stop_action.triggered.connect(self.stop_requested.emit)
        self.menu.addAction(self.stop_action)

        self.restart_action = QAction("Restart Server", window)
        self.restart_action.setObjectName("conductor-restart-action")
        self.restart_action.triggered.connect(self._request_restart)
        self.menu.addAction(self.restart_action)
        self.menu.addSeparator()

        self.copy_url_action = QAction("Copy MCP URL", window)
        self.copy_url_action.setObjectName("conductor-copy-url-action")
        self.copy_url_action.triggered.connect(self._copy_url)
        self.menu.addAction(self.copy_url_action)

        self.agent_menu = QMenu("Open Agent", self.menu)
        self.agent_menu.setObjectName("conductor-agent-menu")
        self.menu.addMenu(self.agent_menu)
        self.open_claude_action = QAction("Claude Code", window)
        self.open_claude_action.setObjectName("conductor-open-claude-action")
        self.open_claude_action.triggered.connect(
            lambda: self.connect_agent_requested.emit("claude")
        )
        self.agent_menu.addAction(self.open_claude_action)
        self.open_codex_action = QAction("Codex", window)
        self.open_codex_action.setObjectName("conductor-open-codex-action")
        self.open_codex_action.triggered.connect(
            lambda: self.connect_agent_requested.emit("codex")
        )
        self.agent_menu.addAction(self.open_codex_action)
        self.menu.addSeparator()

        self.settings_action = QAction("Settings...", window)
        self.settings_action.setObjectName("conductor-settings-action")
        self.settings_action.triggered.connect(self._open_settings)
        self.menu.addAction(self.settings_action)

        menu_bar = window.menuBar()
        if menu_bar is None:
            raise RuntimeError("Conductor menu requires a main-window menu bar")
        help_menu = getattr(window, "help_menu", None)
        help_action = help_menu.menuAction() if isinstance(help_menu, QMenu) else None
        if help_action is None:
            menu_bar.addMenu(self.menu)
        else:
            menu_bar.insertMenu(help_action, self.menu)
        self._refresh_actions()

    @property
    def settings(self) -> ConductorSettings:
        """Return the configuration for the next start or restart."""
        return self._settings

    @property
    def url(self) -> str | None:
        """Return the running MCP URL, if the server is active."""
        return self._url

    @property
    def state(self) -> str:
        """One of ``"stopped"``, ``"starting"``, ``"running"``, ``"stopping"``."""
        return self._state

    def show_connect_dialog(self) -> None:
        """Show (or raise) the non-modal agent connection dialog."""
        if self._connect_dialog is None:
            self._connect_dialog = ConductorConnectDialog(self, self._window)
        self._connect_dialog.show()
        self._connect_dialog.raise_()
        self._connect_dialog.activateWindow()

    def set_settings(self, settings: ConductorSettings) -> None:
        """Replace the next-start configuration without persisting it."""
        self._settings = settings
        self._refresh_actions()

    def set_starting(self) -> None:
        """Show that a server start is in progress."""
        self._state = "starting"
        self._url = None
        self._running_settings = None
        self._refresh_actions()

    def set_running(self, url: str, settings: ConductorSettings) -> None:
        """Show a ready server and enable runtime-only actions."""
        self._state = "running"
        self._url = url
        self._running_settings = settings
        self._refresh_actions()

    def set_stopping(self) -> None:
        """Show that server shutdown is in progress."""
        self._state = "stopping"
        self._refresh_actions()

    def set_stop_failed(self) -> None:
        """Return to the running state after a shutdown attempt failed."""
        self._state = "running" if self._url is not None else "stopped"
        self._refresh_actions()

    def set_stopped(self) -> None:
        """Show a stopped server and disable runtime-only actions."""
        self._state = "stopped"
        self._url = None
        self._running_settings = None
        self._refresh_actions()

    def _request_start(self) -> None:
        """Request a start with the currently configured values."""
        self.start_requested.emit(self._settings.port, self._settings.allow_code)

    def _request_restart(self) -> None:
        """Request a restart with the currently configured values."""
        self.restart_requested.emit(self._settings.port, self._settings.allow_code)

    def _copy_url(self) -> None:
        """Copy the active MCP URL to the system clipboard."""
        clipboard = QApplication.clipboard()
        if self._url is not None and clipboard is not None:
            clipboard.setText(self._url)

    def _open_settings(self) -> None:
        """Open the server settings dialog and retain accepted changes."""
        dialog = ConductorSettingsDialog(self._settings, self._window)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        previous_port = self._settings.port
        self._settings = dialog.settings()
        if self._settings.port != previous_port:
            self.port_changed.emit(self._settings.port)
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        """Synchronize labels and enabled states with the lifecycle state."""
        running = self._state == "running" and self._url is not None
        busy = self._state in {"starting", "stopping"}
        if self._state == "starting":
            status = "Status: Starting..."
        elif self._state == "stopping":
            status = "Status: Stopping..."
        elif running:
            status = f"Status: Running at {self._url}"
        else:
            status = "Status: Stopped"
        self.status_action.setText(status)
        self.status_action.setToolTip(self._url or "Conductor server is stopped")

        self.start_action.setEnabled(self._state == "stopped")
        self.stop_action.setEnabled(running)
        self.copy_url_action.setEnabled(running)
        agent_menu_action = self.agent_menu.menuAction()
        if agent_menu_action is not None:
            # Launching an agent while stopped starts the server first.
            agent_menu_action.setEnabled(not busy)
        self.settings_action.setEnabled(not busy)
        self.connect_action.setEnabled(not busy)

        settings_pending = running and self._running_settings != self._settings
        restart_label = (
            "Restart Server (Apply Settings)" if settings_pending else "Restart Server"
        )
        self.restart_action.setText(restart_label)
        self.restart_action.setEnabled(running)
        self.state_changed.emit(self._state, self._url or "")


class ConductorConnectDialog(QDialog):
    """Non-modal helper to connect an agent client to the Conductor server.

    Shows the live server state, per-client copy-paste setup snippets, and
    launch buttons. Launching an agent while the server is stopped requests
    an automatic start first (handled by the application).
    """

    def __init__(
        self,
        controller: ConductorMenuController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("Connect Agent")
        self.setObjectName("conductor-connect-dialog")

        layout = QVBoxLayout(self)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("conductor-connect-status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.start_button = QPushButton("Start Server", self)
        self.start_button.setObjectName("conductor-connect-start-button")
        self.start_button.clicked.connect(controller._request_start)
        layout.addWidget(self.start_button)

        claude_group = QGroupBox("Claude Code", self)
        claude_layout = QHBoxLayout(claude_group)
        self.claude_command = QLineEdit(claude_group)
        self.claude_command.setObjectName("conductor-connect-claude-command")
        self.claude_command.setReadOnly(True)
        claude_layout.addWidget(self.claude_command)
        self.claude_copy = QPushButton("Copy", claude_group)
        self.claude_copy.setObjectName("conductor-connect-claude-copy")
        self.claude_copy.clicked.connect(
            lambda: _copy_to_clipboard(self.claude_command.text())
        )
        claude_layout.addWidget(self.claude_copy)
        self.claude_launch = QPushButton("Launch", claude_group)
        self.claude_launch.setObjectName("conductor-connect-claude-launch")
        self.claude_launch.clicked.connect(
            lambda: controller.connect_agent_requested.emit("claude")
        )
        claude_layout.addWidget(self.claude_launch)
        layout.addWidget(claude_group)

        codex_group = QGroupBox("Codex", self)
        codex_layout = QVBoxLayout(codex_group)
        self.codex_config = QPlainTextEdit(codex_group)
        self.codex_config.setObjectName("conductor-connect-codex-config")
        self.codex_config.setReadOnly(True)
        codex_layout.addWidget(self.codex_config)
        codex_buttons = QHBoxLayout()
        codex_layout.addLayout(codex_buttons)
        self.codex_copy = QPushButton("Copy Command", codex_group)
        self.codex_copy.setObjectName("conductor-connect-codex-copy")
        self.codex_copy.clicked.connect(
            lambda: _copy_to_clipboard(codex_cli_command(self._current_url()))
        )
        codex_buttons.addWidget(self.codex_copy)
        self.codex_launch = QPushButton("Launch", codex_group)
        self.codex_launch.setObjectName("conductor-connect-codex-launch")
        self.codex_launch.clicked.connect(
            lambda: controller.connect_agent_requested.emit("codex")
        )
        codex_buttons.addWidget(self.codex_launch)
        codex_buttons.addStretch()
        layout.addWidget(codex_group)

        url_row = QHBoxLayout()
        layout.addLayout(url_row)
        url_row.addWidget(QLabel("MCP URL", self))
        self.url_field = QLineEdit(self)
        self.url_field.setObjectName("conductor-connect-url")
        self.url_field.setReadOnly(True)
        url_row.addWidget(self.url_field)
        self.url_copy = QPushButton("Copy", self)
        self.url_copy.setObjectName("conductor-connect-url-copy")
        self.url_copy.clicked.connect(lambda: _copy_to_clipboard(self.url_field.text()))
        url_row.addWidget(self.url_copy)

        note = QLabel(
            "Starting the server writes .mcp.json and agent skill files "
            "(.claude/skills/, .agents/skills/) into the directory DerZug "
            "was launched from; agents launched here start in that directory.",
            self,
        )
        note.setObjectName("conductor-connect-skill-note")
        note.setWordWrap(True)
        layout.addWidget(note)

        controller.state_changed.connect(self._refresh)
        self._refresh()

    def _current_url(self) -> str:
        """The live MCP URL, or the one the configured port would produce."""
        url = self._controller.url
        if url is None:
            return mcp_url(DEFAULT_HOST, self._controller.settings.port)
        return url

    def _refresh(self, *_args) -> None:
        """Synchronize the status line and snippets with the server state."""
        controller = self._controller
        state = controller.state
        url = self._current_url()
        if state == "running":
            status = f"Status: Running at {url}"
        elif state == "starting":
            status = "Status: Starting..."
        elif state == "stopping":
            status = "Status: Stopping..."
        else:
            status = (
                "Status: Stopped — the server starts automatically when you "
                "launch an agent."
            )
        self.status_label.setText(status)
        self.start_button.setVisible(state == "stopped")
        busy = state in {"starting", "stopping"}
        self.claude_launch.setEnabled(not busy)
        self.codex_launch.setEnabled(not busy)
        self.claude_command.setText(claude_add_command(url))
        self.codex_config.setPlainText(
            f"{codex_cli_command(url)}\n\n"
            "# or add to ~/.codex/config.toml:\n"
            f"{codex_config_toml(url)}"
        )
        self.url_field.setText(url)


def _copy_to_clipboard(text: str) -> None:
    """Copy ``text`` to the system clipboard when one is available."""
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


__all__ = (
    "ConductorConnectDialog",
    "ConductorMenuController",
    "ConductorSettings",
    "ConductorSettingsDialog",
    "load_conductor_port",
    "save_conductor_port",
)
