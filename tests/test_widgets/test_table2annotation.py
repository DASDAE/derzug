"""Tests for the Table2Annotation widget."""

from __future__ import annotations

import pandas as pd
import pytest

from derzug.models.annotations import AnnotationSet, PointGeometry, SpanGeometry
from derzug.utils.testing import TestWidgetDefaults, capture_output, widget_context
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


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


class TestSetData:
    def test_none_input_shows_no_data_warning(self, widget, monkeypatch):
        """None input triggers the no_data warning."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_data(None)
        assert widget.Warning.no_data.is_shown()
        assert received[-1] is None

    def test_empty_dataframe_shows_no_data_warning(self, widget, monkeypatch):
        """Empty DataFrame triggers the no_data warning."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_data(pd.DataFrame())
        assert widget.Warning.no_data.is_shown()
        assert received[-1] is None


# ---------------------------------------------------------------------------
# Output correctness
# ---------------------------------------------------------------------------


class TestRunOutput:
    def test_no_dims_shows_error(self, widget, monkeypatch):
        """Missing dims configuration raises no_dims error."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.dims_text = ""
        widget.set_data(_point_df())
        assert widget.Error.no_dims.is_shown()
        assert received[-1] is None

    def test_point_geometry_produces_annotation_set(self, widget, monkeypatch):
        """Valid dot config produces an AnnotationSet with one entry per row."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        widget.set_data(_point_df())
        result = received[-1]
        assert isinstance(result, AnnotationSet)
        assert len(result.annotations) == 2

    def test_point_geometry_values_match_dataframe(self, widget, monkeypatch):
        """Annotation coordinate values come from the mapped columns."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        widget.set_data(_point_df())
        result = received[-1]
        first = result.annotations[0]
        assert isinstance(first.geometry, PointGeometry)
        assert first.geometry.values == (1.0, 10.0)

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
        result = received[-1]
        assert isinstance(result, AnnotationSet)
        assert all(isinstance(a.geometry, SpanGeometry) for a in result.annotations)

    def test_rows_with_nan_are_skipped(self, widget, monkeypatch):
        """Rows containing NaN in a mapped column are skipped with a warning."""
        import math

        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        df = pd.DataFrame({"time": [1.0, float("nan")], "dist": [10.0, 20.0]})
        widget.set_data(df)
        assert widget.Warning.rows_skipped.is_shown()
        result = received[-1]
        assert len(result.annotations) == 1

    def test_clearing_input_sends_none(self, widget, monkeypatch):
        """Sending None after data clears the output."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        _configure_point_widget(widget)
        widget.set_data(_point_df())
        widget.set_data(None)
        assert received[-1] is None
