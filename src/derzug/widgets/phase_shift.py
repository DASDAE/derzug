"""Orange widget for DASCore phase-shift dispersion transforms."""

from __future__ import annotations

from typing import ClassVar

import dascore as dc
import numpy as np
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.orange import Setting
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow import Task


class PhaseShiftTransformTask(Task):
    """Portable phase-shift dispersion task mirroring widget settings."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    velocity_min: float = 100.0
    velocity_max: float = 1500.0
    velocity_step: float = 1.0
    approx_resolution: float | None = 0.1
    frequency_min: float | None = 5.0
    frequency_max: float | None = 70.0
    flip_distance: bool = False

    def phase_velocities(self) -> np.ndarray:
        """Return the velocity axis passed to DASCore."""
        return np.arange(self.velocity_min, self.velocity_max, self.velocity_step)

    def approx_freq(self) -> tuple[float, float] | None:
        """Return optional frequency bounds for DASCore."""
        if self.frequency_min is None and self.frequency_max is None:
            return None
        if self.frequency_min is None or self.frequency_max is None:
            msg = "frequency min and max must both be set or both be blank"
            raise ValueError(msg)
        return (self.frequency_min, self.frequency_max)

    def run(self, patch):
        """Apply the configured dispersion transform to one patch."""
        source = patch.flip("distance") if self.flip_distance else patch
        return source.dispersion_phase_shift(
            self.phase_velocities(),
            approx_resolution=self.approx_resolution,
            approx_freq=self.approx_freq(),
        )


class PhaseShiftTransform(ZugWidget):
    """Compute dispersion images with DASCore's phase-shift transform."""

    name = "Phase Shift"
    description = "Compute a phase-shift dispersion image from a patch"
    icon = "icons/PhaseShift.svg"
    category = "Transform"
    keywords = ("phase", "shift", "dispersion", "velocity", "masw")
    priority = 21.16
    want_main_area = False

    velocity_min = Setting("100")
    velocity_max = Setting("1500")
    velocity_step = Setting("1")
    approx_resolution = Setting("0.1")
    frequency_min = Setting("5")
    frequency_max = Setting("70")
    flip_distance = Setting(False)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        invalid_patch = Msg("Phase Shift requires a patch with time and distance dims")
        invalid_velocity = Msg("Invalid velocity settings: {}")
        invalid_frequency = Msg("Invalid frequency bounds: {}")
        invalid_resolution = Msg("Invalid approximate resolution '{}': {}")
        transform_failed = Msg("Phase Shift failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch, doc="DAS patch to transform")

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch, doc="Patch after phase-shift transform")

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None

        box = gui.widgetBox(self.controlArea, "Parameters")
        gui.lineEdit(
            box,
            self,
            "velocity_min",
            label="Velocity min",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "velocity_max",
            label="Velocity max",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "velocity_step",
            label="Velocity step",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "approx_resolution",
            label="Frequency resolution",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "frequency_min",
            label="Frequency min",
            callback=self.run,
        )
        gui.lineEdit(
            box,
            self,
            "frequency_max",
            label="Frequency max",
            callback=self.run,
        )
        gui.checkBox(
            box,
            self,
            "flip_distance",
            label="Flip distance",
            callback=self.run,
        )

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and run the phase-shift transform."""
        self._patch = patch
        self.run()

    def _supports_async_execution(self) -> bool:
        """Run phase-shift transforms off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one phase-shift execution request."""
        patch = self._patch
        if patch is None:
            return None
        return self._build_task_execution_request(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    @staticmethod
    def _parse_required_float(text: str, *, name: str) -> float:
        """Parse one required numeric value."""
        value = parse_patch_text_value(text, required=True)
        try:
            return float(value)
        except Exception as exc:
            raise ValueError(f"{name} must be numeric") from exc

    @staticmethod
    def _parse_optional_float(text: str, *, name: str) -> float | None:
        """Parse one optional numeric value."""
        if not str(text).strip():
            return None
        value = parse_patch_text_value(text, required=True)
        try:
            return float(value)
        except Exception as exc:
            raise ValueError(f"{name} must be numeric") from exc

    def _parse_velocity_settings(self) -> tuple[float, float, float]:
        """Return validated phase velocity range settings."""
        low = self._parse_required_float(self.velocity_min, name="velocity min")
        high = self._parse_required_float(self.velocity_max, name="velocity max")
        step = self._parse_required_float(self.velocity_step, name="velocity step")
        if low <= 0 or high <= 0:
            raise ValueError("velocities must be positive")
        if step <= 0:
            raise ValueError("velocity step must be positive")
        if low >= high:
            raise ValueError("velocity min must be less than velocity max")
        velocities = np.arange(low, high, step)
        if velocities.size == 0:
            raise ValueError("velocity settings produce no samples")
        return low, high, step

    def _parse_frequency_bounds(self) -> tuple[float | None, float | None]:
        """Return validated optional frequency bounds."""
        low = self._parse_optional_float(self.frequency_min, name="frequency min")
        high = self._parse_optional_float(self.frequency_max, name="frequency max")
        if low is None and high is None:
            return None, None
        if low is None or high is None:
            raise ValueError("frequency min and max must both be set or both be blank")
        if low < 0 or high < 0:
            raise ValueError("frequency bounds must be non-negative")
        if low >= high:
            raise ValueError("frequency min must be less than frequency max")
        return low, high

    def _parse_resolution(self) -> float | None:
        """Return optional approximate frequency resolution."""
        value = self._parse_optional_float(
            self.approx_resolution,
            name="frequency resolution",
        )
        if value is not None and value <= 0:
            raise ValueError("frequency resolution must be positive")
        return value

    def _validated_task(self) -> Task | None:
        """Return the current phase-shift task after widget-side validation."""
        patch = self._patch
        if patch is not None and not {"time", "distance"}.issubset(patch.dims):
            self._show_error_message("invalid_patch")
            return None
        try:
            velocity_min, velocity_max, velocity_step = self._parse_velocity_settings()
        except Exception as exc:
            self._show_exception("invalid_velocity", exc)
            return None
        try:
            frequency_min, frequency_max = self._parse_frequency_bounds()
        except Exception as exc:
            self._show_exception("invalid_frequency", exc)
            return None
        try:
            approx_resolution = self._parse_resolution()
        except Exception as exc:
            self._show_exception(
                "invalid_resolution",
                exc,
                self.approx_resolution,
            )
            return None
        return PhaseShiftTransformTask(
            velocity_min=velocity_min,
            velocity_max=velocity_max,
            velocity_step=velocity_step,
            approx_resolution=approx_resolution,
            frequency_min=frequency_min,
            frequency_max=frequency_max,
            flip_distance=bool(self.flip_distance),
        )

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the phase-shift banner."""
        self._show_exception("transform_failed", exc)

    def _on_result(self, result: dc.Patch | None) -> None:
        """Send the transformed patch."""
        self.Outputs.patch.send(result)

    def get_task(self) -> Task:
        """Return the current phase-shift semantics as a workflow task."""
        velocity_min, velocity_max, velocity_step = self._parse_velocity_settings()
        frequency_min, frequency_max = self._parse_frequency_bounds()
        return PhaseShiftTransformTask(
            velocity_min=velocity_min,
            velocity_max=velocity_max,
            velocity_step=velocity_step,
            approx_resolution=self._parse_resolution(),
            frequency_min=frequency_min,
            frequency_max=frequency_max,
            flip_distance=bool(self.flip_distance),
        )


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(PhaseShiftTransform).run()
