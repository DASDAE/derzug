"""Tests for the Qt-free PlayAudio node DSP."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.nodes.playaudio import (
    PlayAudioParams,
    playback_output_rate_hz,
    render_audition,
)


def _one_d_time_patch() -> dc.Patch:
    """Return a 1D time patch suitable for audition."""
    return dc.get_example_patch("example_event_2").mean("distance").squeeze()


class TestRenderAudition:
    """The params-driven audition renderer works without any widget."""

    def test_default_params_produce_pcm(self):
        """A playable patch renders non-empty PCM at a supported rate."""
        patch = _one_d_time_patch()

        prepared, output_rate, pcm = render_audition(patch)

        assert prepared.sample_count == np.asarray(patch.data).size
        assert output_rate == playback_output_rate_hz(prepared.native_rate_hz * 1.0)
        assert len(pcm) > 0
        assert len(pcm) % 2 == 0  # 16-bit mono PCM

    def test_time_scale_changes_output_rate(self):
        """The params' time scale drives the playback rate."""
        patch = _one_d_time_patch()

        _, slow_rate, _ = render_audition(patch, PlayAudioParams(time_scale=1.0))
        prepared, fast_rate, _ = render_audition(
            patch, PlayAudioParams(time_scale=100.0)
        )

        assert fast_rate == playback_output_rate_hz(prepared.native_rate_hz * 100.0)
        assert fast_rate >= slow_rate

    def test_volume_scales_amplitude(self):
        """A lower volume percent renders quieter PCM."""
        patch = _one_d_time_patch()

        _, _, loud = render_audition(patch, PlayAudioParams(volume_percent=100))
        _, _, quiet = render_audition(patch, PlayAudioParams(volume_percent=10))

        loud_peak = np.abs(np.frombuffer(loud, dtype="<i2")).max()
        quiet_peak = np.abs(np.frombuffer(quiet, dtype="<i2")).max()
        assert quiet_peak < loud_peak

    def test_unplayable_patch_raises(self):
        """A 2D patch is rejected with the shared validation message."""
        with pytest.raises(ValueError, match="expected a 1D patch"):
            render_audition(dc.get_example_patch("example_event_2"))
