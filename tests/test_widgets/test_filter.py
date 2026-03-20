"""Tests for the Filter widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.utils.testing import (
    TestPatchDimWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.filter import _FILTER_NAMES, Filter


@pytest.fixture
def filter_widget():
    """Return a live Filter widget."""
    with widget_context(Filter) as widget:
        yield widget


def _set_gaussian_rows(filter_widget, rows: list[dict[str, str]]) -> None:
    """Persist Gaussian rows and sync the visible row widgets."""
    filter_widget.gaussian_dim_windows = rows
    filter_widget._restore_gaussian_rows()


class TestFilter:
    """Tests for the Filter widget."""

    def test_widget_instantiates(self, filter_widget):
        """Widget defaults to pass_filter with correct stack page."""
        assert filter_widget.selected_filter == "pass_filter"
        assert filter_widget._filter_combo.currentText() == "pass_filter"
        expected_idx = list(_FILTER_NAMES).index("pass_filter")
        assert filter_widget._stack.currentIndex() == expected_idx
        assert filter_widget.apply_taper is True
        assert filter_widget.taper_window == "0.01"

    def test_filter_dropdown_switches_page(self, filter_widget):
        """Changing the filter dropdown updates the stack page index."""
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        expected_idx = list(_FILTER_NAMES).index("gaussian_filter")
        assert filter_widget._stack.currentIndex() == expected_idx
        assert filter_widget.selected_filter == "gaussian_filter"

    def test_none_patch_emits_none(self, filter_widget, monkeypatch, qtbot):
        """set_patch(None) emits None."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        filter_widget.set_patch(None)
        wait_for_output(qtbot, received)
        assert received[-1] is None

    def test_pass_filter_no_bounds_passes_through(
        self, filter_widget, monkeypatch, qtbot
    ):
        """pass_filter with empty bounds passes the patch through unchanged."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget.low_bound = ""
        filter_widget.high_bound = ""
        filter_widget.taper_window = ""
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        assert received[-1] is patch

    def test_blank_taper_skips_taper(self, filter_widget, monkeypatch, qtbot):
        """Blank taper window disables tapering without raising an error."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget.low_bound = "1"
        filter_widget.high_bound = "10"
        filter_widget.taper_window = ""
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        expected = patch.pass_filter(corners=4, zerophase=True, time=(1.0, 10.0))
        assert out is not None
        assert np.array_equal(out.data, expected.data)

    def test_enabled_taper_applies_before_pass_filter(
        self, filter_widget, monkeypatch, qtbot
    ):
        """Enabled taper should run before pass_filter on the selected dim."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget.low_bound = "1"
        filter_widget.high_bound = "10"
        filter_widget.taper_window = "0.01"
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        expected = patch.taper(time=0.01).pass_filter(
            corners=4, zerophase=True, time=(1.0, 10.0)
        )
        assert out is not None
        assert np.array_equal(out.data, expected.data)

    def test_invalid_taper_raises_error(self, filter_widget, monkeypatch, qtbot):
        """Invalid non-blank taper shows error and emits None."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget.taper_window = "not-a-window"
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        assert received[-1] is None
        assert filter_widget.Error.general.is_shown()

    def test_pass_filter_with_bounds(self, filter_widget, monkeypatch, qtbot):
        """
        pass_filter with numeric bounds produces a filtered patch of the same shape.
        """
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget.low_bound = "1"
        filter_widget.high_bound = "10"
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape
        assert not np.array_equal(out.data, patch.data)

    def test_gaussian_filter_applies(self, filter_widget, monkeypatch, qtbot):
        """gaussian_filter produces a different patch of the same shape."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        _set_gaussian_rows(filter_widget, [{"dim": "time", "window": "0.01"}])
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape

    def test_samples_true_integer_text_passes_int_window(
        self, filter_widget, monkeypatch, qtbot
    ):
        """Sample-count text like '2' reaches DASCore as an int."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_gaussian_filter(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "gaussian_filter", _fake_gaussian_filter)
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.apply_taper = False
        filter_widget.samples = True
        _set_gaussian_rows(filter_widget, [{"dim": "time", "window": "2"}])

        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["samples"] is True
        assert captured["time"] == 2
        assert isinstance(captured["time"], int)
        assert not filter_widget.Error.general.is_shown()

    def test_samples_true_explicit_float_stays_float(
        self, filter_widget, monkeypatch, qtbot
    ):
        """Sample-count text like '2.0' is not coerced down to int."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_gaussian_filter(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "gaussian_filter", _fake_gaussian_filter)
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.apply_taper = False
        filter_widget.samples = True
        _set_gaussian_rows(filter_widget, [{"dim": "time", "window": "2.0"}])

        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["time"] == 2.0
        assert isinstance(captured["time"], float)

    def test_taper_applies_before_gaussian_filter(
        self, filter_widget, monkeypatch, qtbot
    ):
        """Enabled taper should run before gaussian_filter."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        _set_gaussian_rows(filter_widget, [{"dim": "time", "window": "0.01"}])
        filter_widget.taper_window = "0.01"
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        expected = patch.taper(time=0.01).gaussian_filter(
            samples=False, mode="reflect", cval=0.0, truncate=4.0, time=0.01
        )
        assert out is not None
        assert np.array_equal(out.data, expected.data)

    def test_notch_filter_applies(self, filter_widget, monkeypatch, qtbot):
        """notch_filter produces a patch of the same shape."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget._filter_combo.setCurrentText("notch_filter")
        filter_widget.filter_window = "10"
        filter_widget.q = 35.0
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape

    def test_sobel_filter_applies(self, filter_widget, monkeypatch, qtbot):
        """sobel_filter requires no window value and produces output of same shape."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget._filter_combo.setCurrentText("sobel_filter")
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        assert out is not None
        assert out.shape == patch.shape

    def test_slope_filter_applies_with_default_taper(
        self, filter_widget, monkeypatch, qtbot
    ):
        """slope_filter still runs when taper is enabled."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget._filter_combo.setCurrentText("slope_filter")
        filter_widget.slope_filt = "2000.0,2200.0,8000.0,20000.0"
        filter_widget.selected_dim = "time"
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        out = received[-1]
        expected = patch.taper(time=0.01).slope_filter(
            filt=[2000.0, 2200.0, 8000.0, 20000.0],
            dims=("distance", "time"),
            directional=False,
            notch=None,
            invert=False,
        )
        assert out is not None
        assert np.array_equal(out.data, expected.data)

    def test_dim_combo_hidden_for_slope_filter(self, filter_widget):
        """Dim combo is hidden when slope_filter is selected."""
        filter_widget._filter_combo.setCurrentText("slope_filter")
        assert filter_widget._dim_combo.isHidden()
        assert filter_widget._dim_label.isHidden()

    def test_dim_combo_visible_for_non_slope_filter(self, filter_widget):
        """Dim combo is visible again for single-dimension filters."""
        filter_widget._filter_combo.setCurrentText("slope_filter")
        filter_widget._filter_combo.setCurrentText("median_filter")
        assert not filter_widget._dim_combo.isHidden()
        assert not filter_widget._dim_label.isHidden()

    def test_dim_combo_hidden_for_gaussian_filter(self, filter_widget):
        """Gaussian manages dims through its own row UI, not the primary combo."""
        filter_widget._filter_combo.setCurrentText("gaussian_filter")

        assert filter_widget._dim_combo.isHidden()
        assert filter_widget._dim_label.isHidden()

    def test_add_gaussian_row_creates_second_row(self, filter_widget):
        """The Gaussian + button should append another dimension row."""
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.set_patch(dc.get_example_patch("example_event_2"))

        filter_widget._gaussian_add_button.click()

        assert len(filter_widget._gaussian_rows) == 2

    def test_gaussian_multiple_dims_reach_patch(
        self, filter_widget, monkeypatch, qtbot
    ):
        """Multiple Gaussian rows should be passed together to DASCore."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_gaussian_filter(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "gaussian_filter", _fake_gaussian_filter)
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.apply_taper = False
        _set_gaussian_rows(
            filter_widget,
            [
                {"dim": "time", "window": "0.01"},
                {"dim": "distance", "window": "3"},
            ],
        )

        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["time"] == 0.01
        assert captured["distance"] == 3.0

    def test_gaussian_duplicate_dims_show_error(
        self, filter_widget, monkeypatch, qtbot
    ):
        """Duplicate Gaussian dimensions should fail clearly."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.apply_taper = False
        _set_gaussian_rows(
            filter_widget,
            [
                {"dim": "time", "window": "0.01"},
                {"dim": "time", "window": "0.02"},
            ],
        )

        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert filter_widget.Error.general.is_shown()

    def test_gaussian_rows_survive_none_then_compatible_patch(
        self, filter_widget, monkeypatch, qtbot
    ):
        """None should not clear Gaussian rows for a compatible next patch."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("example_event_1")
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.apply_taper = False
        _set_gaussian_rows(filter_widget, [{"dim": "time", "window": "0.01"}])

        filter_widget.set_patch(first)
        wait_for_output(qtbot, received)
        filter_widget.set_patch(None)
        wait_for_output(qtbot, received, 2)
        filter_widget.set_patch(second)
        wait_for_output(qtbot, received, 3)

        assert filter_widget.gaussian_dim_windows == [{"dim": "time", "window": "0.01"}]
        assert received[-1] is not None

    def test_gaussian_rows_reset_when_replacement_patch_lacks_dim(
        self, filter_widget, monkeypatch, qtbot
    ):
        """Gaussian rows should reset when a replacement patch removes that dim."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        first = dc.get_example_patch("example_event_2")
        incompatible = first.rename_coords(time="seconds")
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.apply_taper = False
        _set_gaussian_rows(filter_widget, [{"dim": "time", "window": "0.01"}])

        filter_widget.set_patch(first)
        wait_for_output(qtbot, received)
        filter_widget.set_patch(None)
        wait_for_output(qtbot, received, 2)
        filter_widget.set_patch(incompatible)
        wait_for_output(qtbot, received, 3)

        assert filter_widget.gaussian_dim_windows == [{"dim": "", "window": ""}]
        assert received[-1] is None
        assert filter_widget.Error.general.is_shown()

    def test_gaussian_legacy_single_dim_settings_restore_into_rows(self, qtbot):
        """Old stored Gaussian settings should seed the first Gaussian row."""
        stored_settings = {
            "selected_filter": "gaussian_filter",
            "selected_dim": "time",
            "filter_window": "0.01",
        }

        with widget_context(Filter, stored_settings=stored_settings) as widget:
            widget.show()
            qtbot.wait(10)
            widget.set_patch(dc.get_example_patch("example_event_2"))

            assert widget.gaussian_dim_windows == [{"dim": "time", "window": "0.01"}]

    def test_savgol_mode_options_exclude_reflect(self, filter_widget):
        """Savitzky-Golay mode dropdown excludes invalid 'reflect'."""
        filter_widget._filter_combo.setCurrentText("savgol_filter")
        combo = filter_widget._savgol_mode_combo
        assert combo is not None
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "reflect" not in items
        assert "interp" in items

    def test_savgol_coerces_reflect_mode_to_interp(self, filter_widget):
        """Switching to savgol coerces persisted/invalid reflect mode to interp."""
        filter_widget.mode = "reflect"
        filter_widget._filter_combo.setCurrentText("savgol_filter")
        assert filter_widget.mode == "interp"
        combo = filter_widget._savgol_mode_combo
        assert combo is not None
        assert combo.currentText() == "interp"

    def test_invalid_window_raises_error(self, filter_widget, monkeypatch, qtbot):
        """Blank window on a window-based filter shows error and emits None."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        filter_widget._filter_combo.setCurrentText("gaussian_filter")
        filter_widget.filter_window = ""
        _set_gaussian_rows(filter_widget, [{"dim": "", "window": ""}])
        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        assert received[-1] is None
        assert filter_widget.Error.general.is_shown()

    def test_filter_names_tuple_matches_stack_size(self, filter_widget):
        """Stack page count equals the number of supported filter names."""
        assert filter_widget._stack.count() == len(_FILTER_NAMES)

    def test_all_filter_names_in_combo(self, filter_widget):
        """All filter names appear in the dropdown."""
        items = [
            filter_widget._filter_combo.itemText(i)
            for i in range(filter_widget._filter_combo.count())
        ]
        assert set(items) == set(_FILTER_NAMES)


