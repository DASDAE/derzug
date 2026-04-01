"""Tests for the DataFrameLoader widget."""

from __future__ import annotations

import pandas as pd
import pytest
from derzug.utils.testing import capture_output, wait_for_widget_idle, widget_context
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


def test_get_task_matches_loaded_output(widget, tmp_path, monkeypatch):
    """The canonical loader task should match the widget's emitted dataframe."""
    path = tmp_path / "data.csv"
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    df.to_csv(path, index=False)
    received = capture_output(widget.Outputs.data, monkeypatch)

    widget.file_path = str(path)
    widget.file_path_edit.setText(str(path))
    widget.format_name = "CSV"
    widget._load()
    wait_for_widget_idle(widget, timeout=5.0)

    task_result = widget.get_task().run()

    assert received[-1].equals(task_result)
