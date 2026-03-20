"""Error dialog helpers for DerZug's Orange integration."""

from __future__ import annotations

import traceback
from collections import OrderedDict
from collections.abc import Mapping
from urllib.parse import quote, urlencode

from AnyQt.QtCore import Qt, QUrl, Slot
from AnyQt.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from AnyQt.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from orangewidget.workflow.widgetsscheme import OWBaseWidget

_BUG_REPORT_URL = "https://github.com/dasdae/derzug/issues/new"


def _make_text_format(
    *,
    foreground: str,
    bold: bool = False,
    italic: bool = False,
) -> QTextCharFormat:
    """Build a QTextCharFormat with the requested styling."""
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(foreground))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    fmt.setFontItalic(italic)
    return fmt


class _TracebackHighlighter(QSyntaxHighlighter):
    """Apply a small amount of structure-aware color to traceback text."""

    _HEADER = _make_text_format(foreground="#8b0000", bold=True)
    _FILE_LINE = _make_text_format(foreground="#0f766e")
    _CODE_LINE = _make_text_format(foreground="#475569", italic=True)
    _EXCEPTION = _make_text_format(foreground="#b91c1c", bold=True)

    def highlightBlock(self, text: str) -> None:
        """Color traceback sections by their line role."""
        stripped = text.strip()
        if not stripped:
            return
        if stripped == "Traceback (most recent call last):":
            self.setFormat(0, len(text), self._HEADER)
            return
        if text.startswith('  File "') or text.startswith("File "):
            self.setFormat(0, len(text), self._FILE_LINE)
            return
        if text.startswith("    "):
            self.setFormat(0, len(text), self._CODE_LINE)
            return
        if ":" in stripped and not stripped.startswith('File "'):
            exc_name = stripped.split(":", 1)[0]
            if exc_name and ".".join(part for part in exc_name.split(".") if part):
                self.setFormat(0, len(text), self._EXCEPTION)


def _find_last_traceback_frame(tb):
    """Return the last traceback frame, if any."""
    if tb is None:
        return None
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb


def _find_widget_traceback_frame(tb):
    """Return the traceback frame whose `self` is an Orange widget, if any."""
    while tb is not None:
        if isinstance(tb.tb_frame.f_locals.get("self"), OWBaseWidget):
            return tb
        tb = tb.tb_next
    return None


def _build_exception_report_data(
    exc: tuple[type[BaseException], BaseException, object],
):
    """Return key exception metadata and the formatted traceback text."""
    exc_type, exc_value, tb = exc
    exception_text = traceback.format_exception_only(exc_type, exc_value)[-1].strip()
    traceback_text = "".join(traceback.format_exception(exc_type, exc_value, tb))

    location = ""
    frame = _find_last_traceback_frame(tb)
    if frame is not None:
        module = frame.tb_frame.f_globals.get(
            "__name__", frame.tb_frame.f_code.co_filename
        )
        location = f"{module}:{frame.tb_lineno}"

    widget_name = ""
    widget_location = ""
    widget_frame = _find_widget_traceback_frame(tb)
    if widget_frame is not None:
        widget = widget_frame.tb_frame.f_locals["self"]
        widget_class = widget.__class__
        widget_name = getattr(widget_class, "name", widget_class.__name__)
        widget_location = f"{widget_class.__module__}:{widget_frame.tb_lineno}"

    details = OrderedDict(
        [
            ("Exception", exception_text),
            ("Location", location or "Unknown"),
            ("Widget", widget_name or "Unknown"),
            ("Widget Location", widget_location or "Unknown"),
            ("Version", QApplication.applicationVersion() or "Unknown"),
            ("Qt Platform", QApplication.instance().platformName() or "unknown"),
        ]
    )
    return details, traceback_text


def _build_issue_body(details: Mapping[str, str], traceback_text: str) -> str:
    """Return the prefilled GitHub issue body for one dialog instance."""
    lines = [
        "## Summary",
        "",
        "Generated from the DerZug unexpected error dialog.",
        "",
        "## Error Details",
        "",
    ]
    for label, value in details.items():
        lines.append(f"- **{label}**: {value}")
    lines.extend(
        [
            "",
            "## Traceback",
            "",
            "```text",
            traceback_text.rstrip(),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _build_issue_url(details: Mapping[str, str], traceback_text: str) -> str:
    """Return the GitHub new-issue URL with a prefilled body and blank title."""
    params = urlencode(
        {"body": _build_issue_body(details, traceback_text)}, quote_via=quote
    )
    return f"{_BUG_REPORT_URL}?{params}"


class DerZugErrorDialog(QDialog):
    """Compact unexpected-error dialog with key details and copyable traceback."""

    def __init__(self, details: OrderedDict[str, str], traceback_text: str) -> None:
        super().__init__(None)
        self._details = OrderedDict(details)
        self._traceback_text = traceback_text
        self.setModal(True)
        self.setWindowTitle("Unexpected Error")
        self.resize(760, 520)
        self._close_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._close_shortcut.setContext(Qt.WindowShortcut)
        self._close_shortcut.activated.connect(self.reject)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "DerZug encountered an unexpected error. Key details are shown below."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        details_widget = QWidget(self)
        details_layout = QGridLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setColumnStretch(1, 1)
        for row, (label, value) in enumerate(details.items()):
            details_layout.addWidget(QLabel(f"{label}:"), row, 0)
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setWordWrap(True)
            details_layout.addWidget(value_label, row, 1)
        layout.addWidget(details_widget)

        layout.addWidget(QLabel("Traceback:"))
        self._traceback_edit = QPlainTextEdit(self)
        self._traceback_edit.setReadOnly(True)
        self._traceback_edit.setPlainText(traceback_text)
        self._traceback_edit.setStyleSheet(
            "QPlainTextEdit { background: #fffaf5; color: #111827; }"
        )
        self._traceback_highlighter = _TracebackHighlighter(
            self._traceback_edit.document()
        )
        layout.addWidget(self._traceback_edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        copy_button = QPushButton("Copy Traceback", self)
        copy_button.clicked.connect(self.copy_traceback)
        buttons.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._submit_bug_button = QPushButton("Submit Bug Report", self)
        self._submit_bug_button.clicked.connect(self.submit_bug_report)
        buttons.addButton(
            self._submit_bug_button, QDialogButtonBox.ButtonRole.ActionRole
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #b91c1c;")
        self._status_label.hide()
        layout.addWidget(self._status_label)

    def copy_traceback(self) -> None:
        """Copy the traceback text to the clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._traceback_edit.toPlainText())

    def submit_bug_report(self) -> None:
        """Open the GitHub new-issue page with a prefilled issue body."""
        issue_url = _build_issue_url(self._details, self._traceback_text)
        opened = QDesktopServices.openUrl(QUrl(issue_url))
        if opened:
            self._status_label.hide()
            self._status_label.clear()
            return
        self._status_label.setText(
            "Could not open the browser for GitHub issue submission."
        )
        self._status_label.show()


@Slot(object)
def handle_derzug_exception(exc) -> None:
    """Show DerZug's custom unexpected-error dialog for unhandled exceptions."""
    details, traceback_text = _build_exception_report_data(exc)
    dialog = DerZugErrorDialog(details, traceback_text)
    dialog.exec()
