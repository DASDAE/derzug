"""Tests for the PlayAudio widget."""

from __future__ import annotations

from importlib import import_module

import dascore as dc
import numpy as np
import pytest
from AnyQt.QtCore import QIODevice
from derzug.utils.testing import TestWidgetDefaults, widget_context
from derzug.widgets.playaudio import PlayAudio


def _import_qt_multimedia():
    """Import QtMultimedia from any supported PyQt binding."""
    for module_name in ("PyQt6.QtMultimedia", "PyQt5.QtMultimedia"):
        try:
            return import_module(module_name)
        except ModuleNotFoundError:
            continue
    pytest.skip("Neither PyQt6.QtMultimedia nor PyQt5.QtMultimedia is available")


_qt_multimedia = _import_qt_multimedia()
QAudio = _qt_multimedia.QAudio
QAudioFormat = _qt_multimedia.QAudioFormat


@pytest.fixture
def playaudio_widget(qtbot):
    """Return a live PlayAudio widget."""
    with widget_context(PlayAudio) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget


def _capture_patch_output(playaudio_widget, monkeypatch) -> list:
    """Capture patch outputs emitted by the widget."""
    received: list = []

    def _sink(value):
        received.append(value)

    monkeypatch.setattr(playaudio_widget.Outputs.patch, "send", _sink)
    return received


def _to_1d_time_patch() -> dc.Patch:
    """Return a valid 1D example patch with only the time dimension."""
    patch = dc.get_example_patch("example_event_2")
    return patch.mean("distance").squeeze()


def _to_non_time_patch() -> dc.Patch:
    """Return a 1D patch with a non-time dimension."""
    patch = dc.get_example_patch("example_event_2")
    return patch.mean("time").squeeze()


def _to_degenerate_2d_time_patch() -> dc.Patch:
    """Return a 2D patch whose singleton non-time axis squeezes away."""
    patch = dc.get_example_patch("example_event_2")
    return patch.select(samples=True, distance=(0, 1))


class _FakeAudioSink:
    """Minimal sink used to test playback without touching real audio devices."""

    def __init__(self, audio_format: QAudioFormat) -> None:
        self.audio_format = audio_format
        self._error = QAudio.Error.NoError
        self._state = QAudio.State.StoppedState
        self.started_device = None
        self.processed_usecs = 0

        class _Signal:
            def connect(self, _slot) -> None:
                return

            def disconnect(self, _slot) -> None:
                return

        self.stateChanged = _Signal()

    def start(self, device: QIODevice) -> None:
        self.started_device = device
        self._state = QAudio.State.ActiveState

    def stop(self) -> None:
        self._state = QAudio.State.StoppedState

    def deleteLater(self) -> None:
        return

    def error(self) -> QAudio.Error:
        return self._error

    def processedUSecs(self) -> int:
        return int(self.processed_usecs)


