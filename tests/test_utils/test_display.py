"""Tests for shared UI display formatting."""

from __future__ import annotations

import numpy as np
from derzug.utils.display import format_display


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
