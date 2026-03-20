"""Tests for the DataFrameLoader widget."""

from __future__ import annotations

import pytest
from derzug.utils.testing import widget_context
from derzug.widgets.dataframe_loader import DataFrameLoader


@pytest.fixture
def widget(qtbot):
    """Yield a live DataFrameLoader widget."""
    with widget_context(DataFrameLoader) as w:
        yield w


def test_widget_instantiates(widget):
    """Widget creates without errors."""
    assert isinstance(widget, DataFrameLoader)


def test_controls_are_below_table_in_main_area(widget):
    """The loader controls should live below the preview table, not in a sidebar."""
    assert widget.controlArea is None
    layout = widget.mainArea.layout()
    container = layout.itemAt(0).widget()
    container_layout = container.layout()

    assert container_layout.indexOf(widget._table) == 0
    assert container_layout.indexOf(widget._controls_panel) == 1