class TestPlayAudio:
    """Tests for PlayAudio widget behavior."""

    def test_patch_is_forwarded(self, playaudio_widget, monkeypatch):
        """Input patch is emitted unchanged on the output signal."""
        received = _capture_patch_output(playaudio_widget, monkeypatch)
        patch = _to_1d_time_patch()

        playaudio_widget.set_patch(patch)

        assert received == [patch]
        assert playaudio_widget._prepared_audio is not None

    def test_waveform_plot_loads_patch_and_places_marker_at_start(
        self, playaudio_widget
    ):
        """Loading a playable patch should render the waveform and a start marker."""
        patch = _to_1d_time_patch()

        playaudio_widget.set_patch(patch)

        x_data, y_data = playaudio_widget._waveform_curve.getData()
        marker_x, marker_y = playaudio_widget._waveform_marker.getData()
        assert len(x_data) == patch.data.size
        assert len(y_data) == patch.data.size
        assert marker_x == [0.0]
        assert marker_y == [float(np.asarray(patch.data)[0])]

    def test_hidden_set_patch_defers_refresh_until_show(self, qtbot):
        """Hidden widgets should defer visible refresh work until shown."""
        patch = _to_1d_time_patch()

        with widget_context(PlayAudio) as widget:
            calls: list[bool] = []
            original = widget._refresh_ui

            def _wrapped(*args, **kwargs):
                calls.append(True)
                return original(*args, **kwargs)

            widget._refresh_ui = _wrapped  # type: ignore[method-assign]
            widget.set_patch(patch)
            assert calls == []

            widget.show()
            qtbot.wait(10)

            assert calls == [True]

    def test_non_time_1d_patch_shows_validation_error(self, playaudio_widget):
        """Only 1D patches with dim `time` should be accepted."""
        patch = _to_non_time_patch()

        playaudio_widget.set_patch(patch)

        assert playaudio_widget._prepared_audio is None
        assert playaudio_widget.Error.invalid_patch.is_shown()
        assert "('time',)" in playaudio_widget.Error.invalid_patch.formatted

    def test_2d_patch_shows_validation_error(self, playaudio_widget):
        """2D patches should be rejected for playback."""
        patch = dc.get_example_patch("example_event_2")

        playaudio_widget.set_patch(patch)

        assert playaudio_widget._prepared_audio is None
        assert playaudio_widget.Error.invalid_patch.is_shown()
        assert "expected a 1D patch" in playaudio_widget.Error.invalid_patch.formatted

    def test_degenerate_2d_time_patch_is_accepted(self, playaudio_widget, monkeypatch):
        """Singleton extra dims should be squeezed away before validation."""
        received = _capture_patch_output(playaudio_widget, monkeypatch)
        patch = _to_degenerate_2d_time_patch()

        playaudio_widget.set_patch(patch)

        assert received == [patch]
        assert playaudio_widget._prepared_audio is not None
        assert not playaudio_widget.Error.invalid_patch.is_shown()
        x_data, y_data = playaudio_widget._waveform_curve.getData()
        assert len(x_data) == patch.squeeze().data.size
        assert len(y_data) == patch.squeeze().data.size

    def test_non_uniform_time_spacing_shows_validation_error(self, playaudio_widget):
        """Playback requires uniformly spaced time samples."""
        patch = _to_1d_time_patch()
        time = patch.get_array("time").copy()
        time[5] = time[4] + (time[1] - time[0]) * 1.5
        patch = patch.update_coords(time=time)

        playaudio_widget.set_patch(patch)

        assert playaudio_widget._prepared_audio is None
        assert (
            "uniform sample spacing" in playaudio_widget.Error.invalid_patch.formatted
        )

    def test_none_clears_state_and_emits_none(self, playaudio_widget, monkeypatch):
        """Sending None clears playback state and forwards None."""
        received = _capture_patch_output(playaudio_widget, monkeypatch)
        playaudio_widget.set_patch(_to_1d_time_patch())
        received.clear()

        playaudio_widget.set_patch(None)

        assert received == [None]
        assert playaudio_widget._prepared_audio is None
        assert playaudio_widget._status_label.text() == "No patch loaded"

    def test_audible_rate_keeps_default_time_scale_for_long_recording(self):
        """Audible-rate patches should keep a neutral scale when already long enough."""
        native_rate_hz = 1_000.0
        sample_count = 5_000

        assert PlayAudio._default_time_scale(
            native_rate_hz, sample_count
        ) == pytest.approx(1.0)

    def test_short_recording_defaults_to_at_least_two_seconds(self, playaudio_widget):
        """Short clips should slow down by default until playback lasts two seconds."""
        patch = _to_1d_time_patch()

        playaudio_widget.set_patch(patch)

        assert playaudio_widget._prepared_audio is not None
        playback_duration = (
            playaudio_widget._prepared_audio.sample_count
            / playaudio_widget._effective_sample_rate_hz()
        )
        assert playback_duration >= 1.98
        assert playaudio_widget.time_scale < 1.0

    def test_low_rate_chooses_target_audible_default(self):
        """Very slow recordings should scale up toward the target playback band."""
        coord = np.arange(10, dtype=np.float64)
        rate = PlayAudio._infer_native_rate_hz(coord)

        assert rate == pytest.approx(1.0)
        assert PlayAudio._default_time_scale(rate, coord.size) == pytest.approx(4000.0)

    def test_high_rate_chooses_target_audible_default(self):
        """Very fast recordings should scale down toward the target playback band."""
        coord = np.arange(10, dtype=np.float64) * 1e-6
        rate = PlayAudio._infer_native_rate_hz(coord)

        assert rate == pytest.approx(1_000_000.0)
        assert PlayAudio._default_time_scale(rate, coord.size) == pytest.approx(5e-6)

    def test_prepare_pcm_audio_zeroes_non_finite_and_normalizes(self):
        """PCM prep should zero invalid samples and normalize finite values."""
        pcm_bytes, sample_count = PlayAudio._prepare_pcm_audio(
            np.array([0.0, np.nan, np.inf, -2.0, 2.0], dtype=np.float64)
        )
        pcm = np.frombuffer(pcm_bytes, dtype="<i2")

        assert sample_count == 5
        assert pcm[1] == 0
        assert pcm[2] == 0
        assert np.max(np.abs(pcm)) == pytest.approx(
            int(0.95 * np.iinfo(np.int16).max), abs=1
        )

    def test_prepare_pcm_audio_uses_robust_gain_for_spiky_signal(self):
        """A few spikes should not keep the whole clip artificially quiet."""
        data = np.concatenate([np.ones(100, dtype=np.float64), np.array([100.0])])

        pcm_bytes, sample_count = PlayAudio._prepare_pcm_audio(data)
        pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float64)
        normalized = pcm / np.iinfo(np.int16).max

        assert sample_count == data.size
        assert np.max(np.abs(normalized)) == pytest.approx(0.95, abs=1e-4)
        assert np.median(np.abs(normalized[:-1])) > 0.9

    def test_prepare_pcm_audio_applies_default_makeup_gain_to_quieter_body(self):
        """Default playback should not add extra makeup gain above normalization."""
        data = np.concatenate(
            [
                np.full(90, 0.1, dtype=np.float64),
                np.full(10, 1.0, dtype=np.float64),
            ]
        )

        pcm_bytes, sample_count = PlayAudio._prepare_pcm_audio(data)
        pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float64)
        normalized = pcm / np.iinfo(np.int16).max

        assert sample_count == data.size
        assert np.max(np.abs(normalized)) == pytest.approx(0.95, abs=1e-4)
        assert np.median(np.abs(normalized[:90])) == pytest.approx(0.095, abs=0.01)

    def test_prepare_pcm_audio_can_apply_positive_makeup_gain(self):
        """Explicit positive output gain should lift quieter content."""
        data = np.concatenate(
            [
                np.full(90, 0.1, dtype=np.float64),
                np.full(10, 1.0, dtype=np.float64),
            ]
        )

        pcm_bytes, _ = PlayAudio._prepare_pcm_audio(data, output_gain_db=6.0)
        pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float64)
        normalized = pcm / np.iinfo(np.int16).max

        assert np.median(np.abs(normalized[:90])) > 0.17

    def test_prepare_pcm_audio_rejects_all_non_finite(self):
        """Patches without any finite samples should be rejected."""
        with pytest.raises(ValueError, match="finite sample"):
            PlayAudio._prepare_pcm_audio(np.array([np.nan, np.inf]))

    def test_user_time_scale_updates_effective_rate(self, playaudio_widget):
        """Changing the control should update the computed playback rate."""
        patch = _to_1d_time_patch()
        playaudio_widget.set_patch(patch)

        native_rate = playaudio_widget._native_rate_hz
        playaudio_widget._time_scale_spin.setValue(2.5)

        assert playaudio_widget.time_scale == pytest.approx(2.5)
        assert playaudio_widget._effective_sample_rate_hz() == pytest.approx(
            native_rate * 2.5
        )

    def test_user_volume_rebuilds_prepared_pcm(self, playaudio_widget):
        """Changing volume should rebuild the PCM payload louder."""
        patch = _to_1d_time_patch()
        playaudio_widget.set_patch(patch)
        initial_pcm = np.frombuffer(
            playaudio_widget._prepared_audio.pcm_bytes, dtype="<i2"
        ).astype(np.float64)
        initial_median = np.median(np.abs(initial_pcm))

        playaudio_widget.volume_percent = 200
        playaudio_widget._on_volume_changed()

        updated_pcm = np.frombuffer(
            playaudio_widget._prepared_audio.pcm_bytes, dtype="<i2"
        ).astype(np.float64)
        updated_median = np.median(np.abs(updated_pcm))
        assert playaudio_widget._current_output_gain_db() == pytest.approx(
            20.0 * np.log10(2.0)
        )
        assert updated_median >= initial_median

    def test_volume_slider_label_shows_percent_and_db(self, playaudio_widget):
        """The volume control should expose a user-friendly slider label."""
        playaudio_widget.volume_percent = 150
        playaudio_widget._update_volume_label()

        assert "150%" in playaudio_widget._volume_label.text()
        assert "dB" in playaudio_widget._volume_label.text()

    def test_start_playback_uses_scaled_sample_rate(
        self, playaudio_widget, monkeypatch
    ):
        """Playback should create an audio sink with the scaled sample rate."""
        patch = _to_1d_time_patch()
        captured: list[_FakeAudioSink] = []

        def _fake_create_sink(audio_format: QAudioFormat):
            sink = _FakeAudioSink(audio_format)
            captured.append(sink)
            return sink

        monkeypatch.setattr(playaudio_widget, "_create_audio_sink", _fake_create_sink)
        playaudio_widget.set_patch(patch)
        playaudio_widget._time_scale_spin.setValue(2.0)

        playaudio_widget._start_playback()

        assert len(captured) == 1
        assert captured[0].audio_format.sampleRate() == pytest.approx(20_000)
        assert captured[0].started_device is playaudio_widget._audio_buffer

    def test_slow_playback_uses_supported_output_rate_and_stretched_pcm(
        self, playaudio_widget, monkeypatch
    ):
        """Very slow playback should stretch PCM, not request tiny sink rates."""
        patch = _to_1d_time_patch()
        captured: list[_FakeAudioSink] = []

        def _fake_create_sink(audio_format: QAudioFormat):
            sink = _FakeAudioSink(audio_format)
            captured.append(sink)
            return sink

        monkeypatch.setattr(playaudio_widget, "_create_audio_sink", _fake_create_sink)
        playaudio_widget.set_patch(patch)
        playaudio_widget._time_scale_spin.setValue(0.1)

        playaudio_widget._start_playback()

        assert len(captured) == 1
        assert captured[0].audio_format.sampleRate() == 8_000
        assert playaudio_widget._audio_payload is not None
        sample_count = (
            playaudio_widget._audio_payload.size() // np.dtype("<i2").itemsize
        )
        duration_seconds = sample_count / captured[0].audio_format.sampleRate()
        assert duration_seconds == pytest.approx(1.001, abs=0.02)

    def test_playback_marker_advances_with_audio_progress(
        self, playaudio_widget, monkeypatch
    ):
        """The waveform marker should follow playback progress along the trace."""
        patch = _to_1d_time_patch()
        captured: list[_FakeAudioSink] = []

        def _fake_create_sink(audio_format: QAudioFormat):
            sink = _FakeAudioSink(audio_format)
            captured.append(sink)
            return sink

        monkeypatch.setattr(playaudio_widget, "_create_audio_sink", _fake_create_sink)
        playaudio_widget.set_patch(patch)
        playaudio_widget._start_playback()

        assert captured
        midpoint = patch.data.size // 2
        captured[0].processed_usecs = int(
            (midpoint / playaudio_widget._effective_sample_rate_hz()) * 1_000_000
        )

        playaudio_widget._update_playback_marker()

        marker_x, marker_y = playaudio_widget._waveform_marker.getData()
        time_seconds = PlayAudio._coord_to_seconds(np.asarray(patch.get_array("time")))
        time_seconds = np.asarray(time_seconds, dtype=np.float64) - float(
            time_seconds[0]
        )
        index = playaudio_widget._playback_sample_index
        assert index is not None
        assert abs(index - midpoint) <= 1
        assert marker_x == [pytest.approx(float(time_seconds[index]))]
        assert marker_y == [pytest.approx(float(np.asarray(patch.data)[index]))]


class TestPlayAudioDefaults(TestWidgetDefaults):
    """Default tests for PlayAudio."""

    __test__ = True
    widget = PlayAudio
    inputs = (("patch", _to_1d_time_patch()),)
