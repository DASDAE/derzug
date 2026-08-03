"""Benchmarks for spool-contents annotation overlap masking."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from derzug.models.annotations import (
    Annotation,
    AnnotationSet,
    BoxGeometry,
    CoordRange,
    PointGeometry,
    SpanGeometry,
)
from derzug.utils.spool import annotation_overlap_mask

_ROWS = 5000
_ANNOTATIONS = 50
_START = np.datetime64("2024-01-01T00:00:00")
_ROW_DURATION = np.timedelta64(10, "s")


@pytest.fixture(scope="module")
def contents_df() -> pd.DataFrame:
    """Return a 5000-row spool-contents frame with numeric and time bounds."""
    index = np.arange(_ROWS)
    distance_min = index.astype(np.float64) * 10.0
    time_min = _START + index * _ROW_DURATION
    return pd.DataFrame(
        {
            "distance_min": distance_min,
            "distance_max": distance_min + 10.0,
            "time_min": time_min,
            "time_max": time_min + _ROW_DURATION,
        }
    )


@pytest.fixture(scope="module")
def contents_df_object(contents_df) -> pd.DataFrame:
    """Return the same frame with object-dtype distance columns.

    Object dtype forces the per-row ``_ordered_pair`` fallback in
    ``_ContentsBounds.get``, which is the slow path worth guarding.
    """
    frame = contents_df.copy()
    frame["distance_min"] = frame["distance_min"].astype(object)
    frame["distance_max"] = frame["distance_max"].astype(object)
    return frame


def _annotation(index: int, geometry) -> Annotation:
    """Wrap a geometry in an annotation with a deterministic id."""
    return Annotation(id=f"annotation_{index}", geometry=geometry)


@pytest.fixture(scope="module")
def box_annotations() -> AnnotationSet:
    """Return 50 two-dimensional box annotations.

    ``BoxGeometry`` requires at least two dimensions, so every box spans both
    distance and time.
    """
    annotations = []
    for index in range(_ANNOTATIONS):
        offset = index * 997.0
        start = _START + index * np.timedelta64(997, "s")
        annotations.append(
            _annotation(
                index,
                BoxGeometry(
                    bounds={
                        "distance": CoordRange(min=offset, max=offset + 5.0),
                        "time": CoordRange(
                            min=start, max=start + np.timedelta64(5, "s")
                        ),
                    }
                ),
            )
        )
    return AnnotationSet(dims=("distance", "time"), annotations=tuple(annotations))


@pytest.fixture(scope="module")
def span_annotations() -> AnnotationSet:
    """Return 50 single-dimension span annotations."""
    annotations = [
        _annotation(
            index,
            SpanGeometry(dim="distance", start=index * 997.0, end=index * 997.0 + 5.0),
        )
        for index in range(_ANNOTATIONS)
    ]
    return AnnotationSet(dims=("distance", "time"), annotations=tuple(annotations))


@pytest.fixture(scope="module")
def point_annotations() -> AnnotationSet:
    """Return 50 point annotations."""
    annotations = [
        _annotation(
            index,
            PointGeometry(
                coords={
                    "distance": index * 997.0,
                    "time": _START + index * np.timedelta64(997, "s"),
                }
            ),
        )
        for index in range(_ANNOTATIONS)
    ]
    return AnnotationSet(dims=("distance", "time"), annotations=tuple(annotations))


class TestAnnotationMaskBenchmarks:
    """Benchmarks for :func:`derzug.utils.spool.annotation_overlap_mask`."""

    @pytest.mark.benchmark
    def test_box_mask_numeric(self, contents_df, box_annotations):
        """Mask 5000 rows against 50 boxes on native-dtype columns."""
        annotation_overlap_mask(contents_df, box_annotations)

    @pytest.mark.benchmark
    def test_box_mask_object_dtype(self, contents_df_object, box_annotations):
        """Mask the same rows through the object-dtype fallback path."""
        annotation_overlap_mask(contents_df_object, box_annotations)

    @pytest.mark.benchmark
    def test_span_mask(self, contents_df, span_annotations):
        """Mask 5000 rows against 50 single-dimension spans."""
        annotation_overlap_mask(contents_df, span_annotations)

    @pytest.mark.benchmark
    def test_point_mask(self, contents_df, point_annotations):
        """Mask 5000 rows against 50 points."""
        annotation_overlap_mask(contents_df, point_annotations)
