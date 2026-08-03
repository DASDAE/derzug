"""Benchmarks for spool metadata helpers.

The Spool widget filters and displays spool contents on every selection change,
so the vectorized annotation-overlap kernels and the metadata normalization
helpers sit directly on the interactive path.
"""

from __future__ import annotations

import dascore as dc
import pytest
from conftest import SPOOL_ROW_COUNT, make_annotation_set
from derzug.models.annotations import AnnotationSet
from derzug.utils.spool import (
    annotation_overlap_mask,
    extract_single_patch,
    normalize_dims_value,
    series_has_visible_values,
)

DIMS_VALUES = (
    "(time, distance)",
    "['time', 'distance']",
    ("time", "distance"),
    ["time"],
    "",
    None,
)


@pytest.fixture(scope="module")
def empty_annotation_set():
    """Return an annotation set without annotations."""
    return AnnotationSet(dims=("time", "distance"))


@pytest.fixture(scope="module")
def span_annotation_set():
    """Return an annotation set holding only time spans."""
    full = make_annotation_set()
    spans = tuple(
        annotation
        for annotation in full.annotations
        if annotation.geometry.type == "span"
    )
    return full.model_copy(update={"annotations": spans})


@pytest.fixture(scope="module")
def single_patch_spool():
    """Return an in-memory spool holding exactly one patch."""
    return dc.spool([dc.get_example_patch()])


def test_annotation_overlap_mask(benchmark, spool_contents, annotation_set):
    """Mask spool rows overlapped by a large mixed-geometry annotation set."""
    mask = benchmark(annotation_overlap_mask, spool_contents, annotation_set)
    assert len(mask) == SPOOL_ROW_COUNT
    assert mask.any()


def test_annotation_overlap_mask_spans(benchmark, spool_contents, span_annotation_set):
    """Mask spool rows using the span-only fast path."""
    mask = benchmark(annotation_overlap_mask, spool_contents, span_annotation_set)
    assert mask.any()


def test_annotation_overlap_mask_empty(benchmark, spool_contents, empty_annotation_set):
    """Measure the no-annotation short circuit on a large contents frame."""
    mask = benchmark(annotation_overlap_mask, spool_contents, empty_annotation_set)
    assert not mask.any()


def test_series_has_visible_values(benchmark, spool_contents):
    """Detect displayable metadata columns across the contents frame."""

    def check_columns():
        """Return the columns holding at least one displayable value."""
        return [
            column
            for column in spool_contents.columns
            if series_has_visible_values(spool_contents[column])
        ]

    assert "path" in benchmark(check_columns)


def test_normalize_dims_value(benchmark):
    """Normalize the many shapes a dims metadata cell can take."""

    def normalize_all():
        """Normalize every representative dims value."""
        return [normalize_dims_value(value) for value in DIMS_VALUES * 64]

    assert benchmark(normalize_all)


def test_extract_single_patch(benchmark, single_patch_spool):
    """Extract the only patch of a spool."""
    assert benchmark(extract_single_patch, single_patch_spool) is not None
