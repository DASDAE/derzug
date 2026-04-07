"""Tests for the Table2Annotation widget."""

from __future__ import annotations

import pandas as pd
import pytest
from derzug.models.annotations import AnnotationSet, PointGeometry, SpanGeometry
from derzug.utils.testing import (
    TestWidgetDefaults,
    capture_output,
    wait_for_widget_idle,
    widget_context,
)
from derzug.widgets.table2annotation import Table2Annotation

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def widget(qtbot):
    """Return a live Table2Annotation widget."""
    with widget_context(Table2Annotation) as w:
        yield w


def _point_df() -> pd.DataFrame:
    """Simple two-row DataFrame with time/distance columns."""
    return pd.DataFrame({"time": [1.0, 2.0], "dist": [10.0, 20.0]})


def _configure_point_widget(widget) -> None:
    """Set dims and column mapping for dot-geometry output."""
    widget._dims_edit.setText("time,dist")
    widget._on_dims_changed()
    widget.col_map = {"time": "time", "dist": "dist"}


# ---------------------------------------------------------------------------
# Smoke / defaults
# ---------------------------------------------------------------------------


class TestTable2AnnotationDefaults(TestWidgetDefaults):
    """Shared default checks inherited from the DerZug test suite."""

    __test__ = True
    widget = Table2Annotation


def test_widget_uses_only_parameter_sidebar(widget):
    """Table2Annotation should not reserve an empty main-area pane."""
    assert widget.want_main_area is False
    assert widget.controlArea is not None


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


class TestSetData:
    """Tests for Table2Annotation.set_data."""

    def test_none_input_shows_no_data_warning(self, widget, monkeypatch):
        """None input triggers the no_data warning."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_data(None)
        wait_for_widget_idle(widget, timeout=5.0)
        assert widget.Warning.no_data.is_shown()
        assert received[-1] is None

    def test_empty_dataframe_shows_no_data_warning(self, widget, monkeypatch):
        """Empty DataFrame triggers the no_data warning."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_data(pd.DataFrame())
        wait_for_widget_idle(widget, timeout=5.0)
        assert widget.Warning.no_data.is_shown()
        assert received[-1] is None


# ---------------------------------------------------------------------------
# Output correctness
# ---------------------------------------------------------------------------


class TestRunOutput:
    """Tests for Table2Annotation output correctness."""

    def test_no_dims_shows_error(self, widget, monkeypatch):
        """Missing dims configuration raises no_dims error."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.dims_text = ""
        widget.set_data(_point_df())
        wait_for_widget_idle(widget, timeout=5.0)
        assert widget.Error.no_dims.is_shown()
        assert received[-1] is None

    def test_point_geometry_produces_annotation_set(self, widget, monkeypatch):
        """Valid dot config produces an AnnotationSet with one entry per row."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        widget.set_data(_point_df())
        wait_for_widget_idle(widget, timeout=5.0)
        result = received[-1]
        assert isinstance(result, AnnotationSet)
        assert len(result.annotations) == 2

    def test_point_geometry_values_match_dataframe(self, widget, monkeypatch):
        """Annotation coordinate values come from the mapped columns."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        widget.set_data(_point_df())
        wait_for_widget_idle(widget, timeout=5.0)
        result = received[-1]
        first = result.annotations[0]
        assert isinstance(first.geometry, PointGeometry)
        assert first.geometry.coords == {"time": 1.0, "dist": 10.0}

    def test_line_geometry_produces_span_annotations(self, widget, monkeypatch):
        """Line mode produces SpanGeometry annotations."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        # Switch to line mode
        widget.geometry_type = 1
        widget._on_geometry_changed()
        widget.dims_text = "time"
        widget._on_dims_changed()
        widget.line_axis_dim = "time"
        widget.col_map = {"time": "time"}
        widget.set_data(_point_df())
        wait_for_widget_idle(widget, timeout=5.0)
        result = received[-1]
        assert isinstance(result, AnnotationSet)
        assert all(isinstance(a.geometry, SpanGeometry) for a in result.annotations)

    def test_rows_with_nan_are_skipped(self, widget, monkeypatch):
        """Rows containing NaN in a mapped column are skipped with a warning."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        df = pd.DataFrame({"time": [1.0, float("nan")], "dist": [10.0, 20.0]})
        widget.set_data(df)
        wait_for_widget_idle(widget, timeout=5.0)
        assert widget.Warning.rows_skipped.is_shown()
        result = received[-1]
        assert len(result.annotations) == 1

    def test_clearing_input_sends_none(self, widget, monkeypatch):
        """Sending None after data clears the output."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        widget.set_data(_point_df())
        wait_for_widget_idle(widget, timeout=5.0)
        widget.set_data(None)
        wait_for_widget_idle(widget, timeout=5.0)
        assert received[-1] is None

    def test_get_task_matches_widget_output(self, widget, monkeypatch):
        """The canonical task should produce the same annotation set as the widget."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        df = _point_df()

        widget.set_data(df)
        wait_for_widget_idle(widget, timeout=5.0)

        widget_result = received[-1]
        task_result = widget.get_task().run(df)

        assert widget_result == task_result
