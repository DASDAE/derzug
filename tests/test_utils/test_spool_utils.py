"""Tests for spool metadata filtering helpers."""

from __future__ import annotations

import pandas as pd
from derzug.models.annotations import (
    Annotation,
    AnnotationSet,
    BoxGeometry,
    PathGeometry,
    PointGeometry,
    SpanGeometry,
)
from derzug.utils.spool import annotation_overlap_mask, filter_contents_by_annotations


def _contents_df() -> pd.DataFrame:
    """Return a small synthetic spool contents dataframe."""
    return pd.DataFrame(
        {
            "dims": [("distance", "time"), ("distance", "time"), ("distance", "time")],
            "distance_min": [0.0, 100.0, 200.0],
            "distance_max": [50.0, 150.0, 250.0],
            "time_min": [0.0, 0.0, 0.0],
            "time_max": [10.0, 10.0, 10.0],
            "tag": ["first", "second", "third"],
        }
    )


def test_point_annotations_filter_contents_on_shared_dims():
    """Points should keep rows whose extents contain the point."""
    df = _contents_df()
    annotation_set = AnnotationSet(
        dims=("distance",),
        annotations=(
            Annotation(
                id="p1",
                geometry=PointGeometry(coords={"distance": 125.0}),
            ),
        ),
    )

    out = filter_contents_by_annotations(df, annotation_set)

    assert list(out["tag"]) == ["second"]


def test_span_annotations_filter_contents_on_interval_intersection():
    """Spans should keep rows whose extents intersect the annotation span."""
    df = _contents_df()
    annotation_set = AnnotationSet(
        dims=("distance",),
        annotations=(
            Annotation(
                id="s1",
                geometry=SpanGeometry(dim="distance", start=40.0, end=120.0),
            ),
        ),
    )

    out = filter_contents_by_annotations(df, annotation_set)

    assert list(out["tag"]) == ["first", "second"]


def test_box_annotations_require_overlap_on_all_box_dims():
    """Boxes should intersect on every referenced dimension."""
    df = _contents_df()
    annotation_set = AnnotationSet(
        dims=("distance", "time"),
        annotations=(
            Annotation(
                id="b1",
                geometry=BoxGeometry(
                    bounds={
                        "distance": {"min": 90.0, "max": 140.0},
                        "time": {"min": 2.0, "max": 6.0},
                    },
                ),
            ),
        ),
    )

    out = filter_contents_by_annotations(df, annotation_set)

    assert list(out["tag"]) == ["second"]


def test_path_annotations_match_when_any_sampled_point_falls_inside():
    """Paths should match when any sampled point overlaps a row extent."""
    df = _contents_df()
    annotation_set = AnnotationSet(
        dims=("distance", "time"),
        annotations=(
            Annotation(
                id="path1",
                geometry=PathGeometry(
                    points=(
                        {"distance": 10.0, "time": 3.0},
                        {"distance": 110.0, "time": 4.0},
                        {"distance": 180.0, "time": 5.0},
                    ),
                ),
            ),
        ),
    )

    out = filter_contents_by_annotations(df, annotation_set)

    assert list(out["tag"]) == ["first", "second"]


def test_multiple_annotations_use_or_semantics():
    """Rows should be kept when any annotation overlaps them."""
    df = _contents_df()
    annotation_set = AnnotationSet(
        dims=("distance",),
        annotations=(
            Annotation(
                id="p1",
                geometry=PointGeometry(coords={"distance": 25.0}),
            ),
            Annotation(
                id="p2",
                geometry=PointGeometry(coords={"distance": 225.0}),
            ),
        ),
    )

    mask = annotation_overlap_mask(df, annotation_set)

    assert list(mask) == [True, False, True]


def test_empty_annotation_set_matches_no_rows():
    """An empty annotation set should filter out every row."""
    df = _contents_df()
    annotation_set = AnnotationSet(dims=("distance",), annotations=())

    out = filter_contents_by_annotations(df, annotation_set)

    assert out.empty
