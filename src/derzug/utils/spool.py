"""Utilities for working with DASCore spool metadata."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import dascore as dc
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


def normalize_dims_value(value: Any) -> list[str]:
    """Return a normalized list of dimension names from a dims cell value."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        text = text.strip("()[]")
        parts = [x.strip().strip("'\"") for x in text.split(",") if x.strip()]
        return [x for x in parts if x]
    if isinstance(value, tuple | list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def extract_single_patch(spool: dc.BaseSpool) -> dc.Patch | None:
    """Return the only patch in spool, or None when length is not exactly one."""
    iterator = iter(spool)
    try:
        first = next(iterator)
    except StopIteration:
        return None
    try:
        next(iterator)
    except StopIteration:
        return first
    return None


def filter_contents_by_annotations(
    df: pd.DataFrame,
    annotation_set: AnnotationSet,
) -> pd.DataFrame:
    """Return only rows whose extents overlap at least one annotation."""
    if df.empty or not annotation_set.annotations:
        return df.iloc[0:0]
    mask = annotation_overlap_mask(df, annotation_set)
    return df.loc[mask]


def annotation_overlap_mask(
    df: pd.DataFrame,
    annotation_set: AnnotationSet,
) -> pd.Series:
    """Return a boolean row mask for annotation overlap against spool contents."""
    if df.empty:
        return pd.Series(dtype=bool, index=df.index)
    matches = [
        _annotation_overlap_row(annotation, row)
        for _, row in df.iterrows()
        for annotation in annotation_set.annotations
    ]
    if not annotation_set.annotations:
        return pd.Series(False, index=df.index)
    row_count = len(df.index)
    annotation_count = len(annotation_set.annotations)
    reshaped = np.asarray(matches, dtype=bool).reshape(row_count, annotation_count)
    return pd.Series(reshaped.any(axis=1), index=df.index)


def _annotation_overlap_row(annotation: Annotation, row: pd.Series) -> bool:
    """Return True when one spool-contents row overlaps one annotation."""
    geometry = annotation.geometry
    if isinstance(geometry, PointGeometry):
        return _row_contains_coord_map(row, geometry.coords)
    if isinstance(geometry, SpanGeometry):
        start, end = _ordered_pair(geometry.start, geometry.end)
        return _row_intersects_span(row, geometry.dim, start, end)
    if isinstance(geometry, BoxGeometry):
        return all(
            _row_intersects_span(row, dim, bounds.min, bounds.max)
            for dim, bounds in geometry.bounds.items()
        )
    if isinstance(geometry, PathGeometry):
        return any(_row_contains_coord_map(row, point) for point in geometry.points)
    points = getattr(geometry, "points", ())
    return any(_row_contains_coord_map(row, point) for point in points)


def _row_contains_coord_map(row: pd.Series, values: dict[str, Any]) -> bool:
    """Return True when one point lies within row extents on every dim."""
    return all(_row_contains_value(row, dim, value) for dim, value in values.items())


def _row_contains_value(row: pd.Series, dim: str, value: Any) -> bool:
    """Return True when one scalar value lies within one dim extent."""
    bounds = _row_bounds(row, dim)
    if bounds is None:
        return False
    row_min, row_max = bounds
    value = _normalize_coord_scalar(value)
    try:
        return bool(row_min <= value <= row_max)
    except TypeError:
        return False


def _row_intersects_span(row: pd.Series, dim: str, start: Any, end: Any) -> bool:
    """Return True when one interval intersects the row extent on a dim."""
    bounds = _row_bounds(row, dim)
    if bounds is None:
        return False
    row_min, row_max = bounds
    start, end = _ordered_pair(start, end)
    try:
        return not (end < row_min or start > row_max)
    except TypeError:
        return False


def _row_bounds(row: pd.Series, dim: str) -> tuple[Any, Any] | None:
    """Return normalized min/max bounds for one dim from a contents row."""
    min_key = f"{dim}_min"
    max_key = f"{dim}_max"
    if min_key not in row.index or max_key not in row.index:
        return None
    row_min = _normalize_coord_scalar(row[min_key])
    row_max = _normalize_coord_scalar(row[max_key])
    return _ordered_pair(row_min, row_max)


def _ordered_pair(first: Any, second: Any) -> tuple[Any, Any]:
    """Return one pair ordered from low to high."""
    first = _normalize_coord_scalar(first)
    second = _normalize_coord_scalar(second)
    try:
        return (first, second) if first <= second else (second, first)
    except TypeError:
        return first, second


def _normalize_coord_scalar(value: Any) -> Any:
    """Normalize scalars into comparison-friendly pandas/Python values."""
    if isinstance(value, pd.Timestamp | pd.Timedelta):
        return value
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value)
    if isinstance(value, np.timedelta64):
        return pd.Timedelta(value)
    if isinstance(value, datetime):
        return pd.Timestamp(value)
    if isinstance(value, timedelta):
        return pd.Timedelta(value)
    if isinstance(value, np.generic):
        return value.item()
    return value
