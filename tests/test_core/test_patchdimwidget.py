"""Tests for PatchDimWidget helpers."""

from __future__ import annotations

import dascore as dc
import pytest
from AnyQt.QtWidgets import QComboBox
from derzug.core.patchdimwidget import PatchDimWidget
from derzug.utils.testing import widget_context
from Orange.widgets.utils.signals import Output


class _PatchDimHarness(PatchDimWidget):
    """Minimal widget used to exercise PatchDimWidget helper methods."""

    name = "PatchDim Harness"
    description = "PatchDimWidget harness"
    category = "Tests"
    selected_dim = ""

    class Outputs:
        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        self._dim_combo = QComboBox(self.controlArea)
        self.controlArea.layout().addWidget(self._dim_combo)


@pytest.fixture
def patchdim_widget(qtbot):
    """Return a live PatchDimWidget harness."""
    with widget_context(_PatchDimHarness) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget


def test_get_dim_returns_none_without_available_dims(patchdim_widget):
    """No dims should yield None rather than raising or inventing a selection."""
    assert patchdim_widget._get_dim() is None


def test_get_dim_repairs_invalid_selected_dim(patchdim_widget):
    """An invalid persisted dimension should be reset to the default choice."""
    patch = dc.get_example_patch("example_event_2")
    patchdim_widget.selected_dim = "not-a-dim"
    patchdim_widget._set_patch_input(patch)

    assert patchdim_widget._get_dim() == "time"
    assert patchdim_widget.selected_dim == "time"
    assert patchdim_widget._dim_combo.currentText() == "time"


def test_dim_combo_options_sorted_alphabetically(patchdim_widget):
    """Dimension dropdowns should present patch dims in sorted order."""

    class _PatchStub:
        dims = ("z", "time", "distance")

    patchdim_widget._set_patch_input(_PatchStub())

    options = [
        patchdim_widget._dim_combo.itemText(i)
        for i in range(patchdim_widget._dim_combo.count())
    ]

    assert options == ["distance", "time", "z"]
    assert patchdim_widget._dim_combo.currentText() == "time"


def test_on_result_forwards_patch_output(patchdim_widget, monkeypatch):
    """The shared result hook should forward the emitted patch unchanged."""
    received: list[dc.Patch] = []
    patch = dc.get_example_patch("example_event_2")
    monkeypatch.setattr(patchdim_widget.Outputs.patch, "send", received.append)

    patchdim_widget._on_result(patch)

    assert received == [patch]
