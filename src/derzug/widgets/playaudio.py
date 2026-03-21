"""Audio playback widget for 1D DASCore time patches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from math import isfinite

import dascore as dc
import numpy as np
import pyqtgraph as pg
from AnyQt.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer
from AnyQt.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.orange import Setting
from derzug.utils.display import format_display


def _load_qt_multimedia():
    """Load QtMultimedia from whichever PyQt binding is available."""
    for module_name, sink_name, backend in (
        ("PyQt6.QtMultimedia", "QAudioSink", "pyqt6"),
        ("PyQt5.QtMultimedia", "QAudioOutput", "pyqt5"),
    ):
        try:
            module = import_module(module_name)
        except (ImportError, OSError):
            continue
        sink = getattr(module, sink_name, None)
        if sink is None:
            continue
        return module.QAudio, module.QAudioFormat, sink, module_name, backend
    return None


_qt_multimedia = _load_qt_multimedia()
if _qt_multimedia is not None:
    (
        QAudio,
        QAudioFormat,
        QAudioSink,
        _QT_MULTIMEDIA_MODULE,
        _QT_MULTIMEDIA_BACKEND,
    ) = _qt_multimedia
    _QT_MULTIMEDIA_AVAILABLE = True
else:
    _QT_MULTIMEDIA_MODULE = None
    _QT_MULTIMEDIA_BACKEND = None
    _QT_MULTIMEDIA_AVAILABLE = False

    class QAudio:
        """Fallback QtMultimedia enums when the module is unavailable."""

        class Error(Enum):
            """Audio error codes."""

            NoError = 0

        class State(Enum):
            """Audio playback states."""

            StoppedState = 0
            ActiveState = 1
            IdleState = 2

    class QAudioFormat:
        """Fallback audio format storing the requested output settings."""

        class SampleFormat(Enum):
            """PCM sample formats."""

            Int16 = 0

        def __init__(self) -> None:
            self._sample_rate = 0
            self._channel_count = 0
            self._sample_format = self.SampleFormat.Int16

        def setSampleRate(self, value: int) -> None:
            """Set the sample rate in Hz."""
            self._sample_rate = int(value)

        def sampleRate(self) -> int:
            """Return the sample rate in Hz."""
            return int(self._sample_rate)

        def setChannelCount(self, value: int) -> None:
            """Set the channel count."""
            self._channel_count = int(value)

        def setSampleFormat(self, value) -> None:
            """Set the sample format."""
            self._sample_format = value

    class QAudioSink:
        """Fallback sink that raises when playback is attempted without QtMultimedia."""

        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("QtMultimedia is not available")


_AUDIBLE_MIN_HZ = 20.0
_AUDIBLE_MAX_HZ = 20_000.0
_DEFAULT_TARGET_HZ = 4_000.0
_MIN_PLAYBACK_DURATION_S = 2.0
_MIN_OUTPUT_SAMPLE_RATE_HZ = 8_000.0
_MAX_OUTPUT_SAMPLE_RATE_HZ = 48_000.0
_MIN_TIME_SCALE = 1e-6
_MAX_TIME_SCALE = 1e6
_PCM_HEADROOM = 0.95
_PCM_NORMALIZE_PERCENTILE = 95.0
_DEFAULT_OUTPUT_GAIN_DB = 0.0
_DEFAULT_VOLUME_PERCENT = 100
_MIN_VOLUME_PERCENT = 0
_MAX_VOLUME_PERCENT = 200


@dataclass(frozen=True)
class _PreparedAudio:
    """Prepared patch playback metadata and PCM payload."""

    native_rate_hz: float
    pcm_bytes: bytes
    sample_count: int


class PlayAudio(ZugWidget):
    """Play 1D DAS patches as audio with a configurable time scale."""

    name = "PlayAudio"
    description = "Play a 1D time patch as audio"
    icon = "icons/PlayAudio.svg"
    category = "Visualize"
    keywords = ("audio", "sound", "time", "patch")
    priority = 23

    time_scale = Setting(1.0)
    volume_percent = Setting(_DEFAULT_VOLUME_PERCENT)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        invalid_patch = Msg("{}")
        audio_failure = Msg("{}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch, doc="1D DAS patch to play")

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch, doc="Patch passed through unchanged")

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None
        self._prepared_audio: _PreparedAudio | None = None
        self._validation_error: str | None = None
        self._status_text = "No patch loaded"
        self._native_rate_hz: float | None = None
        self._audio_sink: QAudioSink | None = None
        self._audio_buffer: QBuffer | None = None
        self._audio_payload: QByteArray | None = None
        self._syncing_time_scale = False
        self._waveform_time_seconds: np.ndarray | None = None
        self._waveform_samples: np.ndarray | None = None
        self._playback_sample_index: int | None = None
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(30)
        self._playback_timer.timeout.connect(self._update_playback_marker)

        box = gui.widgetBox(self.controlArea, "Playback")
        gui.widgetLabel(box, "Time scale:")
        self._time_scale_spin = QDoubleSpinBox(box)
        self._time_scale_spin.setDecimals(6)
        self._time_scale_spin.setRange(_MIN_TIME_SCALE, _MAX_TIME_SCALE)
        self._time_scale_spin.setStepType(
            QDoubleSpinBox.StepType.AdaptiveDecimalStepType
        )
        self._time_scale_spin.setValue(float(self.time_scale))
        box.layout().addWidget(self._time_scale_spin)
        gui.widgetLabel(box, "Volume:")
        self._volume_slider = gui.hSlider(
            box,
            self,
            "volume_percent",
            minValue=_MIN_VOLUME_PERCENT,
            maxValue=_MAX_VOLUME_PERCENT,
            step=1,
            createLabel=False,
            callback=self._on_volume_changed,
        )
        self._volume_label = gui.widgetLabel(box, "")
        self._update_volume_label()

        controls = QWidget(box)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        self._play_button = QPushButton("Play", controls)
        self._stop_button = QPushButton("Stop", controls)
        controls_layout.addWidget(self._play_button)
        controls_layout.addWidget(self._stop_button)
        box.layout().addWidget(controls)

        self._rate_label = QLabel("Native rate: --\nPlayback rate: --", box)
        self._rate_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.layout().addWidget(self._rate_label)

        self._status_label = QLabel(self._status_text, box)
        self._status_label.setWordWrap(True)
        box.layout().addWidget(self._status_label)

        panel = QWidget(self.mainArea)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(8)
        self._waveform_plot = pg.PlotWidget(panel, background="w")
        self._waveform_plot_item = self._waveform_plot.getPlotItem()
        self._waveform_plot_item.showGrid(x=True, y=True, alpha=0.2)
        self._waveform_plot_item.setLabel("left", "Amplitude")
        self._waveform_plot_item.setLabel("bottom", "Time (s)")
        self._waveform_curve = self._waveform_plot_item.plot(
            pen=pg.mkPen(color="#1f4e79", width=1.5)
        )
        self._waveform_marker = pg.ScatterPlotItem(
            size=9,
            brush=pg.mkBrush("#c0392b"),
            pen=pg.mkPen("#7f1d1d", width=1.0),
        )
        self._waveform_plot_item.addItem(self._waveform_marker)
        panel_layout.addWidget(self._waveform_plot)
        self._summary_label = QLabel(
            "Load a 1D patch with dim `time` to play audio.", panel
        )
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        panel_layout.addWidget(self._summary_label)
        panel_layout.addStretch(1)
        self.mainArea.layout().addWidget(panel)

        self._time_scale_spin.valueChanged.connect(self._on_time_scale_changed)
        self._play_button.clicked.connect(self._start_playback)
        self._stop_button.clicked.connect(self._stop_playback)
        self._refresh_controls()

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive a patch, analyze it for playback, and emit it unchanged."""
        self._stop_playback()
        self._patch = patch
        self._validation_error = None
        self._prepared_audio = None
        self._native_rate_hz = None
        if patch is None:
            self._status_text = "No patch loaded"
            self._waveform_time_seconds = None
            self._waveform_samples = None
            self._playback_sample_index = None
        else:
            try:
                playable_patch = self._coerce_playable_patch(patch)
                self._prepared_audio = self._prepare_patch_audio(
                    playable_patch,
                    output_gain_db=self._current_output_gain_db(),
                )
            except ValueError as exc:
                self._validation_error = str(exc)
                self._status_text = "Patch is not playable"
                self._waveform_time_seconds = None
                self._waveform_samples = None
                self._playback_sample_index = None
            else:
                self._native_rate_hz = self._prepared_audio.native_rate_hz
                self._status_text = "Ready to play"
                self._apply_default_time_scale(
                    self._prepared_audio.native_rate_hz,
                    self._prepared_audio.sample_count,
                )
                self._set_waveform_data(playable_patch)
        self._request_ui_refresh()
        self.Outputs.patch.send(patch)

    def onDeleteWidget(self) -> None:
        """Stop active playback before the widget is destroyed."""
        self._stop_playback()
        super().onDeleteWidget()

    def _refresh_ui(self) -> None:
        """Refresh labels, messages, and enabled state from the current patch."""
        self.Error.clear()
        self._refresh_controls()
        self._refresh_labels()
        self._refresh_waveform_plot()
        if self._validation_error is not None:
            self._show_error_message("invalid_patch", self._validation_error)

    def _refresh_controls(self) -> None:
        """Enable controls based on whether a playable patch is available."""
        playable = self._prepared_audio is not None
        playing = self._audio_sink is not None
        self._time_scale_spin.setEnabled(playable and not playing)
        self._volume_slider.setEnabled(playable and not playing)
        self._play_button.setEnabled(playable and not playing)
        self._stop_button.setEnabled(playing)

    def _refresh_labels(self) -> None:
        """Update the visible readouts for playback state."""
        effective_rate_hz = self._effective_sample_rate_hz()
        if self._patch is None:
            summary = "Load a 1D patch with dim `time` to play audio."
        elif self._validation_error is not None:
            summary = self._validation_error
        elif self._prepared_audio is not None:
            duration = (
                self._prepared_audio.sample_count / self._prepared_audio.native_rate_hz
            )
            summary = (
                f"Samples: {self._prepared_audio.sample_count}\n"
                f"Duration: {format_display(duration)} s"
            )
        else:
            summary = "Load a playable patch to start audio."
        self._summary_label.setText(summary)

        if self._native_rate_hz is None:
            self._rate_label.setText("Native rate: --\nPlayback rate: --")
        else:
            self._rate_label.setText(
                f"Native rate: {format_display(self._native_rate_hz)} Hz\n"
                f"Playback rate: {format_display(effective_rate_hz)} Hz\n"
                f"Volume: {self.volume_percent}% "
                f"({format_display(self._current_output_gain_db())} dB)"
            )
        self._update_volume_label()
        self._status_label.setText(self._status_text)

    def _apply_default_time_scale(
        self, native_rate_hz: float, sample_count: int
    ) -> None:
        """Set the default time scale for a newly received valid patch."""
        self._syncing_time_scale = True
        try:
            self.time_scale = self._default_time_scale(native_rate_hz, sample_count)
            self._time_scale_spin.setValue(self.time_scale)
        finally:
            self._syncing_time_scale = False

    def _on_time_scale_changed(self, value: float) -> None:
        """Persist user-selected time-scale changes and refresh readouts."""
        if self._syncing_time_scale:
            return
        self.time_scale = float(value)
        self._request_ui_refresh()

    def _on_volume_changed(self, *_args) -> None:
        """Persist user-selected volume changes and re-render prepared PCM."""
        self._update_volume_label()
        if self._patch is not None and self._validation_error is None:
            try:
                playable_patch = self._coerce_playable_patch(self._patch)
                self._prepared_audio = self._prepare_patch_audio(
                    playable_patch,
                    output_gain_db=self._current_output_gain_db(),
                )
            except ValueError as exc:
                self._prepared_audio = None
                self._validation_error = str(exc)
                self._status_text = "Patch is not playable"
        self._request_ui_refresh()

    def _update_volume_label(self) -> None:
        """Refresh the visible label for the current volume slider value."""
        if hasattr(self, "_volume_label"):
            self._volume_label.setText(
                f"{self.volume_percent}% "
                f"({format_display(self._current_output_gain_db())} dB)"
            )

    def _current_output_gain_db(self) -> float:
        """Return the current slider volume mapped to decibels."""
        return self._output_gain_db_from_volume_percent(int(self.volume_percent))

    @staticmethod
    def _output_gain_db_from_volume_percent(volume_percent: int) -> float:
        """Map a UI volume percentage onto a linear-gain dB value."""
        if volume_percent <= 0:
            return -120.0
        return float(20.0 * np.log10(float(volume_percent) / 100.0))

    def _start_playback(self) -> None:
        """Start audio playback for the current prepared patch."""
        self.Error.audio_failure.clear()
        prepared = self._prepared_audio
        if prepared is None:
            return
        self._stop_playback()
        effective_rate_hz = self._effective_sample_rate_hz()
        sample_rate = self._playback_output_rate_hz(effective_rate_hz)
        audio_format = self._build_audio_format(sample_rate)
        payload = QByteArray(
            self._render_playback_pcm(
                prepared,
                effective_rate_hz=effective_rate_hz,
                output_rate_hz=sample_rate,
            )
        )
        buffer = QBuffer(self)
        buffer.setData(payload)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            self._show_error_message("audio_failure", "Could not open the audio buffer")
            self._status_text = "Playback failed"
            self._refresh_ui()
            return
        try:
            sink = self._create_audio_sink(audio_format)
        except Exception as exc:
            buffer.close()
            self._show_error_message(
                "audio_failure", f"Could not initialize audio output: {exc}"
            )
            self._status_text = "Playback failed"
            self._refresh_ui()
            return

        self._audio_payload = payload
        self._audio_buffer = buffer
        self._audio_sink = sink
        self._audio_sink.stateChanged.connect(self._on_audio_state_changed)
        self._audio_sink.start(buffer)
        if self._audio_sink.error() != QAudio.Error.NoError:
            error = self._audio_sink.error()
            self._stop_playback()
            self._show_error_message(
                "audio_failure", f"Audio playback failed: {error.name}"
            )
            self._status_text = "Playback failed"
        else:
            self._status_text = "Playing"
            self._playback_timer.start()
            self._set_playback_marker(0)
        self._refresh_ui()

    def _stop_playback(self) -> None:
        """Stop any active sink and release playback resources."""
        self._playback_timer.stop()
        if self._audio_sink is not None:
            try:
                self._audio_sink.stateChanged.disconnect(self._on_audio_state_changed)
            except TypeError:
                pass
            self._audio_sink.stop()
            self._audio_sink.deleteLater()
            self._audio_sink = None
        if self._audio_buffer is not None:
            self._audio_buffer.close()
            self._audio_buffer.deleteLater()
            self._audio_buffer = None
        self._audio_payload = None
        if self._prepared_audio is not None and self._validation_error is None:
            self._status_text = "Ready to play"
        elif self._patch is None:
            self._status_text = "No patch loaded"
        else:
            self._status_text = "Patch is not playable"
        if self._waveform_samples is not None and self._waveform_samples.size:
            self._set_playback_marker(0)
        else:
            self._set_playback_marker(None)
        self._refresh_controls()
        self._refresh_labels()

    def _on_audio_state_changed(self, state: QAudio.State) -> None:
        """Update widget status when Qt playback state changes."""
        if state == QAudio.State.ActiveState:
            self._status_text = "Playing"
            self._refresh_ui()
            return
        if state == QAudio.State.IdleState:
            self._stop_playback()
            self._status_text = "Playback finished"
            self._refresh_ui()
            return
        if state == QAudio.State.StoppedState and self._audio_sink is not None:
            error = self._audio_sink.error()
            if error != QAudio.Error.NoError:
                self._show_error_message(
                    "audio_failure", f"Audio playback failed: {error.name}"
                )
                self._status_text = "Playback failed"
            self._refresh_ui()

    def _effective_sample_rate_hz(self) -> float:
        """Return the current effective playback rate in Hz."""
        if self._native_rate_hz is None:
            return float("nan")
        return self._native_rate_hz * float(self.time_scale)

    def _set_waveform_data(self, patch: dc.Patch) -> None:
        """Cache waveform data for the plot using seconds relative to the start."""
        samples = np.asarray(patch.data, dtype=np.float64).reshape(-1)
        time_seconds = self._coord_to_seconds(np.asarray(patch.get_array("time")))
        time_seconds = np.asarray(time_seconds, dtype=np.float64)
        if time_seconds.size:
            time_seconds = time_seconds - float(time_seconds[0])
        self._waveform_time_seconds = time_seconds
        self._waveform_samples = samples
        self._playback_sample_index = 0 if samples.size else None

    def _refresh_waveform_plot(self) -> None:
        """Refresh the waveform curve and marker from the cached patch data."""
        if (
            self._waveform_time_seconds is None
            or self._waveform_samples is None
            or self._waveform_time_seconds.size == 0
            or self._waveform_samples.size == 0
        ):
            self._waveform_curve.setData([], [])
            self._waveform_marker.setData([], [])
            self._waveform_plot_item.setTitle("No waveform")
            return
        self._waveform_curve.setData(
            self._waveform_time_seconds, self._waveform_samples
        )
        self._waveform_plot_item.setTitle("Waveform")
        self._set_playback_marker(self._playback_sample_index)
        self._waveform_plot_item.enableAutoRange(x=True, y=True)
        self._waveform_plot_item.autoRange()

    def _set_playback_marker(self, sample_index: int | None) -> None:
        """Place the playback marker on the waveform, or hide it."""
        self._playback_sample_index = sample_index
        if (
            sample_index is None
            or self._waveform_time_seconds is None
            or self._waveform_samples is None
            or self._waveform_time_seconds.size == 0
            or self._waveform_samples.size == 0
        ):
            self._waveform_marker.setData([], [])
            return
        index = int(np.clip(sample_index, 0, self._waveform_samples.size - 1))
        self._playback_sample_index = index
        self._waveform_marker.setData(
            [float(self._waveform_time_seconds[index])],
            [float(self._waveform_samples[index])],
        )

    def _update_playback_marker(self) -> None:
        """Advance the waveform marker to the current playback position."""
        sink = self._audio_sink
        prepared = self._prepared_audio
        if sink is None or prepared is None:
            return
        processed_usecs = getattr(sink, "processedUSecs", None)
        if processed_usecs is None:
            return
        try:
            elapsed_usec = int(processed_usecs())
        except Exception:
            return
        sample_rate = self._effective_sample_rate_hz()
        if not np.isfinite(sample_rate) or sample_rate <= 0:
            return
        sample_index = int((elapsed_usec / 1_000_000.0) * sample_rate)
        if sample_index >= prepared.sample_count:
            sample_index = prepared.sample_count - 1
        self._set_playback_marker(sample_index)

    @staticmethod
    def _default_time_scale(native_rate_hz: float, sample_count: int) -> float:
        """Choose a default scale that moves the source into audible range."""
        if _AUDIBLE_MIN_HZ <= native_rate_hz <= _AUDIBLE_MAX_HZ:
            scale = 1.0
        elif native_rate_hz <= 0:
            scale = 1.0
        else:
            scale = float(_DEFAULT_TARGET_HZ / native_rate_hz)
        if native_rate_hz > 0 and sample_count > 0:
            duration_seconds = float(sample_count) / float(native_rate_hz)
            min_duration_scale = duration_seconds / _MIN_PLAYBACK_DURATION_S
            if duration_seconds < _MIN_PLAYBACK_DURATION_S:
                scale = min(scale, min_duration_scale)
        return float(np.clip(scale, _MIN_TIME_SCALE, _MAX_TIME_SCALE))

    @staticmethod
    def _playback_output_rate_hz(effective_rate_hz: float) -> int:
        """Clamp the audio-device output rate to a broadly supported range."""
        if not isfinite(effective_rate_hz) or effective_rate_hz <= 0:
            raise ValueError("effective sample rate must be positive")
        return round(
            float(
                np.clip(
                    effective_rate_hz,
                    _MIN_OUTPUT_SAMPLE_RATE_HZ,
                    _MAX_OUTPUT_SAMPLE_RATE_HZ,
                )
            )
        )

    @staticmethod
    def _render_playback_pcm(
        prepared: _PreparedAudio,
        *,
        effective_rate_hz: float,
        output_rate_hz: int,
    ) -> bytes:
        """Render PCM, stretching or resampling when sink rate is clamped."""
        if prepared.sample_count <= 0:
            return b""
        if not isfinite(effective_rate_hz) or effective_rate_hz <= 0:
            raise ValueError("effective sample rate must be positive")
        if output_rate_hz <= 0:
            raise ValueError("output sample rate must be positive")
        if round(effective_rate_hz) == output_rate_hz:
            return prepared.pcm_bytes

        source = (
            np.frombuffer(prepared.pcm_bytes, dtype="<i2").astype(np.float64)
            / np.iinfo(np.int16).max
        )
        target_count = max(
            1,
            round(prepared.sample_count * float(output_rate_hz) / effective_rate_hz),
        )
        if target_count == prepared.sample_count:
            return prepared.pcm_bytes
        if prepared.sample_count == 1:
            resampled = np.full(target_count, source[0], dtype=np.float64)
        else:
            source_x = np.linspace(0.0, 1.0, prepared.sample_count, endpoint=True)
            target_x = np.linspace(0.0, 1.0, target_count, endpoint=True)
            resampled = np.interp(target_x, source_x, source)
        pcm = np.rint(np.clip(resampled, -1.0, 1.0) * np.iinfo(np.int16).max).astype(
            "<i2"
        )
        return pcm.tobytes()

    @staticmethod
    def _build_audio_format(sample_rate_hz: int) -> QAudioFormat:
        """Build the mono PCM format used for playback."""
        audio_format = QAudioFormat()
        audio_format.setSampleRate(int(sample_rate_hz))
        audio_format.setChannelCount(1)
        if _QT_MULTIMEDIA_BACKEND == "pyqt5":
            audio_format.setCodec("audio/pcm")
            audio_format.setSampleSize(16)
            audio_format.setSampleType(QAudioFormat.SignedInt)
            audio_format.setByteOrder(QAudioFormat.LittleEndian)
        else:
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return audio_format

    def _create_audio_sink(self, audio_format: QAudioFormat) -> QAudioSink:
        """Create a Qt audio sink for the requested output format."""
        return QAudioSink(audio_format, self)

    @classmethod
    def _prepare_patch_audio(
        cls,
        patch: dc.Patch,
        *,
        output_gain_db: float = _DEFAULT_OUTPUT_GAIN_DB,
    ) -> _PreparedAudio:
        """Validate the patch and prepare normalized PCM audio bytes."""
        cls._validate_patch_shape(patch)
        native_rate_hz = cls._infer_native_rate_hz(np.asarray(patch.get_array("time")))
        pcm_bytes, sample_count = cls._prepare_pcm_audio(
            np.asarray(patch.data),
            output_gain_db=output_gain_db,
        )
        return _PreparedAudio(
            native_rate_hz=native_rate_hz,
            pcm_bytes=pcm_bytes,
            sample_count=sample_count,
        )

    @staticmethod
    def _coerce_playable_patch(patch: dc.Patch) -> dc.Patch:
        """Return the squeezed patch shape used for playback validation/rendering."""
        return patch.squeeze()

    @staticmethod
    def _validate_patch_shape(patch: dc.Patch) -> None:
        """Validate that the patch is a 1D time series."""
        data = np.asarray(patch.data)
        if data.ndim != 1:
            raise ValueError(f"expected a 1D patch, got shape {data.shape}")
        if tuple(patch.dims) != ("time",):
            raise ValueError(f"expected patch dims ('time',), got {patch.dims}")

    @staticmethod
    def _infer_native_rate_hz(coord: np.ndarray) -> float:
        """Infer the source sample rate from the patch time coordinate."""
        seconds = PlayAudio._coord_to_seconds(coord)
        if seconds.size < 2:
            raise ValueError("time coordinate must contain at least two samples")
        diffs = np.diff(seconds)
        if not np.all(np.isfinite(diffs)):
            raise ValueError("time coordinate must contain finite sample spacing")
        if np.any(diffs <= 0):
            raise ValueError("time coordinate must be strictly increasing")
        first = float(diffs[0])
        tolerance = max(abs(first) * 1e-6, 1e-12)
        if not np.allclose(diffs, first, rtol=1e-6, atol=tolerance):
            raise ValueError("time coordinate must have uniform sample spacing")
        rate_hz = 1.0 / first
        if not isfinite(rate_hz) or rate_hz <= 0:
            raise ValueError("time coordinate must define a positive sample rate")
        return rate_hz

    @staticmethod
    def _coord_to_seconds(coord: np.ndarray) -> np.ndarray:
        """Convert time coordinates to seconds for rate inference."""
        arr = np.asarray(coord)
        if np.issubdtype(arr.dtype, np.datetime64):
            ns = arr.astype("datetime64[ns]").astype(np.int64)
            return ns.astype(np.float64) / 1e9
        if np.issubdtype(arr.dtype, np.timedelta64):
            ns = arr.astype("timedelta64[ns]").astype(np.int64)
            return ns.astype(np.float64) / 1e9
        if np.issubdtype(arr.dtype, np.number):
            return arr.astype(np.float64)
        raise ValueError("time coordinate must be numeric or datetime-like")

    @staticmethod
    def _prepare_pcm_audio(
        data: np.ndarray,
        *,
        output_gain_db: float = _DEFAULT_OUTPUT_GAIN_DB,
    ) -> tuple[bytes, int]:
        """Normalize mono samples with robust auto-gain and convert to PCM."""
        samples = np.asarray(data, dtype=np.float64).reshape(-1)
        if samples.size == 0:
            raise ValueError("patch data is empty")
        finite_mask = np.isfinite(samples)
        if not np.any(finite_mask):
            raise ValueError("patch data must contain at least one finite sample")
        safe_samples = np.where(finite_mask, samples, 0.0)
        nonzero = np.abs(safe_samples[finite_mask])
        ref = float(np.percentile(nonzero, _PCM_NORMALIZE_PERCENTILE))
        if ref <= 0:
            ref = float(np.max(nonzero))
        if ref > 0:
            safe_samples = safe_samples * (_PCM_HEADROOM / ref)
        linear_gain = float(10 ** (float(output_gain_db) / 20.0))
        safe_samples = safe_samples * linear_gain
        safe_samples = np.clip(safe_samples, -_PCM_HEADROOM, _PCM_HEADROOM)
        pcm = np.rint(safe_samples * np.iinfo(np.int16).max).astype("<i2")
        return pcm.tobytes(), int(samples.size)
