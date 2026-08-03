"""Benchmarks for the Wiggle widget's render path.

Wiggle rendering carries a wide spread between consecutive renders of the
same widget (Qt item-pool warm-up), so treat these numbers as informational
unless they move by a large factor.
"""

from __future__ import annotations

import pytest

pytest.importorskip("AnyQt.QtWidgets", reason="Qt is not installed")
pytest.importorskip("pyqtgraph", reason="pyqtgraph is not installed")


class TestWiggleBenchmarks:
    """Benchmarks for :class:`derzug.widgets.wiggle.Wiggle`."""

    @pytest.mark.benchmark
    def test_render_small_patch(self, wiggle_widget, qapp, patch_small):
        """Render a 300x2000 patch as wiggle traces."""
        wiggle_widget.set_patch(patch_small)
        qapp.processEvents()
        wiggle_widget.grab()
