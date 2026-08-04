"""The PlayAudio node: audition a 1D time patch, passing it through unchanged.

Playback is a display concern, so the compiled workflow just forwards the
patch — but everything between a patch and device-ready PCM (validation, rate
inference, normalization, time-scaling, resampling) is plain signal
processing and lives here. The widget only adds the Qt sink and controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import dascore as dc
import numpy as np
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.sampling import strided_step
from derzug.workflow.widget_tasks import PatchPassThroughTask

AUDIBLE_MIN_HZ = 20.0
AUDIBLE_MAX_HZ = 20_000.0
DEFAULT_TARGET_HZ = 4_000.0
MIN_PLAYBACK_DURATION_S = 2.0
MIN_OUTPUT_SAMPLE_RATE_HZ = 8_000.0
MAX_OUTPUT_SAMPLE_RATE_HZ = 48_000.0
MIN_TIME_SCALE = 1e-6
MAX_TIME_SCALE = 1e6
PCM_HEADROOM = 0.95
PCM_NORMALIZE_PERCENTILE = 95.0
DEFAULT_OUTPUT_GAIN_DB = 0.0
#: Auto-gain calibration reads at most this many strided samples.
PCM_CALIBRATION_SAMPLES = 1_000_000
#: Resampling and rate validation work in bounded blocks of this size.
RESAMPLE_BLOCK_SIZE = 500_000


class PlayAudioParams(BaseModel):
    """Parameters for the PlayAudio node."""

    time_scale: float = 1.0
    volume_percent: int = 100


@dataclass(frozen=True)
class PreparedAudio:
    """Prepared patch playback metadata and PCM payload."""

    native_rate_hz: float
    pcm_bytes: bytes
    sample_count: int


def coerce_playable_patch(patch: dc.Patch) -> dc.Patch:
    """Return the squeezed patch shape used for playback validation/rendering."""
    return patch.squeeze()


def validate_patch_shape(patch: dc.Patch) -> None:
    """Validate that the patch is a 1D time series."""
    data = np.asarray(patch.data)
    if data.ndim != 1:
        raise ValueError(f"expected a 1D patch, got shape {data.shape}")
    if tuple(patch.dims) != ("time",):
        raise ValueError(f"expected patch dims ('time',), got {patch.dims}")


def coord_to_seconds(coord: np.ndarray) -> np.ndarray:
    """Convert time coordinates to seconds for rate inference."""
    arr = np.asarray(coord)
    if np.issubdtype(arr.dtype, np.datetime64):
        ns = arr.astype("datetime64[ns]").astype(np.int64)
        return ns.astype(np.float64) / 1e9
    if np.issubdtype(arr.dtype, np.timedelta64):
        ns = arr.astype("timedelta64[ns]").astype(np.int64)
        return ns.astype(np.float64) / 1e9
    if np.issubdtype(arr.dtype, np.number):
        return arr.astype(np.float64, copy=False)
    raise ValueError("time coordinate must be numeric or datetime-like")


def infer_native_rate_hz(coord: np.ndarray) -> float:
    """Infer the source sample rate from the patch time coordinate."""
    seconds = coord_to_seconds(coord)
    if seconds.size < 2:
        raise ValueError("time coordinate must contain at least two samples")
    first = float(seconds[1] - seconds[0])
    if not isfinite(first):
        raise ValueError("time coordinate must contain finite sample spacing")
    if first <= 0:
        raise ValueError("time coordinate must be strictly increasing")
    tolerance = max(abs(first) * 1e-6, 1e-12)
    # Check bounded slices so validating a long recording does not allocate
    # a second full-length float64 difference array.
    for start in range(1, seconds.size, RESAMPLE_BLOCK_SIZE):
        stop = min(start + RESAMPLE_BLOCK_SIZE, seconds.size)
        diffs = seconds[start:stop] - seconds[start - 1 : stop - 1]
        if not np.all(np.isfinite(diffs)):
            raise ValueError("time coordinate must contain finite sample spacing")
        if np.any(diffs <= 0):
            raise ValueError("time coordinate must be strictly increasing")
        if not np.allclose(diffs, first, rtol=1e-6, atol=tolerance):
            raise ValueError("time coordinate must have uniform sample spacing")
    rate_hz = 1.0 / first
    if not isfinite(rate_hz) or rate_hz <= 0:
        raise ValueError("time coordinate must define a positive sample rate")
    return rate_hz


def prepare_pcm_audio(
    data: np.ndarray,
    *,
    output_gain_db: float = DEFAULT_OUTPUT_GAIN_DB,
) -> tuple[bytes, int]:
    """Normalize mono samples with robust auto-gain and convert to PCM."""
    samples = np.array(data, dtype=np.float32, copy=True).reshape(-1)
    if samples.size == 0:
        raise ValueError("patch data is empty")
    finite_mask = np.isfinite(samples)
    if not np.any(finite_mask):
        raise ValueError("patch data must contain at least one finite sample")
    step = strided_step(samples.size, PCM_CALIBRATION_SAMPLES)
    calibration = samples[::step]
    finite_calibration = calibration[np.isfinite(calibration)]
    if finite_calibration.size == 0:
        finite_calibration = samples[np.argmax(finite_mask) :][:1]
    nonzero = np.abs(finite_calibration)
    ref = float(np.percentile(nonzero, PCM_NORMALIZE_PERCENTILE))
    if ref <= 0:
        # The strided calibration subset can miss all signal energy
        # (e.g. sparse spikes between stride points); fall back to the
        # full-array peak so only truly silent data skips normalization.
        ref = float(np.max(np.abs(samples[finite_mask])))
    if ref > 0:
        samples *= PCM_HEADROOM / ref
    linear_gain = float(10 ** (float(output_gain_db) / 20.0))
    samples[~finite_mask] = 0.0
    samples *= linear_gain
    np.clip(samples, -PCM_HEADROOM, PCM_HEADROOM, out=samples)
    samples *= np.iinfo(np.int16).max
    np.rint(samples, out=samples)
    pcm = samples.astype("<i2")
    return pcm.tobytes(), int(samples.size)


def prepare_patch_audio(
    patch: dc.Patch,
    *,
    output_gain_db: float = DEFAULT_OUTPUT_GAIN_DB,
) -> PreparedAudio:
    """Validate the patch and prepare normalized PCM audio bytes."""
    validate_patch_shape(patch)
    native_rate_hz = infer_native_rate_hz(np.asarray(patch.get_array("time")))
    pcm_bytes, sample_count = prepare_pcm_audio(
        np.asarray(patch.data),
        output_gain_db=output_gain_db,
    )
    return PreparedAudio(
        native_rate_hz=native_rate_hz,
        pcm_bytes=pcm_bytes,
        sample_count=sample_count,
    )


def default_time_scale(native_rate_hz: float, sample_count: int) -> float:
    """Choose a default scale that moves the source into audible range."""
    if AUDIBLE_MIN_HZ <= native_rate_hz <= AUDIBLE_MAX_HZ:
        scale = 1.0
    elif native_rate_hz <= 0:
        scale = 1.0
    else:
        scale = float(DEFAULT_TARGET_HZ / native_rate_hz)
    if native_rate_hz > 0 and sample_count > 0:
        duration_seconds = float(sample_count) / float(native_rate_hz)
        min_duration_scale = duration_seconds / MIN_PLAYBACK_DURATION_S
        if duration_seconds < MIN_PLAYBACK_DURATION_S:
            scale = min(scale, min_duration_scale)
    return float(np.clip(scale, MIN_TIME_SCALE, MAX_TIME_SCALE))


def output_gain_db_from_volume_percent(volume_percent: int) -> float:
    """Map a volume percentage onto a linear-gain dB value."""
    if volume_percent <= 0:
        return -120.0
    return float(20.0 * np.log10(float(volume_percent) / 100.0))


def effective_sample_rate_hz(native_rate_hz: float, time_scale: float) -> float:
    """Return the playback rate after applying the configured time scale."""
    return float(native_rate_hz) * float(time_scale)


def playback_output_rate_hz(effective_rate_hz: float) -> int:
    """Clamp the audio-device output rate to a broadly supported range."""
    if not isfinite(effective_rate_hz) or effective_rate_hz <= 0:
        raise ValueError("effective sample rate must be positive")
    return round(
        float(
            np.clip(
                effective_rate_hz,
                MIN_OUTPUT_SAMPLE_RATE_HZ,
                MAX_OUTPUT_SAMPLE_RATE_HZ,
            )
        )
    )


def render_playback_pcm(
    prepared: PreparedAudio,
    *,
    effective_rate_hz: float,
    output_rate_hz: int,
) -> bytes:
    """Render PCM, stretching or resampling when the sink rate is clamped."""
    if prepared.sample_count <= 0:
        return b""
    if not isfinite(effective_rate_hz) or effective_rate_hz <= 0:
        raise ValueError("effective sample rate must be positive")
    if output_rate_hz <= 0:
        raise ValueError("output sample rate must be positive")
    if round(effective_rate_hz) == output_rate_hz:
        return prepared.pcm_bytes

    source = np.frombuffer(prepared.pcm_bytes, dtype="<i2")
    target_count = max(
        1,
        round(prepared.sample_count * float(output_rate_hz) / effective_rate_hz),
    )
    if target_count == prepared.sample_count:
        return prepared.pcm_bytes
    if prepared.sample_count == 1:
        pcm = np.full(target_count, source[0], dtype="<i2")
        return pcm.tobytes()
    pcm = np.empty(target_count, dtype="<i2")
    position_scale = (prepared.sample_count - 1) / max(target_count - 1, 1)
    for start in range(0, target_count, RESAMPLE_BLOCK_SIZE):
        stop = min(start + RESAMPLE_BLOCK_SIZE, target_count)
        positions = np.arange(start, stop, dtype=np.float64) * position_scale
        left = np.floor(positions).astype(np.int64)
        right = np.minimum(left + 1, prepared.sample_count - 1)
        fraction = positions - left
        left_values = source[left].astype(np.float32)
        right_values = source[right].astype(np.float32)
        values = left_values + ((right_values - left_values) * fraction)
        pcm[start:stop] = np.rint(values).astype("<i2")
    return pcm.tobytes()


def render_audition(
    patch: dc.Patch, params: PlayAudioParams | None = None
) -> tuple[PreparedAudio, int, bytes]:
    """Return ``(prepared, output_rate_hz, pcm)`` for one patch and parameters.

    The one-call headless form of what the widget does interactively: the
    params' volume sets the normalization gain and the time scale sets the
    playback rate, clamped to a device-supported output rate.
    """
    params = PlayAudioParams() if params is None else params
    playable = coerce_playable_patch(patch)
    prepared = prepare_patch_audio(
        playable,
        output_gain_db=output_gain_db_from_volume_percent(int(params.volume_percent)),
    )
    effective = effective_sample_rate_hz(
        prepared.native_rate_hz, float(params.time_scale)
    )
    output_rate = playback_output_rate_hz(effective)
    pcm = render_playback_pcm(
        prepared, effective_rate_hz=effective, output_rate_hz=output_rate
    )
    return prepared, output_rate, pcm


def playaudio_task_from_params(
    params: PlayAudioParams | None = None,
) -> PatchPassThroughTask:
    """Build the pass-through task the player contributes to a workflow."""
    return PatchPassThroughTask()


NODE_SPEC = NodeSpec(
    name="PlayAudio",
    widget_qualified_name="derzug.widgets.playaudio.PlayAudio",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=PlayAudioParams,
    task_factory=playaudio_task_from_params,
    category="Visualize",
    description="Play a 1D time patch as audio",
    keywords=("audio", "sound", "time", "patch"),
    icon="icons/PlayAudio.svg",
    priority=23,
)
