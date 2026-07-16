"""Tests for spool metadata filtering helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
from derzug.models.annotations import (
    Annotation,
    AnnotationSet,
    BoxGeometry,
    PathGeometry,
    PointGeometry,
    SpanGeometry,
)
from derzug.utils.spool import (
    annotation_overlap_mask,
    extract_single_patch,
    filter_contents_by_annotations,
)


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


def test_extract_single_patch_uses_metadata_for_multi_row_spool():
    """Multi-row spools should not be iterated just to reject patch unpacking."""

    class _LazyMultiRowSpool:
        iterated = False

        def get_contents(self):
            return pd.DataFrame({"tag": ["first", "second"]})

        def __iter__(self):
            self.iterated = True
            raise AssertionError("spool payload was materialized")

    spool = _LazyMultiRowSpool()

    assert extract_single_patch(spool) is None
    assert spool.iterated is False


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


def test_overlap_mask_is_columnar_and_preserves_dataframe_index(monkeypatch):
    """Overlap filtering should not iterate Series rows or replace index labels."""
    df = _contents_df().set_axis(["a", "b", "c"])
    annotation_set = AnnotationSet(
        dims=("distance",),
        annotations=(
            Annotation(
                id="p1",
                geometry=PointGeometry(coords={"distance": 125.0}),
            ),
        ),
    )

    def fail_iterrows(self):
        raise AssertionError("annotation filtering iterated dataframe rows")

    monkeypatch.setattr(pd.DataFrame, "iterrows", fail_iterrows)

    mask = annotation_overlap_mask(df, annotation_set)

    assert list(mask.index) == ["a", "b", "c"]
    assert list(mask) == [False, True, False]


def test_overlap_mask_supports_datetime_bounds_and_reversed_rows():
    """Datetime extents should compare vectorially and normalize reversed bounds."""
    start = np.datetime64("2024-01-01T00:00:00")
    df = pd.DataFrame(
        {
            "time_min": [start, start + np.timedelta64(20, "s")],
            "time_max": [
                start + np.timedelta64(10, "s"),
                start + np.timedelta64(15, "s"),
            ],
        }
    )
    annotation_set = AnnotationSet(
        dims=("time",),
        annotations=(
            Annotation(
                id="p1",
                geometry=PointGeometry(
                    coords={"time": start + np.timedelta64(17, "s")}
                ),
            ),
        ),
    )

    mask = annotation_overlap_mask(df, annotation_set)

    assert list(mask) == [False, True]


def test_overlap_mask_treats_missing_object_bounds_as_non_matches():
    """Nullable metadata must not break columnar comparisons or match a row."""
    df = pd.DataFrame(
        {
            "distance_min": pd.Series([0.0, pd.NA], dtype=object),
            "distance_max": pd.Series([10.0, pd.NA], dtype=object),
        }
    )
    annotation_set = AnnotationSet(
        dims=("distance",),
        annotations=(
            Annotation(
                id="p1",
                geometry=PointGeometry(coords={"distance": 5.0}),
            ),
        ),
    )

    mask = annotation_overlap_mask(df, annotation_set)

    assert list(mask) == [True, False]
