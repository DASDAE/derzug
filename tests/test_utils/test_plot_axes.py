"""Tests for shared plot-axis helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from derzug.utils.plot_axes import ContextDateAxisItem


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

