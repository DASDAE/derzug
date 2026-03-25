"""Floating annotation toolbox widget."""

from __future__ import annotations

from pathlib import Path

from AnyQt.QtCore import QPoint, QSize, Qt, Signal
from AnyQt.QtGui import QIcon
from AnyQt.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_ANNOTATION_ICON_DIR = Path(__file__).resolve().parent / "icons" / "annotations"
_TOOL_METADATA = {
    "point": (
        "Point annotation. Double-click or Shift+click to place. "
        "Double-click an annotation to edit.",
        "point",
    ),
    "line": (
        "Line annotation. Double-click or Shift+click to anchor, then click to finish. "
        "Double-click an annotation to edit.",
        "line",
    ),
    "ellipse": (
        "Ellipse annotation. Double-click or Shift+click to place. "
        "Drag selected ellipses to edit.",
        "ellipse",
    ),
    "hyperbola": (
        "Hyperbola annotation. Double-click or Shift+click to place. "
        "Drag selected hyperbolas to edit.",
        "hyperbola",
    ),
    "box": (
        "Box annotation. Double-click or Shift+click to place. "
        "Double-click an annotation to edit.",
        "box",
    ),
    "delete": ("Delete annotation", "delete"),
}


class AnnotationToolbox(QFrame):
    """Compact floating toolbox for annotation-capable hosts."""

    _BASE_TITLE = "Annotations"

    toolChanged = Signal(str)  # noqa: N815
    hideRequested = Signal()  # noqa: N815
    snapToggled = Signal(bool)  # noqa: N815

    def __init__(
        self, parent: QWidget | None = None, *, tools: tuple[str, ...]
    ) -> None:
        super().__init__(parent)
        self._tools = tools
        self._active_tool: str | None = None
        self._pressed_tool: str | None = None
        self.tool_buttons: dict[str, QToolButton] = {}
        self.hide_button: QToolButton | None = None
        self.snap_button: QToolButton | None = None
        self.header_frame: QFrame | None = None
        self._drag_offset: QPoint | None = None
        self._user_moved = False
        self._build_ui()

    def set_tool(self, tool: str) -> None:
        """Update the checked button to match the active tool."""
        if tool not in self.tool_buttons:
            self.clear_tool()
            return
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool)
        self._active_tool = tool

    def clear_tool(self) -> None:
        """Clear any checked tool button to leave the toolbox in a neutral state."""
        for button in self.tool_buttons.values():
            button.setChecked(False)
        self._active_tool = None

    def set_dirty(self, dirty: bool) -> None:
        """Reflect unsent annotation changes in the toolbox title."""
        suffix = " *" if dirty else ""
        self.title_label.setText(f"{self._BASE_TITLE}{suffix}")

    def set_snap_enabled(self, enabled: bool) -> None:
        """Update the snap toggle without requiring direct button access."""
        if self.snap_button is not None:
            self.snap_button.setChecked(bool(enabled))

    def snap_enabled(self) -> bool:
        """Return True when the toolbox snap toggle is enabled."""
        return bool(self.snap_button is not None and self.snap_button.isChecked())

    @property
    def user_moved(self) -> bool:
        """Return True after the user drags the toolbox to a custom position."""
        return self._user_moved

    def mousePressEvent(self, event) -> None:
        """Start dragging the toolbox from the title-bar region."""
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.header_frame is not None
            and self.header_frame.geometry().contains(event.position().toPoint())
        ):
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Drag the toolbox when the left button is held on the frame."""
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self._user_moved = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Finish any active toolbox drag."""
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _build_ui(self) -> None:
        """Create the compact icon-only toolbox."""
        self.setObjectName("annotation-toolbox")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            """
            QFrame#annotation-toolbox {
                background: rgba(246, 246, 246, 242);
                border: 1px solid rgba(62, 62, 62, 170);
                border-radius: 8px;
            }
            QFrame#annotation-toolbox-header {
                background: rgba(228, 228, 228, 245);
                border: 1px solid rgba(0, 0, 0, 0);
                border-bottom: 1px solid rgba(62, 62, 62, 110);
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QLabel#annotation-toolbox-title {
                color: rgb(38, 38, 38);
                font-weight: 600;
                padding-left: 2px;
            }
            QToolButton {
                background: rgba(255, 255, 255, 0);
                border: 1px solid rgba(0, 0, 0, 0);
                border-radius: 4px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 190);
                border: 1px solid rgba(70, 70, 70, 70);
            }
            QToolButton:checked {
                background: rgba(55, 125, 245, 45);
                border: 1px solid rgba(55, 125, 245, 120);
            }
            QToolButton#annotation-toolbox-close {
                color: rgb(80, 80, 80);
                font-weight: 700;
            }
            QToolButton#annotation-toolbox-close:hover {
                background: rgba(220, 70, 70, 55);
                border: 1px solid rgba(180, 40, 40, 90);
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_widget = QFrame(self)
        header_widget.setObjectName("annotation-toolbox-header")
        self.header_frame = header_widget
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(8, 5, 5, 5)
        header.setSpacing(4)
        layout.addWidget(header_widget)

        title = QLabel(self._BASE_TITLE, self)
        title.setObjectName("annotation-toolbox-title")
        title.setToolTip("Press S to send annotations")
        header.addWidget(title)
        self.title_label = title

        header.addStretch(1)

        hide_button = QToolButton(self)
        hide_button.setText("X")
        hide_button.setObjectName("annotation-toolbox-close")
        hide_button.setFixedSize(18, 18)
        hide_button.setToolTip("Hide annotation tools")
        hide_button.clicked.connect(self.hideRequested.emit)
        header.addWidget(hide_button)
        self.hide_button = hide_button

        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(0)
        layout.addWidget(body)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        body_layout.addLayout(row)

        for name in self._tools:
            tooltip, icon_name = _TOOL_METADATA[name]
            button = QToolButton(self)
            button.setCheckable(True)
            button.setFixedSize(24, 24)
            button.setIconSize(QSize(14, 14))
            button.setIcon(QIcon(str(_ANNOTATION_ICON_DIR / f"{icon_name}.svg")))
            button.setToolTip(tooltip)
            button.pressed.connect(
                lambda tool=name: setattr(self, "_pressed_tool", tool)
            )
            button.clicked.connect(
                lambda _checked=False, tool=name: self._on_tool_button_clicked(tool)
            )
            row.addWidget(button)
            self.tool_buttons[name] = button

        snap_button = QToolButton(self)
        snap_button.setText("Snap")
        snap_button.setCheckable(True)
        snap_button.setFixedHeight(24)
        snap_button.setToolTip("Snap point, line, and box edits to nearby annotations")
        snap_button.toggled.connect(self.snapToggled.emit)
        row.addWidget(snap_button)
        self.snap_button = snap_button

        self.hide()
        self.raise_()

    def _on_tool_button_clicked(self, tool: str) -> None:
        """Toggle one tool button on or off and emit the resulting selection."""
        was_active = self._pressed_tool == tool and self._active_tool == tool
        self._pressed_tool = None
        if was_active:
            self.clear_tool()
            self.toolChanged.emit("")
            return
        self.set_tool(tool)
        self.toolChanged.emit(tool)


__all__ = ("AnnotationToolbox",)
