"""
Tests for DerZug's model.
"""

from __future__ import annotations

import warnings
from typing import ClassVar

import pytest
from derzug.core.zugmodel import DerZugModel
from derzug.exceptions import DerZugError, DerZugWarning

# ---------------------------------------------------------------------------
# DerZugModel.__init_subclass__ validation
# ---------------------------------------------------------------------------


class TestInitSubclassValidation:
    """DerZugModel warns when a subclass overrides errors/warnings without 'general'."""

    def test_missing_general_in_errors_warns(self):
        """Defining errors without 'general' emits a UserWarning."""
        with warnings.catch_warnings(record=True) as issued:
            warnings.simplefilter("always")

            class _M(DerZugModel):
                errors: ClassVar = {"load_failed": "Load failed: {}"}

        general_warnings = [
            w
            for w in issued
            if issubclass(w.category, UserWarning) and "general" in str(w.message)
        ]
        assert general_warnings, "Expected a warning about missing 'general' in errors"

    def test_missing_general_in_warnings_warns(self):
        """Defining warnings without 'general' emits a UserWarning."""
        with warnings.catch_warnings(record=True) as issued:
            warnings.simplefilter("always")

            class _M(DerZugModel):
                warnings: ClassVar = {"no_data": "No data"}  # type: ignore[assignment]

        general_warnings = [
            w
            for w in issued
            if issubclass(w.category, UserWarning) and "general" in str(w.message)
        ]
        assert general_warnings

    def test_general_present_no_warning(self):
        """Including 'general' in a custom errors dict suppresses the warning."""
        with warnings.catch_warnings(record=True) as issued:
            warnings.simplefilter("always")

            class _M(DerZugModel):
                errors: ClassVar = {
                    "load_failed": "Load failed: {}",
                    "general": "An unexpected error: {}",
                }

        missing_general_warnings = [
            w
            for w in issued
            if issubclass(w.category, UserWarning) and "general" in str(w.message)
        ]
        assert not missing_general_warnings

    def test_no_override_no_warning(self):
        """A subclass that doesn't override errors/warnings emits no warning."""
        with warnings.catch_warnings(record=True) as issued:
            warnings.simplefilter("always")

            class _M(DerZugModel):
                pass

        missing_general_warnings = [
            w
            for w in issued
            if issubclass(w.category, UserWarning) and "general" in str(w.message)
        ]
        assert not missing_general_warnings


# ---------------------------------------------------------------------------
# DerZugError / DerZugWarning
# ---------------------------------------------------------------------------


class TestDerZugError:
    """DerZugError carries a key and optional format args."""

    def test_key_stored(self):
        """The key passed to DerZugError is accessible as .key."""
        exc = DerZugError("load_failed", "f.hdf5")
        assert exc.key == "load_failed"

    def test_fmt_args_stored(self):
        """Format args passed after the key are stored as .fmt_args."""
        exc = DerZugError("load_failed", "f.hdf5", "not found")
        assert exc.fmt_args == ("f.hdf5", "not found")

    def test_is_exception(self):
        """DerZugError is raiseable as a standard Python exception."""
        with pytest.raises(DerZugError):
            raise DerZugError("general")


class TestDerZugWarning:
    """DerZugWarning carries a key and optional format args."""

    def test_key_stored(self):
        """The key is accessible as .key on the warning instance."""
        w = DerZugWarning("no_data")
        assert w.key == "no_data"

    def test_is_user_warning(self):
        """DerZugWarning is a subclass of UserWarning."""
        assert issubclass(DerZugWarning, UserWarning)
