"""Tests for the Select widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.models.annotations import Annotation, AnnotationSet, PointGeometry
from derzug.utils.display import format_display
from derzug.utils.testing import (
    TestPatchInputStateDefaults,
    TestWidgetDefaults,
    capture_output,
    wait_for_widget_idle,
    widget_context,
)
from derzug.widgets.select import Select
from derzug.widgets.selection import PatchSelectionBasis


@pytest.fixture
def select_widget(qtbot):
    """Return a live Select widget."""
    with widget_context(Select) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget


def _patch_with_datetime_time() -> dc.Patch:
    """Return the example patch with an absolute datetime time axis."""
    patch = dc.get_example_patch("example_event_2")
    count = len(patch.get_array("time"))
    time = np.datetime64("2024-01-02T03:04:05") + np.arange(count).astype(
        "timedelta64[ms]"
    )
    return patch.update_coords(time=time)


def _patch_with_tag(tag: str) -> dc.Patch:
    """Return an example patch with a predictable tag."""
    patch = dc.get_example_patch()
    attrs = patch.attrs.model_dump()
    attrs["tag"] = tag
    return patch.update(attrs=attrs)


def _spool_tags(spool: dc.BaseSpool) -> list[str]:
    """Return tag attributes for each patch in a spool."""
    return [patch.attrs.tag for patch in spool]


def _multi_select_spool() -> dc.BaseSpool:
    """Return a small spool with overlapping tags and distinct distance minima."""
    base = dc.get_example_patch()
    first = _patch_with_tag("bob")
    second = _patch_with_tag("bob").update_coords(
        distance=base.get_array("distance") + 1000
    )
    third = _patch_with_tag("alice").update_coords(
        distance=base.get_array("distance") + 1000
    )
    return dc.spool([first, second, third])


def _annotation_set_for_distance(value: float) -> AnnotationSet:
    """Return one small annotation set constrained only on distance."""
    return AnnotationSet(
        dims=("distance",),
        annotations=(
            Annotation(
                id="ann-1",
                geometry=PointGeometry(dims=("distance",), values=(value,)),
            ),
        ),
    )


class TestSelectDefaults(TestWidgetDefaults):
    """Default widget checks for Select."""

    widget = Select


def _shift_patch_out_of_range(patch: dc.Patch) -> dc.Patch:
    """Return a copy whose absolute coords no longer overlap the source patch."""
    return patch.update_coords(
        time=patch.get_array("time") + 10,
        distance=patch.get_array("distance") + 100,
    )


class TestSelectStateDefaults(TestPatchInputStateDefaults):
    """Shared patch-state defaults for Select."""

    __test__ = True
    widget = Select
    compatible_patch = dc.get_example_patch("example_event_2")
    incompatible_patch = _shift_patch_out_of_range(
        dc.get_example_patch("example_event_2")
    )

    def arrange_persisted_input_state(self, widget_object):
        """Install one absolute time selection range to preserve."""
        patch = widget_object._patch
        assert patch is not None
        time_values = patch.get_array("time")
        selected = (float(time_values[100]), float(time_values[200]))
        widget_object._selection_panel.patch_basis_combo.setCurrentText("Absolute")
        widget_object._selection_update_patch_range_absolute("time", *selected)
        return selected

    def assert_persisted_input_state(self, widget_object, state_token) -> None:
        """Absolute patch selections should survive compatible replacements."""
        assert widget_object._selection_current_patch_range("time") == pytest.approx(
            state_token
        )

    def assert_reset_input_state(self, widget_object, state_token) -> None:
        """Out-of-range replacements should reset the preserved selection."""
        assert widget_object._selection_current_patch_range("time") == (
            widget_object._selection_patch_extent("time")
        )


class TestSelect:
    """Behavioral tests for the Select widget."""

    def test_new_widget_starts_with_blank_selection_state(self, qtbot):
        """Selection state does not carry across widget instances."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Select) as first:
            first.show()
            qtbot.wait(10)
            first.set_patch(patch)
            dim = patch.dims[1]
            _low_edit, high_edit = first._selection_patch_edits[dim]
            midpoint = patch.get_array(dim)[len(patch.get_array(dim)) // 2]
            high_edit.setText(str(midpoint))
            high_edit.editingFinished.emit()
            assert first._selection_panel.status_label.text() != ""

        with widget_context(Select) as second:
            second.show()
            qtbot.wait(10)
            assert second._selection_mode is None
            assert second._selection_panel.status_label.text() == ""

    def test_first_show_compacts_an_oversized_window(self, qtbot):
        """Select should shrink an oversized first-open window to fit its controls."""
        with widget_context(Select) as widget:
            widget.resize(widget.width() + 300, widget.height())
            widened = widget.width()

            widget.show()
            qtbot.wait(10)

            assert widget.width() < widened
            assert widget.width() <= max(
                widget.minimumWidth(), widget.sizeHint().width()
            )

    def test_patch_input_builds_patch_controls(self, select_widget, monkeypatch):
        """Patch input shows per-dimension controls and emits a patch."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        select_widget.set_patch(patch)

        assert received[-1] is patch
        assert select_widget._selection_mode == "patch"
        assert tuple(select_widget._selection_patch_edits) == tuple(patch.dims)
        assert tuple(select_widget._selection_patch_checkboxes) == tuple(patch.dims)

    def test_build_status_text_for_patch_selection(self, select_widget):
        """Patch status text should come from the compact status builder."""
        patch = dc.get_example_patch("example_event_2")
        select_widget.set_patch(patch)

        status = select_widget._build_status_text(selected=patch)

        assert status == "absolute basis, 0 active range filter(s)"

    def test_first_patch_input_primes_delayed_saved_relative_selection(
        self, select_widget
    ):
        """Saved relative patch settings should apply even if restored after init."""
        patch = dc.get_example_patch("example_event_2")
        payload = {
            "basis": "relative",
            "rows": [
                {
                    "dim": "distance",
                    "enabled": True,
                    "low": {"kind": "float", "value": 100.0},
                    "high": {"kind": "float", "value": 200.0},
                }
            ],
        }
        select_widget.saved_selection_basis = payload["basis"]
        select_widget.saved_selection_ranges = payload["rows"]
        select_widget._selection_state = type(select_widget._selection_state)()

        select_widget.set_patch(patch)

        assert select_widget._selection_patch_basis == "relative"
        assert select_widget._selection_current_patch_range("distance") == (
            100.0,
            200.0,
        )

    def test_get_task_matches_patch_output(self, select_widget, monkeypatch):
        """Patch-mode output should match executing the canonical selection task."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        select_widget.set_patch(patch)
        wait_for_widget_idle(select_widget, timeout=5.0)

        task_result = select_widget.get_task().run(
            patch=patch,
            spool=None,
            annotation_set=None,
        )

        assert received[-1] == task_result["patch"]

    def test_get_task_matches_spool_output(self, select_widget, monkeypatch):
        """Spool-mode output should match executing the canonical selection task."""
        received = capture_output(select_widget.Outputs.spool, monkeypatch)
        spool = _multi_select_spool()

        select_widget.set_spool(spool)
        wait_for_widget_idle(select_widget, timeout=5.0)

        task_result = select_widget.get_task().run(
            patch=None,
            spool=spool,
            annotation_set=None,
        )

        assert list(received[-1]) == list(task_result["spool"])

    def test_hidden_patch_input_defers_control_refresh_until_show(
        self, monkeypatch, qtbot
    ):
        """Hidden widgets should keep selection rows synced before first show."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(Select) as widget:
            received = capture_output(widget.Outputs.patch, monkeypatch)

            widget.set_patch(patch)

            assert received == [patch]
            assert tuple(widget._selection_patch_edits) == tuple(patch.dims)
            assert widget._selection_panel.status_label.text() == ""

            widget.show()
            qtbot.wait(10)

            assert tuple(widget._selection_patch_edits) == tuple(patch.dims)
            assert "absolute basis" in widget._selection_panel.status_label.text()

    def test_patch_dimensions_start_checked(self, select_widget):
        """Each patch dimension starts enabled by default."""
        patch = dc.get_example_patch("example_event_2")

        select_widget.set_patch(patch)

        assert all(select_widget._selection_patch_enabled.values())

    def test_patch_controls_stack_each_dimension_vertically(self, select_widget):
        """Each patch dimension should use a compact stacked control layout."""
        patch = dc.get_example_patch("example_event_2")

        select_widget.set_patch(patch)

        time_label = None
        layout = select_widget._selection_panel.patch_layout
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child = item.widget()
            if child is not None and child.text() == "<b>time</b>":
                time_label = child
                break
        assert time_label is not None

        checkbox = select_widget._selection_patch_checkboxes["time"]
        low_edit, high_edit = select_widget._selection_patch_edits["time"]
        label_pos = layout.getItemPosition(layout.indexOf(time_label))
        checkbox_pos = layout.getItemPosition(layout.indexOf(checkbox))
        low_pos = layout.getItemPosition(layout.indexOf(low_edit))
        high_pos = layout.getItemPosition(layout.indexOf(high_edit))

        assert checkbox_pos == (label_pos[0], 0, 1, 1)
        assert label_pos[1:] == (1, 1, 3)
        assert low_pos == (label_pos[0] + 1, 1, 1, 3)
        assert high_pos == (label_pos[0] + 2, 1, 1, 3)

    def test_patch_range_edit_emits_narrower_patch(self, select_widget, monkeypatch):
        """Editing a patch range narrows the emitted patch."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        select_widget.set_patch(patch)
        dim = patch.dims[1]
        midpoint = patch.get_array(dim)[len(patch.get_array(dim)) // 2]
        _low_edit, high_edit = select_widget._selection_patch_edits[dim]

        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()

        assert received
        selected = received[-1]
        assert selected is not None
        assert selected.shape[1] < patch.shape[1]

    def test_unchecking_dimension_disables_edits_and_restores_full_output(
        self, select_widget, monkeypatch
    ):
        """Unchecking a dimension disables its edits and removes its filter."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        select_widget.set_patch(patch)
        dim = patch.dims[1]
        midpoint = patch.get_array(dim)[len(patch.get_array(dim)) // 2]
        checkbox = select_widget._selection_patch_checkboxes[dim]
        _low_edit, high_edit = select_widget._selection_patch_edits[dim]

        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()
        assert received[-1].shape[1] < patch.shape[1]

        checkbox.click()

        checkbox = select_widget._selection_patch_checkboxes[dim]
        _low_edit, high_edit = select_widget._selection_patch_edits[dim]
        assert checkbox.isChecked() is False
        assert high_edit.isEnabled() is False
        assert received[-1] is patch

    def test_rechecking_dimension_restores_prior_range(
        self, select_widget, monkeypatch
    ):
        """Re-enabling a dimension restores its stored range immediately."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        select_widget.set_patch(patch)
        dim = patch.dims[1]
        midpoint = patch.get_array(dim)[len(patch.get_array(dim)) // 2]
        checkbox = select_widget._selection_patch_checkboxes[dim]
        _low_edit, high_edit = select_widget._selection_patch_edits[dim]

        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()
        expected_shape = received[-1].shape

        checkbox.click()
        checkbox.click()

        checkbox = select_widget._selection_patch_checkboxes[dim]
        _low_edit, high_edit = select_widget._selection_patch_edits[dim]
        assert checkbox.isChecked() is True
        assert high_edit.isEnabled() is True
        assert high_edit.text() == format_display(midpoint)
        assert received[-1].shape == expected_shape

    def test_spool_input_builds_metadata_controls(self, select_widget, monkeypatch):
        """Spool input shows metadata controls and emits a spool."""
        received = capture_output(select_widget.Outputs.spool, monkeypatch)
        spool = dc.get_example_spool()

        select_widget.set_spool(spool)

        assert received[-1] is spool
        assert select_widget._selection_mode == "spool"
        assert select_widget._selection_spool_options
        assert select_widget.unpack_checkbox.isVisible() is True
        assert select_widget.unpack_checkbox.text() == "Unpack len1 spool"

    def test_spool_metadata_options_are_sorted(self, select_widget):
        """Spool metadata dropdown options should be alphabetically sorted."""
        select_widget.set_spool(_multi_select_spool())

        options = list(select_widget._selection_spool_options)

        assert options == sorted(options, key=str.casefold)

    def test_patch_input_hides_spool_unpack_checkbox(self, select_widget):
        """Patch mode should hide the spool-only unpack control."""
        select_widget.set_patch(dc.get_example_patch("example_event_2"))

        assert select_widget.unpack_checkbox.isVisible() is False

    def test_unpack_defaults_enabled_and_patch_output_doc_mentions_spool_unpack(
        self, select_widget
    ):
        """Default unpack settings and output help should describe spool unpacking."""
        assert select_widget.unpack_single_patch is True
        assert "length 1 spool" in (select_widget.Outputs.patch.doc or "")

    def test_spool_input_len1_emits_unpacked_patch(self, select_widget, monkeypatch):
        """A single-patch spool should also drive patch output by default."""
        spool_received = capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = _patch_with_tag("single")
        spool = dc.spool([patch])

        select_widget.set_spool(spool)

        assert spool_received[-1] is not None
        assert len(spool_received[-1].get_contents()) == 1
        assert patch_received[-1] is not None
        assert patch_received[-1].attrs.tag == "single"

    def test_unpack_disabled_suppresses_patch_output_for_len1_spool(
        self, select_widget, monkeypatch
    ):
        """Turning unpack off should suppress patch output in spool mode."""
        capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)
        select_widget.unpack_single_patch = False

        select_widget.set_spool(dc.spool([_patch_with_tag("single")]))

        assert patch_received[-1] is None

    def test_spool_filter_emits_filtered_spool(self, select_widget, monkeypatch):
        """Editing the spool filter emits a narrowed spool."""
        received = capture_output(select_widget.Outputs.spool, monkeypatch)
        spool = dc.get_example_spool()
        select_widget.set_spool(spool)
        df = spool.get_contents()
        key = next(c for c in select_widget._selection_spool_options if c in df.columns)
        raw_value = str(df.iloc[0][key])

        select_widget._selection_spool_combo.setCurrentText(key)
        select_widget._selection_spool_value_edit.setText(raw_value)
        select_widget._selection_spool_value_edit.editingFinished.emit()

        assert received
        selected = received[-1]
        assert selected is not None
        assert len(selected.get_contents()) <= len(df)

    def test_spool_filter_plus_button_adds_another_row(self, select_widget):
        """Spool mode should allow adding multiple metadata filter rows."""
        select_widget.set_spool(dc.get_example_spool())

        assert len(select_widget._selection_panel.spool_rows) == 1

        select_widget._selection_panel.spool_add_button.click()

        assert len(select_widget._selection_panel.spool_rows) == 2

    def test_multiple_spool_filters_are_applied_together(
        self, select_widget, monkeypatch
    ):
        """Multiple spool filter rows should narrow the output with AND semantics."""
        received = capture_output(select_widget.Outputs.spool, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        spool = dc.spool(
            [
                patch.update_attrs(tag="alpha", station="s1"),
                patch.update_attrs(tag="alpha", station="s2"),
                patch.update_attrs(tag="beta", station="s1"),
            ]
        )
        select_widget.set_spool(spool)
        select_widget._selection_panel.spool_add_button.click()
        select_widget._on_selection_spool_changed([("tag", "alpha"), ("station", "s1")])

        expected = spool.select(tag="alpha").select(station="s1")
        assert len(received[-1].get_contents()) == len(expected.get_contents())
        assert len(received[-1].get_contents()) == 1

    def test_spool_filter_len1_emits_unpacked_patch(self, select_widget, monkeypatch):
        """Metadata filtering down to one patch should activate patch output."""
        capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        spool = dc.spool(
            [
                patch.update_attrs(tag="alpha", station="s1"),
                patch.update_attrs(tag="alpha", station="s2"),
                patch.update_attrs(tag="beta", station="s1"),
            ]
        )
        select_widget.set_spool(spool)

        select_widget._on_selection_spool_changed([("tag", "beta"), ("station", "s1")])

        assert patch_received[-1] is not None
        assert patch_received[-1].attrs.tag == "beta"

    def test_annotation_input_filters_spool_to_matching_patches(
        self, select_widget, monkeypatch
    ):
        """Incoming annotations should filter the selected spool by overlap."""
        received = capture_output(select_widget.Outputs.spool, monkeypatch)
        spool = _multi_select_spool()
        first_patch = next(iter(spool[:1]))
        point_distance = float(first_patch.get_array("distance")[0])

        select_widget.set_spool(spool)
        received.clear()
        select_widget.set_annotation_set(_annotation_set_for_distance(point_distance))

        assert _spool_tags(received[-1]) == ["bob"]

    def test_annotation_filter_len1_emits_unpacked_patch(
        self, select_widget, monkeypatch
    ):
        """Annotation filtering down to one patch should activate patch output."""
        capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)
        spool = _multi_select_spool()
        first_patch = next(iter(spool[:1]))
        point_distance = float(first_patch.get_array("distance")[0])

        select_widget.set_spool(spool)
        select_widget.set_annotation_set(_annotation_set_for_distance(point_distance))

        assert patch_received[-1] is not None
        assert patch_received[-1].attrs.tag == "bob"

    def test_annotation_filter_uses_shared_dims_only(self, select_widget, monkeypatch):
        """Distance-only annotations should still match multi-dim spool patches."""
        received = capture_output(select_widget.Outputs.spool, monkeypatch)
        spool = _multi_select_spool()
        third_patch = next(iter(spool[2:3]))
        point_distance = float(third_patch.get_array("distance")[0])

        select_widget.set_spool(spool)
        received.clear()
        select_widget.set_annotation_set(_annotation_set_for_distance(point_distance))

        assert _spool_tags(received[-1]) == ["bob", "alice"]

    def test_annotation_filter_composes_with_metadata_filters(
        self, select_widget, monkeypatch
    ):
        """Annotation overlap should narrow the spool before metadata filters."""
        received = capture_output(select_widget.Outputs.spool, monkeypatch)
        spool = _multi_select_spool()
        third_patch = next(iter(spool[2:3]))
        point_distance = float(third_patch.get_array("distance")[0])

        select_widget.set_spool(spool)
        select_widget.set_annotation_set(_annotation_set_for_distance(point_distance))
        select_widget._on_selection_spool_changed([("tag", "alice")])

        assert _spool_tags(received[-1]) == ["alice"]

    def test_multi_patch_spool_emits_no_patch(self, select_widget, monkeypatch):
        """Patch output stays empty while the emitted spool has multiple patches."""
        capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)

        select_widget.set_spool(_multi_select_spool())

        assert patch_received[-1] is None

    def test_clearing_spool_input_clears_patch_output(self, select_widget, monkeypatch):
        """Clearing spool input should clear both spool and patch outputs."""
        capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)
        select_widget.set_spool(dc.spool([_patch_with_tag("single")]))

        select_widget.set_spool(None)

        assert patch_received[-1] is None

    def test_reset_button_clears_active_patch_filter(self, select_widget, monkeypatch):
        """Reset returns patch selection to the full extent."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        select_widget.set_patch(patch)
        dim = patch.dims[1]
        _low_edit, high_edit = select_widget._selection_patch_edits[dim]
        midpoint = patch.get_array(dim)[len(patch.get_array(dim)) // 2]
        high_edit.setText(str(midpoint))
        high_edit.editingFinished.emit()

        select_widget._selection_panel.reset_button.click()

        assert received
        assert received[-1] is patch
        assert (
            select_widget._selection_panel.status_label.text()
            == "absolute basis, 0 active range filter(s)"
        )

    def test_reset_reenables_all_dimensions(self, select_widget, monkeypatch):
        """Reset re-enables unchecked dimensions and clears their filters."""
        capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        select_widget.set_patch(patch)
        dim = patch.dims[1]
        checkbox = select_widget._selection_patch_checkboxes[dim]

        checkbox.click()
        select_widget._selection_panel.reset_button.click()

        checkbox = select_widget._selection_patch_checkboxes[dim]
        assert all(select_widget._selection_patch_enabled.values())
        assert checkbox.isChecked() is True

    def test_patch_basis_selector_updates_status(self, select_widget):
        """Changing patch basis updates the helper state and status line."""
        patch = dc.get_example_patch("example_event_2")

        select_widget.set_patch(patch)
        select_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")

        assert select_widget._selection_state.patch.basis is PatchSelectionBasis.SAMPLES
        assert "samples basis" in select_widget._selection_panel.status_label.text()

    def test_relative_selection_survives_patch_replacement(
        self, select_widget, monkeypatch
    ):
        """Relative patch ranges should be reapplied when a new patch arrives."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        shifted = patch.update_coords(
            time=patch.get_array("time") + 10,
            distance=patch.get_array("distance") + 100,
        )

        select_widget.set_patch(patch)
        select_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")
        _low_edit, high_edit = select_widget._selection_patch_edits["time"]
        high_edit.setText("0.01")
        high_edit.editingFinished.emit()

        select_widget.set_patch(shifted)

        assert select_widget._selection_patch_basis == "relative"
        expected = shifted.select(relative=True, time=(0.0, 0.01))
        assert received[-1].shape == expected.shape

    def test_disabled_dimension_survives_patch_replacement(self, select_widget):
        """Unchecked dimensions stay unchecked after a compatible patch swap."""
        patch = dc.get_example_patch("example_event_2")
        shifted = patch.update_coords(time=patch.get_array("time") + 10)

        select_widget.set_patch(patch)
        select_widget._selection_patch_checkboxes["time"].click()

        select_widget.set_patch(shifted)

        assert select_widget._selection_patch_enabled["time"] is False
        assert select_widget._selection_patch_checkboxes["time"].isChecked() is False

    def test_samples_selection_survives_patch_replacement(
        self, select_widget, monkeypatch
    ):
        """Sample-index ranges should be reapplied when a new patch arrives."""
        received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        shifted = patch.update_coords(time=patch.get_array("time") + 10)

        select_widget.set_patch(patch)
        select_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")
        _low_edit, high_edit = select_widget._selection_patch_edits["time"]
        low_edit = select_widget._selection_patch_edits["time"][0]
        low_edit.setText("10")
        high_edit.setText("20")
        high_edit.editingFinished.emit()

        select_widget.set_patch(shifted)

        assert select_widget._selection_patch_basis == "samples"
        assert received[-1].shape == shifted.select(samples=True, time=(10, 20)).shape

    def test_absolute_datetime_basis_displays_iso_strings(self, select_widget):
        """Absolute datetime selections should accept ISO 8601 strings when entered."""
        patch = _patch_with_datetime_time()

        select_widget.set_patch(patch)

        low_edit, high_edit = select_widget._selection_patch_edits["time"]
        high_value = patch.get_array("time")[5]
        high_expected = np.datetime_as_string(
            high_value.astype("datetime64[ns]"),
            timezone="naive",
        )

        assert low_edit.placeholderText() == ""
        high_edit.setText(high_expected)
        high_edit.editingFinished.emit()

        assert high_edit.text() == high_expected

    def test_relative_and_samples_bases_keep_numeric_displays(self, select_widget):
        """Relative and sample basis controls should continue showing numbers."""
        patch = _patch_with_datetime_time()

        select_widget.set_patch(patch)

        select_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")
        low_edit, high_edit = select_widget._selection_patch_edits["time"]
        assert low_edit.placeholderText() == ""
        high_edit.setText("0.005")
        high_edit.editingFinished.emit()
        assert high_edit.text() == "0.005"

        select_widget._selection_panel.patch_basis_combo.setCurrentText("Samples")
        low_edit, high_edit = select_widget._selection_patch_edits["time"]
        assert low_edit.placeholderText() == ""
        high_edit.setText("5")
        high_edit.editingFinished.emit()
        assert high_edit.text() == "5"

    def test_programmatic_patch_range_updates_use_display_formatter(
        self, select_widget
    ):
        """Programmatic range pushes should use the shared display formatter."""
        patch = dc.get_example_patch("example_event_2")
        precise_value = 0.0054321

        select_widget.set_patch(patch)
        select_widget._selection_update_patch_range(
            "time",
            patch.get_array("time")[0],
            precise_value,
            notify=False,
        )

        _low_edit, high_edit = select_widget._selection_patch_edits["time"]
        assert high_edit.text() == format_display(precise_value)
        assert select_widget._selection_current_patch_range("time")[1] == pytest.approx(
            precise_value
        )

    def test_user_typed_float_precision_is_preserved(self, select_widget):
        """Refreshing state should not collapse user-entered float precision."""
        patch = _patch_with_datetime_time()

        select_widget.set_patch(patch)
        select_widget._selection_panel.patch_basis_combo.setCurrentText("Relative")
        _low_edit, high_edit = select_widget._selection_patch_edits["time"]
        high_edit.setText("0.0054321")
        high_edit.editingFinished.emit()

        assert high_edit.text() == "0.0054321"

    def test_hint_label_word_wrap_enabled(self, select_widget):
        """hint_label must have word wrap so it does not force the sidebar wider."""
        panel = select_widget._selection_panel
        assert panel.hint_label.wordWrap()

    def test_hint_label_min_size_hint_narrower_than_size_hint(self, select_widget):
        """With word wrap, minimumSizeHint width must be less than sizeHint width.

        _layout_target_width uses minimumSizeHint for word-wrapped labels so the
        hint text does not force the sidebar wider than the spool controls.
        """
        panel = select_widget._selection_panel
        panel.hint_label.setText("Values use Python literal syntax when possible.")
        min_w = panel.hint_label.minimumSizeHint().width()
        preferred_w = panel.hint_label.sizeHint().width()
        assert min_w < preferred_w


