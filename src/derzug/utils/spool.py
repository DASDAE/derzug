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
from derzug.utils.misc import ordered_pair


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


def series_has_visible_values(series: pd.Series) -> bool:
    """Return True when a metadata column contains a displayable value."""
    non_missing = series.dropna()
    if non_missing.empty:
        return False
    if pd.api.types.is_string_dtype(non_missing.dtype) or non_missing.dtype == object:
        return bool(non_missing.astype(str).str.strip().ne("").any())
    return True


def extract_single_patch(spool: dc.BaseSpool) -> dc.Patch | None:
    """Return the only patch in spool, or None when length is not exactly one."""
    get_contents = getattr(spool, "get_contents", None)
    if callable(get_contents):
        try:
            contents = get_contents()
        except Exception:
            pass
        else:
            try:
                row_count = len(contents)
            except Exception:
                row_count = 1
            if row_count != 1:
                return None
            try:
                return spool[0]
            except Exception:
                pass

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
    if not annotation_set.annotations:
        return pd.Series(False, index=df.index)

    bounds = _ContentsBounds(df)
    matches = np.zeros(len(df.index), dtype=bool)
    for annotation in annotation_set.annotations:
        matches |= _annotation_overlap_array(annotation, bounds)
        if matches.all():
            break
    return pd.Series(matches, index=df.index)


class _ContentsBounds:
    """Cache normalized columnar bounds for one spool contents dataframe."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df
        self.size = len(df.index)
        self._cache: dict[str, tuple[np.ndarray, np.ndarray] | None] = {}

    def get(self, dim: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Return ordered lower/upper arrays for one dimension."""
        if dim in self._cache:
            return self._cache[dim]
        min_key = f"{dim}_min"
        max_key = f"{dim}_max"
        if min_key not in self.df.columns or max_key not in self.df.columns:
            self._cache[dim] = None
            return None
        lower = _normalize_coord_array(self.df[min_key].to_numpy(copy=False))
        upper = _normalize_coord_array(self.df[max_key].to_numpy(copy=False))
        try:
            swap = np.asarray(upper < lower, dtype=bool)
            ordered = (np.where(swap, upper, lower), np.where(swap, lower, upper))
        except (TypeError, ValueError):
            pairs = [
                _ordered_pair(first, second)
                for first, second in zip(lower, upper, strict=True)
            ]
            ordered = (
                np.asarray([pair[0] for pair in pairs], dtype=object),
                np.asarray([pair[1] for pair in pairs], dtype=object),
            )
        self._cache[dim] = ordered
        return ordered


def _annotation_overlap_array(
    annotation: Annotation,
    bounds: _ContentsBounds,
) -> np.ndarray:
    """Return a vectorized overlap mask for one annotation."""
    geometry = annotation.geometry
    if isinstance(geometry, PointGeometry):
        return _coord_map_overlap_array(geometry.coords, bounds)
    if isinstance(geometry, SpanGeometry):
        start, end = _ordered_pair(geometry.start, geometry.end)
        return _span_overlap_array(geometry.dim, start, end, bounds)
    if isinstance(geometry, BoxGeometry):
        out = np.ones(bounds.size, dtype=bool)
        for dim, dim_bounds in geometry.bounds.items():
            out &= _span_overlap_array(
                dim,
                dim_bounds.min,
                dim_bounds.max,
                bounds,
            )
            if not out.any():
                break
        return out
    points = (
        geometry.points
        if isinstance(geometry, PathGeometry)
        else getattr(geometry, "points", ())
    )
    out = np.zeros(bounds.size, dtype=bool)
    for point in points:
        out |= _coord_map_overlap_array(point, bounds)
        if out.all():
            break
    return out


def _coord_map_overlap_array(
    values: dict[str, Any],
    bounds: _ContentsBounds,
) -> np.ndarray:
    """Return rows containing a point on every referenced dimension."""
    out = np.ones(bounds.size, dtype=bool)
    for dim, value in values.items():
        dim_bounds = bounds.get(dim)
        if dim_bounds is None:
            return np.zeros(bounds.size, dtype=bool)
        lower, upper = dim_bounds
        value = _normalize_coord_scalar(value)
        try:
            current = np.asarray((lower <= value) & (value <= upper), dtype=bool)
        except (TypeError, ValueError):
            current = np.fromiter(
                (
                    _value_within_bounds(low, high, value)
                    for low, high in zip(lower, upper, strict=True)
                ),
                dtype=bool,
                count=bounds.size,
            )
        out &= current
        if not out.any():
            break
    return out


def _span_overlap_array(
    dim: str,
    start: Any,
    end: Any,
    bounds: _ContentsBounds,
) -> np.ndarray:
    """Return rows whose extent intersects one annotation span."""
    dim_bounds = bounds.get(dim)
    if dim_bounds is None:
        return np.zeros(bounds.size, dtype=bool)
    lower, upper = dim_bounds
    start, end = _ordered_pair(start, end)
    try:
        return np.asarray((end >= lower) & (start <= upper), dtype=bool)
    except (TypeError, ValueError):
        return np.fromiter(
            (
                _spans_intersect(low, high, start, end)
                for low, high in zip(lower, upper, strict=True)
            ),
            dtype=bool,
            count=bounds.size,
        )


def _value_within_bounds(lower: Any, upper: Any, value: Any) -> bool:
    """Safely compare one scalar with one pair of bounds."""
    try:
        return bool(lower <= value <= upper)
    except (TypeError, ValueError):
        return False


def _spans_intersect(lower: Any, upper: Any, start: Any, end: Any) -> bool:
    """Safely compare two scalar intervals."""
    try:
        return bool(end >= lower and start <= upper)
    except (TypeError, ValueError):
        return False


def _normalize_coord_array(values: np.ndarray) -> np.ndarray:
    """Normalize object arrays while preserving native numeric/time dtypes."""
    values = np.asarray(values)
    if values.dtype != object:
        return values
    return np.asarray(
        [_normalize_coord_scalar(value) for value in values], dtype=object
    )


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
    """Return one pair ordered from low to high, normalizing scalars first."""
    first = _normalize_coord_scalar(first)
    second = _normalize_coord_scalar(second)
    if first is None or second is None:
        return first, second
    return ordered_pair(first, second)


def _normalize_coord_scalar(value: Any) -> Any:
    """Normalize scalars into comparison-friendly pandas/Python values."""
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None:
            return value.tz_convert("UTC").tz_localize(None)
        return value
    if isinstance(value, pd.Timedelta):
        return value
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value)
    if isinstance(value, np.timedelta64):
        return pd.Timedelta(value)
    if isinstance(value, datetime):
        return _normalize_coord_scalar(pd.Timestamp(value))
    if isinstance(value, timedelta):
        return pd.Timedelta(value)
    if isinstance(value, np.generic):
        return value.item()
    return value
