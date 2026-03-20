"""Tests for signature-driven example-parameter helpers."""

from __future__ import annotations

import inspect

import numpy as np
from derzug.utils.example_parameters import (
    ExampleParametersDialog,
    build_example_call_kwargs,
    filter_example_overrides,
    get_example_parameter_specs,
    parse_example_parameter_text,
)


def _fake_example(
    sample_rate: int = 150,
    duration: float = 1.5,
    enabled: bool = True,
    label: str = "demo",
    shape=(10, 20),
    time_step=np.timedelta64(4, "ms"),
    maybe: float | None = None,
    **kwargs,
):
    return kwargs


class TestExampleParameters:
    """Tests for the example parameter utility module."""

    def test_signature_parsing_skips_variadics_and_keeps_supported_params(self):
        """Supported parameters should be extracted from the callable signature."""
        specs = get_example_parameter_specs(_fake_example)
        names = [spec.name for spec in specs]

        assert names == [
            "sample_rate",
            "duration",
            "enabled",
            "label",
            "shape",
            "time_step",
            "maybe",
        ]

    def test_build_call_kwargs_filters_unknown_keys(self):
        """Only supported saved overrides should be forwarded into the example call."""
        kwargs = build_example_call_kwargs(
            _fake_example,
            {"sample_rate": 200, "unknown": "ignored"},
        )

        assert kwargs == {"sample_rate": 200}

    def test_filter_example_overrides_drops_default_values(self):
        """Persisted state should keep only non-default parameter overrides."""
        specs = get_example_parameter_specs(_fake_example)
        overrides = filter_example_overrides(
            specs,
            {
                "sample_rate": 150,
                "duration": 2.0,
                "enabled": True,
                "label": "demo",
            },
        )

        assert overrides == {"duration": 2.0}

    def test_parse_example_parameter_text_uses_sample_specific_parsers(self):
        """Timedeltas and optional values should parse from dialog text."""
        parsed_timedelta = parse_example_parameter_text(
            "4 milliseconds",
            default=np.timedelta64(4, "ms"),
            annotation=inspect._empty,
            optional=False,
        )
        parsed_optional = parse_example_parameter_text(
            "",
            default=None,
            annotation=float | None,
            optional=True,
        )

        assert parsed_timedelta == np.timedelta64(4, "ms")
        assert parsed_optional is None

    def test_dialog_round_trips_supported_values(self, qtbot):
        """The dialog should parse edited field values into Python objects."""
        specs = get_example_parameter_specs(_fake_example)
        dialog = ExampleParametersDialog(
            example_name="fake",
            specs=specs,
            saved_values={"duration": 2.5, "shape": (3, 4), "maybe": 1.0},
        )
        qtbot.addWidget(dialog)

        dialog._inputs["sample_rate"].setValue(300)
        dialog._inputs["enabled"].setChecked(False)
        dialog._inputs["shape"].setText("(4, 5)")
        dialog._inputs["time_step"].setText("8 milliseconds")
        dialog._inputs["maybe"].setText("")
        dialog._apply()

        assert dialog.result() == dialog.DialogCode.Accepted
        assert dialog.parsed_values["sample_rate"] == 300
        assert dialog.parsed_values["enabled"] is False
        assert dialog.parsed_values["shape"] == (4, 5)
        assert dialog.parsed_values["time_step"] == np.timedelta64(8, "ms")
        assert dialog.parsed_values["maybe"] is None
