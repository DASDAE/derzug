"""Tests for shared plot-axis helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from derzug.utils.plot_axes import ContextDateAxisItem, format_cursor_value


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
