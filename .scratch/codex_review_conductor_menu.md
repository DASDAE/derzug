Reading additional input from stdin...
OpenAI Codex v0.146.0
--------
workdir: /home/derrick/Gits/derzug
model: gpt-5.6-sol
provider: openai
approval: on-request
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019fc683-b233-7651-a64e-388306d41488
--------
user
Review the uncommitted changes on this branch (git diff plus the untracked files src/derzug/views/conductor.py, src/derzug/conductor/constants.py, tests/test_views/test_conductor.py). This adds an always-visible Conductor menu to the DerZug main window that starts/stops/restarts the optional MCP server, persists the port via QSettings, and launches Claude Code or Codex in an external terminal. Focus on correctness bugs, Qt lifecycle/ownership issues, multi-window handling, error handling, and test coverage gaps. Be concrete and cite file:line. Do not make any edits.
warning: Codex's Linux sandbox uses bubblewrap and needs access to create user namespaces.
codex
I’ll inspect the repository guidance, the complete working-tree diff, and the three untracked files, then trace the surrounding application/window lifecycle and relevant tests. I’ll report only concrete findings, prioritized by severity, with file-and-line citations; I won’t edit anything.
exec
/usr/bin/zsh -lc "pwd && rg --files -g 'AGENTS.md' -g '"'!**/.git/**'"' && git status --short && git diff --stat && git diff -- src tests" in /home/derrick/Gits/derzug
 exited 1 in 0ms:
/home/derrick/Gits/derzug

