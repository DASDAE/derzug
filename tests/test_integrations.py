"""Widget-pipeline integration tests."""

from __future__ import annotations

from pathlib import Path

import dascore as dc
import derzug.constants as constants
import numpy as np
import pytest
from AnyQt.QtWidgets import QApplication
from derzug.utils.testing import wait_for_widget_idle, widget_context
from derzug.views import orange as orange_view
from derzug.views.orange import ActiveSourceManager
from derzug.widgets.aggregate import Aggregate
from derzug.widgets.filter import Filter
from derzug.widgets.rolling import Rolling
from derzug.widgets.select import Select
from derzug.widgets.spool import Spool
from derzug.widgets.stft import Stft
from derzug.widgets.waterfall import Waterfall
from derzug.widgets.wiggle import Wiggle


def _graph_signature(scheme) -> tuple[set[str], set[tuple[str, str, str, str]]]:
    """Return comparable node/link signatures for a workflow graph."""
    nodes = {node.title for node in scheme.nodes}
    links = {
        (
            link.source_node.title,
            link.source_channel.name,
            link.sink_node.title,
            link.sink_channel.name,
        )
        for link in scheme.links
    }
    return nodes, links


def _capture_output(output_obj, monkeypatch) -> list:
    """Patch an Orange Output.send method and return captured values."""
    received: list = []

    def _sink(value):
        received.append(value)

    monkeypatch.setattr(output_obj, "send", _sink)
    return received


def _assert_clean_pipeline(rolling_widget, waterfall_widget) -> None:
    """Assert no user-facing errors were raised in the pipeline widgets."""
    assert not rolling_widget.Error.invalid_window.is_shown()
    assert not rolling_widget.Error.invalid_step.is_shown()
    assert not rolling_widget.Error.rolling_failed.is_shown()
    assert not waterfall_widget.Error.invalid_patch.is_shown()


def _write_example_spool_directory(directory: Path) -> dc.BaseSpool:
    """Write DASCore's diverse example spool to a directory and reload it."""
    directory.mkdir(parents=True, exist_ok=True)
    source = dc.get_example_spool("diverse_das")
    dc.examples.spool_to_directory(source, directory)
    return dc.spool(directory)


def _set_select_bounds(select_widget: Select, patch: dc.Patch) -> None:
    """Narrow both patch dimensions to the middle half of their extents."""
    select_widget.show()
    QApplication.processEvents()
    for dim in patch.dims:
        values = patch.get_array(dim)
        low_idx = len(values) // 4
        high_idx = (3 * len(values)) // 4
        low_edit, high_edit = select_widget._selection_patch_edits[dim]
        low_edit.setText(str(values[low_idx]))
        low_edit.editingFinished.emit()
        high_edit.setText(str(values[high_idx]))
        high_edit.editingFinished.emit()


@pytest.mark.integration
def test_all_checked_in_workflows_load_without_partial_reconstruction_warning(
    derzug_app, monkeypatch, qapp
):
    """Every checked-in workflow should load through the app loader without warnings."""
    from orangecanvas.application import canvasmain

    workflow_dir = Path(__file__).resolve().parents[1] / "src" / "derzug" / "workflows"
    workflow_paths = sorted(workflow_dir.glob("*.ows"))
    assert workflow_paths, f"No workflows found in {workflow_dir}"

    captured_warnings: list[dict[str, object]] = []

    def _capture_warning(*args, **kwargs):
        captured_warnings.append({"args": args, "kwargs": kwargs})
        return None

    monkeypatch.setattr(canvasmain, "message_warning", _capture_warning)
    window = derzug_app.window

    for workflow_path in workflow_paths:
        captured_warnings.clear()
        with workflow_path.open("rb") as handle:
            scheme = window.new_scheme_from_contents_and_path(
                handle, str(workflow_path)
            )
        qapp.processEvents()

        assert scheme is not None, f"Failed to load workflow {workflow_path.name}"
        nodes, links = _graph_signature(scheme)
        assert nodes, f"Workflow {workflow_path.name} loaded without nodes"
        assert not captured_warnings, (
            f"Workflow {workflow_path.name} partially loaded: "
            f"{captured_warnings!r}; graph={nodes!r}, links={links!r}"
        )


