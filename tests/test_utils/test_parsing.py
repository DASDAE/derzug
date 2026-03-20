"""Tests for derzug.utils.parsing."""

from __future__ import annotations

import numpy as np
import pytest
from derzug.utils.parsing import (
    parse_coord_text_value,
    parse_patch_text_value,
    parse_text_value,
    parse_timedelta_text,
)


class TestParseTextValue:
    """Tests for generic textbox coercion."""

    @pytest.mark.parametrize(
        ("text", "expected", "expected_type"),
        [
            ("5", 5, int),
            ("-5", -5, int),
            (" 5 ", 5, int),
            ("2.0", 2.0, float),
            (".5", 0.5, float),
            ("1e3", 1000.0, float),
            ("abc", "abc", str),
            ("", "", str),
        ],
    )
    def test_parse_text_value(self, text, expected, expected_type):
        """The parser preserves the type implied by the text."""
        out = parse_text_value(text)
        assert out == expected
        assert type(out) is expected_type


class TestParsePatchTextValue:
    """Tests for DASCore-facing textbox coercion."""

    def test_blank_maps_to_none_when_allowed(self):
        """Blank values map to None for optional patch parameters."""
        assert parse_patch_text_value("", allow_none=True) is None

    def test_none_tokens_map_to_none_when_allowed(self):
        """Known none-like tokens map to None for optional patch parameters."""
        assert parse_patch_text_value("null", allow_none=True) is None
        assert parse_patch_text_value("None", allow_none=True) is None

    def test_required_blank_raises(self):
        """Required values reject blank input."""
        with pytest.raises(ValueError, match="must not be empty"):
            parse_patch_text_value("", required=True)

    def test_ellipsis_is_supported_when_enabled(self):
        """Ellipsis tokens are preserved for pass-filter bounds."""
        assert parse_patch_text_value("...", allow_ellipsis=True) is Ellipsis

    def test_unit_values_return_quantities(self):
        """Unit-bearing values remain quantities for DASCore calls."""
        out = parse_patch_text_value("10 ms")
        assert getattr(out, "magnitude", None) == 10

    def test_dimensionless_integer_intent_stays_int(self):
        """Integer-shaped dimensionless values stay ints."""
        out = parse_patch_text_value("5")
        assert out == 5
        assert isinstance(out, int)

    def test_dimensionless_float_intent_stays_float(self):
        """Explicit float syntax stays float even when numerically integral."""
        out = parse_patch_text_value("2.0")
        assert out == 2.0
        assert isinstance(out, float)

    def test_invalid_non_quantity_raises(self):
        """Invalid values still raise for numeric-only callers."""
        with pytest.raises(ValueError, match="could not parse value"):
            parse_patch_text_value("abc", allow_quantity=False)


class TestParseTimedeltaText:
    """Tests for explicit timedelta parsing."""

    def test_named_units_are_supported(self):
        """Human-readable units from display formatting should round-trip."""
        assert parse_timedelta_text("2000000 nanoseconds") == np.timedelta64(
            2000000, "ns"
        )

    def test_invalid_text_raises(self):
        """Unsupported timedelta text should fail clearly."""
        with pytest.raises(ValueError, match="unsupported timedelta"):
            parse_timedelta_text("soon")


class TestParseCoordTextValue:
    """Tests for sample-aware coord parsing."""

    def test_datetime_uses_datetime64(self):
        """Datetime-like samples parse ISO strings as datetime64 values."""
        sample = np.datetime64("2024-01-02T03:04:05")
        out = parse_coord_text_value("2024-01-03T00:00:00", sample, sample)
        assert out == np.datetime64("2024-01-03T00:00:00")

    def test_timedelta_supports_named_units(self):
        """Timedelta-like samples accept human-readable unit strings."""
        sample = np.timedelta64(1, "ms")
        out = parse_coord_text_value("2 milliseconds", sample, sample)
        assert out == np.timedelta64(2, "ms")

    def test_blank_returns_fallback(self):
        """Blank coord input preserves the provided fallback."""
        assert parse_coord_text_value("", 5, 9) == 9
