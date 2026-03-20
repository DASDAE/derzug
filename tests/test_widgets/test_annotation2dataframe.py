"""Tests for the Annotation2DataFrame widget."""

from __future__ import annotations

import json

import pandas as pd
import pytest
from derzug.models.annotations import (
    Annotation,
    AnnotationSet,
    PointGeometry,
    SpanGeometry,
)
from derzug.utils.testing import capture_output, widget_context
from derzug.widgets.annotation2dataframe import Annotation2DataFrame

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def widget(qtbot):
    """Yield a live Annotation2DataFrame widget."""
    with widget_context(Annotation2DataFrame) as w:
        yield w


def _point_set() -> AnnotationSet:
    """Three point annotations + one span across two dims."""
    return AnnotationSet(
        dims=("time", "distance"),
        annotations=(
            Annotation(
                id="p1",
                geometry=PointGeometry(dims=("time", "distance"), values=(1.0, 10.0)),
                semantic_type="arrival",
                text="first",
                tags=("manual",),
                group="1",
                properties={"confidence": 0.9},
            ),
            Annotation(
                id="p2",
                geometry=PointGeometry(dims=("time",), values=(2.0,)),
                tags=("arrival", "auto"),
            ),
            Annotation(
                id="p3",
                geometry=PointGeometry(dims=("time", "distance"), values=(3.0, 30.0)),
            ),
            Annotation(
                id="s1",
                geometry=SpanGeometry(dim="time", start=0.0, end=5.0),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_widget_instantiates(widget):
    """Widget creates with expected defaults."""
    assert isinstance(widget, Annotation2DataFrame)
    assert widget.include_properties is False


def test_none_input_triggers_no_data_warning(widget, monkeypatch):
    """None input shows no_data warning and emits None."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(None)
    assert widget.Warning.no_data.is_shown()
    assert received[-1] is None


def test_point_annotations_produce_correct_row_count(widget, monkeypatch):
    """One row per point annotation is emitted."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    df = received[-1]
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3


def test_output_columns_in_order(widget, monkeypatch):
    """Output DataFrame has the expected column order."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    df = received[-1]
    assert list(df.columns) == [
        "time",
        "distance",
        "id",
        "semantic_type",
        "text",
        "group",
        "tags",
    ]


def test_non_point_annotations_skipped_with_warning(widget, monkeypatch):
    """Non-point annotations are skipped and a warning is shown."""
    capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    assert widget.Warning.non_point_skipped.is_shown()


def test_partial_dims_produce_nan(widget, monkeypatch):
    """Annotations missing a dim coordinate produce NaN in that column."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    df = received[-1]
    # p2 only has "time", so distance should be NaN
    p2_row = df[df["id"] == "p2"].iloc[0]
    assert pd.isna(p2_row["distance"])
    assert p2_row["time"] == 2.0


def test_tags_are_comma_joined(widget, monkeypatch):
    """Multiple tags are joined into a single comma-separated string."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    df = received[-1]
    p1_row = df[df["id"] == "p1"].iloc[0]
    p2_row = df[df["id"] == "p2"].iloc[0]
    assert p1_row["tags"] == "manual"
    assert p2_row["tags"] == "arrival, auto"


def test_empty_tags_produce_empty_string(widget, monkeypatch):
    """Annotations with no tags produce an empty string in the tags column."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    df = received[-1]
    p3_row = df[df["id"] == "p3"].iloc[0]
    assert p3_row["tags"] == ""


def test_metadata_fields_preserved(widget, monkeypatch):
    """semantic_type, text, and group values are passed through unchanged."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    df = received[-1]
    p1_row = df[df["id"] == "p1"].iloc[0]
    assert p1_row["semantic_type"] == "arrival"
    assert p1_row["text"] == "first"
    assert p1_row["group"] == "1"


def test_none_text_and_group_propagate(widget, monkeypatch):
    """Annotations with None text/group produce None or NaN in those columns."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    df = received[-1]
    p3_row = df[df["id"] == "p3"].iloc[0]
    assert p3_row["text"] is None or pd.isna(p3_row["text"])
    assert p3_row["group"] is None or pd.isna(p3_row["group"])


def test_include_properties_adds_json_column(widget, monkeypatch):
    """Enabling include_properties adds a JSON-encoded properties column."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.include_properties = True
    widget.set_annotation_set(_point_set())
    df = received[-1]
    assert "properties" in df.columns
    p1_row = df[df["id"] == "p1"].iloc[0]
    parsed = json.loads(p1_row["properties"])
    assert parsed == {"confidence": 0.9}


def test_include_properties_off_no_column(widget, monkeypatch):
    """With include_properties=False the properties column is absent."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.include_properties = False
    widget.set_annotation_set(_point_set())
    df = received[-1]
    assert "properties" not in df.columns


def test_empty_annotation_set_returns_empty_dataframe(widget, monkeypatch):
    """An empty AnnotationSet produces an empty DataFrame."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    ann_set = AnnotationSet(dims=("time",), annotations=())
    widget.set_annotation_set(ann_set)
    df = received[-1]
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_all_non_point_annotations_returns_empty_dataframe(widget, monkeypatch):
    """All-span input produces an empty DataFrame with a warning."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    ann_set = AnnotationSet(
        dims=("time",),
        annotations=(
            Annotation(id="s1", geometry=SpanGeometry(dim="time", start=0.0, end=1.0)),
            Annotation(id="s2", geometry=SpanGeometry(dim="time", start=1.0, end=2.0)),
        ),
    )
    widget.set_annotation_set(ann_set)
    df = received[-1]
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert widget.Warning.non_point_skipped.is_shown()


def test_status_label_shows_count(widget, monkeypatch):
    """Status label displays the row count after processing."""
    capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    assert "3" in widget._status_label.text()


def test_status_label_cleared_on_none_input(widget, monkeypatch):
    """Status label is cleared when input is removed."""
    capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(_point_set())
    widget.set_annotation_set(None)
    assert widget._status_label.text() == ""


def test_replacing_input_clears_previous_warning(widget, monkeypatch):
    """Providing valid data after None clears the no_data warning."""
    received = capture_output(widget.Outputs.data, monkeypatch)
    widget.set_annotation_set(None)
    assert widget.Warning.no_data.is_shown()

    widget.set_annotation_set(_point_set())
    assert not widget.Warning.no_data.is_shown()
    assert len(received[-1]) == 3