@pytest.mark.integration
def test_all_derzug_registry_widgets_instantiate_in_live_canvas(derzug_app, qapp):
    """Every DerZug widget in the live registry should instantiate on the canvas."""
    window = derzug_app.window
    registry = derzug_app.main.registry
    scheme = window.current_document().scheme()
    descriptions = [
        desc
        for desc in registry.widgets()
        if desc.package.startswith(constants.PKG_NAME)
    ]
    assert descriptions, "Expected at least one DerZug widget in the live registry."

    failures: list[str] = []

    for node in list(scheme.nodes):
        scheme.remove_node(node)
    qapp.processEvents()

    for index, desc in enumerate(descriptions):
        node = scheme.new_node(desc, title=f"{desc.name}-{index}")
        qapp.processEvents()
        try:
            widget = scheme.widget_for_node(node)
            qapp.processEvents()
            assert widget is not None
            assert widget.__class__.__module__.startswith("derzug.widgets.")
        except Exception as exc:
            failures.append(f"{desc.name}: {type(exc).__name__}: {exc}")
        finally:
            if node in scheme.nodes:
                scheme.remove_node(node)
            qapp.processEvents()

    assert not failures, "Widgets failed to instantiate: " + "; ".join(failures)


@pytest.mark.integration
def test_integration_spool_rolling_waterfall_example_event2(monkeypatch):
    """Single-patch pipeline works from source through processing and visualization."""
    with (
        widget_context(Spool) as spool_widget,
        widget_context(Rolling) as rolling_widget,
        widget_context(Waterfall) as waterfall_widget,
    ):
        spool_patch_received = _capture_output(spool_widget.Outputs.patch, monkeypatch)
        rolling_received = _capture_output(rolling_widget.Outputs.patch, monkeypatch)
        waterfall_received = _capture_output(
            waterfall_widget.Outputs.patch, monkeypatch
        )

        # Source loads a known single patch example.
        spool_widget._clear_other_inputs("example")
        spool_widget.spool_input = "example_event_2"
        spool_widget.example_combo.setCurrentText("example_event_2")
        spool_widget.unpack_single_patch = True
        spool_widget.run()
        wait_for_widget_idle(spool_widget)
        source_spool = spool_widget._current_spool
        assert source_spool is not None
        assert spool_patch_received
        source_patch = spool_patch_received[-1]
        assert source_patch is not None

        # Feed into rolling, then waterfall.
        rolling_widget.set_patch(source_patch)
        assert rolling_received
        rolled_patch = rolling_received[-1]
        assert rolled_patch is not None

        waterfall_widget.set_patch(rolled_patch)
        assert waterfall_received
        out_patch = waterfall_received[-1]
        assert out_patch is not None
        assert out_patch.shape == rolled_patch.shape
        _assert_clean_pipeline(rolling_widget, waterfall_widget)


@pytest.mark.integration
def test_integration_multi_patch_spool_selection_pipeline(monkeypatch):
    """Multi-patch source selection can feed rolling and waterfall end-to-end."""
    with (
        widget_context(Spool) as spool_widget,
        widget_context(Rolling) as rolling_widget,
        widget_context(Waterfall) as waterfall_widget,
    ):
        spool_patch_received = _capture_output(spool_widget.Outputs.patch, monkeypatch)
        rolling_received = _capture_output(rolling_widget.Outputs.patch, monkeypatch)
        waterfall_received = _capture_output(
            waterfall_widget.Outputs.patch, monkeypatch
        )

        # Prefer an example spool with multiple patches.
        multi_name = next(
            (
                name
                for name in spool_widget._examples
                if "spool" in name.lower() and len(list(dc.get_example_spool(name))) > 1
            ),
            None,
        )
        if multi_name is None:
            pytest.skip("No multi-patch example spool available in this environment.")

        spool_widget._clear_other_inputs("example")
        spool_widget.spool_input = multi_name
        spool_widget.example_combo.setCurrentText(multi_name)
        spool_widget.unpack_single_patch = True
        spool_widget.run()

        full_spool = spool_widget._current_spool
        assert full_spool is not None
        full_count = len(list(full_spool))
        assert full_count > 1

        # Select one row to produce a single-patch spool.
        spool_widget._table.selectRow(0)
        selected_rows = {
            idx.row() for idx in spool_widget._table.selectionModel().selectedRows()
        }
        assert selected_rows == {0}
        assert spool_patch_received
        selected_patch = spool_patch_received[-1]
        assert selected_patch is not None

        rolling_widget.set_patch(selected_patch)
        assert rolling_received
        rolled_patch = rolling_received[-1]
        assert rolled_patch is not None

        waterfall_widget.set_patch(rolled_patch)
        assert waterfall_received
        out_patch = waterfall_received[-1]
        assert out_patch is not None
        assert out_patch.shape == rolled_patch.shape
        _assert_clean_pipeline(rolling_widget, waterfall_widget)


