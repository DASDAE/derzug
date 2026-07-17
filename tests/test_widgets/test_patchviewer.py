"""Tests for the PatchViewer widget."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.display import format_display
from derzug.utils.testing import TestWidgetDefaults, widget_context
from derzug.widgets.patchviewer import PatchViewer


@pytest.fixture
def patchviewer_widget(qtbot):
    """Return a live PatchViewer widget."""
    with widget_context(PatchViewer) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget


def _capture_patch_output(patchviewer_widget, monkeypatch) -> list:
    """Patch the patch output slot with a capture function and return the sink."""
    received: list = []

    def _sink(value):
        received.append(value)

    monkeypatch.setattr(patchviewer_widget.Outputs.patch, "send", _sink)
    return received


class TestPatchViewer:
    """Tests for the PatchViewer widget."""

    def test_patch_populates_expected_tree(self, patchviewer_widget):
        """Loading a patch creates the top-level inspection nodes."""
        patch = dc.get_example_patch("example_event_2")

        patchviewer_widget.set_patch(patch)

        root = patchviewer_widget._tree.topLevelItem(0)
        assert root is not None
        assert root.text(0) == "Patch"
        children = {root.child(index).text(0) for index in range(root.childCount())}
        assert {"dims", "shape", "dtype", "attrs", "coords", "data"} <= children

    def test_patch_defaults_to_data_preview(self, patchviewer_widget):
        """Loading a patch should immediately preview the main data array."""
        patch = dc.get_example_patch("example_event_2")

        patchviewer_widget.set_patch(patch)

        current = patchviewer_widget._tree.currentItem()
        assert current is not None
        assert current.text(0) == "data"
        assert patchviewer_widget._preview_mode == "image"
        assert "data" in patchviewer_widget._preview_header.text()

    def test_patch_is_forwarded(self, patchviewer_widget, monkeypatch):
        """Input patch is emitted unchanged on the output signal."""
        received = _capture_patch_output(patchviewer_widget, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        patchviewer_widget.set_patch(patch)

        assert received == [patch]

    def test_hidden_set_patch_defers_tree_rebuild_until_show(self, qtbot):
        """Hidden widgets should defer the expensive tree rebuild until shown."""
        patch = dc.get_example_patch("example_event_2")

        with widget_context(PatchViewer) as widget:
            calls: list[bool] = []
            original = widget._rebuild_tree

            def _wrapped(*args, **kwargs):
                calls.append(True)
                return original(*args, **kwargs)

            widget._rebuild_tree = _wrapped  # type: ignore[method-assign]
            widget.set_patch(patch)
            assert calls == []

            widget.show()
            qtbot.wait(10)

            assert calls == [True]

    def test_selecting_data_shows_image_preview(self, patchviewer_widget):
        """Selecting the main data node switches the preview into image mode."""
        patch = dc.get_example_patch("example_event_2")
        patchviewer_widget.set_patch(patch)
        root = patchviewer_widget._tree.topLevelItem(0)
        data_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "data"
        )

        patchviewer_widget._tree.setCurrentItem(data_item)

        assert patchviewer_widget._preview_mode == "image"
        assert "path: data" in patchviewer_widget._details.toPlainText()
        assert "shape=" in data_item.text(1)
        assert "min=" in data_item.text(1)

    def test_numeric_stats_use_shared_display_formatter(self, patchviewer_widget):
        """PatchViewer stats should use the shared float display formatter."""
        patch = dc.get_example_patch("example_event_2")

        patchviewer_widget.set_patch(patch)

        data = patch.data
        expected = (
            f"min={format_display(float(data.min()))} "
            f"max={format_display(float(data.max()))}"
        )
        assert patchviewer_widget._numeric_stats_text(data) == expected

    def test_selecting_coord_shows_line_preview(self, patchviewer_widget):
        """Selecting a coordinate array uses the 1D line preview."""
        patch = dc.get_example_patch("example_event_2")
        patchviewer_widget.set_patch(patch)
        root = patchviewer_widget._tree.topLevelItem(0)
        coords_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "coords"
        )
        coord_item = coords_item.child(0)

        patchviewer_widget._tree.setCurrentItem(coord_item)

        assert patchviewer_widget._preview_mode == "line"
        details = patchviewer_widget._details.toPlainText()
        assert f"path: coords.{coord_item.text(0)}" in details
        header_text = patchviewer_widget._preview_header.text()
        assert f"coords.{coord_item.text(0)}" in header_text

    def test_selecting_attr_shows_text_summary(self, patchviewer_widget):
        """Selecting an attribute node shows text details without plotting."""
        patch = dc.get_example_patch("example_event_2")
        patchviewer_widget.set_patch(patch)
        root = patchviewer_widget._tree.topLevelItem(0)
        attrs_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "attrs"
        )
        attr_item = attrs_item.child(0)

        patchviewer_widget._tree.setCurrentItem(attr_item)

        assert patchviewer_widget._preview_mode == "summary"
        assert "path: attrs." in patchviewer_widget._details.toPlainText()

    def test_tree_filter_hides_non_matching_branches(self, patchviewer_widget):
        """Typing into the filter should narrow the visible tree rows."""
        patchviewer_widget.set_patch(dc.get_example_patch("example_event_2"))
        root = patchviewer_widget._tree.topLevelItem(0)

        patchviewer_widget._tree_filter.setText("coords.time")

        coords_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "coords"
        )
        time_item = next(
            coords_item.child(index)
            for index in range(coords_item.childCount())
            if coords_item.child(index).text(0) == "time"
        )
        data_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "data"
        )

        assert not root.isHidden()
        assert not coords_item.isHidden()
        assert not time_item.isHidden()
        assert data_item.isHidden()

    def test_selection_path_is_preserved_across_patch_updates(self, patchviewer_widget):
        """Refreshing with another patch keeps the same selected node when possible."""
        patch = dc.get_example_patch("example_event_2")
        shifted = patch.update_coords(time=patch.get_array("time") + 1.0)
        patchviewer_widget.set_patch(patch)
        root = patchviewer_widget._tree.topLevelItem(0)
        coords_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "coords"
        )
        coord_item = coords_item.child(0)
        coord_name = coord_item.text(0)
        expected_path = f"coords.{coord_name}"
        patchviewer_widget._tree.setCurrentItem(coord_item)

        patchviewer_widget.set_patch(shifted)

        current = patchviewer_widget._tree.currentItem()
        assert current is not None
        assert current.text(0) == coord_name
        assert patchviewer_widget._current_descriptor is not None
        assert patchviewer_widget._current_descriptor.path == expected_path
        assert patchviewer_widget._preview_mode == "line"

    def test_expanded_state_is_preserved_across_patch_updates(self, patchviewer_widget):
        """Expanded branches should stay expanded when the patch refreshes."""
        patch = dc.get_example_patch("example_event_2")
        shifted = patch.update_coords(time=patch.get_array("time") + 2.0)
        patchviewer_widget.set_patch(patch)
        root = patchviewer_widget._tree.topLevelItem(0)
        attrs_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "attrs"
        )
        attrs_item.setExpanded(False)
        patchviewer_widget._remember_expanded_paths()

        patchviewer_widget.set_patch(shifted)

        root = patchviewer_widget._tree.topLevelItem(0)
        attrs_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "attrs"
        )
        coords_item = next(
            root.child(index)
            for index in range(root.childCount())
            if root.child(index).text(0) == "coords"
        )

        assert not attrs_item.isExpanded()
        assert coords_item.isExpanded()

    def test_clearing_input_resets_tree_preview_and_output(
        self,
        patchviewer_widget,
        monkeypatch,
    ):
        """Sending None clears the tree and preview and emits None."""
        received = _capture_patch_output(patchviewer_widget, monkeypatch)
        patchviewer_widget.set_patch(dc.get_example_patch("example_event_2"))
        received.clear()

        patchviewer_widget.set_patch(None)

        assert received == [None]
        assert patchviewer_widget._tree.topLevelItemCount() == 0
        assert patchviewer_widget._preview_mode == "empty"
        assert patchviewer_widget._preview_header.text() == "PatchViewer"
        assert patchviewer_widget._stats_label.text() == ""


class TestPatchViewerDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for PatchViewer."""

    __test__ = True
    widget = PatchViewer
    inputs = (("patch", dc.get_example_patch("example_event_2")),)

    def test_control_area_items_are_top_aligned(self):
        """PatchViewer intentionally disables the Orange control sidebar."""
        widget_object = self.create_default_widget()
        assert widget_object.controlArea is None
