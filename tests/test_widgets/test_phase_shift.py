"""Tests for the phase-shift dispersion widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.utils.testing import (
    TestWidgetDefaults,
    capture_output,
    wait_for_output,
    wait_for_widget_idle,
    widget_context,
)
from derzug.widgets.phase_shift import PhaseShiftTransform, PhaseShiftTransformTask


@pytest.fixture
def phase_shift_widget(qtbot):
    """Return a live Phase Shift widget for one test case."""
    with widget_context(PhaseShiftTransform) as widget:
        yield widget


class TestPhaseShiftTransform:
    """Tests for the Phase Shift widget."""

    def test_widget_instantiates(self, phase_shift_widget):
        """Widget creates with expected defaults."""
        assert isinstance(phase_shift_widget, PhaseShiftTransform)
        assert phase_shift_widget.velocity_min == "100"
        assert phase_shift_widget.velocity_max == "1500"
        assert phase_shift_widget.velocity_step == "1"
        assert phase_shift_widget.approx_resolution == "0.1"
        assert phase_shift_widget.frequency_min == "5"
        assert phase_shift_widget.frequency_max == "70"
        assert phase_shift_widget.flip_distance is False

    def test_patch_none_emits_none(self, phase_shift_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)

        phase_shift_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_valid_dispersion_event_emits_frequency_velocity_patch(
        self, phase_shift_widget, monkeypatch
    ):
        """A valid dispersion gather emits a dispersion-image patch."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("dispersion_event")
        phase_shift_widget.velocity_min = "100"
        phase_shift_widget.velocity_max = "160"
        phase_shift_widget.velocity_step = "20"
        phase_shift_widget.approx_resolution = "1"
        phase_shift_widget.frequency_min = "5"
        phase_shift_widget.frequency_max = "20"

        phase_shift_widget.set_patch(patch)
        wait_for_widget_idle(phase_shift_widget)

        out = received[-1]
        assert out is not None
        assert out.dims == ("velocity", "frequency")
        assert out.shape == (3, 15)
        assert not phase_shift_widget.Error.transform_failed.is_shown()

    def test_settings_reach_patch_method(self, phase_shift_widget, monkeypatch, qtbot):
        """Parsed settings should reach dispersion_phase_shift."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("dispersion_event")
        captured: dict[str, object] = {}

        def _fake_dispersion_phase_shift(
            phase_velocities,
            *,
            approx_resolution=None,
            approx_freq=None,
        ):
            captured["phase_velocities"] = np.asarray(phase_velocities)
            captured["approx_resolution"] = approx_resolution
            captured["approx_freq"] = approx_freq
            return patch

        monkeypatch.setattr(
            patch,
            "dispersion_phase_shift",
            _fake_dispersion_phase_shift,
        )
        phase_shift_widget.velocity_min = "100"
        phase_shift_widget.velocity_max = "175"
        phase_shift_widget.velocity_step = "25"
        phase_shift_widget.approx_resolution = ""
        phase_shift_widget.frequency_min = "5"
        phase_shift_widget.frequency_max = "30"

        phase_shift_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert np.array_equal(captured["phase_velocities"], np.array([100, 125, 150]))
        assert captured["approx_resolution"] is None
        assert captured["approx_freq"] == (5.0, 30.0)

    def test_blank_frequency_bounds_reach_patch_method_as_none(
        self, phase_shift_widget, monkeypatch, qtbot
    ):
        """Blank frequency bounds should use DASCore defaults."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("dispersion_event")
        captured: dict[str, object] = {}

        def _fake_dispersion_phase_shift(
            phase_velocities,
            *,
            approx_resolution=None,
            approx_freq=None,
        ):
            _ = phase_velocities, approx_resolution
            captured["approx_freq"] = approx_freq
            return patch

        monkeypatch.setattr(
            patch,
            "dispersion_phase_shift",
            _fake_dispersion_phase_shift,
        )
        phase_shift_widget.velocity_min = "100"
        phase_shift_widget.velocity_max = "120"
        phase_shift_widget.frequency_min = ""
        phase_shift_widget.frequency_max = ""

        phase_shift_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["approx_freq"] is None

    def test_task_flip_distance_before_transform(self):
        """The task flips left-sided gathers before the transform when requested."""
        calls: list[str] = []

        class _FakePatch:
            def flip(self, dim):
                calls.append(f"flip:{dim}")
                return self

            def dispersion_phase_shift(
                self,
                phase_velocities,
                *,
                approx_resolution=None,
                approx_freq=None,
            ):
                _ = phase_velocities, approx_resolution, approx_freq
                calls.append("dispersion")
                return "out"

        task = PhaseShiftTransformTask(
            velocity_min=100,
            velocity_max=120,
            velocity_step=10,
            flip_distance=True,
        )

        assert task.run(_FakePatch()) == "out"
        assert calls == ["flip:distance", "dispersion"]

    def test_patch_without_time_or_distance_shows_error(
        self, phase_shift_widget, monkeypatch, qtbot
    ):
        """Inputs missing required dimensions should emit None."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("dispersion_event").rename_coords(
            distance="channel"
        )

        phase_shift_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert phase_shift_widget.Error.invalid_patch.is_shown()

    def test_invalid_velocity_settings_show_error(
        self, phase_shift_widget, monkeypatch, qtbot
    ):
        """Invalid velocity ranges should show a widget error."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        phase_shift_widget.velocity_min = "200"
        phase_shift_widget.velocity_max = "100"

        phase_shift_widget.set_patch(dc.get_example_patch("dispersion_event"))
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert phase_shift_widget.Error.invalid_velocity.is_shown()

    def test_invalid_frequency_settings_show_error(
        self, phase_shift_widget, monkeypatch, qtbot
    ):
        """Invalid frequency ranges should show a widget error."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        phase_shift_widget.frequency_min = "70"
        phase_shift_widget.frequency_max = "5"

        phase_shift_widget.set_patch(dc.get_example_patch("dispersion_event"))
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert phase_shift_widget.Error.invalid_frequency.is_shown()

    def test_invalid_resolution_shows_error(
        self, phase_shift_widget, monkeypatch, qtbot
    ):
        """Invalid frequency resolution should show a widget error."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        phase_shift_widget.approx_resolution = "-1"

        phase_shift_widget.set_patch(dc.get_example_patch("dispersion_event"))
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert phase_shift_widget.Error.invalid_resolution.is_shown()

    def test_transform_failure_shows_error(
        self, phase_shift_widget, monkeypatch, qtbot
    ):
        """Transform exceptions should show a widget error and emit None."""
        received = capture_output(phase_shift_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("dispersion_event")

        def _raise(*_args, **_kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "dispersion_phase_shift", _raise)
        phase_shift_widget.velocity_min = "100"
        phase_shift_widget.velocity_max = "120"

        phase_shift_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert phase_shift_widget.Error.transform_failed.is_shown()


class TestPhaseShiftTransformDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for Phase Shift."""

    __test__ = True
    widget = PhaseShiftTransform
