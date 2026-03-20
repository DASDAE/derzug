"""
Tests for derzug.core.abstractcontrols.
"""

# ruff: noqa: D101, D102

from __future__ import annotations

from typing import Annotated

from derzug.core.abstractcontrols import (
    AbstractControl,
    CheckboxControl,
    ComboControl,
    DoubleSpinControl,
    HiddenControl,
    LineEditControl,
    SkipControl,
    SpinControl,
    get_control,
)

# ---------------------------------------------------------------------------
# Instantiation and defaults
# ---------------------------------------------------------------------------


class TestAbstractControl:
    """AbstractControl provides default label=None and group='Parameters'."""

    def test_defaults(self):
        ctrl = AbstractControl()
        assert ctrl.label is None
        assert ctrl.group == "Parameters"

    def test_label_override(self):
        ctrl = AbstractControl(label="My Label")
        assert ctrl.label == "My Label"

    def test_group_override(self):
        ctrl = AbstractControl(group="IO")
        assert ctrl.group == "IO"


class TestHiddenControl:
    def test_is_abstract_control(self):
        assert isinstance(HiddenControl(), AbstractControl)

    def test_defaults_inherited(self):
        ctrl = HiddenControl()
        assert ctrl.label is None
        assert ctrl.group == "Parameters"


class TestSkipControl:
    def test_is_abstract_control(self):
        assert isinstance(SkipControl(), AbstractControl)


class TestComboControl:
    def test_is_abstract_control(self):
        assert isinstance(ComboControl(), AbstractControl)

    def test_default_binds_to(self):
        assert ComboControl().binds_to == ""

    def test_binds_to_set(self):
        ctrl = ComboControl(binds_to="selection")
        assert ctrl.binds_to == "selection"

    def test_label_and_group(self):
        ctrl = ComboControl(label="Pick one", group="IO", binds_to="sel")
        assert ctrl.label == "Pick one"
        assert ctrl.group == "IO"


class TestSpinControl:
    def test_is_abstract_control(self):
        assert isinstance(SpinControl(), AbstractControl)

    def test_default_bounds(self):
        ctrl = SpinControl()
        assert ctrl.min == -(2**31)
        assert ctrl.max == 2**31 - 1

    def test_custom_bounds(self):
        ctrl = SpinControl(min=0, max=100)
        assert ctrl.min == 0
        assert ctrl.max == 100


class TestDoubleSpinControl:
    def test_is_abstract_control(self):
        assert isinstance(DoubleSpinControl(), AbstractControl)

    def test_default_bounds_are_float(self):
        ctrl = DoubleSpinControl()
        assert isinstance(ctrl.min, float)
        assert isinstance(ctrl.max, float)

    def test_custom_bounds(self):
        ctrl = DoubleSpinControl(min=-1.5, max=1.5)
        assert ctrl.min == -1.5
        assert ctrl.max == 1.5


class TestCheckboxControl:
    def test_is_abstract_control(self):
        assert isinstance(CheckboxControl(), AbstractControl)


class TestLineEditControl:
    def test_is_abstract_control(self):
        assert isinstance(LineEditControl(), AbstractControl)


# ---------------------------------------------------------------------------
# get_control
# ---------------------------------------------------------------------------


class TestGetControl:
    """get_control extracts the first AbstractControl from Annotated metadata."""

    def test_returns_none_for_plain_type(self):
        assert get_control(int) is None

    def test_returns_none_for_annotated_without_control(self):
        assert get_control(Annotated[int, "some_string"]) is None

    def test_returns_control_from_annotated(self):
        ctrl = SpinControl(min=0, max=10)
        annotation = Annotated[int, ctrl]
        assert get_control(annotation) is ctrl

    def test_returns_first_control_when_multiple(self):
        ctrl1 = SpinControl()
        ctrl2 = CheckboxControl()
        annotation = Annotated[int, ctrl1, ctrl2]
        assert get_control(annotation) is ctrl1

    def test_hidden_control_extracted(self):
        annotation = Annotated[str | None, HiddenControl()]
        result = get_control(annotation)
        assert isinstance(result, HiddenControl)

    def test_combo_control_extracted(self):
        annotation = Annotated[tuple, ComboControl(binds_to="sel")]
        result = get_control(annotation)
        assert isinstance(result, ComboControl)
        assert result.binds_to == "sel"