class TestOnResult:
    """Tests for Select._on_result output routing."""

    def test_none_result_clears_both_outputs(self, select_widget, monkeypatch):
        """None result sends None on both channels and clears preview."""
        spool_received = capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)

        select_widget._on_result(None)

        assert spool_received[-1] is None
        assert patch_received[-1] is None
        assert select_widget._preview_selected is None

    def test_dict_result_sends_patch_and_spool(self, select_widget, monkeypatch):
        """Dict result routes patch and spool to their respective channels."""
        spool_received = capture_output(select_widget.Outputs.spool, monkeypatch)
        patch_received = capture_output(select_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch()
        spool = dc.spool([patch])

        select_widget._on_result({"patch": patch, "spool": spool})

        assert patch_received[-1] is patch
        assert list(spool_received[-1]) == list(spool)

    def test_spool_input_kind_sets_preview_to_spool(self, select_widget):
        """In spool mode _preview_selected should be the spool, not the patch."""
        patch = dc.get_example_patch()
        spool = dc.spool([patch])
        select_widget._input_kind = "spool"

        select_widget._on_result({"patch": patch, "spool": spool})

        assert select_widget._preview_selected is spool

    def test_patch_input_kind_sets_preview_to_patch(self, select_widget):
        """In patch mode _preview_selected should be the patch."""
        patch = dc.get_example_patch()
        select_widget._input_kind = "patch"

        select_widget._on_result({"patch": patch, "spool": None})

        assert select_widget._preview_selected is patch

    def test_on_result_triggers_ui_refresh(self, select_widget, monkeypatch):
        """_on_result should schedule a UI refresh."""
        refreshed = []
        monkeypatch.setattr(
            select_widget, "_request_ui_refresh", lambda: refreshed.append(True)
        )

        select_widget._on_result(None)

        assert refreshed


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
