"""Shared display formatting helpers for UI text."""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np

from derzug.constants import DISPLAY_SIGFIGS


def _format_duration(seconds: float) -> str:
    """Format a duration as a concise, human-readable string."""
    abs_s = abs(seconds)
    if abs_s < 1e-6:
        return f"{seconds * 1e9:.3g} ns"
    if abs_s < 1e-3:
        return f"{seconds * 1e6:.3g} µs"
    if abs_s < 1.0:
        return f"{seconds * 1e3:.3g} ms"
    if abs_s < 60.0:
        return f"{seconds:.4g} s"
    m, s = divmod(seconds, 60.0)
    if abs_s < 3600.0:
        return f"{int(m)} m {s:.3g} s"
    h, rem = divmod(seconds, 3600.0)
    return f"{int(h)} h {int(rem / 60)} m"


def format_display(value: Any) -> str:
    """Return a stable UI display string for scalar values."""
    if value is None:
        return ""

    # Handle timedelta before np.asarray: pd.Timedelta is a datetime.timedelta
    # subclass but np.asarray returns object dtype in recent pandas versions.
    if isinstance(value, datetime.timedelta):
        return _format_duration(value.total_seconds())

    arr = np.asarray(value)
    if np.issubdtype(arr.dtype, np.datetime64):
        return np.datetime_as_string(arr.astype("datetime64[ns]"), timezone="naive")
    if np.issubdtype(arr.dtype, np.timedelta64):
        seconds = float(arr.astype("timedelta64[ns]").astype(np.int64)) / 1e9
        return _format_duration(seconds)

    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, float):
        return f"{value:.{DISPLAY_SIGFIGS}g}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def format_nd_coord_value(value: Any) -> str:
    """Return a compact display string for a slice-slider coordinate label.

    Unlike :func:`format_display`, this favors brevity over precision: raw
    datetime/timedelta strings (trimmed rather than reformatted), four
    significant figures for floats, and a hard 20-character cap on non-scalar
    fallbacks so slider overlays stay readable.
    """
    if isinstance(value, np.datetime64):
        text = str(value)
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    if isinstance(value, datetime.timedelta | np.timedelta64):
        return str(value)[:20]
    if isinstance(value, np.floating | float):
        return f"{float(value):.4g}"
    if isinstance(value, np.integer | int):
        return str(int(value))
    return str(value)[:20]