# ---------------------------------------------------------------------------
# Reference comparison: widget output must match direct DASCore call exactly.
# Each entry is (filter_name, widget_overrides, expected_fn).
# widget_overrides: attribute dict applied to the widget before set_patch.
# expected_fn: callable(patch) → expected DASCore output.
# ---------------------------------------------------------------------------
_FILTER_REFERENCE_CASES = [
    pytest.param(
        "pass_filter",
        {
            "low_bound": "1",
            "high_bound": "10",
            "corners": 4,
            "zerophase": True,
            "apply_taper": False,
        },
        lambda p: p.pass_filter(corners=4, zerophase=True, time=(1.0, 10.0)),
        id="pass_filter",
    ),
    pytest.param(
        "gaussian_filter",
        {
            "gaussian_dim_windows": [{"dim": "time", "window": "0.01"}],
            "samples": False,
            "mode": "reflect",
            "cval": 0.0,
            "truncate": 4.0,
            "apply_taper": False,
        },
        lambda p: p.gaussian_filter(
            samples=False, mode="reflect", cval=0.0, truncate=4.0, time=0.01
        ),
        id="gaussian_filter",
    ),
    pytest.param(
        "hampel_filter",
        {
            "filter_window": "0.0003",
            "threshold": 10.0,
            "samples": False,
            "approximate": True,
            "apply_taper": False,
        },
        lambda p: p.hampel_filter(
            threshold=10.0, samples=False, approximate=True, time=0.0003
        ),
        id="hampel_filter",
    ),
    pytest.param(
        "median_filter",
        {
            "filter_window": "0.01",
            "samples": False,
            "mode": "reflect",
            "cval": 0.0,
            "apply_taper": False,
        },
        lambda p: p.median_filter(samples=False, mode="reflect", cval=0.0, time=0.01),
        id="median_filter",
    ),
    pytest.param(
        "notch_filter",
        {"filter_window": "10", "q": 35.0, "apply_taper": False},
        lambda p: p.notch_filter(q=35.0, time=10.0),
        id="notch_filter",
    ),
    pytest.param(
        # mode must be "interp" for savgol; "reflect" is not a valid scipy savgol mode.
        "savgol_filter",
        {
            "filter_window": "0.01",
            "polyorder": 3,
            "samples": False,
            "mode": "interp",
            "cval": 0.0,
            "apply_taper": False,
        },
        lambda p: p.savgol_filter(
            polyorder=3, samples=False, mode="interp", cval=0.0, time=0.01
        ),
        id="savgol_filter",
    ),
    pytest.param(
        "slope_filter",
        {
            "slope_filt": "2000.0,2200.0,8000.0,20000.0",
            "slope_dim0": "distance",
            "slope_dim1": "time",
            "slope_directional": False,
            "slope_notch": False,
            "slope_invert": False,
            "apply_taper": False,
        },
        lambda p: p.slope_filter(
            filt=[2000.0, 2200.0, 8000.0, 20000.0],
            dims=("distance", "time"),
            directional=False,
            notch=None,
            invert=False,
        ),
        id="slope_filter",
    ),
    pytest.param(
        "sobel_filter",
        {"mode": "reflect", "cval": 0.0, "apply_taper": False},
        lambda p: p.sobel_filter(dim="time", mode="reflect", cval=0.0),
        id="sobel_filter",
    ),
    pytest.param(
        "wiener_filter",
        {
            "filter_window": "0.01",
            "noise": "",
            "samples": False,
            "apply_taper": False,
        },
        lambda p: p.wiener_filter(noise=None, samples=False, time=0.01),
        id="wiener_filter",
    ),
]