@pytest.mark.integration
def test_integration_directory_spool_row_selection_pipeline(tmp_path, monkeypatch):
    """A directory-backed spool can load, select one row, and feed processing."""
    with (
        widget_context(Spool) as spool_widget,
        widget_context(Rolling) as rolling_widget,
        widget_context(Waterfall) as waterfall_widget,
    ):
        spool_patch_received = _capture_output(spool_widget.Outputs.patch, monkeypatch)
        rolling_received = _capture_output(rolling_widget.Outputs.patch, monkeypatch)
        waterfall_received = _capture_output(
            waterfall_widget.Outputs.patch, monkeypatch
        )

        directory = tmp_path / "written_spool"
        expected_spool = _write_example_spool_directory(directory)
        expected_patches = list(expected_spool)
        assert len(expected_patches) > 1
        selected_index = next(
            (
                index
                for index, patch in enumerate(expected_patches)
                if patch.data.ndim == 2
            ),
            None,
        )
        if selected_index is None:
            pytest.skip("diverse_das did not contain a 2D patch to process.")
        expected_patch = expected_patches[selected_index]

        spool_widget.show()
        spool_widget._set_file_input(str(directory), trigger_run=True)
        wait_for_widget_idle(spool_widget)
        spool_widget._flush_pending_ui_refresh()
        loaded_spool = spool_widget._current_spool
        assert loaded_spool is not None
        assert len(list(loaded_spool)) == len(expected_patches)

        model = spool_widget._table.model()
        assert model is not None
        assert model.rowCount() == len(expected_patches)
        spool_widget._table.selectRow(selected_index)
        wait_for_widget_idle(spool_widget)

        assert spool_patch_received
        selected_patch = spool_patch_received[-1]
        assert selected_patch is not None
        assert selected_patch.shape == expected_patch.shape
        assert selected_patch.dims == expected_patch.dims

        rolling_widget.set_patch(selected_patch)
        assert rolling_received
        rolled_patch = rolling_received[-1]
        assert rolled_patch is not None

        waterfall_widget.set_patch(rolled_patch)
        assert waterfall_received
        out_patch = waterfall_received[-1]
        assert out_patch is not None
        assert out_patch.shape == rolled_patch.shape
        _assert_clean_pipeline(rolling_widget, waterfall_widget)


