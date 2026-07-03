"""Cross-widget tests for the unified ``ZugWidget.apply_settings`` interface."""

from __future__ import annotations

import importlib
import inspect

import pytest
from AnyQt.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
)
from derzug.core import ZugWidget
from derzug.utils.misc import load_widget_entrypoints
from derzug.utils.testing import widget_context


def _widget_classes():
    """Return every registered concrete ZugWidget class as pytest params."""
    found: dict[str, type] = {}
    for entry_point in load_widget_entrypoints():
        try:
            module = importlib.import_module(entry_point.value)
        except Exception:
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ZugWidget)
                and obj.__module__ == entry_point.value
                and getattr(obj, "name", "")
            ):
                found[obj.__name__] = obj
    return [pytest.param(cls, id=name) for name, cls in sorted(found.items())]


WIDGET_CLASSES = _widget_classes()


@pytest.mark.parametrize("widget_cls", WIDGET_CLASSES)
class TestApplySettingsContract:
    """Every widget honors the unified apply_settings contract."""

    def test_noop_apply_is_safe(self, widget_cls, qtbot):
        """Applying no values is a no-op that returns no prior values."""
        with widget_context(widget_cls) as widget:
            assert widget.apply_settings({}, run=False) == {}

    def test_unknown_setting_rejected(self, widget_cls, qtbot):
        """Applying an unknown setting name raises rather than silently passing."""
        with widget_context(widget_cls) as widget:
            with pytest.raises(KeyError):
                widget.apply_settings({"__definitely_not_a_setting__": 1})

    def test_control_map_names_are_settings(self, widget_cls, qtbot):
        """Every name in the control map is a real Setting on the widget."""
        with widget_context(widget_cls) as widget:
            for name in widget._settings_control_map():
                assert widget._is_setting(name), f"{widget_cls.__name__}.{name}"

    def test_mapped_settings_roundtrip_and_sync(self, widget_cls, qtbot):
        """Applying a mapped setting updates the value and its visible control."""
        with widget_context(widget_cls) as widget:
            for name, control in widget._settings_control_map().items():
                target = _alternate_value(control)
                if target is None:
                    continue
                widget.apply_settings({name: target})
                assert getattr(widget, name) == target  # setting applied
                assert _control_value(control) == target  # control synced


def _alternate_value(control):
    """Return a valid new value for a control, or None when not derivable."""
    if isinstance(control, QComboBox):
        current = control.currentText()
        for i in range(control.count()):
            if control.itemText(i) != current:
                return control.itemText(i)
        return None
    if isinstance(control, QAbstractButton):
        return not control.isChecked()
    if isinstance(control, QAbstractSpinBox):
        current = control.value()
        step = control.singleStep()
        decimals = getattr(control, "decimals", lambda: 0)()
        for candidate in (current + step, current - step):
            if control.minimum() <= candidate <= control.maximum():
                return round(candidate, decimals) if decimals else int(candidate)
        return None
    if isinstance(control, QAbstractSlider):
        current = control.value()
        step = control.singleStep() or 1
        for candidate in (current + step, current - step):
            if control.minimum() <= candidate <= control.maximum():
                return int(candidate)
        return None
    return None


def _control_value(control):
    """Return the current value of a control, matching its Setting form."""
    if isinstance(control, QComboBox):
        return control.currentText()
    if isinstance(control, QAbstractButton):
        return control.isChecked()
    if isinstance(control, QAbstractSpinBox | QAbstractSlider):
        return control.value()
    return None
