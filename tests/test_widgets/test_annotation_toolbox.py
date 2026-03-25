"""Tests for the floating annotation toolbox widget."""

from __future__ import annotations

from AnyQt.QtCore import QPoint, Qt
from AnyQt.QtTest import QTest
from derzug.widgets.annotation_toolbox import AnnotationToolbox


def test_toolbox_emits_tool_changes_and_tracks_checked_button(qtbot):
    """Clicking a tool button should emit the tool name and latch the button."""
    toolbox = AnnotationToolbox(tools=("point", "delete"))
    qtbot.addWidget(toolbox)
    emitted: list[str] = []
    toolbox.toolChanged.connect(emitted.append)

    toolbox.tool_buttons["point"].click()
    toolbox.set_tool("delete")

    assert emitted == ["point"]
    assert toolbox.tool_buttons["delete"].isChecked() is True


def test_toolbox_buttons_toggle_on_and_off_when_clicked_twice(qtbot):
    """Clicking an active tool again should return the toolbox to no selection."""
    tools = ("point", "line", "ellipse", "hyperbola", "box", "delete")
    toolbox = AnnotationToolbox(tools=tools)
    qtbot.addWidget(toolbox)
    emitted: list[str] = []
    toolbox.toolChanged.connect(emitted.append)

    for tool in tools:
        toolbox.tool_buttons[tool].click()
        assert toolbox.tool_buttons[tool].isChecked() is True
        assert sum(button.isChecked() for button in toolbox.tool_buttons.values()) == 1

        toolbox.tool_buttons[tool].click()
        assert not any(button.isChecked() for button in toolbox.tool_buttons.values())

    expected: list[str] = []
    for tool in tools:
        expected.extend((tool, ""))
    assert emitted == expected


def test_toolbox_renders_annotations_title(qtbot):
    """The toolbox should show a visible title for discoverability."""
    toolbox = AnnotationToolbox(tools=("point",))
    qtbot.addWidget(toolbox)

    assert toolbox.title_label.text() == "Annotations"


def test_toolbox_can_stay_in_a_neutral_no_tool_selected_state(qtbot):
    """No checked draw tool should be a supported steady state."""
    toolbox = AnnotationToolbox(tools=("point", "line"))
    qtbot.addWidget(toolbox)

    toolbox.set_tool("point")
    toolbox.clear_tool()

    assert not any(button.isChecked() for button in toolbox.tool_buttons.values())


def test_toolbox_title_reflects_dirty_state(qtbot):
    """The toolbox title should mark and clear unsent state."""
    toolbox = AnnotationToolbox(tools=("point",))
    qtbot.addWidget(toolbox)

    toolbox.set_dirty(True)
    assert toolbox.title_label.text() == "Annotations *"

    toolbox.set_dirty(False)
    assert toolbox.title_label.text() == "Annotations"


def test_toolbox_hide_button_emits_signal(qtbot):
    """The compact hide button should emit the hide request signal."""
    toolbox = AnnotationToolbox(tools=("point",))
    qtbot.addWidget(toolbox)
    emitted: list[bool] = []
    toolbox.hideRequested.connect(lambda: emitted.append(True))

    toolbox.hide_button.click()

    assert emitted == [True]
    assert toolbox.hide_button.text() == "X"


def test_annotation_tooltips_explain_double_click_edit(qtbot):
    """Annotation tools should advertise the double-click edit behavior."""
    toolbox = AnnotationToolbox(
        tools=(
            "point",
            "line",
            "ellipse",
            "hyperbola",
            "box",
            "delete",
        )
    )
    qtbot.addWidget(toolbox)

    assert "Double-click" in toolbox.tool_buttons["point"].toolTip()
    assert "Double-click" in toolbox.tool_buttons["line"].toolTip()
    assert "Drag to draw" in toolbox.tool_buttons["ellipse"].toolTip()
    assert "Double-click" in toolbox.tool_buttons["box"].toolTip()
    assert "visible branch" in toolbox.tool_buttons["hyperbola"].toolTip()


def test_toolbox_has_no_fit_button(qtbot):
    """The toolbox should expose draw tools only; fitting stays elsewhere."""
    toolbox = AnnotationToolbox(tools=("point", "line", "ellipse"))
    qtbot.addWidget(toolbox)

    assert not hasattr(toolbox, "fit_button")
    assert not hasattr(toolbox, "fit_actions")


def test_toolbox_preserves_requested_tool_order(qtbot):
    """The toolbox should render host-provided tools in the requested order."""
    tools = (
        "point",
        "line",
        "ellipse",
        "hyperbola",
        "box",
        "delete",
    )
    toolbox = AnnotationToolbox(tools=tools)
    qtbot.addWidget(toolbox)

    assert tuple(toolbox.tool_buttons) == tools


def test_toolbox_can_be_dragged(qtbot):
    """Dragging the toolbox frame should move it and mark it as user-positioned."""
    toolbox = AnnotationToolbox(tools=("point",))
    qtbot.addWidget(toolbox)
    toolbox.show()
    qtbot.wait(10)
    toolbox.move(20, 20)
    start = toolbox.pos()
    header_rect = toolbox.header_frame.geometry()
    press = header_rect.center()
    release = press + QPoint(30, 18)

    QTest.mousePress(toolbox, Qt.MouseButton.LeftButton, Qt.NoModifier, press)
    QTest.mouseMove(toolbox, release)
    QTest.mouseRelease(toolbox, Qt.MouseButton.LeftButton, Qt.NoModifier, release)

    assert toolbox.pos() != start
    assert toolbox.user_moved is True