class TestFilterMatchesDASCore:
    """Verify each filter method produces output identical to a direct DASCore call."""

    @pytest.mark.parametrize(
        "filter_name,overrides,expected_fn", _FILTER_REFERENCE_CASES
    )
    def test_output_matches_dascore_direct(
        self, filter_widget, monkeypatch, qtbot, filter_name, overrides, expected_fn
    ):
        """Widget output for each filter matches the equivalent direct DASCore call."""
        received = capture_output(filter_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        filter_widget._filter_combo.setCurrentText(filter_name)
        for attr, val in overrides.items():
            setattr(filter_widget, attr, val)

        filter_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert (
            not filter_widget.Error.general.is_shown()
        ), f"Filter widget raised an error for {filter_name}"
        assert received, f"{filter_name}: no output received"
        out = received[-1]
        assert out is not None, f"{filter_name}: output was None"

        expected = expected_fn(patch)
        assert np.array_equal(out.data, expected.data), (
            f"{filter_name}: widget output does not match direct DASCore call.\n"
            f"  max diff: {np.max(np.abs(out.data - expected.data))}"
        )


class TestFilterDefaults(TestPatchDimWidgetDefaults):
    """Shared default/smoke tests for Filter."""

    __test__ = True
    widget = Filter
    inputs = (("patch", dc.get_example_patch("example_event_2")),)
    compatible_patch = dc.get_example_patch("example_event_2")
    incompatible_patch = dc.get_example_patch("example_event_2").rename_coords(
        time="seconds"
    )
