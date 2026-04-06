"""Tests for the DataFrameLoader widget."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from derzug.utils.testing import capture_output, wait_for_widget_idle, widget_context
from derzug.widgets.dataframe_loader import DataFrameLoader

duckdb = pytest.importorskip("duckdb")


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


def _write_duckdb(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Create one DuckDB file with the provided tables."""
    with duckdb.connect(str(path)) as con:
        for name, df in tables.items():
            con.register("source_df", df)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM source_df')
            con.unregister("source_df")


def test_duckdb_auto_detect_shows_sorted_tables_and_defaults_first(
    widget, tmp_path, monkeypatch
):
    """Auto-detected DuckDB files should expose alphabetized table choices."""
    path = tmp_path / "tables.duckdb"
    alpha = pd.DataFrame({"value": [1]})
    beta = pd.DataFrame({"value": [2]})
    _write_duckdb(path, {"beta": beta, "alpha": alpha})
    received = capture_output(widget.Outputs.data, monkeypatch)

    widget.show()
    widget.file_path = str(path)
    widget.file_path_edit.setText(str(path))
    widget.format_name = "Auto"
    widget.format_combo.setCurrentText("Auto")
    widget._load()
    wait_for_widget_idle(widget, timeout=5.0)

    assert not widget._table_row.isHidden()
    assert [
        widget.table_combo.itemText(i) for i in range(widget.table_combo.count())
    ] == [
        "alpha",
        "beta",
    ]
    assert widget.table_name == "alpha"
    assert received[-1].equals(alpha)


def test_duckdb_table_change_reloads_selected_table(widget, tmp_path, monkeypatch):
    """Changing the DuckDB table dropdown should emit that table's data."""
    path = tmp_path / "tables.duckdb"
    alpha = pd.DataFrame({"value": [1]})
    beta = pd.DataFrame({"value": [2]})
    _write_duckdb(path, {"alpha": alpha, "beta": beta})
    received = capture_output(widget.Outputs.data, monkeypatch)

    widget.show()
    widget.file_path = str(path)
    widget.file_path_edit.setText(str(path))
    widget.format_name = "DuckDB"
    widget.format_combo.setCurrentText("DuckDB")
    widget._load()
    wait_for_widget_idle(widget, timeout=5.0)

    widget.table_combo.setCurrentText("beta")
    wait_for_widget_idle(widget, timeout=5.0)

    assert widget.table_name == "beta"
    assert received[-1].equals(beta)
    assert widget.get_task().run().equals(beta)


def test_non_duckdb_hides_table_selector(widget, tmp_path):
    """Non-DuckDB formats should keep the table selector hidden."""
    path = tmp_path / "data.csv"
    pd.DataFrame({"a": [1]}).to_csv(path, index=False)

    widget.show()
    widget.file_path = str(path)
    widget.file_path_edit.setText(str(path))
    widget.format_name = "CSV"
    widget.format_combo.setCurrentText("CSV")
    widget._load()
    wait_for_widget_idle(widget, timeout=5.0)

    assert widget._table_row.isHidden()
    assert widget.table_combo.count() == 0


def test_duckdb_invalid_saved_table_falls_back_to_first(widget, tmp_path, monkeypatch):
    """An unknown persisted table name should fall back to the first sorted table."""
    path = tmp_path / "tables.duckdb"
    alpha = pd.DataFrame({"value": [1]})
    gamma = pd.DataFrame({"value": [3]})
    _write_duckdb(path, {"gamma": gamma, "alpha": alpha})
    received = capture_output(widget.Outputs.data, monkeypatch)

    widget.show()
    widget.file_path = str(path)
    widget.file_path_edit.setText(str(path))
    widget.format_name = "DuckDB"
    widget.format_combo.setCurrentText("DuckDB")
    widget.table_name = "missing"
    widget._load()
    wait_for_widget_idle(widget, timeout=5.0)

    assert widget.table_name == "alpha"
    assert widget.table_combo.currentText() == "alpha"
    assert received[-1].equals(alpha)


def test_duckdb_without_user_tables_shows_error(widget, tmp_path):
    """DuckDB files with no user tables should surface a load failure."""
    path = tmp_path / "empty.duckdb"
    with duckdb.connect(str(path)):
        pass

    widget.show()
    widget.file_path = str(path)
    widget.file_path_edit.setText(str(path))
    widget.format_name = "DuckDB"
    widget.format_combo.setCurrentText("DuckDB")
    widget._load()

    assert widget.Error.load_failed.is_shown()
