"""Tests for the Fourier widget."""

from __future__ import annotations

import dascore as dc
import pytest
from AnyQt.QtCore import Qt
from derzug.utils.testing import (
    capture_output,
    wait_for_output,
    wait_for_widget_idle,
    widget_context,
)
from derzug.widgets.fourier import Fourier


@pytest.fixture
def fourier_widget(qtbot):
    """Return a live Fourier widget for one test case."""
    with widget_context(Fourier) as widget:
        yield widget


class TestFourier:
    """Tests for the Fourier widget."""

    def test_widget_instantiates(self, fourier_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(fourier_widget, Fourier)
        assert fourier_widget.transform == "dft"
        assert fourier_widget.real_mode == "Auto"
        assert fourier_widget.pad is True
        assert fourier_widget.selected_dims == []

    def test_patch_none_emits_none(self, fourier_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)

        fourier_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_dft_emits_patch(self, fourier_widget, monkeypatch, qtbot):
        """A forward DFT emits a Fourier-domain patch."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        out = received[-1]
        assert out is not None
        assert "ft_time" in out.dims

    def test_idft_selector_triggers_rerun(self, fourier_widget, monkeypatch, qtbot):
        """Changing the transform selector reruns with idft."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1").dft("time")
        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        fourier_widget._transform_combo.setCurrentText("idft")
        wait_for_widget_idle(fourier_widget)

        out = received[-1]
        assert fourier_widget.transform == "idft"
        assert out is not None
        assert "time" in out.dims

    def test_idft_works_on_fourier_domain_patch(
        self, fourier_widget, monkeypatch, qtbot
    ):
        """IDFT succeeds when the input patch already has a Fourier axis."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1").dft("time")

        fourier_widget.transform = "idft"
        fourier_widget.selected_dim = "ft_time"
        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        out = received[-1]
        assert out is not None
        assert "time" in out.dims

    def test_dft_dimension_list_change_triggers_rerun(
        self, fourier_widget, monkeypatch, qtbot
    ):
        """Checking another DFT dimension reruns and emits a fresh output."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        if fourier_widget._dim_list.count() < 2:
            pytest.skip("Need at least two dimensions for this test")

        current = set(fourier_widget.selected_dims)
        other_item = next(
            fourier_widget._dim_list.item(i)
            for i in range(fourier_widget._dim_list.count())
            if fourier_widget._dim_list.item(i).text() not in current
        )
        other_item.setCheckState(Qt.Checked)
        wait_for_widget_idle(fourier_widget)

        assert other_item.text() in fourier_widget.selected_dims
        out = received[-1]
        assert out is not None
        assert all(f"ft_{dim}" in out.dims for dim in fourier_widget.selected_dims)

    def test_real_output_reduces_spectral_length(
        self, fourier_widget, monkeypatch, qtbot
    ):
        """Real-valued DFT should reduce the transformed axis length."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        fourier_widget.real_mode = "Auto"
        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)
        full_out = received[-1]

        fourier_widget._real_combo.setCurrentText("Real")
        wait_for_widget_idle(fourier_widget)
        real_out = received[-1]

        assert full_out is not None
        assert real_out is not None
        full_axis = full_out.shape[full_out.dims.index("ft_time")]
        real_axis = real_out.shape[real_out.dims.index("ft_time")]
        assert real_axis < full_axis

    def test_pad_toggle_reaches_patch_method(self, fourier_widget, monkeypatch, qtbot):
        """The pad setting is passed through to patch.dft."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_dft(dim, *, real=None, pad=True):
            captured["dim"] = dim
            captured["real"] = real
            captured["pad"] = pad
            return patch

        monkeypatch.setattr(patch, "dft", _fake_dft)
        fourier_widget.pad = False
        fourier_widget.real_mode = "Complex"
        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        assert received[-1] is patch
        assert captured["dim"] == ("time",)
        assert captured["real"] is False
        assert captured["pad"] is False

    def test_invalid_transform_falls_back(self, fourier_widget, monkeypatch, qtbot):
        """Invalid transform setting falls back to the default."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        fourier_widget.transform = "not-a-transform"

        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        assert fourier_widget.transform == "dft"
        assert fourier_widget._transform_combo.currentText() == "dft"
        assert received[-1] is not None

    def test_invalid_dim_falls_back(self, fourier_widget, monkeypatch, qtbot):
        """Invalid dimension selection falls back to a valid axis."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        fourier_widget.selected_dim = "not-a-dim"

        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        assert fourier_widget.selected_dim == "time"
        assert fourier_widget._dim_combo.currentText() == "time"
        assert received[-1] is not None

    def test_invalid_selected_dims_fall_back_to_default(self, fourier_widget, qtbot):
        """Invalid forward-transform dims should repair to one available dim."""
        patch = dc.get_example_patch("example_event_1")
        fourier_widget.selected_dims = ["not-a-dim"]

        fourier_widget.set_patch(patch)
        qtbot.waitUntil(lambda: bool(fourier_widget.selected_dims), timeout=3000)

        assert fourier_widget.selected_dims == ["time"]
        checked = [
            fourier_widget._dim_list.item(i).text()
            for i in range(fourier_widget._dim_list.count())
            if fourier_widget._dim_list.item(i).checkState() == Qt.Checked
        ]
        assert checked == ["time"]

    def test_dft_multiple_dims_reach_patch(self, fourier_widget, monkeypatch, qtbot):
        """Forward DFT should pass all checked dimensions through to DASCore."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")
        captured: dict[str, object] = {}

        def _fake_dft(dim, *, real=None, pad=True):
            captured["dim"] = dim
            captured["real"] = real
            captured["pad"] = pad
            return patch

        monkeypatch.setattr(patch, "dft", _fake_dft)
        fourier_widget.selected_dims = ["time", "distance"]
        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        assert received[-1] is patch
        assert captured["dim"] == ("time", "distance")

    def test_idft_dimension_change_triggers_rerun(
        self, fourier_widget, monkeypatch, qtbot
    ):
        """Changing the IDFT combo selection reruns with the new Fourier axis."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1").dft(("time", "distance"))
        fourier_widget.transform = "idft"
        fourier_widget.set_patch(patch)
        wait_for_widget_idle(fourier_widget)

        if fourier_widget._dim_combo.count() < 2:
            pytest.skip("Need at least two Fourier dimensions for this test")

        current = fourier_widget.selected_dim
        other_dim = next(
            fourier_widget._dim_combo.itemText(i)
            for i in range(fourier_widget._dim_combo.count())
            if fourier_widget._dim_combo.itemText(i) != current
        )
        fourier_widget._dim_combo.setCurrentText(other_dim)
        wait_for_widget_idle(fourier_widget)

        assert fourier_widget.selected_dim == other_dim
        assert received[-1] is not None

    def test_transform_failed_shows_error(self, fourier_widget, monkeypatch, qtbot):
        """When the transform raises, the widget emits None and shows an error."""
        received = capture_output(fourier_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "dft", _raise)
        fourier_widget._patch = patch
        fourier_widget._available_dims = tuple(patch.dims)
        fourier_widget.selected_dim = "time"
        fourier_widget.transform = "dft"
        fourier_widget.run()
        wait_for_widget_idle(fourier_widget)

        assert received[-1] is None
        assert fourier_widget.Error.transform_failed.is_shown()
