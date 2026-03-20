"""Floating annotation toolbox widget."""

from __future__ import annotations

from pathlib import Path

from AnyQt.QtCore import QPoint, QSize, Qt, Signal
from AnyQt.QtGui import QIcon
from AnyQt.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_ANNOTATION_ICON_DIR = Path(__file__).resolve().parent / "icons" / "annotations"
_TOOL_METADATA = {
    "select": ("Select ROI", "select"),
    "annotation_select": (
        "Select and move annotations. Double-click an annotation to edit.",
        "pointer",
    ),
    "point": ("Point annotation. Double-click an annotation to edit.", "point"),
    "line": ("Line annotation. Double-click an annotation to edit.", "line"),
    "ellipse": ("Ellipse annotation. Drag to draw a fitted ellipse.", "ellipse"),
    "hyperbola": (
        "Hyperbola annotation. Drag to draw one visible branch.",
        "hyperbola",
    ),
    "box": ("Box annotation. Double-click an annotation to edit.", "box"),
    "delete": ("Delete annotation", "delete"),
}


class AnnotationToolbox(QFrame):
    """Compact floating toolbox for annotation-capable hosts."""

    toolChanged = Signal(str)  # noqa: N815
    fitRequested = Signal(str)  # noqa: N815
    hideRequested = Signal()  # noqa: N815

    def __init__(
        self, parent: QWidget | None = None, *, tools: tuple[str, ...]
    ) -> None:
        super().__init__(parent)
        self._tools = tools
        self.tool_buttons: dict[str, QToolButton] = {}
        self.hide_button: QToolButton | None = None
        self.fit_button: QToolButton | None = None
        self.fit_menu: QMenu | None = None
        self.fit_actions: dict[str, object] = {}
        self.header_frame: QFrame | None = None
        self._drag_offset: QPoint | None = None
        self._user_moved = False
        self._build_ui()

    def set_tool(self, tool: str) -> None:
        """Update the checked button to match the active tool."""
        button = self.tool_buttons.get(tool)
        if button is not None:
            button.setChecked(True)

    def clear_tool(self) -> None:
        """Clear any checked tool button to leave the toolbox in a neutral state."""
        buttons = tuple(self.tool_buttons.values())
        for button in buttons:
            button.setAutoExclusive(False)
        for button in buttons:
            button.setChecked(False)
        for button in buttons:
            button.setAutoExclusive(True)

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

        title = QLabel("Annotations", self)
        title.setObjectName("annotation-toolbox-title")
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
            button.setAutoExclusive(True)
            button.setFixedSize(24, 24)
            button.setIconSize(QSize(14, 14))
            button.setIcon(QIcon(str(_ANNOTATION_ICON_DIR / f"{icon_name}.svg")))
            button.setToolTip(tooltip)
            button.clicked.connect(
                lambda _checked=False, tool=name: self.toolChanged.emit(tool)
            )
            row.addWidget(button)
            self.tool_buttons[name] = button

        fit_button = QToolButton(self)
        fit_button.setText("Fit")
        fit_button.setFixedHeight(24)
        fit_button.setToolTip("Fit a shape from the selected point annotations")
        fit_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        fit_menu = QMenu(fit_button)
        for shape in ("line", "ellipse", "square", "hyperbola"):
            action = fit_menu.addAction(shape.capitalize())
            action.triggered.connect(
                lambda _checked=False, fit_shape=shape: self.fitRequested.emit(
                    fit_shape
                )
            )
            self.fit_actions[shape] = action
        fit_button.setMenu(fit_menu)
        row.addWidget(fit_button)
        self.fit_button = fit_button
        self.fit_menu = fit_menu

        self.hide()
        self.raise_()


__all__ = ("AnnotationToolbox",)
