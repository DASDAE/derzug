"""Tests for shared plot-axis helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from derzug.utils.plot_axes import (
    ContextDateAxisItem,
    format_cursor_value,
    map_coord_to_plot_value,
    map_plot_value_to_coord,
    nearest_axis_index,
    nearest_value_index,
)


def _timestamp(year: int, month: int, day: int) -> float:
    """Return one UTC timestamp for test date-axis coordinates."""
    return datetime(year, month, day, tzinfo=UTC).timestamp()


def _day_ticks(axis: ContextDateAxisItem) -> list[float]:
    """Return day-level tick values for a fixed multi-day range."""
    values = axis.tickValues(
        _timestamp(2024, 1, 1),
        _timestamp(2024, 1, 5),
        800,
    )
    for spacing, ticks in values:
        if spacing == 24 * 60 * 60:
            return ticks
    return []


class TestContextDateAxisItem:
    """Tests for DerZug's timezone-naive datetime axis."""

    def test_day_ticks_use_naive_midnight_positions(self, qapp):
        """Day ticks should land on UTC-like midnight, not local-time boundaries."""
        axis = ContextDateAxisItem(orientation="bottom")

        ticks = _day_ticks(axis)

        assert ticks
        assert all(tick % (24 * 60 * 60) == 0 for tick in ticks)

    def test_day_ticks_ignore_later_utc_offset_mutation(self, qapp):
        """A nonzero utcOffset should not shift DerZug's naive datetime ticks."""
        axis = ContextDateAxisItem(orientation="bottom")
        axis.utcOffset = -(60 * 60)

        ticks = _day_ticks(axis)

        assert ticks
        assert all(tick % (24 * 60 * 60) == 0 for tick in ticks)
        assert axis.utcOffset == -(60 * 60)


class TestFormatCursorValue:
    """Tests for cursor-specific value formatting."""

    def test_float_precision_tracks_visible_span(self):
        """Float cursor values should use the visible extent as display context."""
        assert format_cursor_value(12345.6789, visible_span=1.0) == "12345.679"
        assert format_cursor_value(12345.6789, visible_span=1000.0) == "12346"

    def test_invalid_visible_span_uses_generic_display_format(self):
        """Missing or invalid extent context should preserve existing formatting."""
        assert format_cursor_value(12345.6789) == "1.23e+04"
        assert format_cursor_value(12345.6789, visible_span=0.0) == "1.23e+04"
        assert format_cursor_value(12345.6789, visible_span=np.nan) == "1.23e+04"

    def test_datetime_precision_tracks_visible_span(self):
        """Datetime cursor values should omit unresolvable sub-second digits."""
        value = np.datetime64("2024-01-02T03:04:05.006789123")

        assert (
            format_cursor_value(value, visible_span=60.0) == "2024-01-02T03:04:05.006"
        )
        assert (
            format_cursor_value(value, visible_span=0.001)
            == "2024-01-02T03:04:05.006789"
        )

    def test_timedelta_precision_tracks_visible_span(self):
        """Timedelta cursor values should use the same extent-derived quantum."""
        value = np.timedelta64(5_006_789_123, "ns")

        assert format_cursor_value(value, visible_span=60.0) == "5.01 s"
        assert format_cursor_value(value, visible_span=0.001) == "5.006789 s"


class TestNearestAxisIndex:
    """Tests for allocation-free monotonic coordinate lookup."""

    def test_ascending_axis_uses_nearest_neighbor(self):
        """Ascending lookup should clamp and resolve values between samples."""
        axis = np.asarray([0.0, 10.0, 20.0, 30.0])

        assert nearest_axis_index(-1.0, axis) == 0
        assert nearest_axis_index(14.0, axis) == 1
        assert nearest_axis_index(16.0, axis) == 2
        assert nearest_axis_index(99.0, axis) == 3

    def test_descending_axis_preserves_original_indices(self):
        """Descending lookup should search a view and map back to source indices."""
        axis = np.asarray([30.0, 20.0, 10.0, 0.0])

        assert nearest_axis_index(29.0, axis) == 0
        assert nearest_axis_index(14.0, axis) == 2
        assert nearest_axis_index(-1.0, axis) == 3

    def test_empty_and_nonfinite_values_return_safe_index(self):
        """Degenerate cursor inputs should resolve without allocating or raising."""
        assert nearest_axis_index(1.0, np.asarray([])) == 0
        assert nearest_axis_index(np.nan, np.asarray([1.0, 2.0])) == 0


class TestNearestValueIndex:
    """Tests for nearest lookup on unsorted arrays."""

    def test_unsorted_values_use_true_nearest(self):
        """Unsorted data must resolve by distance, not sorted insertion."""
        values = np.asarray([0.0, 10.0, 2.0, 8.0, 4.0])

        assert nearest_value_index(9.9, values) == 1
        assert nearest_value_index(3.1, values) == 4
        assert nearest_value_index(-5.0, values) == 0

    def test_degenerate_inputs_return_safe_index(self):
        """Empty, non-finite, and all-nan inputs should resolve to zero."""
        assert nearest_value_index(1.0, np.asarray([])) == 0
        assert nearest_value_index(np.nan, np.asarray([1.0, 2.0])) == 0
        assert nearest_value_index(1.0, np.asarray([np.nan, np.nan])) == 0

    def test_nan_entries_are_skipped(self):
        """NaN entries must never win the nearest-distance comparison."""
        values = np.asarray([np.nan, 5.0, 1.0])

        assert nearest_value_index(4.0, values) == 1


class TestAxisValueMapping:
    """Tests for neighbor-only interpolation in cursor mapping paths."""

    def test_numeric_mapping_interpolates_and_extrapolates(self):
        """Numeric axes should retain linear mapping outside and between samples."""
        plot = np.asarray([0.0, 1.0, 2.0])
        coord = np.asarray([10.0, 20.0, 30.0])

        assert map_plot_value_to_coord(0.5, plot, coord) == 15.0
        assert map_plot_value_to_coord(3.0, plot, coord) == 40.0
        assert map_coord_to_plot_value(25.0, coord, plot) == 1.5

    def test_descending_datetime_mapping_preserves_nanosecond_values(self):
        """Descending datetime axes should map without converting whole arrays."""
        coord = np.asarray(
            [
                "2024-01-01T00:00:02.000000000",
                "2024-01-01T00:00:01.000000000",
                "2024-01-01T00:00:00.000000000",
            ],
            dtype="datetime64[ns]",
        )
        plot = np.asarray([2.0, 1.0, 0.0])

        mapped = map_plot_value_to_coord(0.5, plot, coord)

        assert mapped == np.datetime64("2024-01-01T00:00:00.500000000")
        assert map_coord_to_plot_value(mapped, coord, plot) == 0.5