exec
/usr/bin/zsh -lc 'git status --short' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "rg --files -g 'AGENTS.md' -g '"'!**/.git/**'"'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'git diff --stat' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "sed -n '1,220p' src/derzug/conductor/constants.py" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "sed -n '1,340p' tests/test_views/test_conductor.py" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'git diff -- src tests' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "sed -n '1,260p' src/derzug/views/conductor.py" in /home/derrick/Gits/derzug
 succeeded in 0ms:
 docs/dev/conductor.md                     |  45 ++++++--
 docs/dev/plans/conductor_terminal_pane.md |  17 +--
 src/derzug/conductor/mcp_server.py        |   4 +-
 src/derzug/views/orange.py                | 174 +++++++++++++++++++++++++++---
 tests/test_cli.py                         |  30 ++++++
 tests/test_views/test_orange_qt.py        | 113 +++++++++++++++++++
 6 files changed, 350 insertions(+), 33 deletions(-)

 succeeded in 0ms:
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
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from orangecanvas.utils.settings import QSettings

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
    launch_agent_requested = Signal(str)
    port_changed = Signal(int)

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

        self.menu = QMenu("Conductor", window)
        self.menu.setObjectName("conductor-menu")

        self.status_action = QAction("Status: Stopped", window)
        self.status_action.setObjectName("conductor-status-action")
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
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
            lambda: self.launch_agent_requested.emit("claude")
        )
        self.agent_menu.addAction(self.open_claude_action)
        self.open_codex_action = QAction("Codex", window)
        self.open_codex_action.setObjectName("conductor-open-codex-action")
        self.open_codex_action.triggered.connect(
            lambda: self.launch_agent_requested.emit("codex")
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

    def set_stopped(self) -> None:
        """Show a stopped server and disable runtime-only actions."""
        self._state = "stopped"
        self._url = None
        self._running_settings = None
        self._refresh_actions()

 succeeded in 0ms:
diff --git a/src/derzug/conductor/mcp_server.py b/src/derzug/conductor/mcp_server.py
index d78dff0..f60426c 100644
--- a/src/derzug/conductor/mcp_server.py
+++ b/src/derzug/conductor/mcp_server.py
@@ -32,15 +32,13 @@ from typing import Any
 
 from mcp.server.fastmcp import FastMCP
 
+from derzug.conductor.constants import DEFAULT_HOST, DEFAULT_PORT
 from derzug.conductor.controller import CanvasController
 from derzug.conductor.dispatch import MainThreadDispatcher
 from derzug.conductor.launch import SERVER_NAME, launch_agent_in_terminal
 
 log = logging.getLogger(__name__)
 
-DEFAULT_HOST = "127.0.0.1"
-DEFAULT_PORT = 4319
-
 
 def build_conductor_mcp(
     controller: CanvasController, dispatcher: MainThreadDispatcher
diff --git a/src/derzug/views/orange.py b/src/derzug/views/orange.py
index 9303d9b..3d926dd 100644
--- a/src/derzug/views/orange.py
+++ b/src/derzug/views/orange.py
@@ -2782,6 +2782,8 @@ class DerZugMain(OMain):
     conductor_agent: str | None = None
     conductor_allow_code = False
     _conductor_service = None
+    _conductor_window = None
+    _conductor_cwd: str | None = None
     startup_workflow_path: str | None = None
     startup_open_widget_ids: ClassVar[list[int]] = []
 
@@ -2856,6 +2858,7 @@ class DerZugMain(OMain):
 
     def tear_down_application(self):
         """Remove DerZug app-global hooks before base QApplication teardown."""
+        self._stop_conductor()
         self._tear_down_application_filters()
         super().tear_down_application()
 
@@ -2884,17 +2887,80 @@ class DerZugMain(OMain):
         global _APP_ACTIVE_SOURCE_MAIN_WINDOW
         _APP_ACTIVE_SOURCE_MAIN_WINDOW = window
         self.application.active_source_main_window = window
+        self._install_conductor_controls(window)
         window.install_dev_controls()
         if self.show_demo:
             QTimer.singleShot(0, window.examples_dialog)
         if self.conductor_enabled:
-            self._start_conductor(window)
+            settings = window.conductor_controls.settings
+            self._start_conductor(
+                window,
+                port=settings.port,
+                allow_code=settings.allow_code,
+                agent=self.conductor_agent,
+            )
         return window
 
-    def _start_conductor(self, window) -> None:
-        """Start the in-app Conductor MCP server (optional ``conductor`` extra)."""
+    def _install_conductor_controls(self, window) -> None:
+        """Install the always-available menu and connect lifecycle requests."""
+        from derzug.views.conductor import (
+            ConductorMenuController,
+            ConductorSettings,
+            load_conductor_port,
+            save_conductor_port,
+        )
+
+        if window.conductor_controls is not None:
+            return
+        settings = ConductorSettings(
+            port=load_conductor_port(_derzug_settings()),
+            allow_code=bool(self.conductor_allow_code),
+        )
+        controls = ConductorMenuController(window, settings)
+        window.conductor_controls = controls
+        self._conductor_window = window
+
+        controls.start_requested.connect(
+            lambda port, allow_code: self._start_conductor(
+                window,
+                port=port,
+                allow_code=allow_code,
+            )
+        )
+        controls.stop_requested.connect(self._stop_conductor)
+        controls.restart_requested.connect(
+            lambda port, allow_code: self._restart_conductor(
+                window,
+                port=port,
+                allow_code=allow_code,
+            )
+        )
+        controls.launch_agent_requested.connect(
+            lambda agent: self._launch_conductor_agent(window, agent)
+        )
+        controls.port_changed.connect(
+            lambda port: save_conductor_port(port, _derzug_settings())
+        )
+        self.application.aboutToQuit.connect(self._stop_conductor)
+
+    def _start_conductor(
+        self,
+        window,
+        *,
+        port: int,
+        allow_code: bool,
+        agent: str | None = None,
+    ) -> bool:
+        """Start the optional Conductor server and synchronize its menu state."""
         import logging
-        import os
+
+        from derzug.views.conductor import ConductorSettings
+
+        if self._conductor_service is not None:
+            return True
+        controls = window.conductor_controls
+        settings = ConductorSettings(port=port, allow_code=allow_code)
+        controls.set_starting()
 
         try:
             from derzug.conductor.mcp_server import start_conductor
@@ -2902,27 +2968,108 @@ class DerZugMain(OMain):
             logging.getLogger(__name__).error(
                 "Conductor requires the 'mcp' extra: pip install 'derzug[conductor]'"
             )
-            return
+            controls.set_stopped()
+            QMessageBox.critical(
+                window,
+                "Conductor Unavailable",
+                "Conductor requires the optional MCP dependency. Install it with "
+                "pip install 'derzug[conductor]'.",
+            )
+            return False
+        config_path = Path.cwd() / ".mcp.json"
         try:
-            config_path = os.path.join(os.getcwd(), ".mcp.json")
-            self._conductor_service = start_conductor(
+            service = start_conductor(
                 window,
                 config_path=config_path,
-                agent=self.conductor_agent,
-                allow_code=self.conductor_allow_code,
+                port=settings.port,
+                allow_code=settings.allow_code,
             )
-        except Exception:
+        except Exception as exc:
             logging.getLogger(__name__).error(
                 "Failed to start the Conductor MCP server", exc_info=True
             )
-            return
-        self.application.aboutToQuit.connect(self._stop_conductor)
+            controls.set_stopped()
+            detail = str(exc) or type(exc).__name__
+            QMessageBox.critical(
+                window,
+                "Conductor Start Failed",
+                f"Could not start the Conductor server:\n\n{detail}",
+            )
+            return False
+        self._conductor_service = service
+        self._conductor_cwd = str(config_path.parent)
+        controls.set_running(service.url, settings)
+        if agent is not None:
+            self._launch_conductor_agent(window, agent)
+        return True
 
     def _stop_conductor(self) -> None:
         """Shut the Conductor service down at application teardown."""
         service, self._conductor_service = self._conductor_service, None
-        if service is not None:
+        window = self._conductor_window
+        controls = (
+            None
+            if window is None or _qt_object_is_deleted(window)
+            else getattr(window, "conductor_controls", None)
+        )
+        if service is None:
+            if controls is not None:
+                controls.set_stopped()
+            return
+        if controls is not None:
+            controls.set_stopping()
+        try:
             service.stop()
+        except Exception as exc:
+            import logging
+
+            logging.getLogger(__name__).error(
+                "Failed to stop the Conductor MCP server", exc_info=True
+            )
+            if window is not None:
+                QMessageBox.warning(
+                    window,
+                    "Conductor Stop Failed",
+                    f"The Conductor server reported an error while stopping:\n\n{exc}",
+                )
+        finally:
+            self._conductor_cwd = None
+            if controls is not None:
+                controls.set_stopped()
+
+    def _restart_conductor(
+        self,
+        window,
+        *,
+        port: int,
+        allow_code: bool,
+    ) -> bool:
+        """Restart the server so the current menu settings take effect."""
+        self._stop_conductor()
+        return self._start_conductor(
+            window,
+            port=port,
+            allow_code=allow_code,
+        )
+
+    def _launch_conductor_agent(self, window, agent: str) -> bool:
+        """Launch one agent connected to the active Conductor service."""
+        from derzug.conductor.launch import launch_agent_in_terminal
+
+        service = self._conductor_service
+        cwd = self._conductor_cwd
+        if service is None or cwd is None:
+            return False
+        if launch_agent_in_terminal(agent, cwd, service.url):
+            return True
+        display_name = "Claude Code" if agent == "claude" else "Codex"
+        QMessageBox.warning(
+            window,
+            "Agent Launch Failed",
+            f"Could not open {display_name}. Ensure the agent and a supported "
+            "terminal are installed.",
+        )
+        return False
 
     def main_window_stylesheet(self):
         """
@@ -3022,6 +3169,7 @@ class DerZugMainWindow(OrangeMainWindow):
         self.startup_demo_mode = False
         self.startup_workflow_path: str | None = None
         self.startup_open_widget_ids: list[int] = []
+        self.conductor_controls = None
         self.dev_menu: QMenu | None = None
         self.hot_reload_action: QAction | None = None
         self.edit_config_file_action: QAction | None = None
diff --git a/tests/test_cli.py b/tests/test_cli.py
index 5085000..cfbb7c6 100644
--- a/tests/test_cli.py
+++ b/tests/test_cli.py
@@ -64,3 +64,33 @@ def test_workflow_argument_allows_dev_flag_after_path(monkeypatch):
     assert seen["dev_mode"] is True
     assert seen["show_demo"] is False
     assert seen["startup_workflow_path"] == "file_path.ows"
+
+
+def test_agent_flag_keeps_conductor_cli_startup_wiring(monkeypatch):
+    """Agent startup still enables Conductor and forwards the security opt-in."""
+    seen: dict[str, object] = {}
+
+    class _FakeMain:
+        def run(self, argv):
+            seen["argv"] = argv
+            seen["conductor_enabled"] = self.conductor_enabled
+            seen["conductor_agent"] = self.conductor_agent
+            seen["conductor_allow_code"] = self.conductor_allow_code
+            return 0
+
+    monkeypatch.setattr("derzug.views.orange.DerZugMain", _FakeMain)
+    monkeypatch.setattr("derzug.views.orange.ensure_linux_desktop_entry", lambda: None)
+
+    runner = CliRunner()
+    result = runner.invoke(
+        cli.app,
+        ["--agent", "codex", "--conductor-allow-code"],
+    )
+
+    assert result.exit_code == 0
+    assert seen == {
+        "argv": ["derzug"],
+        "conductor_enabled": True,
+        "conductor_agent": "codex",
+        "conductor_allow_code": True,
+    }
diff --git a/tests/test_views/test_orange_qt.py b/tests/test_views/test_orange_qt.py
index cdf3d9b..1e2aa94 100644
--- a/tests/test_views/test_orange_qt.py
+++ b/tests/test_views/test_orange_qt.py
@@ -5,6 +5,7 @@ from __future__ import annotations
 import io
 import os
 import sys
+import types
 from contextlib import contextmanager
 from pathlib import Path
 from urllib.parse import parse_qs, urlparse
@@ -364,6 +365,118 @@ class TestDerZugMainWindow:
         assert "Settings" in _menu_labels(window, "Options")
         assert window.dock_help_action not in window.canvas_toolbar.actions()
 
+    def test_conductor_menu_is_always_available(self, derzug_app):
+        """Server controls should be discoverable without a startup CLI flag."""
+        window = derzug_app.window
+
+        assert window.conductor_controls is not None
+        assert window.conductor_controls.menu.objectName() == "conductor-menu"
+        assert any(
+            action.text().replace("&", "") == "Conductor"
+            for action in window.menuBar().actions()
+        )
+
+    def test_conductor_menu_controls_service_lifecycle(
+        self, derzug_app, monkeypatch, tmp_path
+    ):
+        """Menu actions start, launch against, and stop the owned service."""
+        main = derzug_app.main
+        window = derzug_app.window
+        controls = window.conductor_controls
+        services = []
+        start_calls = []
+        launch_calls = []
+
+        class _FakeService:
+            def __init__(self, port):
+                self.url = f"http://127.0.0.1:{port}/mcp"
+                self.stop_calls = 0
+
+            def stop(self):
+                self.stop_calls += 1
+
+        def _fake_start(window_arg, **kwargs):
+            assert window_arg is window
+            start_calls.append(kwargs)
+            service = _FakeService(kwargs["port"])
+            services.append(service)
+            return service
+
+        monkeypatch.chdir(tmp_path)
+        mcp_server = types.ModuleType("derzug.conductor.mcp_server")
+        mcp_server.start_conductor = _fake_start
+        monkeypatch.setitem(sys.modules, "derzug.conductor.mcp_server", mcp_server)
+        monkeypatch.setattr(
+            "derzug.conductor.launch.launch_agent_in_terminal",
+            lambda agent, cwd, url: launch_calls.append((agent, cwd, url)) or True,
+        )
+        from derzug.views.conductor import ConductorSettings
+
+        controls.set_settings(ConductorSettings(port=5432, allow_code=True))
+
+        controls.start_action.trigger()
+
+        assert start_calls == [
+            {
+                "config_path": tmp_path / ".mcp.json",
+                "port": 5432,
+                "allow_code": True,
+            }
+        ]
+        assert controls.url == services[0].url
+        assert controls.stop_action.isEnabled()
+
+        controls.set_settings(ConductorSettings(port=5433, allow_code=False))
+        assert controls.restart_action.text() == "Restart Server (Apply Settings)"
+        controls.restart_action.trigger()
+        assert services[0].stop_calls == 1
+        assert start_calls[-1] == {
+            "config_path": tmp_path / ".mcp.json",
+            "port": 5433,
+            "allow_code": False,
+        }
+        assert controls.url == services[1].url
+
+        controls.open_codex_action.trigger()
+        assert launch_calls == [("codex", str(tmp_path), services[1].url)]
+
+        controls.stop_action.trigger()
+        assert services[1].stop_calls == 1
+        assert main._conductor_service is None
+        assert controls.url is None
+        assert controls.start_action.isEnabled()
+
+    def test_conductor_start_failure_returns_menu_to_stopped(
+        self, derzug_app, monkeypatch
+    ):
+        """A startup error should be reported without leaving stale UI state."""
+        window = derzug_app.window
+        controls = window.conductor_controls
+        errors = []
+
+        def _fail_start(*_args, **_kwargs):
+            raise OSError("port is already in use")
+
+        mcp_server = types.ModuleType("derzug.conductor.mcp_server")
+        mcp_server.start_conductor = _fail_start
+        monkeypatch.setitem(sys.modules, "derzug.conductor.mcp_server", mcp_server)
+        monkeypatch.setattr(
+            QMessageBox,
+            "critical",
+            lambda *args: errors.append(args[1:]),
+        )
+
+        controls.start_action.trigger()
+
+        assert errors == [
+            (
+                "Conductor Start Failed",
+                "Could not start the Conductor server:\n\nport is already in use",
+            )
+        ]
+        assert controls.status_action.text() == "Status: Stopped"
+        assert controls.start_action.isEnabled()
+
     def test_annotation_settings_action_opens_dialog(self, derzug_app, monkeypatch):
         """The Options menu should expose the global annotation settings dialog."""
         self._clear_annotation_settings()

 succeeded in 0ms:
"""Shared defaults for the DerZug Conductor transport."""

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4319

__all__ = ("DEFAULT_HOST", "DEFAULT_PORT")

 succeeded in 0ms:
 M docs/dev/conductor.md
 M docs/dev/plans/conductor_terminal_pane.md
 M src/derzug/conductor/mcp_server.py
 M src/derzug/views/orange.py
 M tests/test_cli.py
 M tests/test_views/test_orange_qt.py
?? .scratch/
?? src/derzug/conductor/constants.py
?? src/derzug/views/conductor.py
?? tests/test_views/test_conductor.py

 succeeded in 0ms:
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

 exited 1 in 0ms:
codex
The first pass shows that Conductor state is stored once on the application object but UI state is stored separately on every window. I’m tracing window creation/closure and the server thread’s stop semantics now, because that combination is the highest-risk area for stale menus and leaked/running services.
exec
/usr/bin/zsh -lc "nl -ba src/derzug/views/conductor.py | sed -n '220,430p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/views/orange.py | sed -n '2760,3075p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'rg -n "create_window|new_window|window.*close|lastWindowClosed|_conductor|tear_down_application|aboutToQuit|DerZugMainWindow" src/derzug/views/orange.py tests/test_views/test_orange_qt.py' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/conductor/mcp_server.py | sed -n '1,360p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'git diff -- docs/dev/conductor.md docs/dev/plans/conductor_terminal_pane.md' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/views/orange.py | sed -n '3140,3210p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba tests/test_views/test_conductor.py | sed -n '1,330p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/conductor/launch.py | sed -n '1,320p'" in /home/derrick/Gits/derzug
 succeeded in 0ms:
     1	"""Launch an agent CLI in a terminal, wired to the Conductor MCP server.
     2	
     3	Pure process/config helpers with no ``mcp`` dependency: build the launch
     4	command for a known agent, and best-effort open it in a new terminal window.
     5	"""
     6	
     7	from __future__ import annotations
     8	
     9	import logging
    10	import shlex
    11	import shutil
    12	import subprocess
    13	import sys
    14	
    15	log = logging.getLogger(__name__)
    16	
    17	#: The MCP server entry name clients see (``.mcp.json`` key / Codex table name).
    18	SERVER_NAME = "derzug-conductor"
    19	
    20	
    21	def agent_command(agent: str, url: str) -> list[str]:
    22	    """Return the command that starts ``agent`` connected to the server at ``url``.
    23	
    24	    ``claude`` needs no arguments: Claude Code picks up the ``.mcp.json`` in the
    25	    launch directory. ``codex`` supports streamable-HTTP MCP servers natively;
    26	    a per-invocation ``-c`` override wires it without touching the user's
    27	    ``~/.codex/config.toml``. Unknown agents are launched bare.
    28	    """
    29	    if agent == "codex":
    30	        return ["codex", "-c", f'mcp_servers.{SERVER_NAME}.url="{url}"']
    31	    return [agent]
    32	
    33	
    34	def _open_in_terminal(command: list[str], cwd: str) -> bool:
    35	    """Best-effort: open a new terminal window running ``command`` in ``cwd``."""
    36	    joined = " ".join(shlex.quote(part) for part in command)
    37	
    38	    def _spawn(argv: list[str], spawn_cwd: str | None = None) -> bool:
    39	        try:
    40	            subprocess.Popen(argv, cwd=spawn_cwd)
    41	            return True
    42	        except Exception:
    43	            log.error("Failed to launch terminal: %s", argv, exc_info=True)
    44	            return False
    45	
    46	    if sys.platform == "darwin":
    47	        script = (
    48	            f'tell application "Terminal" to do script '
    49	            f'"cd {shlex.quote(cwd)} && exec {joined}"'
    50	        )
    51	        return _spawn(["osascript", "-e", script])
    52	    if sys.platform == "win32":
    53	        if shutil.which("wt"):
    54	            return _spawn(["wt", "-d", cwd, *command])
    55	        return _spawn(["cmd", "/c", "start", "", "cmd", "/k", joined], spawn_cwd=cwd)
    56	    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
    57	        exe = shutil.which(term)
    58	        if exe is None:
    59	            continue
    60	        if term == "gnome-terminal":
    61	            return _spawn([exe, "--working-directory", cwd, "--", *command])
    62	        # xterm/konsole-style launchers take the executable and each argument
    63	        # separately after ``-e``. Passing one shell-joined string makes a
    64	        # multi-argument command (notably Codex's ``-c`` override) look like a
    65	        # single nonexistent executable.
    66	        return _spawn([exe, "-e", *command], spawn_cwd=cwd)
    67	    log.error("No terminal emulator found; run '%s' in %s yourself", joined, cwd)
    68	    return False
    69	
    70	
    71	def launch_agent_in_terminal(agent: str, cwd: str, url: str) -> bool:
    72	    """Launch ``agent`` in a new terminal in ``cwd``, wired to the server at ``url``."""
    73	    command = agent_command(agent, url)
    74	    if shutil.which(command[0]) is None:
    75	        log.error("Agent %r not found on PATH; run it yourself in %s", agent, cwd)
    76	        return False
    77	    return _open_in_terminal(command, cwd)

 succeeded in 0ms:
     1	"""In-app MCP server exposing the Conductor over localhost.
     2	
     3	Builds a FastMCP server whose tools drive a live ``CanvasController``. Every tool
     4	marshals its call onto the Qt main thread via a ``MainThreadDispatcher``, so an
     5	external agent client (e.g. Claude Code) can observe and drive the running canvas
     6	over a localhost transport while DerZug's UI stays responsive.
     7	
     8	``ConductorService`` owns the server lifecycle: it pre-binds the port (so a
     9	conflict fails fast and loudly), serves in a background thread, reports
    10	readiness, and shuts down cleanly on application teardown.
    11	
    12	Trust model: the server binds loopback only and carries no authentication —
    13	any local process may connect, so local clients are trusted by design. The
    14	``Code`` widget (arbitrary Python via parameters) is additionally excluded from
    15	the agent surface unless the user opts in with ``--conductor-allow-code``.
    16	
    17	Requires the optional ``mcp`` dependency: ``pip install 'derzug[conductor]'``.
    18	This module is imported only when the Conductor server is started, so the core
    19	app never depends on ``mcp``.
    20	"""
    21	
    22	from __future__ import annotations
    23	
    24	import json
    25	import logging
    26	import os
    27	import socket
    28	import threading
    29	import time
    30	from pathlib import Path
    31	from typing import Any
    32	
    33	from mcp.server.fastmcp import FastMCP
    34	
    35	from derzug.conductor.constants import DEFAULT_HOST, DEFAULT_PORT
    36	from derzug.conductor.controller import CanvasController
    37	from derzug.conductor.dispatch import MainThreadDispatcher
    38	from derzug.conductor.launch import SERVER_NAME, launch_agent_in_terminal
    39	
    40	log = logging.getLogger(__name__)
    41	
    42	
    43	def build_conductor_mcp(
    44	    controller: CanvasController, dispatcher: MainThreadDispatcher
    45	) -> FastMCP:
    46	    """Return a FastMCP server whose tools drive ``controller`` on the main thread."""
    47	    mcp = FastMCP(
    48	        "DerZug Conductor",
    49	        instructions=(
    50	            "Drive a live DerZug DAS (distributed acoustic sensing) workflow "
    51	            "canvas of connected widget nodes.\n\n"
    52	            "COMMON RECIPE (view data): add_node('Spool') -> "
    53	            "set_params(spool_id, {'spool_input': 'example_event_1'}) -> "
    54	            "add_node('Waterfall') -> connect(spool_id, waterfall_id) -> "
    55	            "run(spool_id) -> wait_for_idle().\n\n"
    56	            "CONVENTIONS:\n"
    57	            "- Almost every node has one input port 'Patch' and one output port "
    58	            "'Patch'; connect(source_id, sink_id) defaults to them, so you rarely "
    59	            "need port names.\n"
    60	            "- Omit x/y on add_node; nodes auto-place in a tidy left-to-right "
    61	            "row.\n"
    62	            "- set_params/set_view take PARTIAL updates, are validated against the "
    63	            "node's schema, and return the prior value. They do NOT re-run the "
    64	            "node by default: assemble and configure the graph first, then call "
    65	            "run(source_id) once and wait_for_idle().\n"
    66	            "- run() only schedules execution; wait_for_idle() blocks until no "
    67	            "node is busy (each node also reports a 'busy' flag).\n"
    68	            "- Structural edits (add/remove/connect) are undoable in the app "
    69	            "(Ctrl+Z).\n"
    70	            "- show_node pops up a node's widget window to display results.\n\n"
    71	            "DISCOVERY: list_widget_types = the catalog with each type's "
    72	            "params/view schema; get_canvas_state = the current graph; "
    73	            "describe_node = one node's detail incl. its output patch shape.\n\n"
    74	            "COMMON NODE TYPES: Spool (source; loads data/examples), Filter "
    75	            "(bandpass etc.), Waterfall (2D image view), Wiggle (trace view), "
    76	            "Detrend, Taper, Resample, Select, Aggregate. See list_widget_types "
    77	            "for the full set and parameters."
    78	        ),
    79	    )
    80	
    81	    def call(func: Any, *args: Any, **kwargs: Any) -> Any:
    82	        return dispatcher.run(func, *args, **kwargs)
    83	
    84	    @mcp.tool()
    85	    def get_canvas_state() -> dict[str, Any]:
    86	        """Return the whole canvas: nodes (typed params/view, ports) and links."""
    87	        return call(controller.get_canvas_state).model_dump()
    88	
    89	    @mcp.tool()
    90	    def list_widget_types() -> list[dict[str, Any]]:
    91	        """List placeable widget types with their params/view JSON schemas."""
    92	        return [info.model_dump() for info in call(controller.list_widget_types)]
    93	
    94	    @mcp.tool()
    95	    def describe_node(node_id: str) -> dict[str, Any]:
    96	        """Return one node's detail plus an input-patch shape/dims summary."""
    97	        return call(controller.describe_node, node_id).model_dump()
    98	
    99	    @mcp.tool()
   100	    def compile_check() -> dict[str, Any]:
   101	        """Report whether the current canvas compiles into a runnable workflow."""
   102	        return call(controller.compile_check)
   103	
   104	    @mcp.tool()
   105	    def get_focus() -> dict[str, Any]:
   106	        """What the user is looking at and pointing to (focused node + cursor)."""
   107	        return call(controller.get_focus).model_dump()
   108	
   109	    @mcp.tool()
   110	    def set_params(
   111	        node_id: str, params: dict[str, Any], run: bool = False
   112	    ) -> dict[str, Any]:
   113	        """Apply a partial params update to a node; returns its prior params.
   114	
   115	        Does not re-run the node unless ``run=True``: configure the graph fully,
   116	        then call the ``run`` tool once and ``wait_for_idle``.
   117	        """
   118	        return {"prior": call(controller.set_params, node_id, params, run=run)}
   119	
   120	    @mcp.tool()
   121	    def set_view(
   122	        node_id: str, view: dict[str, Any], run: bool = False
   123	    ) -> dict[str, Any]:
   124	        """Apply a partial view update (colormap, range, ...); returns the prior."""
   125	        return {"prior": call(controller.set_view, node_id, view, run=run)}
   126	
   127	    @mcp.tool()
   128	    def add_node(
   129	        widget_type: str,
   130	        title: str | None = None,
   131	        x: float | None = None,
   132	        y: float | None = None,
   133	    ) -> str:
   134	        """Add a node (display or qualified type name); returns its id.
   135	
   136	        Omit x/y to auto-place it compactly to the right of existing nodes.
   137	        Undoable.
   138	        """
   139	        position = (x, y) if x is not None and y is not None else None
   140	        return call(controller.add_node, widget_type, title=title, position=position)
   141	
   142	    @mcp.tool()
   143	    def remove_node(node_id: str) -> None:
   144	        """Remove a node and its links. Undoable."""
   145	        call(controller.remove_node, node_id)
   146	
   147	    @mcp.tool()
   148	    def connect(
   149	        source_id: str,
   150	        sink_id: str,
   151	        source_port: str = "Patch",
   152	        sink_port: str = "Patch",
   153	    ) -> None:
   154	        """Link source -> sink. Ports default to 'Patch' (the common case). Undoable."""
   155	        call(controller.connect, source_id, source_port, sink_id, sink_port)
   156	
   157	    @mcp.tool()
   158	    def disconnect(
   159	        source_id: str,
   160	        sink_id: str,
   161	        source_port: str = "Patch",
   162	        sink_port: str = "Patch",
   163	    ) -> None:
   164	        """Remove the matching link (ports default to 'Patch'). Undoable."""
   165	        call(controller.disconnect, source_id, source_port, sink_id, sink_port)
   166	
   167	    @mcp.tool()
   168	    def run(node_id: str) -> None:
   169	        """Schedule a node re-run (async); follow with wait_for_idle to await it."""
   170	        call(controller.run, node_id)
   171	
   172	    @mcp.tool()
   173	    def wait_for_idle(timeout_seconds: float = 30.0) -> dict[str, Any]:
   174	        """Block until no node is executing; reports still-busy nodes on timeout.
   175	
   176	        Polls from the server thread (brief main-thread hops), so the UI stays
   177	        responsive while waiting.
   178	        """
   179	        deadline = time.monotonic() + timeout_seconds
   180	        while True:
   181	            busy = call(controller.busy_nodes)
   182	            if not busy:
   183	                return {"idle": True, "busy_nodes": []}
   184	            if time.monotonic() > deadline:
   185	                return {"idle": False, "busy_nodes": busy}
   186	            time.sleep(0.1)
   187	
   188	    @mcp.tool()
   189	    def show_node(node_id: str, x: float | None = None, y: float | None = None) -> None:
   190	        """Pop up a node's widget window (show/raise/focus), optionally at (x, y)."""
   191	        call(controller.show_node, node_id, x=x, y=y)
   192	
   193	    @mcp.tool()
   194	    def move_node_window(node_id: str, x: float, y: float) -> None:
   195	        """Move a node's widget window to screen coordinates (x, y)."""
   196	        call(controller.move_node_window, node_id, x, y)
   197	
   198	    @mcp.tool()
   199	    def hide_node(node_id: str) -> None:
   200	        """Hide (close) a node's widget window."""
   201	        call(controller.hide_node, node_id)
   202	
   203	    return mcp
   204	
   205	
   206	class ConductorService:
   207	    """Owns the Conductor MCP server lifecycle: bind, serve, readiness, stop.
   208	
   209	    ``start`` pre-binds the listening socket on the calling thread — a port
   210	    conflict raises immediately instead of dying silently inside a worker —
   211	    then serves the streamable-http app on a background uvicorn server and
   212	    blocks until it reports ready (or raises on startup failure). ``stop``
   213	    halts the dispatcher (releasing any in-flight marshalled calls), signals
   214	    uvicorn to exit, and joins the thread.
   215	    """
   216	
   217	    def __init__(
   218	        self,
   219	        mcp: FastMCP,
   220	        *,
   221	        host: str = DEFAULT_HOST,
   222	        port: int = DEFAULT_PORT,
   223	        dispatcher: MainThreadDispatcher | None = None,
   224	    ) -> None:
   225	        self._mcp = mcp
   226	        self._host = host
   227	        self._port = port
   228	        self._dispatcher = dispatcher
   229	        self._server: Any | None = None
   230	        self._thread: threading.Thread | None = None
   231	
   232	    @property
   233	    def host(self) -> str:
   234	        """The interface the server binds (loopback by default)."""
   235	        return self._host
   236	
   237	    @property
   238	    def port(self) -> int:
   239	        """The bound port (resolved after ``start`` when constructed with 0)."""
   240	        return self._port
   241	
   242	    @property
   243	    def url(self) -> str:
   244	        """The server's MCP endpoint URL."""
   245	        return f"http://{self._host}:{self._port}/mcp"
   246	
   247	    def start(self, timeout: float = 15.0) -> str:
   248	        """Bind, serve in a background thread, and wait for readiness; return URL.
   249	
   250	        Raises ``OSError`` when the port is already taken and ``RuntimeError``
   251	        when the server exits or is not ready within ``timeout`` seconds.
   252	        """
   253	        import uvicorn
   254	
   255	        sock = socket.create_server((self._host, self._port))
   256	        try:
   257	            self._port = sock.getsockname()[1]  # resolves an ephemeral port (0)
   258	            config = uvicorn.Config(
   259	                self._mcp.streamable_http_app(),
   260	                host=self._host,
   261	                port=self._port,
   262	                log_level="warning",
   263	            )
   264	            self._server = uvicorn.Server(config)
   265	            self._thread = threading.Thread(
   266	                target=self._server.run,
   267	                kwargs={"sockets": [sock]},
   268	                name="conductor-mcp",
   269	                daemon=True,
   270	            )
   271	            self._thread.start()
   272	            deadline = time.monotonic() + timeout
   273	            while not self._server.started:
   274	                if not self._thread.is_alive():
   275	                    raise RuntimeError("Conductor MCP server exited during startup")
   276	                if time.monotonic() > deadline:
   277	                    raise RuntimeError(
   278	                        f"Conductor MCP server not ready after {timeout:.0f}s"
   279	                    )
   280	                time.sleep(0.05)
   281	        except BaseException:
   282	            self.stop()
   283	            sock.close()
   284	            raise
   285	        log.info("Conductor MCP server ready at %s", self.url)
   286	        return self.url
   287	
   288	    def stop(self, timeout: float = 5.0) -> None:
   289	        """Shut down: stop the dispatcher, signal uvicorn to exit, join the thread."""
   290	        if self._dispatcher is not None:
   291	            self._dispatcher.stop()
   292	        if self._server is not None:
   293	            self._server.should_exit = True
   294	        if self._thread is not None and self._thread.is_alive():
   295	            self._thread.join(timeout)
   296	            if self._thread.is_alive():
   297	                log.warning("Conductor MCP server thread did not stop cleanly")
   298	        self._server = None
   299	        self._thread = None
   300	
   301	
   302	def write_mcp_config(
   303	    path: str | Path,
   304	    *,
   305	    host: str = DEFAULT_HOST,
   306	    port: int = DEFAULT_PORT,
   307	    name: str = SERVER_NAME,
   308	) -> str:
   309	    """Merge our server entry into the MCP client config at ``path``; return URL.
   310	
   311	    The file is an ``.mcp.json`` a client such as Claude Code picks up. An
   312	    existing config keeps its other entries — only ``mcpServers[name]`` is
   313	    replaced — and the file is written atomically (temp file + rename). An
   314	    existing file that is not valid JSON is left untouched (logged), so a
   315	    user's hand-edited config is never clobbered.
   316	    """
   317	    url = f"http://{host}:{port}/mcp"
   318	    path = Path(path)
   319	    config: dict[str, Any] = {}
   320	    if path.exists():
   321	        try:
   322	            config = json.loads(path.read_text())
   323	        except ValueError:
   324	            log.error(
   325	                "Existing %s is not valid JSON; leaving it untouched. "
   326	                "Add the server yourself: %s",
   327	                path,
   328	                url,
   329	            )
   330	            return url
   331	        if not isinstance(config, dict):
   332	            config = {}
   333	    servers = config.setdefault("mcpServers", {})
   334	    servers[name] = {"type": "http", "url": url}
   335	    tmp = path.with_name(path.name + ".tmp")
   336	    tmp.write_text(json.dumps(config, indent=2))
   337	    os.replace(tmp, path)
   338	    return url
   339	
   340	
   341	def start_conductor(
   342	    window: Any,
   343	    *,
   344	    host: str = DEFAULT_HOST,
   345	    port: int = DEFAULT_PORT,
   346	    config_path: str | Path | None = None,
   347	    agent: str | None = None,
   348	    allow_code: bool = False,
   349	) -> ConductorService:
   350	    """Wire and start the in-app Conductor MCP server for ``window``.
   351	
   352	    Builds a ``CanvasController`` + ``MainThreadDispatcher``, starts a
   353	    ``ConductorService`` and waits for readiness (raising on bind/startup
   354	    failure). Only after the server is ready is the client config written and,
   355	    when ``agent`` is given (e.g. ``"claude"`` / ``"codex"``), the agent
   356	    launched in a new terminal in the config directory. The caller owns the
   357	    returned service and should ``stop()`` it on application teardown.
   358	    """
   359	    controller = CanvasController(window, allow_code=allow_code)
   360	    dispatcher = MainThreadDispatcher()

 succeeded in 0ms:
  3140	        if window is None:
  3141	            return
  3142	        with suppress(RuntimeError):
  3143	            window.raise_()
  3144	            window.activateWindow()
  3145	
  3146	
  3147	_APP_SHELL_SERVICE = _AppShellService()
  3148	
  3149	
  3150	class DerZugMainWindow(OrangeMainWindow):
  3151	    """Orange main window customized for DerZug."""
  3152	
  3153	    def set_notification_server(self, notif_server):
  3154	        """Accept a missing notification server when creating secondary windows."""
  3155	        self.notification_server = notif_server
  3156	        if notif_server is None:
  3157	            return
  3158	        super().set_notification_server(notif_server)
  3159	
  3160	    def __init__(self, *args, **kwargs):
  3161	        """Initialize the DerZug main window."""
  3162	        ensure_canvas_patches_installed()
  3163	        register_app_shell_service(_APP_SHELL_SERVICE)
  3164	        super().__init__(*args, **kwargs)
  3165	        self.setWindowTitle("DerZug")
  3166	        self.set_float_widgets_on_top_enabled(False)
  3167	        self.active_source_manager: ActiveSourceManager | None = None
  3168	        self.dev_mode = False
  3169	        self.startup_demo_mode = False
  3170	        self.startup_workflow_path: str | None = None
  3171	        self.startup_open_widget_ids: list[int] = []
  3172	        self.conductor_controls = None
  3173	        self.dev_menu: QMenu | None = None
  3174	        self.hot_reload_action: QAction | None = None
  3175	        self.edit_config_file_action: QAction | None = None
  3176	        self.annotation_settings_action: QAction | None = None
  3177	        self._hot_reload_in_progress = False
  3178	        self._startup_warning_shown = False
  3179	        self._canvas_composite_controller = _CanvasCompositeController(self)
  3180	        self._canvas_traceback_filter = _CanvasTracebackIconFilter(self)
  3181	        self._canvas_middle_button_pan_filter = _CanvasMiddleButtonPanFilter(self)
  3182	        self._canvas_arrow_palette_controller: (
  3183	            _CanvasArrowColorPaletteController | None
  3184	        ) = None
  3185	        self._canvas_text_palette_controller: (
  3186	            _CanvasTextStylePaletteController | None
  3187	        ) = None
  3188	        self._apply_default_help_visibility()
  3189	        self._customize_shell()
  3190	        self._install_canvas_traceback_filter()
  3191	        self._install_canvas_middle_button_pan_filter()
  3192	        self._install_canvas_reset_view_handler()
  3193	        document = self.current_document()
  3194	        if document is not None:
  3195	            _install_canvas_clipboard_actions(document)
  3196	            self._canvas_arrow_palette_controller = _CanvasArrowColorPaletteController(
  3197	                self
  3198	            )
  3199	            self._canvas_text_palette_controller = _CanvasTextStylePaletteController(
  3200	                self
  3201	            )
  3202	
  3203	    def _apply_default_help_visibility(self) -> None:
  3204	        """Default quick-help pane to hidden unless user has saved a preference."""
  3205	        settings = QSettings()
  3206	        settings.beginGroup("mainwindow")
  3207	        has_saved_visibility = settings.contains("quick-help/visible")
  3208	        settings.endGroup()
  3209	        if has_saved_visibility:
  3210	            return

 succeeded in 0ms:
tests/test_views/test_orange_qt.py:280:class TestDerZugMainWindow:
tests/test_views/test_orange_qt.py:368:    def test_conductor_menu_is_always_available(self, derzug_app):
tests/test_views/test_orange_qt.py:379:    def test_conductor_menu_controls_service_lifecycle(
tests/test_views/test_orange_qt.py:407:        mcp_server.start_conductor = _fake_start
tests/test_views/test_orange_qt.py:445:        assert main._conductor_service is None
tests/test_views/test_orange_qt.py:449:    def test_conductor_start_failure_returns_menu_to_stopped(
tests/test_views/test_orange_qt.py:461:        mcp_server.start_conductor = _fail_start
tests/test_views/test_orange_qt.py:1302:    def test_create_new_window_allows_missing_notification_server(
tests/test_views/test_orange_qt.py:1309:        created = window.create_new_window()
tests/test_views/test_orange_qt.py:1314:            assert isinstance(created, orange_view.DerZugMainWindow)
tests/test_views/test_orange_qt.py:4097:        main._tear_down_application_filters()
tests/test_views/test_orange_qt.py:4110:    def test_tear_down_application_runs_filter_teardown_before_base(
tests/test_views/test_orange_qt.py:4120:            "_tear_down_application_filters",
tests/test_views/test_orange_qt.py:4125:            "tear_down_application",
tests/test_views/test_orange_qt.py:4129:        main.tear_down_application()
src/derzug/views/orange.py:154:    "DerZugMainWindow",
src/derzug/views/orange.py:186:    never mutates global orangecanvas classes. ``DerZugMainWindow`` triggers
src/derzug/views/orange.py:908:    def __init__(self, main_window: DerZugMainWindow) -> None:
src/derzug/views/orange.py:1138:    def __init__(self, main_window: DerZugMainWindow) -> None:
src/derzug/views/orange.py:2615:        """Return the running DerZugMainWindow, or None."""
src/derzug/views/orange.py:2617:            if isinstance(widget, DerZugMainWindow):
src/derzug/views/orange.py:2650:        """Return the running DerZugMainWindow, or None."""
src/derzug/views/orange.py:2652:            if isinstance(widget, DerZugMainWindow):
src/derzug/views/orange.py:2695:            if isinstance(widget, DerZugMainWindow):
src/derzug/views/orange.py:2784:    _conductor_service = None
src/derzug/views/orange.py:2785:    _conductor_window = None
src/derzug/views/orange.py:2786:    _conductor_cwd: str | None = None
src/derzug/views/orange.py:2817:    def _tear_down_application_filters(self) -> None:
src/derzug/views/orange.py:2859:    def tear_down_application(self):
src/derzug/views/orange.py:2861:        self._stop_conductor()
src/derzug/views/orange.py:2862:        self._tear_down_application_filters()
src/derzug/views/orange.py:2863:        super().tear_down_application()
src/derzug/views/orange.py:2875:        return DerZugMainWindow()
src/derzug/views/orange.py:2890:        self._install_conductor_controls(window)
src/derzug/views/orange.py:2896:            self._start_conductor(
src/derzug/views/orange.py:2904:    def _install_conductor_controls(self, window) -> None:
src/derzug/views/orange.py:2909:            load_conductor_port,
src/derzug/views/orange.py:2910:            save_conductor_port,
src/derzug/views/orange.py:2916:            port=load_conductor_port(_derzug_settings()),
src/derzug/views/orange.py:2921:        self._conductor_window = window
src/derzug/views/orange.py:2924:            lambda port, allow_code: self._start_conductor(
src/derzug/views/orange.py:2930:        controls.stop_requested.connect(self._stop_conductor)
src/derzug/views/orange.py:2932:            lambda port, allow_code: self._restart_conductor(
src/derzug/views/orange.py:2939:            lambda agent: self._launch_conductor_agent(window, agent)
src/derzug/views/orange.py:2942:            lambda port: save_conductor_port(port, _derzug_settings())
src/derzug/views/orange.py:2944:        self.application.aboutToQuit.connect(self._stop_conductor)
src/derzug/views/orange.py:2946:    def _start_conductor(
src/derzug/views/orange.py:2959:        if self._conductor_service is not None:
src/derzug/views/orange.py:2966:            from derzug.conductor.mcp_server import start_conductor
src/derzug/views/orange.py:2981:            service = start_conductor(
src/derzug/views/orange.py:2999:        self._conductor_service = service
src/derzug/views/orange.py:3000:        self._conductor_cwd = str(config_path.parent)
src/derzug/views/orange.py:3003:            self._launch_conductor_agent(window, agent)
src/derzug/views/orange.py:3006:    def _stop_conductor(self) -> None:
src/derzug/views/orange.py:3008:        service, self._conductor_service = self._conductor_service, None
src/derzug/views/orange.py:3009:        window = self._conductor_window
src/derzug/views/orange.py:3036:            self._conductor_cwd = None
src/derzug/views/orange.py:3040:    def _restart_conductor(
src/derzug/views/orange.py:3048:        self._stop_conductor()
src/derzug/views/orange.py:3049:        return self._start_conductor(
src/derzug/views/orange.py:3055:    def _launch_conductor_agent(self, window, agent: str) -> bool:
src/derzug/views/orange.py:3059:        service = self._conductor_service
src/derzug/views/orange.py:3060:        cwd = self._conductor_cwd
src/derzug/views/orange.py:3150:class DerZugMainWindow(OrangeMainWindow):

 succeeded in 0ms:
   220	
   221	    @property
   222	    def settings(self) -> ConductorSettings:
   223	        """Return the configuration for the next start or restart."""
   224	        return self._settings
   225	
   226	    @property
   227	    def url(self) -> str | None:
   228	        """Return the running MCP URL, if the server is active."""
   229	        return self._url
   230	
   231	    def set_settings(self, settings: ConductorSettings) -> None:
   232	        """Replace the next-start configuration without persisting it."""
   233	        self._settings = settings
   234	        self._refresh_actions()
   235	
   236	    def set_starting(self) -> None:
   237	        """Show that a server start is in progress."""
   238	        self._state = "starting"
   239	        self._url = None
   240	        self._running_settings = None
   241	        self._refresh_actions()
   242	
   243	    def set_running(self, url: str, settings: ConductorSettings) -> None:
   244	        """Show a ready server and enable runtime-only actions."""
   245	        self._state = "running"
   246	        self._url = url
   247	        self._running_settings = settings
   248	        self._refresh_actions()
   249	
   250	    def set_stopping(self) -> None:
   251	        """Show that server shutdown is in progress."""
   252	        self._state = "stopping"
   253	        self._refresh_actions()
   254	
   255	    def set_stopped(self) -> None:
   256	        """Show a stopped server and disable runtime-only actions."""
   257	        self._state = "stopped"
   258	        self._url = None
   259	        self._running_settings = None
   260	        self._refresh_actions()
   261	
   262	    def _request_start(self) -> None:
   263	        """Request a start with the currently configured values."""
   264	        self.start_requested.emit(self._settings.port, self._settings.allow_code)
   265	
   266	    def _request_restart(self) -> None:
   267	        """Request a restart with the currently configured values."""
   268	        self.restart_requested.emit(self._settings.port, self._settings.allow_code)
   269	
   270	    def _copy_url(self) -> None:
   271	        """Copy the active MCP URL to the system clipboard."""
   272	        clipboard = QApplication.clipboard()
   273	        if self._url is not None and clipboard is not None:
   274	            clipboard.setText(self._url)
   275	
   276	    def _open_settings(self) -> None:
   277	        """Open the server settings dialog and retain accepted changes."""
   278	        dialog = ConductorSettingsDialog(self._settings, self._window)
   279	        if dialog.exec() != QDialog.DialogCode.Accepted:
   280	            return
   281	        previous_port = self._settings.port
   282	        self._settings = dialog.settings()
   283	        if self._settings.port != previous_port:
   284	            self.port_changed.emit(self._settings.port)
   285	        self._refresh_actions()
   286	
   287	    def _refresh_actions(self) -> None:
   288	        """Synchronize labels and enabled states with the lifecycle state."""
   289	        running = self._state == "running" and self._url is not None
   290	        busy = self._state in {"starting", "stopping"}
   291	        if self._state == "starting":
   292	            status = "Status: Starting..."
   293	        elif self._state == "stopping":
   294	            status = "Status: Stopping..."
   295	        elif running:
   296	            status = f"Status: Running at {self._url}"
   297	        else:
   298	            status = "Status: Stopped"
   299	        self.status_action.setText(status)
   300	        self.status_action.setToolTip(self._url or "Conductor server is stopped")
   301	
   302	        self.start_action.setEnabled(self._state == "stopped")
   303	        self.stop_action.setEnabled(running)
   304	        self.copy_url_action.setEnabled(running)
   305	        agent_menu_action = self.agent_menu.menuAction()
   306	        if agent_menu_action is not None:
   307	            agent_menu_action.setEnabled(running)
   308	        self.settings_action.setEnabled(not busy)
   309	
   310	        settings_pending = running and self._running_settings != self._settings
   311	        restart_label = (
   312	            "Restart Server (Apply Settings)" if settings_pending else "Restart Server"
   313	        )
   314	        self.restart_action.setText(restart_label)
   315	        self.restart_action.setEnabled(running)
   316	
   317	
   318	__all__ = (
   319	    "ConductorMenuController",
   320	    "ConductorSettings",
   321	    "ConductorSettingsDialog",
   322	    "load_conductor_port",
   323	    "save_conductor_port",
   324	)

 succeeded in 0ms:
diff --git a/docs/dev/conductor.md b/docs/dev/conductor.md
index 9423434..3a7ddf8 100644
--- a/docs/dev/conductor.md
+++ b/docs/dev/conductor.md
@@ -14,27 +14,30 @@ handles model credentials.
    pip install '.[conductor]'
    ```
 
-2. Start DerZug with the Conductor server:
+2. Start DerZug:
 
    ```bash
-   derzug --conductor
+   derzug
    ```
 
-   This starts an MCP server on `http://127.0.0.1:4319/mcp` and merges a
-   `derzug-conductor` entry into the `.mcp.json` in the current directory
-   (other entries in an existing file are preserved; the file is gitignored).
-   A port conflict or startup failure is reported immediately, and the server
-   shuts down with the application.
+   Open the **Conductor** menu and choose **Start Server**. The status entry
+   reports the active MCP URL (by default `http://127.0.0.1:4319/mcp`). Starting
+   the server merges a `derzug-conductor` entry into the `.mcp.json` in the
+   current directory; other entries are preserved and the file is gitignored.
 
-3. From that directory, start your agent (Claude Code picks up `.mcp.json`):
+3. Choose **Open Agent → Claude Code** or **Open Agent → Codex** to launch a
+   pre-wired client in a new terminal. You can also start an agent yourself from
+   the directory containing `.mcp.json` (Claude Code picks it up automatically):
 
    ```bash
    claude
    ```
 
-   Or let DerZug launch it for you in a new terminal, pre-wired:
+   For automation or the previous one-command workflow, the CLI flags remain
+   available:
 
    ```bash
+   derzug --conductor
    derzug --agent claude   # or: derzug --agent codex
    ```
 
@@ -83,6 +86,26 @@ surface (hidden from the catalog; add/configure rejected) unless you opt in:
 derzug --conductor --conductor-allow-code
 ```
 
+You can also opt in for the current session through **Conductor → Settings...**.
+The menu does not persist this permission.
+
+## Menu controls
+
+The **Conductor** menu remains available whether the server is running or not:
+
+- **Start Server**, **Stop Server**, and **Restart Server** own the service
+  lifecycle. Closing DerZug also stops the service.
+- **Copy MCP URL** and **Open Agent** are enabled only while the server is
+  running.
+- **Settings...** configures the port and the Code-widget permission. The port
+  is remembered across launches. The arbitrary-code permission is deliberately
+  session-only and defaults to off each time DerZug starts. Changes made while
+  the server is running take effect after **Restart Server (Apply Settings)**.
+
+The host is fixed to loopback (`127.0.0.1`). Port conflicts, missing optional
+dependencies, and agent-launch failures are reported in the UI and leave the
+menu in a usable state.
+
 ## Architecture
 
 - `conductor/controller.py` — `CanvasController`, the main-thread surface over the
@@ -97,7 +120,9 @@ derzug --conductor --conductor-allow-code
   the dispatcher) and owns its lifecycle via `ConductorService`: the port is
   pre-bound (a conflict raises at startup), readiness is awaited before the
   client config is written or an agent launched, and the service stops on
-  application teardown. Imported only when `--conductor` is used, so the core
+  application teardown. Imported only when the server is started, so the core
   app never depends on `mcp`.
 - `conductor/launch.py` — agent launch helpers: the per-agent connect command
   and the cross-platform "open a terminal" spawn.
+- `views/conductor.py` — the always-available menu, lifecycle state display,
+  and settings dialog. It has no dependency on the optional MCP package.
diff --git a/docs/dev/plans/conductor_terminal_pane.md b/docs/dev/plans/conductor_terminal_pane.md
index d23038a..b0d9dd1 100644
--- a/docs/dev/plans/conductor_terminal_pane.md
+++ b/docs/dev/plans/conductor_terminal_pane.md
@@ -32,11 +32,12 @@ rendering. That is the load-bearing engineering piece.
 Phase the risk: prove the connection ergonomics first, then invest in the
 emulator.
 
-**Prototype step 1 — auto-wired external terminal (lowest risk).**
-- On `derzug --conductor`, we already start the MCP server and write `.mcp.json`.
-- Add a **Conductor menu/toolbar action** ("Open agent terminal") that launches
-  the user's *system* terminal in the workflow directory (where `.mcp.json`
-  lives) so `claude` auto-connects. No embedded rendering yet.
+**Prototype step 1 — lifecycle menu + auto-wired external terminal (lowest
+risk).**
+- The always-visible **Conductor** menu starts, stops, and configures the MCP
+  server, with CLI startup retained for automation.
+- **Open Agent** launches Claude Code or Codex in the user's *system* terminal,
+  wired to the running server. No embedded rendering yet.
 - Ships a usable end-to-end demo immediately; validates the "it just connects"
   ergonomics.
 
@@ -59,7 +60,8 @@ emulator.
 | File | Role |
 |---|---|
 | `src/derzug/conductor/terminal.py` | The terminal pane widget (pty + emulator + shell process lifecycle). |
-| `src/derzug/views/orange.py` | Menu/toolbar action to open the pane / external terminal; dock it into the main window; gate behind `--conductor`. |
+| `src/derzug/views/conductor.py` | Existing server lifecycle menu and external-agent controls; later add the pane action here. |
+| `src/derzug/views/orange.py` | Own the service lifecycle and eventually dock the terminal pane into the main window. |
 | `src/derzug/conductor/mcp_server.py` | Already writes `.mcp.json`; may add a helper to resolve the agent launch command/cwd. |
 | `docs/dev/conductor.md` | Update the demo once the pane exists. |
 
@@ -78,7 +80,8 @@ emulator.
 
 - Unit: the launch-command/config helpers (cwd, `.mcp.json` presence) are pure
   and testable; the emulator/pty is integration-level and largely manual.
-- Manual: `derzug --conductor`, open the pane, run `claude`, confirm it connects
+- Manual: start the server from the **Conductor** menu, open the pane, run
+  `claude`, confirm it connects
   and can drive the canvas; confirm `Ctrl+Z` still reverts agent edits and global
   shortcuts behave when the terminal has focus.
 - Keep any Qt/pty rendering out of the headless CI path (guard/skip), matching

 succeeded in 0ms:
  2760	        return changed
  2761	
  2762	
  2763	# def get_app(app=None):
  2764	#     """Get or create the QApplication, with Ctrl+C (SIGINT) support."""
  2765	#     app = app or QApplication.instance() or QApplication(sys.argv)
  2766	#     signal.signal(signal.SIGINT, lambda *_: app.quit())
  2767	#     app._sigint_timer = QTimer()
  2768	#     app._sigint_timer.start(600)
  2769	#     app._sigint_timer.timeout.connect(lambda: None)
  2770	#     return app
  2771	
  2772	
  2773	class DerZugMain(OMain):
  2774	    """Orange main runner customized for DerZug."""
  2775	
  2776	    DefaultConfig = "derzug.views.orange.DerZugConfig"
  2777	    gpu_rendering_enabled = False
  2778	    active_source_manager = None
  2779	    show_demo = False
  2780	    dev_mode = False
  2781	    conductor_enabled = False
  2782	    conductor_agent: str | None = None
  2783	    conductor_allow_code = False
  2784	    _conductor_service = None
  2785	    _conductor_window = None
  2786	    _conductor_cwd: str | None = None
  2787	    startup_workflow_path: str | None = None
  2788	    startup_open_widget_ids: ClassVar[list[int]] = []
  2789	
  2790	    def run(self, argv=None):
  2791	        """Run the Orange main loop for DerZug."""
  2792	        # self.app = get_app()
  2793	        return super().run(argv or [])
  2794	
  2795	    def setup_application(self):
  2796	        """Apply DerZug-specific application setup."""
  2797	        super().setup_application()
  2798	        install_sigint_handler(self.application)
  2799	        self.gpu_rendering_enabled = _configure_pyqtgraph_gpu_rendering()
  2800	        self.active_source_manager = ActiveSourceManager()
  2801	        global _APP_ACTIVE_SOURCE_MANAGER
  2802	        _APP_ACTIVE_SOURCE_MANAGER = self.active_source_manager
  2803	        self.application.active_source_manager = self.active_source_manager
  2804	        _configure_linux_desktop_integration(self.application)
  2805	        self.application.setWindowIcon(DerZugConfig.application_icon())
  2806	        self._tab_window_cycler = _TabWindowCycler(self.application)
  2807	        self._active_source_navigator = _ActiveSourceNavigator(
  2808	            self.active_source_manager
  2809	        )
  2810	        self._canvas_z_order_toggler = _CanvasZOrderToggler(self.application)
  2811	        self._canvas_escape_defocuser = _CanvasEscapeDefocuser(self.application)
  2812	        self.application.installEventFilter(self._tab_window_cycler)
  2813	        self.application.installEventFilter(self._active_source_navigator)
  2814	        self.application.installEventFilter(self._canvas_z_order_toggler)
  2815	        self.application.installEventFilter(self._canvas_escape_defocuser)
  2816	
  2817	    def _tear_down_application_filters(self) -> None:
  2818	        """Remove DerZug-installed QApplication event filters and globals."""
  2819	        app = getattr(self, "application", None)
  2820	        for attr_name in (
  2821	            "_tab_window_cycler",
  2822	            "_active_source_navigator",
  2823	            "_canvas_z_order_toggler",
  2824	            "_canvas_escape_defocuser",
  2825	        ):
  2826	            event_filter = getattr(self, attr_name, None)
  2827	            if event_filter is not None and app is not None:
  2828	                with suppress((TypeError, RuntimeError)):
  2829	                    app.removeEventFilter(event_filter)
  2830	            setattr(self, attr_name, None)
  2831	
  2832	        global _APP_ACTIVE_SOURCE_MANAGER, _APP_ACTIVE_SOURCE_MAIN_WINDOW
  2833	        _APP_ACTIVE_SOURCE_MANAGER = None
  2834	        _APP_ACTIVE_SOURCE_MAIN_WINDOW = None
  2835	        self.active_source_manager = None
  2836	
  2837	        if app is not None:
  2838	            with suppress(AttributeError):
  2839	                app.active_source_manager = None
  2840	            with suppress(AttributeError):
  2841	                app.active_source_main_window = None
  2842	
  2843	    def setup_sys_redirections(self):
  2844	        """Install stdout/stderr redirection and DerZug's exception dialog hook."""
  2845	        super().setup_sys_redirections()
  2846	        _install_derzug_exception_handler()
  2847	
  2848	    def tear_down_sys_redirections(self):
  2849	        """Remove DerZug's exception handler before restoring base redirections."""
  2850	        if isinstance(sys.excepthook, ExceptHook):
  2851	            with suppress((TypeError, RuntimeError)):
  2852	                sys.excepthook.handledException.disconnect(handle_derzug_exception)
  2853	            # Restore Orange's expected connection so the base teardown can
  2854	            # disconnect it without raising when shutting the app down.
  2855	            with suppress((TypeError, RuntimeError)):
  2856	                sys.excepthook.handledException.connect(orange_handle_exception)
  2857	        super().tear_down_sys_redirections()
  2858	
  2859	    def tear_down_application(self):
  2860	        """Remove DerZug app-global hooks before base QApplication teardown."""
  2861	        self._stop_conductor()
  2862	        self._tear_down_application_filters()
  2863	        super().tear_down_application()
  2864	
  2865	    def splash_screen(self):
  2866	        """Disable splash screen for the DerZug app."""
  2867	        return None
  2868	
  2869	    def show_welcome_screen(self, parent):
  2870	        """Disable Orange welcome screen for DerZug."""
  2871	        return None
  2872	
  2873	    def create_main_window(self):
  2874	        """Create the main window instance for DerZug."""
  2875	        return DerZugMainWindow()
  2876	
  2877	    def setup_main_window(self):
  2878	        """Configure the main window with the filtered widget registry."""
  2879	        window = super().setup_main_window()
  2880	        self.registry = filter_registry_for_das(self.registry)
  2881	        window.set_widget_registry(self.registry)
  2882	        window.active_source_manager = self.active_source_manager
  2883	        window.dev_mode = bool(self.dev_mode)
  2884	        window.startup_demo_mode = bool(self.show_demo)
  2885	        window.startup_workflow_path = self.startup_workflow_path
  2886	        window.startup_open_widget_ids = list(self.startup_open_widget_ids)
  2887	        global _APP_ACTIVE_SOURCE_MAIN_WINDOW
  2888	        _APP_ACTIVE_SOURCE_MAIN_WINDOW = window
  2889	        self.application.active_source_main_window = window
  2890	        self._install_conductor_controls(window)
  2891	        window.install_dev_controls()
  2892	        if self.show_demo:
  2893	            QTimer.singleShot(0, window.examples_dialog)
  2894	        if self.conductor_enabled:
  2895	            settings = window.conductor_controls.settings
  2896	            self._start_conductor(
  2897	                window,
  2898	                port=settings.port,
  2899	                allow_code=settings.allow_code,
  2900	                agent=self.conductor_agent,
  2901	            )
  2902	        return window
  2903	
  2904	    def _install_conductor_controls(self, window) -> None:
  2905	        """Install the always-available menu and connect lifecycle requests."""
  2906	        from derzug.views.conductor import (
  2907	            ConductorMenuController,
  2908	            ConductorSettings,
  2909	            load_conductor_port,
  2910	            save_conductor_port,
  2911	        )
  2912	
  2913	        if window.conductor_controls is not None:
  2914	            return
  2915	        settings = ConductorSettings(
  2916	            port=load_conductor_port(_derzug_settings()),
  2917	            allow_code=bool(self.conductor_allow_code),
  2918	        )
  2919	        controls = ConductorMenuController(window, settings)
  2920	        window.conductor_controls = controls
  2921	        self._conductor_window = window
  2922	
  2923	        controls.start_requested.connect(
  2924	            lambda port, allow_code: self._start_conductor(
  2925	                window,
  2926	                port=port,
  2927	                allow_code=allow_code,
  2928	            )
  2929	        )
  2930	        controls.stop_requested.connect(self._stop_conductor)
  2931	        controls.restart_requested.connect(
  2932	            lambda port, allow_code: self._restart_conductor(
  2933	                window,
  2934	                port=port,
  2935	                allow_code=allow_code,
  2936	            )
  2937	        )
  2938	        controls.launch_agent_requested.connect(
  2939	            lambda agent: self._launch_conductor_agent(window, agent)
  2940	        )
  2941	        controls.port_changed.connect(
  2942	            lambda port: save_conductor_port(port, _derzug_settings())
  2943	        )
  2944	        self.application.aboutToQuit.connect(self._stop_conductor)
  2945	
  2946	    def _start_conductor(
  2947	        self,
  2948	        window,
  2949	        *,
  2950	        port: int,
  2951	        allow_code: bool,
  2952	        agent: str | None = None,
  2953	    ) -> bool:
  2954	        """Start the optional Conductor server and synchronize its menu state."""
  2955	        import logging
  2956	
  2957	        from derzug.views.conductor import ConductorSettings
  2958	
  2959	        if self._conductor_service is not None:
  2960	            return True
  2961	        controls = window.conductor_controls
  2962	        settings = ConductorSettings(port=port, allow_code=allow_code)
  2963	        controls.set_starting()
  2964	
  2965	        try:
  2966	            from derzug.conductor.mcp_server import start_conductor
  2967	        except ImportError:
  2968	            logging.getLogger(__name__).error(
  2969	                "Conductor requires the 'mcp' extra: pip install 'derzug[conductor]'"
  2970	            )
  2971	            controls.set_stopped()
  2972	            QMessageBox.critical(
  2973	                window,
  2974	                "Conductor Unavailable",
  2975	                "Conductor requires the optional MCP dependency. Install it with "
  2976	                "pip install 'derzug[conductor]'.",
  2977	            )
  2978	            return False
  2979	        config_path = Path.cwd() / ".mcp.json"
  2980	        try:
  2981	            service = start_conductor(
  2982	                window,
  2983	                config_path=config_path,
  2984	                port=settings.port,
  2985	                allow_code=settings.allow_code,
  2986	            )
  2987	        except Exception as exc:
  2988	            logging.getLogger(__name__).error(
  2989	                "Failed to start the Conductor MCP server", exc_info=True
  2990	            )
  2991	            controls.set_stopped()
  2992	            detail = str(exc) or type(exc).__name__
  2993	            QMessageBox.critical(
  2994	                window,
  2995	                "Conductor Start Failed",
  2996	                f"Could not start the Conductor server:\n\n{detail}",
  2997	            )
  2998	            return False
  2999	        self._conductor_service = service
  3000	        self._conductor_cwd = str(config_path.parent)
  3001	        controls.set_running(service.url, settings)
  3002	        if agent is not None:
  3003	            self._launch_conductor_agent(window, agent)
  3004	        return True
  3005	
  3006	    def _stop_conductor(self) -> None:
  3007	        """Shut the Conductor service down at application teardown."""
  3008	        service, self._conductor_service = self._conductor_service, None
  3009	        window = self._conductor_window
  3010	        controls = (
  3011	            None
  3012	            if window is None or _qt_object_is_deleted(window)
  3013	            else getattr(window, "conductor_controls", None)
  3014	        )
  3015	        if service is None:
  3016	            if controls is not None:
  3017	                controls.set_stopped()
  3018	            return
  3019	        if controls is not None:
  3020	            controls.set_stopping()
  3021	        try:
  3022	            service.stop()
  3023	        except Exception as exc:
  3024	            import logging
  3025	
  3026	            logging.getLogger(__name__).error(
  3027	                "Failed to stop the Conductor MCP server", exc_info=True
  3028	            )
  3029	            if window is not None:
  3030	                QMessageBox.warning(
  3031	                    window,
  3032	                    "Conductor Stop Failed",
  3033	                    f"The Conductor server reported an error while stopping:\n\n{exc}",
  3034	                )
  3035	        finally:
  3036	            self._conductor_cwd = None
  3037	            if controls is not None:
  3038	                controls.set_stopped()
  3039	
  3040	    def _restart_conductor(
  3041	        self,
  3042	        window,
  3043	        *,
  3044	        port: int,
  3045	        allow_code: bool,
  3046	    ) -> bool:
  3047	        """Restart the server so the current menu settings take effect."""
  3048	        self._stop_conductor()
  3049	        return self._start_conductor(
  3050	            window,
  3051	            port=port,
  3052	            allow_code=allow_code,
  3053	        )
  3054	
  3055	    def _launch_conductor_agent(self, window, agent: str) -> bool:
  3056	        """Launch one agent connected to the active Conductor service."""
  3057	        from derzug.conductor.launch import launch_agent_in_terminal
  3058	
  3059	        service = self._conductor_service
  3060	        cwd = self._conductor_cwd
  3061	        if service is None or cwd is None:
  3062	            return False
  3063	        if launch_agent_in_terminal(agent, cwd, service.url):
  3064	            return True
  3065	        display_name = "Claude Code" if agent == "claude" else "Codex"
  3066	        QMessageBox.warning(
  3067	            window,
  3068	            "Agent Launch Failed",
  3069	            f"Could not open {display_name}. Ensure the agent and a supported "
  3070	            "terminal are installed.",
  3071	        )
  3072	        return False
  3073	
  3074	    def main_window_stylesheet(self):
  3075	        """

 succeeded in 0ms:
     1	"""Tests for the Conductor menu and settings UI."""
     2	
     3	from __future__ import annotations
     4	
     5	import pytest
     6	from AnyQt.QtWidgets import QApplication, QDialog, QMainWindow
     7	from derzug.conductor.constants import DEFAULT_HOST, DEFAULT_PORT
     8	from derzug.views import conductor as conductor_view
     9	from derzug.views.conductor import (
    10	    ConductorMenuController,
    11	    ConductorSettings,
    12	    ConductorSettingsDialog,
    13	    load_conductor_port,
    14	    save_conductor_port,
    15	)
    16	from orangecanvas.utils.settings import QSettings
    17	
    18	URL = "http://127.0.0.1:4319/mcp"
    19	
    20	
    21	@pytest.fixture
    22	def conductor_menu(qtbot):
    23	    """Return a standalone main window and its Conductor menu controller."""
    24	    window = QMainWindow()
    25	    window.help_menu = window.menuBar().addMenu("Help")
    26	    qtbot.addWidget(window)
    27	    controller = ConductorMenuController(window)
    28	    return window, controller
    29	
    30	
    31	def test_conductor_settings_validate_port():
    32	    """Conductor ports must be valid non-boolean TCP port numbers."""
    33	    assert ConductorSettings().port == DEFAULT_PORT
    34	    with pytest.raises(ValueError, match="port must be between"):
    35	        ConductorSettings(port=0)
    36	    with pytest.raises(ValueError, match="port must be between"):
    37	        ConductorSettings(port=True)
    38	
    39	
    40	def test_conductor_port_round_trip_and_invalid_fallback(tmp_path):
    41	    """Only a valid port is persisted; bad stored values use the default."""
    42	    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    43	    save_conductor_port(5432, settings)
    44	    assert load_conductor_port(settings) == 5432
    45	
    46	    settings.beginGroup("conductor")
    47	    settings.setValue("port", "not-a-port")
    48	    settings.endGroup()
    49	    assert load_conductor_port(settings) == DEFAULT_PORT
    50	
    51	
    52	def test_conductor_settings_dialog_exposes_safe_defaults(qtbot):
    53	    """The dialog keeps the host local and returns edited session settings."""
    54	    dialog = ConductorSettingsDialog(ConductorSettings(port=4321, allow_code=False))
    55	    qtbot.addWidget(dialog)
    56	
    57	    assert dialog.host_field.text() == DEFAULT_HOST
    58	    assert dialog.host_field.isReadOnly()
    59	    assert dialog.port_field.value() == 4321
    60	    assert not dialog.allow_code_checkbox.isChecked()
    61	
    62	    dialog.port_field.setValue(5432)
    63	    dialog.allow_code_checkbox.setChecked(True)
    64	    assert dialog.settings() == ConductorSettings(port=5432, allow_code=True)
    65	
    66	
    67	def test_menu_is_inserted_before_help_and_starts_stopped(conductor_menu):
    68	    """The always-visible menu starts with runtime actions disabled."""
    69	    window, controller = conductor_menu
    70	    labels = [action.text().replace("&", "") for action in window.menuBar().actions()]
    71	
    72	    assert labels == ["Conductor", "Help"]
    73	    assert controller.status_action.text() == "Status: Stopped"
    74	    assert controller.start_action.isEnabled()
    75	    assert not controller.stop_action.isEnabled()
    76	    assert not controller.restart_action.isEnabled()
    77	    assert not controller.copy_url_action.isEnabled()
    78	    assert not controller.agent_menu.menuAction().isEnabled()
    79	
    80	
    81	def test_menu_emits_lifecycle_requests_with_current_settings(conductor_menu, qtbot):
    82	    """Start and restart requests carry the currently configured values."""
    83	    _, controller = conductor_menu
    84	    settings = ConductorSettings(port=4321, allow_code=True)
    85	    controller.set_settings(settings)
    86	
    87	    with qtbot.waitSignal(controller.start_requested) as started:
    88	        controller.start_action.trigger()
    89	    assert started.args == [4321, True]
    90	
    91	    controller.set_running(URL, settings)
    92	    with qtbot.waitSignal(controller.restart_requested) as restarted:
    93	        controller.restart_action.trigger()
    94	    assert restarted.args == [4321, True]
    95	
    96	    with qtbot.waitSignal(controller.stop_requested):
    97	        controller.stop_action.trigger()
    98	
    99	
   100	def test_running_state_enables_runtime_actions_and_copies_url(conductor_menu, qtbot):
   101	    """A ready server enables its URL and agent controls."""
   102	    _, controller = conductor_menu
   103	    controller.set_running(URL, controller.settings)
   104	
   105	    assert controller.status_action.text() == f"Status: Running at {URL}"
   106	    assert not controller.start_action.isEnabled()
   107	    assert controller.stop_action.isEnabled()
   108	    assert controller.restart_action.isEnabled()
   109	    assert controller.copy_url_action.isEnabled()
   110	    assert controller.agent_menu.menuAction().isEnabled()
   111	
   112	    controller.copy_url_action.trigger()
   113	    assert QApplication.clipboard().text() == URL
   114	    with qtbot.waitSignal(controller.launch_agent_requested) as launched:
   115	        controller.open_codex_action.trigger()
   116	    assert launched.args == ["codex"]
   117	
   118	    controller.set_stopped()
   119	    assert controller.status_action.text() == "Status: Stopped"
   120	    assert controller.start_action.isEnabled()
   121	
   122	
   123	def test_accepted_settings_mark_running_server_for_restart(
   124	    conductor_menu, monkeypatch, qtbot
   125	):
   126	    """Accepted changes are retained and identify when restart is required."""
   127	    _, controller = conductor_menu
   128	    controller.set_running(URL, controller.settings)
   129	
   130	    class _AcceptedSettingsDialog:
   131	        def __init__(self, settings, parent):
   132	            assert settings == ConductorSettings()
   133	            assert parent is not None
   134	
   135	        def exec(self):
   136	            return QDialog.DialogCode.Accepted
   137	
   138	        def settings(self):
   139	            return ConductorSettings(port=5432, allow_code=True)
   140	
   141	    monkeypatch.setattr(
   142	        conductor_view,
   143	        "ConductorSettingsDialog",
   144	        _AcceptedSettingsDialog,
   145	    )
   146	    with qtbot.waitSignal(controller.port_changed) as changed:
   147	        controller.settings_action.trigger()
   148	
   149	    assert changed.args == [5432]
   150	    assert controller.settings == ConductorSettings(port=5432, allow_code=True)
   151	    assert controller.restart_action.text() == "Restart Server (Apply Settings)"
   152	
   153	
   154	def test_code_permission_is_not_part_of_persisted_settings(tmp_path):
   155	    """The arbitrary-code opt-in must be chosen again in each app session."""
   156	    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
   157	    save_conductor_port(5432, settings)
   158	
   159	    restored = ConductorSettings(port=load_conductor_port(settings))
   160	
   161	    assert restored == ConductorSettings(port=5432, allow_code=False)

exec
/usr/bin/zsh -lc "nl -ba src/derzug/conductor/mcp_server.py | sed -n '180,390p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba tests/test_views/test_orange_qt.py | sed -n '1280,1335p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/conductor/mcp_server.py | sed -n '390,560p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/conductor/launch.py | sed -n '1,180p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'rg -n "def create_new_window" .venv/lib src /home/derrick/mambaforge/envs 2>/dev/null' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/views/orange.py | sed -n '3150,3240p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "rg -n \"def _derzug_settings|_derzug_settings\\(\" src/derzug/views/orange.py tests | head -80" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'rg -n "conductor_enabled|conductor_agent|conductor_allow_code|--conductor|--agent" src/derzug tests/test_cli.py' in /home/derrick/Gits/derzug
 succeeded in 0ms:
 succeeded in 0ms:
tests/test_cli.py:76:            seen["conductor_enabled"] = self.conductor_enabled
tests/test_cli.py:77:            seen["conductor_agent"] = self.conductor_agent
tests/test_cli.py:78:            seen["conductor_allow_code"] = self.conductor_allow_code
tests/test_cli.py:87:        ["--agent", "codex", "--conductor-allow-code"],
tests/test_cli.py:93:        "conductor_enabled": True,
tests/test_cli.py:94:        "conductor_agent": "codex",
tests/test_cli.py:95:        "conductor_allow_code": True,
src/derzug/cli.py:27:        "--conductor",
src/derzug/cli.py:32:        "--agent",
src/derzug/cli.py:35:            "Conductor. Implies --conductor, e.g. derzug --agent claude."
src/derzug/cli.py:38:    conductor_allow_code: bool = typer.Option(
src/derzug/cli.py:40:        "--conductor-allow-code",
src/derzug/cli.py:63:    runner.conductor_enabled = conductor or agent is not None
src/derzug/cli.py:64:    runner.conductor_agent = agent
src/derzug/cli.py:65:    runner.conductor_allow_code = conductor_allow_code
src/derzug/views/orange.py:2781:    conductor_enabled = False
src/derzug/views/orange.py:2782:    conductor_agent: str | None = None
src/derzug/views/orange.py:2783:    conductor_allow_code = False
src/derzug/views/orange.py:2894:        if self.conductor_enabled:
src/derzug/views/orange.py:2900:                agent=self.conductor_agent,
src/derzug/views/orange.py:2917:            allow_code=bool(self.conductor_allow_code),
src/derzug/views/orange.py:2939:            lambda agent: self._launch_conductor_agent(window, agent)
src/derzug/views/orange.py:3003:            self._launch_conductor_agent(window, agent)
src/derzug/views/orange.py:3055:    def _launch_conductor_agent(self, window, agent: str) -> bool:
src/derzug/conductor/controller.py:55:# (``--conductor-allow-code``): a connected agent must not gain arbitrary
src/derzug/conductor/controller.py:188:                "disabled for agents; start DerZug with --conductor-allow-code "
src/derzug/conductor/mcp_server.py:15:the agent surface unless the user opts in with ``--conductor-allow-code``.

 succeeded in 0ms:
src/derzug/views/orange.py:1759:def _derzug_settings() -> QSettings:
src/derzug/views/orange.py:2916:            port=load_conductor_port(_derzug_settings()),
src/derzug/views/orange.py:2942:            lambda port: save_conductor_port(port, _derzug_settings())
src/derzug/views/orange.py:3714:        return _derzug_settings().fileName()
src/derzug/views/orange.py:3719:            settings = _derzug_settings()
src/derzug/views/orange.py:3774:        settings = _derzug_settings()
src/derzug/views/orange.py:3782:        settings = _derzug_settings()
src/derzug/views/orange.py:3789:        settings = _derzug_settings()
src/derzug/views/orange.py:3804:        settings = _derzug_settings()
src/derzug/views/orange.py:3812:        settings = _derzug_settings()
src/derzug/views/orange.py:3819:        settings = _derzug_settings()
tests/test_views/test_orange_qt.py:165:    settings = orange_view._derzug_settings()
tests/test_views/test_orange_qt.py:286:        settings = orange_view._derzug_settings()
tests/test_views/test_orange_qt.py:524:        settings = orange_view._derzug_settings()
tests/test_views/test_orange_qt.py:577:        settings = orange_view._derzug_settings()

 succeeded in 0ms:
  1280	        _select_canvas_nodes(window, spool_node, code_node)
  1281	
  1282	        menu = window._canvas_composite_controller.context_menu_for_node(spool_node)
  1283	        labels = (
  1284	            [action.text() for action in menu.actions()] if menu is not None else []
  1285	        )
  1286	
  1287	        assert "Group" in labels
  1288	        assert "Set Active Source" in labels
  1289	
  1290	    def test_example_workflow_entrypoints_are_derzug_only(self):
  1291	        """Help-menu example workflows should come only from DerZug."""
  1292	        examples = list(DerZugConfig.examples_entry_points())
  1293	        loaded = [(ep.name, ep.group, ep.dist.name.lower()) for ep in examples]
  1294	
  1295	        assert loaded, f"Loaded example workflows: {loaded}"
  1296	        assert all(
  1297	            group == "orange.widgets.tutorials" for _, group, _ in loaded
  1298	        ), loaded
  1299	        assert all(dist == constants.PKG_NAME for _, _, dist in loaded), loaded
  1300	        assert "000-Orange3" not in {name for name, _, _ in loaded}
  1301	
  1302	    def test_create_new_window_allows_missing_notification_server(
  1303	        self, derzug_app, qapp
  1304	    ):
  1305	        """Opening example workflows should not crash without a notification server."""
  1306	        window = derzug_app.window
  1307	        assert window.notification_server is None
  1308	
  1309	        created = window.create_new_window()
  1310	        qapp.processEvents()
  1311	
  1312	        try:
  1313	            assert created is not None
  1314	            assert isinstance(created, orange_view.DerZugMainWindow)
  1315	        finally:
  1316	            created.hide()
  1317	            created.close()
  1318	            created.deleteLater()
  1319	            qapp.processEvents()
  1320	
  1321	    def test_application_icon_loads_from_packaged_asset(self):
  1322	        """DerZug should expose a non-null application icon from static assets."""
  1323	        icon = DerZugConfig.application_icon()
  1324	
  1325	        assert not icon.isNull()
  1326	
  1327	    def test_linux_desktop_file_name_is_set_for_launcher_matching(self, qapp):
  1328	        """Linux launches should advertise the desktop file for dock matching."""
  1329	        original = qapp.desktopFileName() if hasattr(qapp, "desktopFileName") else None
  1330	        try:
  1331	            _configure_linux_desktop_integration(qapp)
  1332	            if sys.platform.startswith("linux") and hasattr(qapp, "desktopFileName"):
  1333	                assert qapp.desktopFileName() == "derzug"
  1334	        finally:
  1335	            if original is not None and hasattr(qapp, "setDesktopFileName"):

 succeeded in 0ms:
     1	"""Launch an agent CLI in a terminal, wired to the Conductor MCP server.
     2	
     3	Pure process/config helpers with no ``mcp`` dependency: build the launch
     4	command for a known agent, and best-effort open it in a new terminal window.
     5	"""
     6	
     7	from __future__ import annotations
     8	
     9	import logging
    10	import shlex
    11	import shutil
    12	import subprocess
    13	import sys
    14	
    15	log = logging.getLogger(__name__)
    16	
    17	#: The MCP server entry name clients see (``.mcp.json`` key / Codex table name).
    18	SERVER_NAME = "derzug-conductor"
    19	
    20	
    21	def agent_command(agent: str, url: str) -> list[str]:
    22	    """Return the command that starts ``agent`` connected to the server at ``url``.
    23	
    24	    ``claude`` needs no arguments: Claude Code picks up the ``.mcp.json`` in the
    25	    launch directory. ``codex`` supports streamable-HTTP MCP servers natively;
    26	    a per-invocation ``-c`` override wires it without touching the user's
    27	    ``~/.codex/config.toml``. Unknown agents are launched bare.
    28	    """
    29	    if agent == "codex":
    30	        return ["codex", "-c", f'mcp_servers.{SERVER_NAME}.url="{url}"']
    31	    return [agent]
    32	
    33	
    34	def _open_in_terminal(command: list[str], cwd: str) -> bool:
    35	    """Best-effort: open a new terminal window running ``command`` in ``cwd``."""
    36	    joined = " ".join(shlex.quote(part) for part in command)
    37	
    38	    def _spawn(argv: list[str], spawn_cwd: str | None = None) -> bool:
    39	        try:
    40	            subprocess.Popen(argv, cwd=spawn_cwd)
    41	            return True
    42	        except Exception:
    43	            log.error("Failed to launch terminal: %s", argv, exc_info=True)
    44	            return False
    45	
    46	    if sys.platform == "darwin":
    47	        script = (
    48	            f'tell application "Terminal" to do script '
    49	            f'"cd {shlex.quote(cwd)} && exec {joined}"'
    50	        )
    51	        return _spawn(["osascript", "-e", script])
    52	    if sys.platform == "win32":
    53	        if shutil.which("wt"):
    54	            return _spawn(["wt", "-d", cwd, *command])
    55	        return _spawn(["cmd", "/c", "start", "", "cmd", "/k", joined], spawn_cwd=cwd)
    56	    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
    57	        exe = shutil.which(term)
    58	        if exe is None:
    59	            continue
    60	        if term == "gnome-terminal":
    61	            return _spawn([exe, "--working-directory", cwd, "--", *command])
    62	        # xterm/konsole-style launchers take the executable and each argument
    63	        # separately after ``-e``. Passing one shell-joined string makes a
    64	        # multi-argument command (notably Codex's ``-c`` override) look like a
    65	        # single nonexistent executable.
    66	        return _spawn([exe, "-e", *command], spawn_cwd=cwd)
    67	    log.error("No terminal emulator found; run '%s' in %s yourself", joined, cwd)
    68	    return False
    69	
    70	
    71	def launch_agent_in_terminal(agent: str, cwd: str, url: str) -> bool:
    72	    """Launch ``agent`` in a new terminal in ``cwd``, wired to the server at ``url``."""
    73	    command = agent_command(agent, url)
    74	    if shutil.which(command[0]) is None:
    75	        log.error("Agent %r not found on PATH; run it yourself in %s", agent, cwd)
    76	        return False
    77	    return _open_in_terminal(command, cwd)

 succeeded in 0ms:
  3150	class DerZugMainWindow(OrangeMainWindow):
  3151	    """Orange main window customized for DerZug."""
  3152	
  3153	    def set_notification_server(self, notif_server):
  3154	        """Accept a missing notification server when creating secondary windows."""
  3155	        self.notification_server = notif_server
  3156	        if notif_server is None:
  3157	            return
  3158	        super().set_notification_server(notif_server)
  3159	
  3160	    def __init__(self, *args, **kwargs):
  3161	        """Initialize the DerZug main window."""
  3162	        ensure_canvas_patches_installed()
  3163	        register_app_shell_service(_APP_SHELL_SERVICE)
  3164	        super().__init__(*args, **kwargs)
  3165	        self.setWindowTitle("DerZug")
  3166	        self.set_float_widgets_on_top_enabled(False)
  3167	        self.active_source_manager: ActiveSourceManager | None = None
  3168	        self.dev_mode = False
  3169	        self.startup_demo_mode = False
  3170	        self.startup_workflow_path: str | None = None
  3171	        self.startup_open_widget_ids: list[int] = []
  3172	        self.conductor_controls = None
  3173	        self.dev_menu: QMenu | None = None
  3174	        self.hot_reload_action: QAction | None = None
  3175	        self.edit_config_file_action: QAction | None = None
  3176	        self.annotation_settings_action: QAction | None = None
  3177	        self._hot_reload_in_progress = False
  3178	        self._startup_warning_shown = False
  3179	        self._canvas_composite_controller = _CanvasCompositeController(self)
  3180	        self._canvas_traceback_filter = _CanvasTracebackIconFilter(self)
  3181	        self._canvas_middle_button_pan_filter = _CanvasMiddleButtonPanFilter(self)
  3182	        self._canvas_arrow_palette_controller: (
  3183	            _CanvasArrowColorPaletteController | None
  3184	        ) = None
  3185	        self._canvas_text_palette_controller: (
  3186	            _CanvasTextStylePaletteController | None
  3187	        ) = None
  3188	        self._apply_default_help_visibility()
  3189	        self._customize_shell()
  3190	        self._install_canvas_traceback_filter()
  3191	        self._install_canvas_middle_button_pan_filter()
  3192	        self._install_canvas_reset_view_handler()
  3193	        document = self.current_document()
  3194	        if document is not None:
  3195	            _install_canvas_clipboard_actions(document)
  3196	            self._canvas_arrow_palette_controller = _CanvasArrowColorPaletteController(
  3197	                self
  3198	            )
  3199	            self._canvas_text_palette_controller = _CanvasTextStylePaletteController(
  3200	                self
  3201	            )
  3202	
  3203	    def _apply_default_help_visibility(self) -> None:
  3204	        """Default quick-help pane to hidden unless user has saved a preference."""
  3205	        settings = QSettings()
  3206	        settings.beginGroup("mainwindow")
  3207	        has_saved_visibility = settings.contains("quick-help/visible")
  3208	        settings.endGroup()
  3209	        if has_saved_visibility:
  3210	            return
  3211	
  3212	        self.canvas_tool_dock.setQuickHelpVisible(False)
  3213	        if getattr(self, "dock_help_action", None) is not None:
  3214	            self.dock_help_action.setChecked(False)
  3215	
  3216	    def _customize_shell(self) -> None:
  3217	        """Trim inherited Orange shell actions down to the DerZug UX."""
  3218	        self._customize_help_menu()
  3219	        self._remove_toolbar_help_action()
  3220	        self._prune_menu_actions("File", {"Open Report..."})
  3221	        self._prune_menu_actions("View", {"Window Groups", "Show report"})
  3222	        self._prune_menu_actions(
  3223	            "Options",
  3224	            {"Add-ons...", "Reset Widget Settings..."},
  3225	        )
  3226	        self._install_annotation_settings_action()
  3227	
  3228	    def _remove_toolbar_help_action(self) -> None:
  3229	        """Remove the quick-help toggle from the canvas toolbar."""
  3230	        action = getattr(self, "dock_help_action", None)
  3231	        toolbar = getattr(self, "canvas_toolbar", None)
  3232	        if action is None or toolbar is None:
  3233	            return
  3234	        toolbar.removeAction(action)
  3235	
  3236	    def _customize_help_menu(self) -> None:
  3237	        """Keep only the DerZug-relevant help actions."""
  3238	        help_menu = getattr(self, "help_menu", None)
  3239	        if help_menu is None:
  3240	            return

 succeeded in 0ms:
   180	        while True:
   181	            busy = call(controller.busy_nodes)
   182	            if not busy:
   183	                return {"idle": True, "busy_nodes": []}
   184	            if time.monotonic() > deadline:
   185	                return {"idle": False, "busy_nodes": busy}
   186	            time.sleep(0.1)
   187	
   188	    @mcp.tool()
   189	    def show_node(node_id: str, x: float | None = None, y: float | None = None) -> None:
   190	        """Pop up a node's widget window (show/raise/focus), optionally at (x, y)."""
   191	        call(controller.show_node, node_id, x=x, y=y)
   192	
   193	    @mcp.tool()
   194	    def move_node_window(node_id: str, x: float, y: float) -> None:
   195	        """Move a node's widget window to screen coordinates (x, y)."""
   196	        call(controller.move_node_window, node_id, x, y)
   197	
   198	    @mcp.tool()
   199	    def hide_node(node_id: str) -> None:
   200	        """Hide (close) a node's widget window."""
   201	        call(controller.hide_node, node_id)
   202	
   203	    return mcp
   204	
   205	
   206	class ConductorService:
   207	    """Owns the Conductor MCP server lifecycle: bind, serve, readiness, stop.
   208	
   209	    ``start`` pre-binds the listening socket on the calling thread — a port
   210	    conflict raises immediately instead of dying silently inside a worker —
   211	    then serves the streamable-http app on a background uvicorn server and
   212	    blocks until it reports ready (or raises on startup failure). ``stop``
   213	    halts the dispatcher (releasing any in-flight marshalled calls), signals
   214	    uvicorn to exit, and joins the thread.
   215	    """
   216	
   217	    def __init__(
   218	        self,
   219	        mcp: FastMCP,
   220	        *,
   221	        host: str = DEFAULT_HOST,
   222	        port: int = DEFAULT_PORT,
   223	        dispatcher: MainThreadDispatcher | None = None,
   224	    ) -> None:
   225	        self._mcp = mcp
   226	        self._host = host
   227	        self._port = port
   228	        self._dispatcher = dispatcher
   229	        self._server: Any | None = None
   230	        self._thread: threading.Thread | None = None
   231	
   232	    @property
   233	    def host(self) -> str:
   234	        """The interface the server binds (loopback by default)."""
   235	        return self._host
   236	
   237	    @property
   238	    def port(self) -> int:
   239	        """The bound port (resolved after ``start`` when constructed with 0)."""
   240	        return self._port
   241	
   242	    @property
   243	    def url(self) -> str:
   244	        """The server's MCP endpoint URL."""
   245	        return f"http://{self._host}:{self._port}/mcp"
   246	
   247	    def start(self, timeout: float = 15.0) -> str:
   248	        """Bind, serve in a background thread, and wait for readiness; return URL.
   249	
   250	        Raises ``OSError`` when the port is already taken and ``RuntimeError``
   251	        when the server exits or is not ready within ``timeout`` seconds.
   252	        """
   253	        import uvicorn
   254	
   255	        sock = socket.create_server((self._host, self._port))
   256	        try:
   257	            self._port = sock.getsockname()[1]  # resolves an ephemeral port (0)
   258	            config = uvicorn.Config(
   259	                self._mcp.streamable_http_app(),
   260	                host=self._host,
   261	                port=self._port,
   262	                log_level="warning",
   263	            )
   264	            self._server = uvicorn.Server(config)
   265	            self._thread = threading.Thread(
   266	                target=self._server.run,
   267	                kwargs={"sockets": [sock]},
   268	                name="conductor-mcp",
   269	                daemon=True,
   270	            )
   271	            self._thread.start()
   272	            deadline = time.monotonic() + timeout
   273	            while not self._server.started:
   274	                if not self._thread.is_alive():
   275	                    raise RuntimeError("Conductor MCP server exited during startup")
   276	                if time.monotonic() > deadline:
   277	                    raise RuntimeError(
   278	                        f"Conductor MCP server not ready after {timeout:.0f}s"
   279	                    )
   280	                time.sleep(0.05)
   281	        except BaseException:
   282	            self.stop()
   283	            sock.close()
   284	            raise
   285	        log.info("Conductor MCP server ready at %s", self.url)
   286	        return self.url
   287	
   288	    def stop(self, timeout: float = 5.0) -> None:
   289	        """Shut down: stop the dispatcher, signal uvicorn to exit, join the thread."""
   290	        if self._dispatcher is not None:
   291	            self._dispatcher.stop()
   292	        if self._server is not None:
   293	            self._server.should_exit = True
   294	        if self._thread is not None and self._thread.is_alive():
   295	            self._thread.join(timeout)
   296	            if self._thread.is_alive():
   297	                log.warning("Conductor MCP server thread did not stop cleanly")
   298	        self._server = None
   299	        self._thread = None
   300	
   301	
   302	def write_mcp_config(
   303	    path: str | Path,
   304	    *,
   305	    host: str = DEFAULT_HOST,
   306	    port: int = DEFAULT_PORT,
   307	    name: str = SERVER_NAME,
   308	) -> str:
   309	    """Merge our server entry into the MCP client config at ``path``; return URL.
   310	
   311	    The file is an ``.mcp.json`` a client such as Claude Code picks up. An
   312	    existing config keeps its other entries — only ``mcpServers[name]`` is
   313	    replaced — and the file is written atomically (temp file + rename). An
   314	    existing file that is not valid JSON is left untouched (logged), so a
   315	    user's hand-edited config is never clobbered.
   316	    """
   317	    url = f"http://{host}:{port}/mcp"
   318	    path = Path(path)
   319	    config: dict[str, Any] = {}
   320	    if path.exists():
   321	        try:
   322	            config = json.loads(path.read_text())
   323	        except ValueError:
   324	            log.error(
   325	                "Existing %s is not valid JSON; leaving it untouched. "
   326	                "Add the server yourself: %s",
   327	                path,
   328	                url,
   329	            )
   330	            return url
   331	        if not isinstance(config, dict):
   332	            config = {}
   333	    servers = config.setdefault("mcpServers", {})
   334	    servers[name] = {"type": "http", "url": url}
   335	    tmp = path.with_name(path.name + ".tmp")
   336	    tmp.write_text(json.dumps(config, indent=2))
   337	    os.replace(tmp, path)
   338	    return url
   339	
   340	
   341	def start_conductor(
   342	    window: Any,
   343	    *,
   344	    host: str = DEFAULT_HOST,
   345	    port: int = DEFAULT_PORT,
   346	    config_path: str | Path | None = None,
   347	    agent: str | None = None,
   348	    allow_code: bool = False,
   349	) -> ConductorService:
   350	    """Wire and start the in-app Conductor MCP server for ``window``.
   351	
   352	    Builds a ``CanvasController`` + ``MainThreadDispatcher``, starts a
   353	    ``ConductorService`` and waits for readiness (raising on bind/startup
   354	    failure). Only after the server is ready is the client config written and,
   355	    when ``agent`` is given (e.g. ``"claude"`` / ``"codex"``), the agent
   356	    launched in a new terminal in the config directory. The caller owns the
   357	    returned service and should ``stop()`` it on application teardown.
   358	    """
   359	    controller = CanvasController(window, allow_code=allow_code)
   360	    dispatcher = MainThreadDispatcher()
   361	    mcp = build_conductor_mcp(controller, dispatcher)
   362	    service = ConductorService(mcp, host=host, port=port, dispatcher=dispatcher)
   363	    try:
   364	        url = service.start()
   365	        cwd = os.getcwd()
   366	        if config_path is not None:
   367	            write_mcp_config(config_path, host=service.host, port=service.port)
   368	            cwd = str(Path(config_path).resolve().parent)
   369	            log.info("Conductor client config written to %s", config_path)
   370	        if agent:
   371	            launch_agent_in_terminal(agent, cwd, url)
   372	    except BaseException:
   373	        service.stop()
   374	        raise
   375	    return service

exec
/usr/bin/zsh -lc "nl -ba /home/derrick/mambaforge/envs/derzug/lib/python3.14/site-packages/Orange/canvas/mainwindow.py | sed -n '105,165p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba /home/derrick/mambaforge/envs/daszug/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py | sed -n '1010,1075p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba tests/test_views/test_orange_qt.py | sed -n '130,320p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'git diff --name-only' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "rg -n \"ConductorService|start_conductor|stop\\(|launch_agent|write_mcp_config|agent_command\" tests src/derzug/conductor | head -240" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'rg -n "pytest|testpaths|addopts|ruff|coverage" pyproject.toml tox.ini setup.cfg .github 2>/dev/null | head -200' in /home/derrick/Gits/derzug
 succeeded in 0ms:
   105	        self.notification_overlay = NotificationOverlay(self.scheme_widget)
   106	        self.notification_server = None
   107	        self.scheme_widget.setDropHandlers([
   108	            PluginDropHandler("orange.canvas.drophandler")
   109	        ])
   110	
   111	    def open_canvas_settings(self):
   112	        # type: () -> None
   113	        """Reimplemented."""
   114	        dlg = OUserSettingsDialog(self, windowTitle=self.tr(_tr.m[39, "Preferences"]))
   115	        dlg.show()
   116	        status = dlg.exec()
   117	        if status == 0:
   118	            self.user_preferences_changed_notify_all()
   119	
   120	    def set_notification_server(self, notif_server):
   121	        self.notification_server = notif_server
   122	
   123	        # populate notification overlay with current notifications
   124	        for notif in self.notification_server.getNotificationQueue():
   125	            self.notification_overlay.addNotification(notif)
   126	
   127	        notif_server.newNotification.connect(self.notification_overlay.addNotification)
   128	        notif_server.nextNotification.connect(self.notification_overlay.nextWidget)
   129	
   130	    def create_new_window(self):  # type: () -> CanvasMainWindow
   131	        window = super().create_new_window()
   132	        window.set_notification_server(self.notification_server)
   133	        return window

 succeeded in 0ms:
docs/dev/conductor.md
docs/dev/plans/conductor_terminal_pane.md
src/derzug/conductor/mcp_server.py
src/derzug/views/orange.py
tests/test_cli.py
tests/test_views/test_orange_qt.py

 succeeded in 0ms:
pyproject.toml:122:    "coverage>=7.4,<8",
pyproject.toml:125:    "pytest-cov>=4",
pyproject.toml:127:    "pytest",
pyproject.toml:128:    "pytest-qt",
pyproject.toml:153:[tool.ruff]
pyproject.toml:184:    ".ruff_cache",
pyproject.toml:206:[tool.ruff.lint.mccabe]
pyproject.toml:211:[tool.ruff.lint.pydocstyle]
pyproject.toml:214:[tool.pytest.ini_options]
pyproject.toml:222:[tool.ruff.format]
.github/test_code.sh:14:python -m pytest $args || exit_code=$?
.github/workflows/runtests.yml:74:      # Runs test suite and calculates coverage
.github/workflows/runtests.yml:83:        run: python -m pytest tests -s --cov derzug --cov-append --cov-report=xml
.github/workflows/runtests.yml:90:#      # Upload coverage files
.github/workflows/runtests.yml:94:#          files: ./coverage.xml

 succeeded in 0ms:
   130	def _select_test_spool() -> dc.BaseSpool:
   131	    """Return a spool with predictable metadata for Select round-trip tests."""
   132	    return dc.spool(
   133	        [
   134	            _patch_with_attrs(tag="bob", station="alpha"),
   135	            _patch_with_attrs(tag="bob", station="beta"),
   136	            _patch_with_attrs(tag="alice", station="beta"),
   137	        ]
   138	    )
   139	
   140	
   141	def _select_canvas_nodes(window, *nodes) -> None:
   142	    """Select the given workflow nodes in the live canvas scene."""
   143	    scene = window.current_document().scene()
   144	    scene.clearSelection()
   145	    for node in nodes:
   146	        scene.item_for_node(node).setSelected(True)
   147	
   148	
   149	def _menu_labels(window, menu_name: str) -> list[str]:
   150	    """Return visible non-separator labels from one top-level menu."""
   151	    menu = next(
   152	        action.menu()
   153	        for action in window.menuBar().actions()
   154	        if action.text().replace("&", "") == menu_name
   155	    )
   156	    return [
   157	        action.text().replace("&", "")
   158	        for action in menu.actions()
   159	        if action.isVisible() and not action.isSeparator()
   160	    ]
   161	
   162	
   163	def _clear_code_warning_setting() -> None:
   164	    """Reset the persisted code-workflow warning preference for one test."""
   165	    settings = orange_view._derzug_settings()
   166	    settings.beginGroup("load")
   167	    settings.remove("hide-code-widget-warning")
   168	    settings.endGroup()
   169	
   170	
   171	def _dispatch_mouse_event(
   172	    widget,
   173	    event_type: QEvent.Type,
   174	    pos: QPoint,
   175	    *,
   176	    button: Qt.MouseButton,
   177	    buttons: Qt.MouseButton,
   178	) -> None:
   179	    """Send one mouse event directly to a widget."""
   180	    event = QMouseEvent(
   181	        event_type,
   182	        QPointF(pos),
   183	        QPointF(widget.mapToGlobal(pos)),
   184	        button,
   185	        buttons,
   186	        Qt.NoModifier,
   187	    )
   188	    QApplication.sendEvent(widget, event)
   189	
   190	
   191	def _visible_scene_rect(view) -> QRectF:
   192	    """Return the current viewport coverage mapped into scene coordinates."""
   193	    return view.mapToScene(view.viewport().rect()).boundingRect()
   194	
   195	
   196	class _SipModuleWrongWrapper:
   197	    """Stub SIP module that rejects one wrapper family."""
   198	
   199	    @staticmethod
   200	    def isdeleted(obj):
   201	        raise TypeError(
   202	            "isdeleted() argument 1 must be PyQt6.sip.simplewrapper, "
   203	            f"not {type(obj).__name__}"
   204	        )
   205	
   206	
   207	class _SipModuleAlive:
   208	    """Stub SIP module that accepts the wrapper and reports it alive."""
   209	
   210	    @staticmethod
   211	    def isdeleted(obj):
   212	        return False
   213	
   214	
   215	class _SipModuleDeleted:
   216	    """Stub SIP module that accepts the wrapper and reports it deleted."""
   217	
   218	    @staticmethod
   219	    def isdeleted(obj):
   220	        return True
   221	
   222	
   223	@contextmanager
   224	def _fresh_derzug_window(qapp, tmp_path):
   225	    """Yield a freshly constructed DerZug main window for cold-reopen tests."""
   226	    main = DerZugMain()
   227	    old_cache_home = os.environ.get("XDG_CACHE_HOME")
   228	    old_data_home = os.environ.get("XDG_DATA_HOME")
   229	    cache_home = tmp_path / "fresh-cache"
   230	    data_home = tmp_path / "fresh-data"
   231	    cache_home.mkdir(parents=True, exist_ok=True)
   232	    data_home.mkdir(parents=True, exist_ok=True)
   233	    os.environ["XDG_CACHE_HOME"] = str(cache_home)
   234	    os.environ["XDG_DATA_HOME"] = str(data_home)
   235	    main.parse_arguments(
   236	        [sys.argv[0], "--no-splash", "--no-welcome", "--force-discovery"]
   237	    )
   238	    main.activate_default_config()
   239	    main.application = qapp
   240	    main.output = TerminalTextDocument()
   241	    main.registry = main.run_discovery()
   242	    window = main.setup_main_window()
   243	    qapp.processEvents()
   244	    try:
   245	        yield window
   246	    finally:
   247	        window.hide()
   248	        window.deleteLater()
   249	        qapp.processEvents()
   250	        QCoreApplication.sendPostedEvents()
   251	        if old_cache_home is None:
   252	            os.environ.pop("XDG_CACHE_HOME", None)
   253	        else:
   254	            os.environ["XDG_CACHE_HOME"] = old_cache_home
   255	        if old_data_home is None:
   256	            os.environ.pop("XDG_DATA_HOME", None)
   257	        else:
   258	            os.environ["XDG_DATA_HOME"] = old_data_home
   259	
   260	
   261	@pytest.fixture
   262	def orange_workflow(derzug_app, qapp):
   263	    """Return a helper for building workflows in the DerZug main window."""
   264	    window = derzug_app.window
   265	    registry = derzug_app.main.registry
   266	
   267	    def _build(widgets, links=(), *, clear=True):
   268	        return build_window_workflow(
   269	            window,
   270	            registry,
   271	            widgets,
   272	            links,
   273	            qapp=qapp,
   274	            clear=clear,
   275	        )
   276	
   277	    return _build
   278	
   279	
   280	class TestDerZugMainWindow:
   281	    """Simple checks for DerZug Orange startup wiring."""
   282	
   283	    @staticmethod
   284	    def _clear_startup_warning_setting() -> None:
   285	        """Reset the persisted startup warning preference for one test."""
   286	        settings = orange_view._derzug_settings()
   287	        settings.beginGroup("startup")
   288	        settings.remove("hide-experimental-warning")
   289	        settings.endGroup()
   290	
   291	    @staticmethod
   292	    def _clear_annotation_settings() -> None:
   293	        """Reset persisted annotation preferences for one test."""
   294	        clear_annotation_config_cache()
   295	        save_annotation_config(AnnotationConfig())
   296	
   297	    def test_annotation_settings_load_uses_cache_until_save(
   298	        self, derzug_app, monkeypatch
   299	    ):
   300	        """Repeated default loads should reuse the cached config until a save."""
   301	        self._clear_annotation_settings()
   302	        calls: list[str] = []
   303	        original_reader = orange_view.load_annotation_config.__globals__[
   304	            "_read_annotation_config"
   305	        ]
   306	
   307	        def _wrapped_reader(settings):
   308	            calls.append("read")
   309	            return original_reader(settings)
   310	
   311	        monkeypatch.setitem(
   312	            orange_view.load_annotation_config.__globals__,
   313	            "_read_annotation_config",
   314	            _wrapped_reader,
   315	        )
   316	
   317	        first = orange_view.load_annotation_config(force_reload=True)
   318	        second = orange_view.load_annotation_config()
   319	        save_annotation_config(AnnotationConfig(annotator="alice"))
   320	        third = orange_view.load_annotation_config()

 succeeded in 0ms:
src/derzug/conductor/__init__.py:9:``mcp`` extra) and is owned by a ``ConductorService``.
src/derzug/conductor/mcp_server.py:8:``ConductorService`` owns the server lifecycle: it pre-binds the port (so a
src/derzug/conductor/mcp_server.py:38:from derzug.conductor.launch import SERVER_NAME, launch_agent_in_terminal
src/derzug/conductor/mcp_server.py:206:class ConductorService:
src/derzug/conductor/mcp_server.py:282:            self.stop()
src/derzug/conductor/mcp_server.py:288:    def stop(self, timeout: float = 5.0) -> None:
src/derzug/conductor/mcp_server.py:291:            self._dispatcher.stop()
src/derzug/conductor/mcp_server.py:302:def write_mcp_config(
src/derzug/conductor/mcp_server.py:341:def start_conductor(
src/derzug/conductor/mcp_server.py:349:) -> ConductorService:
src/derzug/conductor/mcp_server.py:353:    ``ConductorService`` and waits for readiness (raising on bind/startup
src/derzug/conductor/mcp_server.py:357:    returned service and should ``stop()`` it on application teardown.
src/derzug/conductor/mcp_server.py:362:    service = ConductorService(mcp, host=host, port=port, dispatcher=dispatcher)
src/derzug/conductor/mcp_server.py:367:            write_mcp_config(config_path, host=service.host, port=service.port)
src/derzug/conductor/mcp_server.py:371:            launch_agent_in_terminal(agent, cwd, url)
src/derzug/conductor/mcp_server.py:373:        service.stop()
src/derzug/conductor/launch.py:21:def agent_command(agent: str, url: str) -> list[str]:
src/derzug/conductor/launch.py:71:def launch_agent_in_terminal(agent: str, cwd: str, url: str) -> bool:
src/derzug/conductor/launch.py:73:    command = agent_command(agent, url)
src/derzug/conductor/dispatch.py:25:#: Poll interval while waiting on the main thread; keeps stop() responsive.
src/derzug/conductor/dispatch.py:48:    def stop(self) -> None:
tests/test_conductor/test_end_to_end.py:78:    from derzug.conductor.mcp_server import ConductorService, build_conductor_mcp
tests/test_conductor/test_end_to_end.py:83:    service = ConductorService(
tests/test_conductor/test_end_to_end.py:124:        service.stop()
tests/test_conductor/test_mcp_server.py:15:    start_conductor,
tests/test_conductor/test_mcp_server.py:16:    write_mcp_config,
tests/test_conductor/test_mcp_server.py:62:def test_write_mcp_config(tmp_path):
tests/test_conductor/test_mcp_server.py:65:    url = write_mcp_config(path, port=4321)
tests/test_conductor/test_mcp_server.py:72:def test_write_mcp_config_merges_existing_entries(tmp_path):
tests/test_conductor/test_mcp_server.py:85:    url = write_mcp_config(path, port=4321)
tests/test_conductor/test_mcp_server.py:91:def test_write_mcp_config_leaves_invalid_json_untouched(tmp_path):
tests/test_conductor/test_mcp_server.py:95:    write_mcp_config(path, port=4321)
tests/test_conductor/test_mcp_server.py:103:    from derzug.conductor.mcp_server import ConductorService
tests/test_conductor/test_mcp_server.py:109:        service = ConductorService(mcp, port=taken_port)
tests/test_conductor/test_mcp_server.py:114:def test_service_start_ready_and_stop(blank_canvas):
tests/test_conductor/test_mcp_server.py:116:    from derzug.conductor.mcp_server import ConductorService
tests/test_conductor/test_mcp_server.py:120:    service = ConductorService(mcp, port=0)
tests/test_conductor/test_mcp_server.py:126:        service.stop()
tests/test_conductor/test_mcp_server.py:130:def test_start_conductor_stops_service_when_config_write_fails(
tests/test_conductor/test_mcp_server.py:134:    from derzug.conductor.mcp_server import ConductorService
tests/test_conductor/test_mcp_server.py:137:    stopped: list[ConductorService] = []
tests/test_conductor/test_mcp_server.py:138:    original_stop = ConductorService.stop
tests/test_conductor/test_mcp_server.py:140:    def track_stop(self, timeout=5.0):
tests/test_conductor/test_mcp_server.py:142:        original_stop(self, timeout)
tests/test_conductor/test_mcp_server.py:147:    monkeypatch.setattr(ConductorService, "stop", track_stop)
tests/test_conductor/test_mcp_server.py:148:    monkeypatch.setattr("derzug.conductor.mcp_server.write_mcp_config", fail_write)
tests/test_conductor/test_mcp_server.py:151:        start_conductor(window, port=0, config_path=tmp_path / ".mcp.json")
tests/test_conductor/test_launch.py:7:    agent_command,
tests/test_conductor/test_launch.py:8:    launch_agent_in_terminal,
tests/test_conductor/test_launch.py:16:    assert agent_command("claude", URL) == ["claude"]
tests/test_conductor/test_launch.py:23:    command = agent_command("codex", URL)
tests/test_conductor/test_launch.py:31:def test_launch_agent_missing_binary_is_safe(tmp_path):
tests/test_conductor/test_launch.py:33:    assert launch_agent_in_terminal("no-such-agent-xyz", str(tmp_path), URL) is False
tests/test_conductor/test_launch.py:39:    command = agent_command("codex", URL)
tests/test_conductor/test_dispatch.py:63:def test_run_refuses_new_calls_after_stop(qapp):
tests/test_conductor/test_dispatch.py:66:    dispatcher.stop()
tests/test_conductor/test_dispatch.py:72:        raise AssertionError("expected RuntimeError after stop()")
tests/test_conductor/test_dispatch.py:111:    """stop() unblocks a worker already waiting on the main thread."""
tests/test_conductor/test_dispatch.py:125:    dispatcher.stop()
tests/test_views/test_conductor.py:114:    with qtbot.waitSignal(controller.launch_agent_requested) as launched:
tests/test_views/test_orange_qt.py:395:            def stop(self):
tests/test_views/test_orange_qt.py:407:        mcp_server.start_conductor = _fake_start
tests/test_views/test_orange_qt.py:410:            "derzug.conductor.launch.launch_agent_in_terminal",
tests/test_views/test_orange_qt.py:461:        mcp_server.start_conductor = _fail_start
tests/test_widgets/test_playaudio.py:93:    def stop(self) -> None:

 succeeded in 0ms:
  1010	        """
  1011	        enabled = self.__scheme_margins_enabled
  1012	        self.__dummy_top_toolbar.setVisible(enabled)
  1013	        self.__dummy_bottom_toolbar.setVisible(enabled)
  1014	        central = self.centralWidget()
  1015	
  1016	        margin = 20 if enabled else 0
  1017	
  1018	        if self.dockWidgetArea(self.dock_widget) == Qt.LeftDockWidgetArea:
  1019	            margins = (margin // 2, 0, margin, 0)
  1020	        else:
  1021	            margins = (margin, 0, margin // 2, 0)
  1022	
  1023	        central.layout().setContentsMargins(*margins)
  1024	
  1025	    def is_transient(self):
  1026	        # type: () -> bool
  1027	        """
  1028	        Is this window a transient window.
  1029	
  1030	        I.e. a window that was created empty and does not contain any modified
  1031	        contents. In particular it can be reused to load a workflow model
  1032	        without any detrimental effects (like lost information).
  1033	        """
  1034	        return self.__is_transient
  1035	
  1036	    # All instances created through the create_new_window below.
  1037	    # They are removed on `destroyed`
  1038	    _instances = []  # type: List[CanvasMainWindow]
  1039	
  1040	    def create_new_window(self):
  1041	        # type: () -> CanvasMainWindow
  1042	        """
  1043	        Create a new top level CanvasMainWindow instance.
  1044	
  1045	        The window is positioned slightly offset to the originating window
  1046	        (`self`).
  1047	
  1048	        Note
  1049	        ----
  1050	        The window has `Qt.WA_DeleteOnClose` flag set. If this flag is unset
  1051	        it is the callers responsibility to explicitly delete the widget (via
  1052	        `deleteLater` or `sip.delete`).
  1053	
  1054	        Returns
  1055	        -------
  1056	        window: CanvasMainWindow
  1057	        """
  1058	        window = type(self)()  # 'preserve' subclass type
  1059	        window.setAttribute(Qt.WA_DeleteOnClose)
  1060	        window.setGeometry(self.geometry().translated(20, 20))
  1061	        window.setStyleSheet(self.styleSheet())
  1062	        window.setWindowIcon(self.windowIcon())
  1063	        if self.widget_registry is not None:
  1064	            window.set_widget_registry(self.widget_registry)
  1065	        window.restoreState(self.saveState(self.SETTINGS_VERSION),
  1066	                            self.SETTINGS_VERSION)
  1067	        window.set_tool_dock_expanded(self.dock_widget.expanded())
  1068	        window.set_float_widgets_on_top_enabled(self.float_widgets_on_top_action.isChecked())
  1069	
  1070	        output = window.output_view()  # type: OutputView
  1071	        doc = self.output_view().document()
  1072	        doc = doc.clone(output)
  1073	        output.setDocument(doc)
  1074	
  1075	        def is_connected(stream: TextStream) -> bool:

codex
I’ve confirmed one concrete multi-window failure from the construction path: secondary `DerZugMainWindow` instances are created directly and never pass through the application’s menu installer, so their `conductor_controls` remains `None`. I’m doing a targeted test run and checking the failure paths next, especially stop/restart behavior and deleted-window parents.
exec
/usr/bin/zsh -lc 'pytest -q tests/test_views/test_conductor.py tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_conductor_menu_is_always_available tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_conductor_menu_controls_service_lifecycle tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_conductor_start_failure_returns_menu_to_stopped tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_create_new_window_allows_missing_notification_server -p no:cacheprovider' in /home/derrick/Gits/derzug
 exited 127 in 0ms:
zsh:1: command not found: pytest

 succeeded in 85321ms:
/home/derrick/mambaforge/envs/derzug/lib/python3.14/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/daszug/lib/python3.14/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/daszug/lib/python3.14/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/daszug/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/derzug/lib/python3.14/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/derzug/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/orange/lib/python3.14/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/orange/lib/python3.14/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/orange/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/tt/lib/python3.14/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/tt/lib/python3.14/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/tt/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/orange313/lib/python3.13/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/orange313/lib/python3.13/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/orange313/lib/python3.13/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/derzug3/lib/python3.14/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/derzug3/lib/python3.14/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/derzug3/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/dasview/lib/python3.14/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/dasview/lib/python3.14/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/dasview/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/derzug2/lib/python3.14/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/derzug2/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):
/home/derrick/mambaforge/envs/derzug2/lib/python3.14/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/test_derzug/lib/python3.13/site-packages/Orange/canvas/mainwindow.py:130:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/test_derzug/lib/python3.13/site-packages/orangecanvas/application/tests/test_mainwindow.py:27:    def create_new_window(self):  # type: () -> CanvasMainWindow
/home/derrick/mambaforge/envs/test_derzug/lib/python3.13/site-packages/orangecanvas/application/canvasmain.py:1040:    def create_new_window(self):

exec
/usr/bin/zsh -lc 'ls -l /home/derrick/mambaforge/envs/derzug/bin/pytest' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'command -v python' in /home/derrick/Gits/derzug
 exited 1 in 0ms:
exec
/usr/bin/zsh -lc 'command -v uv' in /home/derrick/Gits/derzug
 succeeded in 0ms:
/home/derrick/.local/bin/uv

 succeeded in 0ms:
-rwxrwxr-x 1 derrick derrick 204 Mar  9 12:42 /home/derrick/mambaforge/envs/derzug/bin/pytest

exec
/usr/bin/zsh -lc '/home/derrick/mambaforge/envs/derzug/bin/pytest -q tests/test_views/test_conductor.py tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_conductor_menu_is_always_available tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_conductor_menu_controls_service_lifecycle tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_conductor_start_failure_returns_menu_to_stopped tests/test_views/test_orange_qt.py::TestDerZugMainWindow::test_create_new_window_allows_missing_notification_server -p no:cacheprovider' in /home/derrick/Gits/derzug
 succeeded in 6039ms:
............                                                             [100%]
12 passed in 2.37s

exec
/usr/bin/zsh -lc "nl -ba src/derzug/views/orange.py | sed -n '1735,1775p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/views/orange.py | sed -n '1,180p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba /home/derrick/mambaforge/envs/daszug/lib/python3.14/site-packages/orangecanvas/application/canvasmain.py | sed -n '1055,1125p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "rg -n \"def _qt_object_is_deleted\" src/derzug/views/orange.py && nl -ba src/derzug/views/orange.py | sed -n '385,435p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'git diff -- tests/test_conductor src/derzug/conductor/launch.py' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "rg -n \"\\.scratch|pytest_cache\" .gitignore .git/info/exclude 2>/dev/null" in /home/derrick/Gits/derzug
 succeeded in 0ms:
  1055	        -------
  1056	        window: CanvasMainWindow
  1057	        """
  1058	        window = type(self)()  # 'preserve' subclass type
  1059	        window.setAttribute(Qt.WA_DeleteOnClose)
  1060	        window.setGeometry(self.geometry().translated(20, 20))
  1061	        window.setStyleSheet(self.styleSheet())
  1062	        window.setWindowIcon(self.windowIcon())
  1063	        if self.widget_registry is not None:
  1064	            window.set_widget_registry(self.widget_registry)
  1065	        window.restoreState(self.saveState(self.SETTINGS_VERSION),
  1066	                            self.SETTINGS_VERSION)
  1067	        window.set_tool_dock_expanded(self.dock_widget.expanded())
  1068	        window.set_float_widgets_on_top_enabled(self.float_widgets_on_top_action.isChecked())
  1069	
  1070	        output = window.output_view()  # type: OutputView
  1071	        doc = self.output_view().document()
  1072	        doc = doc.clone(output)
  1073	        output.setDocument(doc)
  1074	
  1075	        def is_connected(stream: TextStream) -> bool:
  1076	            item = findf(doc.connectedStreams(), lambda s: s is stream)
  1077	            return item is not None
  1078	
  1079	        # # route the stdout/err if possible
  1080	        # TODO: Deprecate and remove this behaviour (use connectStream)
  1081	        stdout, stderr = sys.stdout, sys.stderr
  1082	        if isinstance(stdout, TextStream) and not is_connected(stdout):
  1083	            doc.connectStream(stdout)
  1084	
  1085	        if isinstance(stderr, TextStream) and not is_connected(stderr):
  1086	            doc.connectStream(stderr, color=Qt.red)
  1087	
  1088	        CanvasMainWindow._instances.append(window)
  1089	        window.destroyed.connect(
  1090	            lambda: CanvasMainWindow._instances.remove(window))
  1091	        return window
  1092	
  1093	    def new_workflow_window(self):
  1094	        # type: () -> None
  1095	        """
  1096	        Create and show a new CanvasMainWindow instance.
  1097	        """
  1098	        newwindow = self.create_new_window()
  1099	        newwindow.ask_load_swp_if_exists()
  1100	
  1101	        newwindow.raise_()
  1102	        newwindow.show()
  1103	        newwindow.activateWindow()
  1104	
  1105	        settings = QSettings()
  1106	        show = settings.value("schemeinfo/show-at-new-scheme", False,
  1107	                              type=bool)
  1108	        if show:
  1109	            newwindow.show_scheme_properties()
  1110	
  1111	    def open_scheme_file(self, filename, **kwargs):
  1112	        # type: (Union[str, QUrl], Any) -> None
  1113	        """
  1114	        Open and load a scheme file.
  1115	        """
  1116	        if isinstance(filename, QUrl):
  1117	            filename = filename.toLocalFile()
  1118	
  1119	        if self.is_transient():
  1120	            window = self
  1121	        else:
  1122	            window = self.create_new_window()
  1123	            window.show()
  1124	            window.raise_()
  1125	            window.activateWindow()

 succeeded in 0ms:
     1	"""
     2	Custom modifications to Orange for DerZug.
     3	"""
     4	
     5	from __future__ import annotations
     6	
     7	import io
     8	import math
     9	import re
    10	import subprocess
    11	import sys
    12	import tempfile
    13	from collections.abc import Iterable
    14	from contextlib import suppress
    15	from copy import deepcopy
    16	from importlib import import_module
    17	from pathlib import Path
    18	from typing import ClassVar
    19	
    20	# isort: off
    21	# Must run before AnyQt imports on macOS.
    22	import derzug._anyqt_patch  # noqa: F401
    23	from AnyQt import _api as anyqt_api
    24	from AnyQt.QtCore import (
    25	    QDir,
    26	    QEvent,
    27	    QLineF,
    28	    QObject,
    29	    QPointF,
    30	    QPropertyAnimation,
    31	    QSignalBlocker,
    32	    Qt,
    33	    QTimer,
    34	    QUrl,
    35	)
    36	from AnyQt.QtGui import (
    37	    QBrush,
    38	    QColor,
    39	    QCursor,
    40	    QDesktopServices,
    41	    QIcon,
    42	    QFont,
    43	    QKeySequence,
    44	    QPen,
    45	    QTextCharFormat,
    46	    QTextCursor,
    47	    QTextBlockFormat,
    48	)
    49	from AnyQt.QtWidgets import (
    50	    QAbstractItemView,
    51	    QAbstractSpinBox,
    52	    QAction,
    53	    QApplication,
    54	    QComboBox,
    55	    QDialog,
    56	    QGraphicsItem,
    57	    QGraphicsRectItem,
    58	    QGraphicsView,
    59	    QHBoxLayout,
    60	    QLineEdit,
    61	    QMenu,
    62	    QMessageBox,
    63	    QPlainTextEdit,
    64	    QPushButton,
    65	    QTextEdit,
    66	    QVBoxLayout,
    67	    QWidget,
    68	)
    69	
    70	# isort: on
    71	from Orange.canvas.__main__ import OMain
    72	from Orange.canvas.config import Config as OrangeConfig
    73	from Orange.canvas.mainwindow import MainWindow as OrangeMainWindow
    74	from orangecanvas.application.canvastooldock import SplitterResizer
    75	from orangecanvas.application.outputview import ExceptHook
    76	from orangecanvas.canvas import scene as orange_canvas_scene
    77	from orangecanvas.canvas.items import controlpoints as orange_controlpoints
    78	from orangecanvas.canvas.items.nodeitem import NodeItem
    79	from orangecanvas.document import commands as orange_commands
    80	from orangecanvas.document import interactions as orange_interactions
    81	from orangecanvas.document import schemeedit as orange_schemeedit
    82	from orangecanvas.gui.windowlistmanager import WindowListManager
    83	from orangecanvas.scheme import (
    84	    SchemeArrowAnnotation,
    85	    SchemeTextAnnotation,
    86	    readwrite,
    87	)
    88	from orangecanvas.utils.settings import QSettings
    89	from orangewidget.workflow.errorreporting import (
    90	    handle_exception as orange_handle_exception,
    91	)
    92	from orangewidget.workflow.widgetsscheme import (
    93	    OWWidgetManager,
    94	    Scheme,
    95	    WidgetsScheme,
    96	    WidgetsSignalManager,
    97	)
    98	
    99	from derzug.annotations_config import (
   100	    AnnotationSettingsDialog,
   101	    load_annotation_config,
   102	    save_annotation_config,
   103	)
   104	from derzug.core.error_dialog import (
   105	    DerZugErrorDialog,
   106	    _build_exception_report_data,
   107	    handle_derzug_exception,
   108	)
   109	from derzug.core.services import register_app_shell_service
   110	from derzug.core.zugwidget import ZugWidget
   111	from derzug.utils.misc import (
   112	    load_example_workflow_entrypoints,
   113	    load_widget_entrypoints,
   114	)
   115	from derzug.utils.qt_runtime import install_sigint_handler
   116	from derzug.views.dialogs import (
   117	    CodeWorkflowWarningDialog,
   118	    DerZugAboutDialog,
   119	    DerZugKeyboardShortcutsDialog,
   120	    ExperimentalWarningDialog,
   121	)
   122	from derzug.views.orange_registry import filter_registry_for_das
   123	from derzug.views.platform import (
   124	    _linux_desktop_entry_contents as _linux_desktop_entry_contents,
   125	)
   126	from derzug.views.platform import (
   127	    configure_linux_desktop_integration as _configure_linux_desktop_integration,
   128	)
   129	from derzug.views.platform import (
   130	    configure_pyqtgraph_gpu_rendering as _configure_pyqtgraph_gpu_rendering,
   131	)
   132	from derzug.views.platform import (
   133	    ensure_linux_desktop_entry as ensure_linux_desktop_entry,
   134	)
   135	from derzug.views.platform import (
   136	    install_derzug_exception_handler as _install_derzug_exception_handler,
   137	)
   138	from derzug.widgets.composite import (
   139	    NODE_ID_KEY,
   140	    composite_payload_from_properties,
   141	    composite_properties,
   142	    composite_widget_description,
   143	    ensure_composite_widget_class,
   144	    ensure_node_id,
   145	    get_internal_node_id,
   146	    get_node_id,
   147	)
   148	
   149	__all__ = (
   150	    "ActiveSourceManager",
   151	    "DerZugConfig",
   152	    "DerZugErrorDialog",
   153	    "DerZugMain",
   154	    "DerZugMainWindow",
   155	    "_build_exception_report_data",
   156	    "filter_registry_for_das",
   157	    "handle_derzug_exception",
   158	)
   159	
   160	_APP_ACTIVE_SOURCE_MANAGER = None
   161	_APP_ACTIVE_SOURCE_MAIN_WINDOW = None
   162	_EXPERIMENTAL_WARNING_GROUP = "startup"
   163	_EXPERIMENTAL_WARNING_HIDE_KEY = "hide-experimental-warning"
   164	_CODE_WARNING_GROUP = "load"
   165	_CODE_WARNING_HIDE_KEY = "hide-code-widget-warning"
   166	_CODE_WIDGET_QUALIFIED_NAME = "derzug.widgets.code.Code"
   167	_CANVAS_ARROW_COLORS = ("#000", "#C1272D", "#662D91", "#1F9CDF", "#39B54A")
   168	_CANVAS_TEXT_SIZES = ("10", "11", "12", "14", "16", "18", "20", "22", "24", "28", "32")
   169	_CANVAS_TEXT_FONTS = (
   170	    "Arial",
   171	    "Helvetica",
   172	    "Times New Roman",
   173	    "Georgia",
   174	    "Courier New",
   175	    "Verdana",
   176	)
   177	_ORIGINAL_CANVAS_FONT_FROM_DICT = orange_canvas_scene.font_from_dict
   178	_CANVAS_TEXT_ALIGNMENTS = ("Left", "Center", "Right")
   179	_CANVAS_PATCHES_INSTALLED = False
   180	

 succeeded in 0ms:
1742:def _qt_object_is_deleted(obj: object) -> bool:
   385	        delta = pos - origin
   386	        axis = "x" if abs(delta.x()) >= abs(delta.y()) else "y"
   387	        setattr(item, "_derzug_axis_lock_axis", axis)
   388	
   389	    if axis == "x":
   390	        return QPointF(pos.x(), origin.y())
   391	    return QPointF(origin.x(), pos.y())
   392	
   393	
   394	def _selection_top_left(nodes, annotations) -> QPointF:
   395	    """Return one top-left anchor for a mixed node/annotation selection."""
   396	    points = [orange_schemeedit.nodes_top_left(nodes)] if nodes else []
   397	    points.extend(_annotation_top_left(annotation) for annotation in annotations)
   398	    if not points:
   399	        return QPointF(0, 0)
   400	    return QPointF(
   401	        min(point.x() for point in points), min(point.y() for point in points)
   402	    )
   403	
   404	
   405	def _cursor_scene_paste_target(document) -> QPointF | None:
   406	    """Return a cursor-relative paste target over the canvas viewport."""
   407	    view = document.view()
   408	    viewport = view.viewport()
   409	    viewport_pos = viewport.mapFromGlobal(QCursor.pos())
   410	    if not viewport.rect().contains(viewport_pos):
   411	        return None
   412	    return view.mapToScene(viewport_pos)
   413	
   414	
   415	def _install_canvas_annotation_clipboard_support() -> None:
   416	    """Extend Orange canvas clipboard actions to include text and arrow annotations."""
   417	
   418	    def __copySelected(self):
   419	        """Return deep-copied selected nodes, links, and annotations."""
   420	        scheme = self.scheme()
   421	        if scheme is None:
   422	            return [], [], []
   423	
   424	        scheme.sync_node_properties()
   425	        nodes = self.selectedNodes()
   426	        links = [
   427	            link
   428	            for link in scheme.links
   429	            if link.source_node in nodes and link.sink_node in nodes
   430	        ]
   431	        annotations = self.selectedAnnotations()
   432	
   433	        nodedups = [orange_schemeedit.copy_node(node) for node in nodes]
   434	        node_to_dup = dict(zip(nodes, nodedups))
   435	        linkdups = [

 succeeded in 0ms:
 succeeded in 0ms:
  1735	            modules.append(import_module(module_name))
  1736	    return tuple(modules)
  1737	
  1738	
  1739	_SIP_MODULES = _load_sip_modules()
  1740	
  1741	
  1742	def _qt_object_is_deleted(obj: object) -> bool:
  1743	    """Return True when a Qt wrapper is gone across supported SIP variants."""
  1744	    if obj is None:
  1745	        return True
  1746	    for sip_module in _SIP_MODULES:
  1747	        isdeleted = getattr(sip_module, "isdeleted", None)
  1748	        if isdeleted is None:
  1749	            continue
  1750	        try:
  1751	            return bool(isdeleted(obj))
  1752	        except TypeError:
  1753	            continue
  1754	        except RuntimeError:
  1755	            return True
  1756	    return False
  1757	
  1758	
  1759	def _derzug_settings() -> QSettings:
  1760	    """Return a settings object scoped to DerZug's real app identity."""
  1761	    organization = getattr(DerZugConfig, "OrganizationName", None) or getattr(
  1762	        DerZugConfig, "OrganizationDomain", ""
  1763	    )
  1764	    return QSettings(
  1765	        QSettings.IniFormat,
  1766	        QSettings.UserScope,
  1767	        str(organization),
  1768	        DerZugConfig.ApplicationName,
  1769	    )
  1770	
  1771	
  1772	def _reserved_node_metadata(properties: object) -> dict[str, object]:
  1773	    """Return the reserved DerZug node metadata subset from one properties dict."""
  1774	    if not isinstance(properties, dict):
  1775	        return {}

 succeeded in 0ms:
.gitignore:16:.pytest_cache/

exec
/usr/bin/zsh -lc '/home/derrick/mambaforge/envs/derzug/bin/python -m ruff check src/derzug/views/conductor.py src/derzug/conductor/constants.py src/derzug/views/orange.py tests/test_views/test_conductor.py tests/test_views/test_orange_qt.py tests/test_cli.py' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'git status --short' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'git diff --check' in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc 'command -v claude' in /home/derrick/Gits/derzug
 succeeded in 0ms:
/home/derrick/.local/bin/claude

 succeeded in 0ms:
 M docs/dev/conductor.md
 M docs/dev/plans/conductor_terminal_pane.md
 M src/derzug/conductor/mcp_server.py
 M src/derzug/views/orange.py
 M tests/test_cli.py
 M tests/test_views/test_orange_qt.py
?? .scratch/
?? src/derzug/conductor/constants.py
?? src/derzug/views/conductor.py
?? tests/test_views/test_conductor.py

 succeeded in 0ms:
 exited 1 in 0ms:
/home/derrick/mambaforge/envs/derzug/bin/python: No module named ruff

exec
/usr/bin/zsh -lc "nl -ba src/derzug/conductor/controller.py | sed -n '70,145p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba tests/test_views/test_orange_qt.py | sed -n '360,485p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba tests/test_conductor/test_mcp_server.py | sed -n '100,165p'" in /home/derrick/Gits/derzug
exec
/usr/bin/zsh -lc "nl -ba src/derzug/conductor/dispatch.py | sed -n '1,150p'" in /home/derrick/Gits/derzug
 succeeded in 0ms:
    70	    """Return a JSON-serializable view of one setting value."""
    71	    if value is None or isinstance(value, str | int | float | bool):
    72	        return value
    73	    if isinstance(value, list | tuple):
    74	        return [_json_safe(item) for item in value]
    75	    if isinstance(value, dict):
    76	        return {str(key): _json_safe(item) for key, item in value.items()}
    77	    return str(value)
    78	
    79	
    80	def _model_field_names(model: object) -> set[str]:
    81	    """All valid field names for a model, combining discriminated-union members."""
    82	    fields = getattr(model, "model_fields", None)
    83	    if fields is not None:
    84	        return set(fields)
    85	    names: set[str] = set()
    86	    for arg in get_args(model):  # Annotated[Union[...], FieldInfo]
    87	        for member in get_args(arg):  # the union members
    88	            member_fields = getattr(member, "model_fields", None)
    89	            if member_fields:
    90	                names |= set(member_fields)
    91	    return names
    92	
    93	
    94	def _read_params(widget: object) -> dict[str, Any]:
    95	    """Return the widget's typed parameters as JSON-safe data."""
    96	    if getattr(type(widget), "params_model", None) is None:
    97	        return {}
    98	    try:
    99	        return _json_safe(widget.get_params().model_dump())
   100	    except Exception:
   101	        return {}
   102	
   103	
   104	def _read_view(widget: object) -> dict[str, Any] | None:
   105	    """Return the widget's typed presentation state as JSON-safe data, or None."""
   106	    if getattr(type(widget), "view_model", None) is None:
   107	        return None
   108	    try:
   109	        return _json_safe(widget.get_view().model_dump())
   110	    except Exception:
   111	        return None
   112	
   113	
   114	def _signal_type_name(signal: object) -> str:
   115	    """Return a readable type name for one Orange input/output signal."""
   116	    signal_type = getattr(signal, "type", None)
   117	    if isinstance(signal_type, str):
   118	        return signal_type
   119	    if isinstance(signal_type, type):
   120	        return signal_type.__name__
   121	    return str(signal_type)
   122	
   123	
   124	def _ports(signals: object, kind: str) -> list[PortInfo]:
   125	    """Return typed ``PortInfo`` entries for a signal container."""
   126	    return [
   127	        PortInfo(name=getattr(sig, "name", ""), type=_signal_type_name(sig), kind=kind)
   128	        for sig in (signals or ())
   129	    ]
   130	
   131	
   132	def _patch_summary(obj: object) -> dict[str, Any] | None:
   133	    """Return a shape/dims summary for a patch-like object, else None."""
   134	    if not isinstance(obj, dc.Patch):
   135	        return None
   136	    return {"shape": list(obj.shape), "dims": list(obj.dims)}
   137	
   138	
   139	def _widget_busy(widget: object) -> bool:
   140	    """Return True while the widget's async execution is in flight."""
   141	    return bool(getattr(widget, "_async_busy_state", False))
   142	
   143	
   144	def _widget_error(widget: object) -> str | None:
   145	    """Return the widget's last unhandled error message, when tracked."""

 succeeded in 0ms:
   100	    """A taken port raises immediately from start() instead of dying silently."""
   101	    import socket
   102	
   103	    from derzug.conductor.mcp_server import ConductorService
   104	
   105	    window, _ = blank_canvas
   106	    mcp, _ = _server(window)
   107	    with socket.create_server(("127.0.0.1", 0)) as sock:
   108	        taken_port = sock.getsockname()[1]
   109	        service = ConductorService(mcp, port=taken_port)
   110	        with pytest.raises(OSError):
   111	            service.start()
   112	
   113	
   114	def test_service_start_ready_and_stop(blank_canvas):
   115	    """The service binds an ephemeral port, reports ready, and stops cleanly."""
   116	    from derzug.conductor.mcp_server import ConductorService
   117	
   118	    window, _ = blank_canvas
   119	    mcp, _ = _server(window)
   120	    service = ConductorService(mcp, port=0)
   121	    url = service.start(timeout=30.0)
   122	    try:
   123	        assert service.port > 0
   124	        assert url == f"http://127.0.0.1:{service.port}/mcp"
   125	    finally:
   126	        service.stop()
   127	    assert service._thread is None
   128	
   129	
   130	def test_start_conductor_stops_service_when_config_write_fails(
   131	    blank_canvas, tmp_path, monkeypatch
   132	):
   133	    """Failure after bind/readiness must not leave an orphan listening server."""
   134	    from derzug.conductor.mcp_server import ConductorService
   135	
   136	    window, _ = blank_canvas
   137	    stopped: list[ConductorService] = []
   138	    original_stop = ConductorService.stop
   139	
   140	    def track_stop(self, timeout=5.0):
   141	        stopped.append(self)
   142	        original_stop(self, timeout)
   143	
   144	    def fail_write(*args, **kwargs):
   145	        raise OSError("config is not writable")
   146	
   147	    monkeypatch.setattr(ConductorService, "stop", track_stop)
   148	    monkeypatch.setattr("derzug.conductor.mcp_server.write_mcp_config", fail_write)
   149	
   150	    with pytest.raises(OSError, match="not writable"):
   151	        start_conductor(window, port=0, config_path=tmp_path / ".mcp.json")
   152	
   153	    assert len(stopped) == 1
   154	    assert stopped[0]._thread is None
   155	
   156	
   157	def test_connect_tool_defaults_ports_to_patch(blank_canvas):
   158	    """The connect tool links two nodes using the default 'Patch' ports."""
   159	    window, _ = blank_canvas
   160	    mcp, controller = _server(window)
   161	    spool = controller.add_node("Spool", title="s")
   162	    view = controller.add_node("Waterfall", title="v")
   163	    asyncio.run(mcp.call_tool("connect", {"source_id": spool, "sink_id": view}))
   164	    links = controller.get_canvas_state().links
   165	    assert any(link.source_id == spool and link.sink_id == view for link in links)

 succeeded in 0ms:
     1	"""Marshal Conductor calls onto the Qt main thread.
     2	
     3	``CanvasController`` must run on the Qt main thread (it touches the live scheme
     4	and widgets), but the transport that drives it (the MCP server) runs off-thread.
     5	``MainThreadDispatcher.run`` executes a callable on the main thread and blocks
     6	the calling thread until it returns a result or raises — the inverse of the
     7	worker-to-main marshalling in ``core/widget_runtime.py``.
     8	"""
     9	
    10	from __future__ import annotations
    11	
    12	import threading
    13	import time
    14	from collections.abc import Callable
    15	from typing import Any
    16	
    17	from AnyQt.QtCore import QObject, Qt, QThread, Signal
    18	from AnyQt.QtWidgets import QApplication
    19	
    20	#: How long one marshalled call may wait to start on the main thread before
    21	#: failing. Once execution starts it is allowed to finish: returning a timeout
    22	#: while a mutating call is still running would make retries unsafe.
    23	DEFAULT_CALL_TIMEOUT = 30.0
    24	
    25	#: Poll interval while waiting on the main thread; keeps stop() responsive.
    26	_WAIT_SLICE = 0.05
    27	
    28	
    29	class MainThreadDispatcher(QObject):
    30	    """Run callables on the Qt main thread from any thread, blocking for result."""
    31	
    32	    #: Carries a zero-arg callable to invoke on the main thread.
    33	    _invoke = Signal(object)
    34	
    35	    def __init__(self, *, timeout: float = DEFAULT_CALL_TIMEOUT) -> None:
    36	        super().__init__()
    37	        self._timeout = timeout
    38	        self._stopped = threading.Event()
    39	        app = QApplication.instance()
    40	        if app is not None:
    41	            self.moveToThread(app.thread())
    42	        self._invoke.connect(self._run_on_main, Qt.QueuedConnection)
    43	
    44	    @staticmethod
    45	    def _run_on_main(func: Callable[[], None]) -> None:
    46	        func()
    47	
    48	    def stop(self) -> None:
    49	        """Refuse new calls and release any caller waiting on the main thread.
    50	
    51	        Called at application teardown, when the main thread may never service
    52	        another queued invocation.
    53	        """
    54	        self._stopped.set()
    55	
    56	    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    57	        """Execute ``func(*args, **kwargs)`` on the main thread; block for result.
    58	
    59	        Runs directly when already on the main thread (so it never deadlocks on
    60	        itself). Exceptions raised by ``func`` are re-raised on the caller.
    61	        Raises ``RuntimeError`` once stopped and ``TimeoutError`` when the main
    62	        thread does not service the call within the dispatcher's timeout.
    63	        """
    64	        if self._stopped.is_set():
    65	            raise RuntimeError("dispatcher is stopped (application shutting down)")
    66	        app = QApplication.instance()
    67	        if app is None or QThread.currentThread() is app.thread():
    68	            return func(*args, **kwargs)
    69	
    70	        outcome: dict[str, Any] = {}
    71	        done = threading.Event()
    72	        state_lock = threading.Lock()
    73	        started = False
    74	        cancelled = False
    75	
    76	        def _cancel_if_queued() -> bool:
    77	            """Cancel an invocation that has not started; report whether it won."""
    78	            nonlocal cancelled
    79	            with state_lock:
    80	                if started:
    81	                    return False
    82	                cancelled = True
    83	                return True
    84	
    85	        def _call() -> None:
    86	            nonlocal started
    87	            with state_lock:
    88	                if cancelled:
    89	                    done.set()
    90	                    return
    91	                started = True
    92	            try:
    93	                outcome["value"] = func(*args, **kwargs)
    94	            except BaseException as exc:  # - re-raised on the caller
    95	                outcome["error"] = exc
    96	            finally:
    97	                done.set()
    98	
    99	        self._invoke.emit(_call)
   100	        deadline = time.monotonic() + self._timeout
   101	        while not done.wait(_WAIT_SLICE):
   102	            if self._stopped.is_set() and _cancel_if_queued():
   103	                raise RuntimeError(
   104	                    "dispatcher stopped while waiting on the main thread"
   105	                )
   106	            if time.monotonic() > deadline and _cancel_if_queued():
   107	                raise TimeoutError(
   108	                    f"main thread did not service the call within "
   109	                    f"{self._timeout:.0f}s (busy or blocked)"
   110	                )
   111	        if "error" in outcome:
   112	            raise outcome["error"]
   113	        return outcome["value"]

 succeeded in 0ms:
   360	        assert "Window Groups" not in _menu_labels(window, "View")
   361	        assert "Show report" not in _menu_labels(window, "View")
   362	        assert "Add-ons..." not in _menu_labels(window, "Options")
   363	        assert "Reset Widget Settings..." not in _menu_labels(window, "Options")
   364	        assert "Annotation Settings..." in _menu_labels(window, "Options")
   365	        assert "Settings" in _menu_labels(window, "Options")
   366	        assert window.dock_help_action not in window.canvas_toolbar.actions()
   367	
   368	    def test_conductor_menu_is_always_available(self, derzug_app):
   369	        """Server controls should be discoverable without a startup CLI flag."""
   370	        window = derzug_app.window
   371	
   372	        assert window.conductor_controls is not None
   373	        assert window.conductor_controls.menu.objectName() == "conductor-menu"
   374	        assert any(
   375	            action.text().replace("&", "") == "Conductor"
   376	            for action in window.menuBar().actions()
   377	        )
   378	
   379	    def test_conductor_menu_controls_service_lifecycle(
   380	        self, derzug_app, monkeypatch, tmp_path
   381	    ):
   382	        """Menu actions start, launch against, and stop the owned service."""
   383	        main = derzug_app.main
   384	        window = derzug_app.window
   385	        controls = window.conductor_controls
   386	        services = []
   387	        start_calls = []
   388	        launch_calls = []
   389	
   390	        class _FakeService:
   391	            def __init__(self, port):
   392	                self.url = f"http://127.0.0.1:{port}/mcp"
   393	                self.stop_calls = 0
   394	
   395	            def stop(self):
   396	                self.stop_calls += 1
   397	
   398	        def _fake_start(window_arg, **kwargs):
   399	            assert window_arg is window
   400	            start_calls.append(kwargs)
   401	            service = _FakeService(kwargs["port"])
   402	            services.append(service)
   403	            return service
   404	
   405	        monkeypatch.chdir(tmp_path)
   406	        mcp_server = types.ModuleType("derzug.conductor.mcp_server")
   407	        mcp_server.start_conductor = _fake_start
   408	        monkeypatch.setitem(sys.modules, "derzug.conductor.mcp_server", mcp_server)
   409	        monkeypatch.setattr(
   410	            "derzug.conductor.launch.launch_agent_in_terminal",
   411	            lambda agent, cwd, url: launch_calls.append((agent, cwd, url)) or True,
   412	        )
   413	        from derzug.views.conductor import ConductorSettings
   414	
   415	        controls.set_settings(ConductorSettings(port=5432, allow_code=True))
   416	
   417	        controls.start_action.trigger()
   418	
   419	        assert start_calls == [
   420	            {
   421	                "config_path": tmp_path / ".mcp.json",
   422	                "port": 5432,
   423	                "allow_code": True,
   424	            }
   425	        ]
   426	        assert controls.url == services[0].url
   427	        assert controls.stop_action.isEnabled()
   428	
   429	        controls.set_settings(ConductorSettings(port=5433, allow_code=False))
   430	        assert controls.restart_action.text() == "Restart Server (Apply Settings)"
   431	        controls.restart_action.trigger()
   432	        assert services[0].stop_calls == 1
   433	        assert start_calls[-1] == {
   434	            "config_path": tmp_path / ".mcp.json",
   435	            "port": 5433,
   436	            "allow_code": False,
   437	        }
   438	        assert controls.url == services[1].url
   439	
   440	        controls.open_codex_action.trigger()
   441	        assert launch_calls == [("codex", str(tmp_path), services[1].url)]
   442	
   443	        controls.stop_action.trigger()
   444	        assert services[1].stop_calls == 1
   445	        assert main._conductor_service is None
   446	        assert controls.url is None
   447	        assert controls.start_action.isEnabled()
   448	
   449	    def test_conductor_start_failure_returns_menu_to_stopped(
   450	        self, derzug_app, monkeypatch
   451	    ):
   452	        """A startup error should be reported without leaving stale UI state."""
   453	        window = derzug_app.window
   454	        controls = window.conductor_controls
   455	        errors = []
   456	
   457	        def _fail_start(*_args, **_kwargs):
   458	            raise OSError("port is already in use")
   459	
   460	        mcp_server = types.ModuleType("derzug.conductor.mcp_server")
   461	        mcp_server.start_conductor = _fail_start
   462	        monkeypatch.setitem(sys.modules, "derzug.conductor.mcp_server", mcp_server)
   463	        monkeypatch.setattr(
   464	            QMessageBox,
   465	            "critical",
   466	            lambda *args: errors.append(args[1:]),
   467	        )
   468	
   469	        controls.start_action.trigger()
   470	
   471	        assert errors == [
   472	            (
   473	                "Conductor Start Failed",
   474	                "Could not start the Conductor server:\n\nport is already in use",
   475	            )
   476	        ]
   477	        assert controls.status_action.text() == "Status: Stopped"
   478	        assert controls.start_action.isEnabled()
   479	
   480	    def test_annotation_settings_action_opens_dialog(self, derzug_app, monkeypatch):
   481	        """The Options menu should expose the global annotation settings dialog."""
   482	        self._clear_annotation_settings()
   483	        window = derzug_app.window
   484	        opened = []
   485	

exec
/usr/bin/zsh -lc "rg -n \"class CanvasController|def __init__\" src/derzug/conductor/controller.py | head -20 && nl -ba src/derzug/conductor/controller.py | sed -n '155,225p'" in /home/derrick/Gits/derzug
 succeeded in 0ms:
152:class CanvasController:
179:    def __init__(self, window: object, *, allow_code: bool = False) -> None:
   155	    Wraps a running window and projects its workflow as JSON-serializable
   156	    observations for an agent, and lets the agent configure existing nodes:
   157	
   158	    - :meth:`get_canvas_state` — the whole node/link graph and active source.
   159	    - :meth:`list_widget_types` — the placeable widget catalog + param schemas.
   160	    - :meth:`describe_node` — one node's detail plus an input-patch summary.
   161	    - :meth:`compile_check` — whether the canvas currently compiles.
   162	    - :meth:`get_focused_node` / :meth:`get_focus` — what the user is looking at
   163	      and pointing to, for shared user/agent context.
   164	    - :meth:`set_params` / :meth:`set_view` — apply typed, validated state to a
   165	      node, returning the prior state for undo.
   166	    - :meth:`add_node` / :meth:`remove_node` / :meth:`connect` /
   167	      :meth:`disconnect` / :meth:`run` — author and drive the graph.
   168	
   169	    Must be called on the Qt main thread. Undo-stack integration and off-thread
   170	    dispatch arrive in later phases.
   171	
   172	    Examples
   173	    --------
   174	    >>> controller = CanvasController(main_window)
   175	    >>> controller.get_canvas_state().model_dump()   # agent-ready JSON
   176	    {'title': None, 'nodes': [...], 'links': [...], 'active_source_id': None}
   177	    """
   178	
   179	    def __init__(self, window: object, *, allow_code: bool = False) -> None:
   180	        self._window = window
   181	        self._allow_code = allow_code
   182	
   183	    def _check_type_allowed(self, qualified_name: str) -> None:
   184	        """Raise unless ``qualified_name`` may be authored/configured."""
   185	        if not self._allow_code and qualified_name in UNSAFE_WIDGET_QNAMES:
   186	            raise PermissionError(
   187	                f"widget type {qualified_name!r} executes arbitrary Python and is "
   188	                "disabled for agents; start DerZug with --conductor-allow-code "
   189	                "to enable it"
   190	            )
   191	
   192	    def _check_widget_allowed(self, widget: object) -> None:
   193	        """Raise unless ``widget``'s type may be configured by an agent."""
   194	        widget_type = type(widget)
   195	        self._check_type_allowed(f"{widget_type.__module__}.{widget_type.__name__}")
   196	
   197	    def _document(self) -> Any:
   198	        """Return the window's current document (undoable scheme editor)."""
   199	        return self._window.current_document()
   200	
   201	    def _scheme(self) -> Any:
   202	        """Return the live scheme backing the window's current document."""
   203	        return self._document().scheme()
   204	
   205	    def _active_source_widget(self) -> object | None:
   206	        """Return the current active-source widget, if any."""
   207	        manager = getattr(self._window, "active_source_manager", None)
   208	        return getattr(manager, "_active_widget", None) if manager else None
   209	
   210	    def _node_state(
   211	        self, node: Any, widget: object, active: object | None
   212	    ) -> NodeState:
   213	        """Build the observable state for one node."""
   214	        description = getattr(node, "description", None)
   215	        widget_type = type(widget)
   216	        qualified_name = getattr(
   217	            description,
   218	            "qualified_name",
   219	            f"{widget_type.__module__}.{widget_type.__name__}",
   220	        )
   221	        position = getattr(node, "position", None)
   222	        return NodeState(
   223	            id=ensure_node_id(node),
   224	            type=widget_type.__name__,
   225	            qualified_name=qualified_name,

codex
## Findings

1. **[P1] Secondary main windows have no Conductor menu and the server remains bound to the original window.** Controls are installed only by [`setup_main_window`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:2890>), while each directly constructed `DerZugMainWindow` initializes `conductor_controls` to `None` at [`orange.py:3172`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3172>). The inherited `create_new_window()` route exercised at [`test_orange_qt.py:1309`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:1309>) bypasses the installer. Additionally, `CanvasController` permanently retains the supplied window at [`controller.py:179`](</home/derrick/Gits/derzug/src/derzug/conductor/controller.py:179>). Closing the original while another window remains therefore leaves an uncontrollable server targeting the closed or deleted workflow window. The new always-visible test checks only the initial window at [`test_orange_qt.py:368`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:368>).

2. **[P1] A failed or incomplete stop loses ownership of a potentially running server and falsely reports “Stopped.”** `_conductor_service` is cleared before calling `stop()` at [`orange.py:3008`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3008>), and the `finally` block always clears the cwd and marks the UI stopped at [`orange.py:3035`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3035>). This is especially problematic because `ConductorService.stop()` merely logs when its thread survives the five-second join and still discards its thread/server references at [`mcp_server.py:294`](</home/derrick/Gits/derzug/src/derzug/conductor/mcp_server.py:294>). Restart then proceeds unconditionally at [`orange.py:3048`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3048>), likely hitting the still-bound port, with no way to retry stopping the old service. The lifecycle test’s fake `stop()` can only succeed at [`test_orange_qt.py:395`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:395>); it needs failure/timeout coverage.

3. **[P2] Start, stop, and restart block the Qt GUI thread for up to 15 and 5 seconds.** The QAction handler synchronously calls `start_conductor()` at [`orange.py:2981`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:2981>), whose readiness loop sleeps for up to 15 seconds at [`mcp_server.py:273`](</home/derrick/Gits/derzug/src/derzug/conductor/mcp_server.py:273>). Stop synchronously joins the worker at [`mcp_server.py:294`](</home/derrick/Gits/derzug/src/derzug/conductor/mcp_server.py:294>). During slow startup or shutdown, the window freezes and the newly set “Starting…”/“Stopping…” states cannot repaint. Current UI tests replace the service with immediate fakes, so this behavior is uncovered.

4. **[P3] Any import defect is misreported as a missing optional MCP dependency.** The broad `except ImportError` at [`orange.py:2965`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:2965>) also catches import failures from DerZug’s own controller, dispatcher, or other transitive dependencies, then tells the user to reinstall the `conductor` extra and suppresses the original traceback. The failure test only covers an `OSError` after a successful module import at [`test_orange_qt.py:457`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:457>); a non-`mcp` import failure should be tested separately.

No files were edited. Targeted tests passed: **12 passed in 2.37s**. `git diff --check` passed. Ruff was not available in the active environment, so lint was not run.
tokens used
74,001
## Findings

1. **[P1] Secondary main windows have no Conductor menu and the server remains bound to the original window.** Controls are installed only by [`setup_main_window`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:2890>), while each directly constructed `DerZugMainWindow` initializes `conductor_controls` to `None` at [`orange.py:3172`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3172>). The inherited `create_new_window()` route exercised at [`test_orange_qt.py:1309`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:1309>) bypasses the installer. Additionally, `CanvasController` permanently retains the supplied window at [`controller.py:179`](</home/derrick/Gits/derzug/src/derzug/conductor/controller.py:179>). Closing the original while another window remains therefore leaves an uncontrollable server targeting the closed or deleted workflow window. The new always-visible test checks only the initial window at [`test_orange_qt.py:368`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:368>).

2. **[P1] A failed or incomplete stop loses ownership of a potentially running server and falsely reports “Stopped.”** `_conductor_service` is cleared before calling `stop()` at [`orange.py:3008`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3008>), and the `finally` block always clears the cwd and marks the UI stopped at [`orange.py:3035`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3035>). This is especially problematic because `ConductorService.stop()` merely logs when its thread survives the five-second join and still discards its thread/server references at [`mcp_server.py:294`](</home/derrick/Gits/derzug/src/derzug/conductor/mcp_server.py:294>). Restart then proceeds unconditionally at [`orange.py:3048`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:3048>), likely hitting the still-bound port, with no way to retry stopping the old service. The lifecycle test’s fake `stop()` can only succeed at [`test_orange_qt.py:395`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:395>); it needs failure/timeout coverage.

3. **[P2] Start, stop, and restart block the Qt GUI thread for up to 15 and 5 seconds.** The QAction handler synchronously calls `start_conductor()` at [`orange.py:2981`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:2981>), whose readiness loop sleeps for up to 15 seconds at [`mcp_server.py:273`](</home/derrick/Gits/derzug/src/derzug/conductor/mcp_server.py:273>). Stop synchronously joins the worker at [`mcp_server.py:294`](</home/derrick/Gits/derzug/src/derzug/conductor/mcp_server.py:294>). During slow startup or shutdown, the window freezes and the newly set “Starting…”/“Stopping…” states cannot repaint. Current UI tests replace the service with immediate fakes, so this behavior is uncovered.

4. **[P3] Any import defect is misreported as a missing optional MCP dependency.** The broad `except ImportError` at [`orange.py:2965`](</home/derrick/Gits/derzug/src/derzug/views/orange.py:2965>) also catches import failures from DerZug’s own controller, dispatcher, or other transitive dependencies, then tells the user to reinstall the `conductor` extra and suppresses the original traceback. The failure test only covers an `OSError` after a successful module import at [`test_orange_qt.py:457`](</home/derrick/Gits/derzug/tests/test_views/test_orange_qt.py:457>); a non-`mcp` import failure should be tested separately.

No files were edited. Targeted tests passed: **12 passed in 2.37s**. `git diff --check` passed. Ruff was not available in the active environment, so lint was not run.
