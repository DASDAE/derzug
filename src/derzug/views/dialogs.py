"""Standalone DerZug dialog windows.

These QDialog subclasses are self-contained UI leaves with no dependency on
:mod:`derzug.views.orange`; that module imports and re-exports them so its
main-window code (and existing tests) can keep referencing them by name.
"""

from __future__ import annotations

from contextlib import suppress
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_dist_version
from pathlib import Path
from xml.sax.saxutils import escape

from AnyQt.QtCore import Qt
from AnyQt.QtGui import QPixmap
from AnyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


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

        qt_binding_name = "PyQt6" if _pkg_version("PyQt6") != "n/a" else "Qt Binding"
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


class CodeWorkflowWarningDialog(QDialog):
    """Modal warning shown before loading workflows that can execute code."""

    TITLE = "Code Execution Warning"
    HEADING = "This Workflow Can Run Arbitrary Code"
    MESSAGE = (
        "This .ows file contains a Code widget. Loading it can execute arbitrary "
        "Python code on your machine. Only continue if you trust the workflow "
        "author and understand the risks."
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.TITLE)
        self.setModal(True)
        self.resize(540, 250)
        self.hide_future_warnings = False
        self.setObjectName("code-workflow-warning-dialog")
        self.setStyleSheet(
            """
            QDialog#code-workflow-warning-dialog {
                background-color: #fff7ed;
            }
            QWidget#code-workflow-warning-panel {
                background-color: #fffbf5;
                border: 1px solid #d8b38a;
                border-left: 6px solid #c26b1d;
                border-radius: 10px;
            }
            QLabel#code-workflow-warning-heading {
                color: #8a3d00;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#code-workflow-warning-body {
                color: #5b3418;
                font-size: 14px;
                line-height: 1.35;
            }
            QPushButton#code-workflow-warning-open {
                background-color: #c26b1d;
                border: 1px solid #9f5715;
                border-radius: 6px;
                color: white;
                font-weight: 700;
                padding: 6px 16px;
            }
            QPushButton#code-workflow-warning-open:hover {
                background-color: #d47623;
            }
            QPushButton#code-workflow-warning-cancel {
                border-radius: 6px;
                padding: 6px 16px;
            }
            QCheckBox#code-workflow-warning-checkbox {
                color: #5b3418;
                font-size: 13px;
                spacing: 8px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        panel = QWidget(self)
        panel.setObjectName("code-workflow-warning-panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.setSpacing(8)

        heading = QLabel(self.HEADING, panel)
        heading.setObjectName("code-workflow-warning-heading")
        heading.setWordWrap(True)
        panel_layout.addWidget(heading)

        label = QLabel(self.MESSAGE, panel)
        label.setObjectName("code-workflow-warning-body")
        label.setWordWrap(True)
        panel_layout.addWidget(label)

        layout.addWidget(panel)

        self._hide_checkbox = QCheckBox("Don't show this message again", self)
        self._hide_checkbox.setObjectName("code-workflow-warning-checkbox")
        layout.addWidget(self._hide_checkbox)

        buttons = QDialogButtonBox(self)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.setObjectName("code-workflow-warning-cancel")
        buttons.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.clicked.connect(self.reject)
        open_button = QPushButton("Load Workflow", self)
        open_button.setObjectName("code-workflow-warning-open")
        buttons.addButton(open_button, QDialogButtonBox.ButtonRole.AcceptRole)
        open_button.clicked.connect(self._accept_for_now)
        layout.addWidget(buttons)

    def _accept_for_now(self) -> None:
        """Accept the dialog and optionally suppress future warnings."""
        self.hide_future_warnings = self._hide_checkbox.isChecked()
        self.accept()
