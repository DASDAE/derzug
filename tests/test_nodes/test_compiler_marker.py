"""Tests for the Qt-free ``get_task`` fallback probe and dimension resolver."""

from __future__ import annotations

import functools

import dascore as dc
import pytest
from derzug.core.zugwidget import ZugWidget
from derzug.workflow.compiler import DEFAULT_GET_TASK_MARKER, _uses_default_get_task
from derzug.workflow.dims import default_patch_dim, resolve_patch_dim
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask


class TestDefaultGetTaskProbe:
    """The marker probe must match the old ``is ZugWidget.get_task`` identity."""

    def test_base_fallback_is_detected(self):
        """A widget that never implements ``get_task`` uses the fallback."""

        class Bare:
            get_task = ZugWidget.get_task

        assert _uses_default_get_task(Bare())

    def test_real_override_is_not_detected(self):
        """A widget with its own ``get_task`` does not use the fallback."""

        class Implemented:
            def get_task(self):
                """Return nothing; only its identity matters here."""

        assert not _uses_default_get_task(Implemented())

    def test_wrapped_override_is_not_detected(self):
        """``functools.wraps`` copies ``__dict__``; the marker must survive that.

        A boolean marker would be copied onto the wrapper and misread the
        override as an unimplemented fallback, silently compiling a
        task-backed source widget as an external input.
        """

        class Wrapping:
            @functools.wraps(ZugWidget.get_task)
            def get_task(self):
                """Wrap the base contract while genuinely implementing it."""

        assert getattr(Wrapping.get_task, DEFAULT_GET_TASK_MARKER, None) is not None
        assert not _uses_default_get_task(Wrapping())

    def test_missing_get_task_is_not_detected(self):
        """An object with no ``get_task`` at all is not the fallback case."""
        assert not _uses_default_get_task(object())


class TestDimResolution:
    """Widgets and headless tasks must resolve a dimension identically."""

    def test_time_is_preferred(self):
        """``time`` wins over an earlier dimension."""
        assert default_patch_dim(("distance", "time")) == "time"

    def test_first_dim_when_no_time(self):
        """Without ``time`` the first dimension is the fallback."""
        assert default_patch_dim(("distance", "frequency")) == "distance"

    def test_no_dims(self):
        """An empty patch has no dimension to choose."""
        assert default_patch_dim(()) is None

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [("distance", "distance"), ("", "time"), (None, "time"), ("nope", "time")],
    )
    def test_resolve_falls_back(self, requested, expected):
        """An absent or unknown request falls back to the preferred dimension."""
        assert resolve_patch_dim(requested, ("distance", "time")) == expected

    def test_configured_method_task_resolves_a_blank_dim(self):
        """A headless task with no stored dimension still runs."""
        patch = dc.get_example_patch("example_event_2")
        assert patch.dims[0] != "time"
        task = PatchConfiguredMethodTask(
            method_name="taper", call_style="keyword_dim", dim="", dim_value=0.05
        )
        assert isinstance(task.run(patch), dc.Patch)

    def test_configured_method_task_needs_some_dimension(self):
        """A method needing a dimension fails clearly when the patch has none."""
        task = PatchConfiguredMethodTask(
            method_name="taper", call_style="keyword_dim", dim="", dim_value=0.05
        )

        class _DimlessPatch:
            dims = ()

            def taper(self, **kwargs):
                """Never reached; the task must fail before calling this."""

        with pytest.raises(ValueError, match="needs a dimension"):
            task.run(_DimlessPatch())
