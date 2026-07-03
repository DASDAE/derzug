"""Tests for shared UI display formatting."""

from __future__ import annotations

import numpy as np
from derzug.utils.display import format_display, format_nd_coord_value


class TestFormatDisplay:
    """Tests for the shared display formatter."""

    def test_none_is_blank(self):
        """None should render as an empty string."""
        assert format_display(None) == ""

    def test_float_uses_shared_sigfigs(self):
        """Python floats should use the shared significant-figures setting."""
        assert format_display(0.0054321) == "0.00543"

    def test_numpy_float_uses_shared_sigfigs(self):
        """NumPy floating scalars should format like Python floats."""
        assert format_display(np.float64(1234.567)) == "1.23e+03"

    def test_int_is_decimal_string(self):
        """Python ints should render as plain decimal strings."""
        assert format_display(12) == "12"

    def test_numpy_int_is_decimal_string(self):
        """NumPy integer scalars should render as plain decimal strings."""
        assert format_display(np.int64(12)) == "12"

    def test_datetime_uses_iso_string(self):
        """Datetime scalars should render as naive ISO strings."""
        value = np.datetime64("2024-01-02T03:04:05.006")
        assert format_display(value) == "2024-01-02T03:04:05.006000000"

    def test_timedelta_uses_human_readable(self):
        """Timedelta scalars should render as a concise human-readable string."""
        assert format_display(np.timedelta64(5432100, "ns")) == "5.43 ms"
        assert format_display(np.timedelta64(10, "s")) == "10 s"

    def test_fallback_uses_str(self):
        """Non-special values should fall back to their string representation."""
        assert format_display({"a": 1}) == "{'a': 1}"


class TestFormatNdCoordValue:
    """Tests for the compact slider-label formatter."""

    def test_float_uses_4g_format(self):
        """Floats use four significant figures (more compact than format_display)."""
        assert format_nd_coord_value(np.float64(1234.5678)) == "1235"
        assert format_nd_coord_value(np.float64(0.000123456)) == "0.0001235"

    def test_integer_returns_plain_string(self):
        """Integers render as plain decimal strings."""
        assert format_nd_coord_value(np.int64(42)) == "42"

    def test_datetime64_strips_trailing_zeros(self):
        """Datetime64 values strip trailing fractional zeros (raw, not ISO)."""
        val = np.datetime64("2020-01-03T00:00:01.500000000")
        result = format_nd_coord_value(val)
        assert result == "2020-01-03T00:00:01.5"
        assert not result.endswith("0")

    def test_datetime64_no_fractional_part(self):
        """Datetime64 with zero fraction omits the decimal point entirely."""
        val = np.datetime64("2020-01-03T12:00:00.000000000")
        assert format_nd_coord_value(val) == "2020-01-03T12:00:00"

    def test_timedelta_renders_as_truncated_string(self):
        """Timedelta-like values render as raw strings for slider labels."""
        assert format_nd_coord_value(np.timedelta64(5, "s")) == "5 seconds"

    def test_long_fallback_is_capped(self):
        """Non-scalar fallbacks are capped at 20 characters for slider overlays."""
        assert format_nd_coord_value("x" * 40) == "x" * 20