class TestConnections:
    """Tests that verify (or diagnose) signal compatibility between widget pairs."""

    @pytest.mark.integration
    def test_spool_to_filter_pipeline(self, monkeypatch):
        """
        Spool patch output feeds Filter via Inputs.patch and emits a filtered patch.
        """
        with (
            widget_context(Spool) as spool_widget,
            widget_context(Filter) as filter_widget,
        ):
            spool_patch_received = _capture_output(
                spool_widget.Outputs.patch, monkeypatch
            )
            received = _capture_output(filter_widget.Outputs.patch, monkeypatch)

            # Load a known single-patch example through the Spool widget.
            spool_widget._clear_other_inputs("example")
            spool_widget.spool_input = "example_event_2"
            spool_widget.example_combo.setCurrentText("example_event_2")
            spool_widget.unpack_single_patch = True
            spool_widget.run()
            wait_for_widget_idle(spool_widget)
            assert spool_patch_received
            patch = spool_patch_received[-1]
            assert patch is not None

            filter_widget.set_patch(patch)

            assert received, "Filter should emit a patch after receiving a patch input"
            assert received[-1] is not None
            assert not filter_widget.Error.general.is_shown()

    @pytest.mark.integration
    def test_spool_to_stft_pipeline(self, monkeypatch):
        """Spool patch output feeds Stft and emits a transformed patch."""
        with (
            widget_context(Spool) as spool_widget,
            widget_context(Stft) as stft_widget,
        ):
            spool_patch_received = _capture_output(
                spool_widget.Outputs.patch, monkeypatch
            )
            received = _capture_output(stft_widget.Outputs.patch, monkeypatch)

            spool_widget._clear_other_inputs("example")
            spool_widget.spool_input = "example_event_2"
            spool_widget.example_combo.setCurrentText("example_event_2")
            spool_widget.unpack_single_patch = True
            spool_widget.run()
            wait_for_widget_idle(spool_widget)
            assert spool_patch_received
            patch = spool_patch_received[-1]
            assert patch is not None

            stft_widget.samples = True
            stft_widget.window_length = "128"
            stft_widget.overlap = "64"
            stft_widget.set_patch(patch)

            assert received, "Stft should emit a patch after receiving a patch input"
            assert received[-1] is not None
            assert not stft_widget.Error.invalid_window_length.is_shown()
            assert not stft_widget.Error.invalid_overlap.is_shown()
            assert not stft_widget.Error.invalid_taper_window.is_shown()
            assert not stft_widget.Error.transform_failed.is_shown()

    @pytest.mark.integration
    def test_patch_output_feeds_spool_input(self, monkeypatch):
        """A patch-producing widget can feed Spool.Inputs.patch and grow its spool."""
        with (
            widget_context(Rolling) as rolling_widget,
            widget_context(Spool) as spool_widget,
        ):
            rolling_received = _capture_output(
                rolling_widget.Outputs.patch, monkeypatch
            )
            spool_received = _capture_output(spool_widget.Outputs.spool, monkeypatch)

            source_patch = dc.get_example_patch()
            rolling_widget.set_patch(source_patch)
            assert rolling_received
            rolled_patch = rolling_received[-1]
            assert rolled_patch is not None

            spool_widget._current_spool = None
            spool_widget.set_patch(rolled_patch)
            wait_for_widget_idle(spool_widget)

            assert spool_received
            output_spool = spool_received[-1]
            assert output_spool is not None
            assert len(list(output_spool)) == 1
            assert len(list(spool_widget._current_spool)) == 1

    @pytest.mark.integration
    def test_aggregate_squeeze_output_renders_in_wiggle_time_series(self, monkeypatch):
        """A 1D aggregate result should drive Wiggle into time-series mode."""
        with (
            widget_context(Aggregate) as aggregate_widget,
            widget_context(Wiggle) as wiggle_widget,
        ):
            aggregate_received = _capture_output(
                aggregate_widget.Outputs.patch, monkeypatch
            )
            wiggle_received = _capture_output(wiggle_widget.Outputs.patch, monkeypatch)

            patch = dc.get_example_patch("example_event_2")
            aggregate_widget.selected_dim = "time"
            aggregate_widget.method = "mean"
            aggregate_widget.dim_reduce = "squeeze"

            aggregate_widget.set_patch(patch)
            assert aggregate_received
            aggregated = aggregate_received[-1]
            assert aggregated is not None
            assert aggregated.data.ndim == 1

            wiggle_widget.set_patch(aggregated)

            assert wiggle_received
            assert wiggle_received[-1] is aggregated
            assert wiggle_widget.mode == "time series"
            wiggle_widget.show()
            QApplication.processEvents()
            assert wiggle_widget._render_state is not None
            assert wiggle_widget._render_state.mode == "time series"

    @pytest.mark.integration
    def test_story_crop_an_event_window(self, monkeypatch):
        """A source patch can be cropped in Select and rendered downstream."""
        with (
            widget_context(Spool) as spool_widget,
            widget_context(Select) as select_widget,
            widget_context(Waterfall) as waterfall_widget,
        ):
            spool_patch_received = _capture_output(
                spool_widget.Outputs.patch, monkeypatch
            )
            select_received = _capture_output(select_widget.Outputs.patch, monkeypatch)
            waterfall_received = _capture_output(
                waterfall_widget.Outputs.patch, monkeypatch
            )

            spool_widget._clear_other_inputs("example")
            spool_widget.spool_input = "example_event_2"
            spool_widget.example_combo.setCurrentText("example_event_2")
            spool_widget.unpack_single_patch = True
            spool_widget.run()
            wait_for_widget_idle(spool_widget)
            assert spool_patch_received
            patch = spool_patch_received[-1]
            assert patch is not None

            select_widget.set_patch(patch)
            _set_select_bounds(select_widget, patch)

            assert select_received
            selected_patch = select_received[-1]
            assert selected_patch is not None
            assert selected_patch.shape[0] < patch.shape[0]
            assert selected_patch.shape[1] < patch.shape[1]

            waterfall_widget.set_patch(selected_patch)
            assert waterfall_received
            out_patch = waterfall_received[-1]
            assert out_patch is not None
            assert out_patch.shape == selected_patch.shape
            assert not waterfall_widget.Error.invalid_patch.is_shown()

    @pytest.mark.integration
    def test_story_filter_and_compare_noise(self, monkeypatch):
        """Raw and filtered versions of one patch can be reviewed side by side."""
        with (
            widget_context(Spool) as spool_widget,
            widget_context(Filter) as filter_widget,
            widget_context(Waterfall) as raw_waterfall,
            widget_context(Waterfall) as filtered_waterfall,
        ):
            spool_patch_received = _capture_output(
                spool_widget.Outputs.patch, monkeypatch
            )
            filter_received = _capture_output(filter_widget.Outputs.patch, monkeypatch)
            raw_received = _capture_output(raw_waterfall.Outputs.patch, monkeypatch)
            filtered_received = _capture_output(
                filtered_waterfall.Outputs.patch, monkeypatch
            )

            spool_widget._clear_other_inputs("example")
            spool_widget.spool_input = "example_event_2"
            spool_widget.example_combo.setCurrentText("example_event_2")
            spool_widget.unpack_single_patch = True
            spool_widget.run()
            wait_for_widget_idle(spool_widget)
            assert spool_patch_received
            patch = spool_patch_received[-1]
            assert patch is not None

            filter_widget.low_bound = "1"
            filter_widget.high_bound = "10"
            filter_widget.set_patch(patch)

            assert filter_received
            filtered_patch = filter_received[-1]
            assert filtered_patch is not None
            assert filtered_patch.shape == patch.shape
            assert not np.array_equal(filtered_patch.data, patch.data)

            raw_waterfall.set_patch(patch)
            filtered_waterfall.set_patch(filtered_patch)
            assert raw_received
            assert filtered_received
            assert raw_received[-1] is patch
            assert filtered_received[-1].shape == filtered_patch.shape

    @pytest.mark.integration
    def test_story_inspect_frequency_content(self, monkeypatch):
        """A cropped patch can be transformed with STFT for spectral review."""
        with (
            widget_context(Spool) as spool_widget,
            widget_context(Select) as select_widget,
            widget_context(Stft) as stft_widget,
        ):
            spool_patch_received = _capture_output(
                spool_widget.Outputs.patch, monkeypatch
            )
            select_received = _capture_output(select_widget.Outputs.patch, monkeypatch)
            stft_received = _capture_output(stft_widget.Outputs.patch, monkeypatch)

            spool_widget._clear_other_inputs("example")
            spool_widget.spool_input = "example_event_2"
            spool_widget.example_combo.setCurrentText("example_event_2")
            spool_widget.unpack_single_patch = True
            spool_widget.run()
            wait_for_widget_idle(spool_widget)
            assert spool_patch_received
            patch = spool_patch_received[-1]
            assert patch is not None

            select_widget.set_patch(patch)
            _set_select_bounds(select_widget, patch)
            assert select_received
            selected_patch = select_received[-1]
            assert selected_patch is not None

            stft_widget.samples = True
            stft_widget.window_length = "128"
            stft_widget.overlap = "64"
            stft_widget.set_patch(selected_patch)

            assert stft_received
            transformed = stft_received[-1]
            assert transformed is not None
            assert transformed.shape != selected_patch.shape
            assert not stft_widget.Error.invalid_window_length.is_shown()
            assert not stft_widget.Error.invalid_overlap.is_shown()
            assert not stft_widget.Error.transform_failed.is_shown()

    @pytest.mark.integration
    def test_story_compare_multiple_processing_branches(self, monkeypatch):
        """One source patch can feed two processing branches for comparison."""
        with (
            widget_context(Spool) as spool_widget,
            widget_context(Filter) as filter_widget,
            widget_context(Rolling) as rolling_widget,
        ):
            spool_patch_received = _capture_output(
                spool_widget.Outputs.patch, monkeypatch
            )
            filter_received = _capture_output(filter_widget.Outputs.patch, monkeypatch)
            rolling_received = _capture_output(
                rolling_widget.Outputs.patch, monkeypatch
            )

            spool_widget._clear_other_inputs("example")
            spool_widget.spool_input = "example_event_2"
            spool_widget.example_combo.setCurrentText("example_event_2")
            spool_widget.unpack_single_patch = True
            spool_widget.run()
            wait_for_widget_idle(spool_widget)
            assert spool_patch_received
            patch = spool_patch_received[-1]
            assert patch is not None

            filter_widget.low_bound = "1"
            filter_widget.high_bound = "10"
            filter_widget.set_patch(patch)
            rolling_widget.rolling_window = "0.01"
            rolling_widget.aggregation = "mean"
            rolling_widget.set_patch(patch)

            assert filter_received
            assert rolling_received
            filtered_patch = filter_received[-1]
            rolled_patch = rolling_received[-1]
            assert filtered_patch is not None
            assert rolled_patch is not None
            assert filtered_patch.shape == patch.shape
            assert rolled_patch.shape == patch.shape
            assert not np.array_equal(filtered_patch.data, patch.data)
            assert not np.array_equal(rolled_patch.data, patch.data)
            assert not np.array_equal(filtered_patch.data, rolled_patch.data)

    @pytest.mark.integration
    def test_story_reduce_data_for_export(self, monkeypatch):
        """A processed patch can be reduced to a compact 1D output for review."""
        with (
            widget_context(Spool) as spool_widget,
            widget_context(Filter) as filter_widget,
            widget_context(Aggregate) as aggregate_widget,
            widget_context(Wiggle) as wiggle_widget,
        ):
            spool_patch_received = _capture_output(
                spool_widget.Outputs.patch, monkeypatch
            )
            filter_received = _capture_output(filter_widget.Outputs.patch, monkeypatch)
            aggregate_received = _capture_output(
                aggregate_widget.Outputs.patch, monkeypatch
            )
            wiggle_received = _capture_output(wiggle_widget.Outputs.patch, monkeypatch)

            spool_widget._clear_other_inputs("example")
            spool_widget.spool_input = "example_event_2"
            spool_widget.example_combo.setCurrentText("example_event_2")
            spool_widget.unpack_single_patch = True
            spool_widget.run()
            wait_for_widget_idle(spool_widget)
            assert spool_patch_received
            patch = spool_patch_received[-1]
            assert patch is not None

            filter_widget.low_bound = "1"
            filter_widget.high_bound = "10"
            filter_widget.set_patch(patch)
            assert filter_received
            filtered_patch = filter_received[-1]
            assert filtered_patch is not None

            aggregate_widget.selected_dim = "time"
            aggregate_widget.method = "mean"
            aggregate_widget.dim_reduce = "squeeze"
            aggregate_widget.set_patch(filtered_patch)
            assert aggregate_received
            reduced = aggregate_received[-1]
            assert reduced is not None
            assert reduced.data.ndim == 1

            wiggle_widget.set_patch(reduced)
            assert wiggle_received
            assert wiggle_received[-1] is reduced
            assert wiggle_widget.mode == "time series"


class TestActiveSourceIntegration:
    """Integration tests for automatic active-source selection."""

    @pytest.mark.integration
    def test_new_spool_auto_selected_when_only_source(self, derzug_app, qapp):
        """Creating one source widget auto-selects it as the active source."""
        window = derzug_app.window
        manager = ActiveSourceManager()
        window.active_source_manager = manager
        orange_view._APP_ACTIVE_SOURCE_MANAGER = manager
        orange_view._APP_ACTIVE_SOURCE_MAIN_WINDOW = window
        qapp.active_source_manager = manager
        qapp.active_source_main_window = window
        window.show()
        qapp.processEvents()
        # Clear any stale active-source pointer from prior tests.
        manager._active_widget = None
        manager._active_node = None

        with widget_context(Spool) as spool_widget:
            spool_widget.show()
            qapp.processEvents()

            assert manager._active_widget is spool_widget
            assert manager.ensure_active_source(window) is spool_widget
