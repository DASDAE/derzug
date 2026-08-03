"""Pilot tests for the Filter pydantic params-model layer."""

from __future__ import annotations

import os
import tempfile

import pytest
from derzug.nodes.filter import (
    FilterParams,
    GaussianFilterParams,
    HampelFilterParams,
    MedianFilterParams,
    NotchFilterParams,
    PassFilterParams,
    SavgolFilterParams,
    SlopeFilterParams,
    SobelFilterParams,
    WienerFilterParams,
)
from derzug.utils.testing import widget_context
from derzug.widgets.filter import Filter
from pydantic import TypeAdapter


class TestFilterParamsModel:
    """The typed params model reflects and drives the widget."""

    def test_get_params_pass_filter(self, qtbot):
        """A pass filter reports a PassFilterParams with its real fields."""
        with widget_context(Filter) as widget:
            widget.apply_settings(
                {
                    "selected_dim": "time",
                    "selected_filter": "pass_filter",
                    "low_bound": "5 Hz",
                    "high_bound": "40 Hz",
                    "corners": 6,
                }
            )
            params = widget.get_params()
            assert isinstance(params, PassFilterParams)
            assert params.low_bound == "5 Hz"
            assert params.high_bound == "40 Hz"
            assert params.corners == 6

    def test_apply_params_notch_cascades(self, qtbot):
        """Applying a NotchFilterParams switches the widget and its page."""
        with widget_context(Filter) as widget:
            prior = widget.apply_params(
                NotchFilterParams(dim="time", frequency="60 Hz", q=30.0)
            )
            assert widget.selected_filter == "notch_filter"
            assert widget.filter_window == "60 Hz"  # frequency -> filter_window
            assert widget.q == 30.0
            assert widget._stack.currentIndex() == 3  # notch page
            assert "selected_filter" in prior  # prior returned for undo

            # round-trips back out as the same typed model
            assert widget.get_params() == NotchFilterParams(
                dim="time", frequency="60 Hz", q=30.0
            )

    def test_apply_params_accepts_dict(self, qtbot):
        """A plain dict is validated into the discriminated union."""
        with widget_context(Filter) as widget:
            widget.apply_params(
                {"kind": "pass_filter", "dim": "time", "low_bound": "1 Hz"}
            )
            assert isinstance(widget.get_params(), PassFilterParams)
            assert widget.low_bound == "1 Hz"

    @pytest.mark.parametrize(
        "model",
        [
            PassFilterParams(dim="time", low_bound="5 Hz", high_bound="40 Hz"),
            NotchFilterParams(dim="time", frequency="60 Hz", q=30.0),
            MedianFilterParams(dim="time", window="0.02"),
            HampelFilterParams(dim="time", window="0.02", threshold=5.0),
            SavgolFilterParams(dim="time", window="0.02", polyorder=2),
            WienerFilterParams(dim="time", window="0.02"),
            GaussianFilterParams(dim="time", truncate=3.0),
            SobelFilterParams(dim="time"),
            SlopeFilterParams(slope_filt="1,2"),
        ],
    )
    def test_all_filter_types_roundtrip(self, model, qtbot):
        """Every modeled filter type applies and reads back as the same model."""
        with widget_context(Filter) as widget:
            widget.apply_params(model)
            assert widget.get_params() == model

    def test_schema_is_discriminated(self):
        """The JSON schema an agent would read distinguishes the filter types."""
        schema = TypeAdapter(FilterParams).json_schema()
        text = str(schema)
        assert "pass_filter" in text and "notch_filter" in text
        assert "frequency" in text  # notch names its frequency explicitly


def test_filter_params_survive_ows_roundtrip(qtbot, tmp_path):
    """A notch set via the model round-trips through save + reload as a model."""
    from derzug.dascore import namespace as ns

    def _filter_desc(window):
        for desc in window.widget_registry.widgets():
            if desc.qualified_name == "derzug.widgets.filter.Filter":
                return desc
        raise LookupError("Filter not registered")

    window = ns._create_main_window()
    scheme = window.current_document().scheme()
    node = scheme.new_node(_filter_desc(window), title="flt", position=(0.0, 0.0))
    widget = scheme.widget_for_node(node)
    widget.apply_params(NotchFilterParams(dim="time", frequency="60 Hz", q=30.0))

    path = os.path.join(tempfile.mkdtemp(), "filter_roundtrip.ows")
    window.save_scheme_to(scheme, path)

    reloaded = ns._create_main_window()
    reloaded.load_scheme(path)
    reloaded_scheme = reloaded.current_document().scheme()
    restored = next(
        reloaded_scheme.widget_for_node(n)
        for n in reloaded_scheme.nodes
        if isinstance(reloaded_scheme.widget_for_node(n), Filter)
    )

    assert restored.get_params() == NotchFilterParams(
        dim="time", frequency="60 Hz", q=30.0
    )
