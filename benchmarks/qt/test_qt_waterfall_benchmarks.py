"""Benchmarks for the Waterfall widget's level computation and render path."""

from __future__ import annotations

import itertools

import pytest

pytest.importorskip("AnyQt.QtWidgets", reason="Qt is not installed")
pytest.importorskip("pyqtgraph", reason="pyqtgraph is not installed")

from derzug.widgets.waterfall import Waterfall  # noqa: E402


@pytest.fixture(scope="module")
def alternating_patches(patch_small, patch_large):
    """Return an endless alternation of two differently shaped patches."""
    return itertools.cycle((patch_small, patch_large))


class TestWaterfallBenchmarks:
    """Benchmarks for :class:`derzug.widgets.waterfall.Waterfall`."""

    @pytest.mark.benchmark
    def test_compute_default_levels(self, patch_large):
        """Derive display levels from a five-million element patch.

        This is the real call site of the strided-subsample optimisation.
        """
        Waterfall._compute_default_levels(patch_large.data)

    @pytest.mark.benchmark
    def test_should_reset_identical(self, patch_large, patch_large_copy):
        """Compare two distinct patches holding identical coordinates."""
        Waterfall._should_reset_view_for_new_patch(patch_large, patch_large_copy)

    @pytest.mark.benchmark
    def test_render_alternating_patches(
        self, waterfall_widget, qapp, alternating_patches
    ):
        """Render alternating patch shapes, forcing a full view reset each time."""
        waterfall_widget.set_patch(next(alternating_patches))
        qapp.processEvents()
        waterfall_widget.grab()

    @pytest.mark.benchmark
    def test_render_same_patch(self, waterfall_widget, qapp, patch_large):
        """Re-render the same patch.

        The fast path: ``_should_reset_view_for_new_patch`` returns False, so
        levels and view ranges are reused.
        """
        waterfall_widget.set_patch(patch_large)
        qapp.processEvents()
        waterfall_widget.grab()
