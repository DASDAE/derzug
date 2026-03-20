"""Shared parsing helpers for textbox values."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from dascore.units import get_quantity

_NONE_TOKENS: frozenset[str] = frozenset({"", "none", "null"})
_INT_PATTERN = re.compile(r"^[+-]?\d+$")
_FLOAT_PATTERN = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+(?:[eE][+-]?\d+)|\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+)$"
)
_LEADING_NUMBER_PATTERN = re.compile(
    r"^[\s]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
)


def parse_text_value(text: str) -> int | float | str:
    """
    Parse a textbox value to the narrowest type implied by the input text.

    Integer-shaped text returns ``int``. Explicit float syntax, including
    decimal points and scientific notation, returns ``float``. Everything
    else returns the stripped string unchanged.
    """
    value = text.strip()
    if value == "":
        return ""
    if _INT_PATTERN.fullmatch(value):
        return int(value)
    if _FLOAT_PATTERN.fullmatch(value):
        return float(value)
    return value


def parse_patch_text_value(
    text: str,
    *,
    allow_none: bool = False,
    required: bool = False,
    allow_ellipsis: bool = False,
    allow_quantity: bool = True,
) -> Any | None:
    """
    Parse a textbox value destined for a DASCore patch method.

    This preserves numeric intent from the raw text, while still supporting
    unit-bearing quantities and widget-level sentinels.
    """
    value = text.strip()
    lowered = value.lower()

    if allow_none and lowered in _NONE_TOKENS:
        return None
    if required and lowered in _NONE_TOKENS:
        raise ValueError("value must not be empty")
    if allow_ellipsis and value == "...":
        return Ellipsis

    parsed = parse_text_value(value)
    if not isinstance(parsed, str):
        return parsed
    if not allow_quantity:
        raise ValueError(f"could not parse value {text!r}")

    quantity = get_quantity(value)
    if not getattr(quantity, "dimensionless", False):
        return quantity

    magnitude = quantity.magnitude
    if isinstance(magnitude, int):
        return magnitude
    if isinstance(magnitude, float):
        if _looks_integer_like(value) and magnitude.is_integer():
            return int(magnitude)
        return float(magnitude)

    magnitude_text = str(magnitude)
    magnitude_value = parse_text_value(magnitude_text)
    if isinstance(magnitude_value, int) and not _looks_integer_like(value):
        return float(magnitude)
    return magnitude_value


def parse_timedelta_text(text: str) -> np.timedelta64:
    """Parse free-form timedelta text, including `format_display` output."""
    try:
        return np.timedelta64(text)
    except Exception:
        pass

    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"unsupported timedelta text '{text}'")
    value_text, unit_text = parts
    unit_key = unit_text.strip().lower()
    unit_map = {
        "attosecond": "as",
        "attoseconds": "as",
        "femtosecond": "fs",
        "femtoseconds": "fs",
        "picosecond": "ps",
        "picoseconds": "ps",
        "nanosecond": "ns",
        "nanoseconds": "ns",
        "microsecond": "us",
        "microseconds": "us",
        "millisecond": "ms",
        "milliseconds": "ms",
        "second": "s",
        "seconds": "s",
        "minute": "m",
        "minutes": "m",
        "hour": "h",
        "hours": "h",
        "day": "D",
        "days": "D",
        "week": "W",
        "weeks": "W",
    }
    unit = unit_map.get(unit_key)
    if unit is None:
        raise ValueError(f"unsupported timedelta unit '{unit_text}'")
    return np.timedelta64(int(value_text), unit)


def parse_coord_text_value(text: str, sample: Any, fallback: Any) -> Any:
    """Parse UI text into a coordinate-compatible value using sample dtype."""
    stripped = text.strip()
    if not stripped:
        return fallback

    sample_dtype = getattr(np.asarray(sample), "dtype", None)
    if sample_dtype is not None and np.issubdtype(sample_dtype, np.datetime64):
        return np.datetime64(stripped)
    if sample_dtype is not None and np.issubdtype(sample_dtype, np.timedelta64):
        unit = np.datetime_data(sample_dtype)[0]
        if any(char.isalpha() for char in stripped):
            return parse_timedelta_text(stripped)
        parsed = parse_patch_text_value(stripped, required=True)
        if isinstance(parsed, str):
            return parse_timedelta_text(stripped)
        return np.timedelta64(int(parsed), unit)

    parsed = parse_patch_text_value(stripped, required=True)
    if sample_dtype is not None and np.issubdtype(sample_dtype, np.integer):
        return int(parsed)
    if sample_dtype is not None and np.issubdtype(sample_dtype, np.floating):
        return float(parsed)
    return parsed


def _looks_integer_like(text: str) -> bool:
    """Return True when the leading numeric token is integer-shaped."""
    match = _LEADING_NUMBER_PATTERN.match(text)
    if not match:
        return False
    return _INT_PATTERN.fullmatch(match.group(1)) is not None
