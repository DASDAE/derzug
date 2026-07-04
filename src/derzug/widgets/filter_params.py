"""Pydantic parameter models for the Filter widget.

Reference implementation of the widget-wide params-model layer: a discriminated
union (keyed by ``kind``) that names each filter type's real parameters, so an
agent gets an honest per-filter schema via ``TypeAdapter(FilterParams)
.json_schema()`` instead of one flat pile of 25 settings.

The models are deliberately kept close to the widget's stored values so the
widget's ``get_params``/``apply_params`` bridge stays a trivial rename map. The
one notable rename: the shared ``filter_window`` setting becomes ``frequency``
for notch and ``window`` elsewhere, which is what it actually means per type.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class _SharedFilter(BaseModel):
    """Fields common to every filter type."""

    dim: str = ""
    apply_taper: bool = True
    taper_window: str = "0.01"


class PassFilterParams(_SharedFilter):
    """Band / low / high pass filter."""

    kind: Literal["pass_filter"] = "pass_filter"
    low_bound: str = ""
    high_bound: str = ""
    corners: int = 4
    zerophase: bool = True


class NotchFilterParams(_SharedFilter):
    """Notch (band-stop) filter."""

    kind: Literal["notch_filter"] = "notch_filter"
    frequency: str = "0.01"  # stored as filter_window
    q: float = 35.0


class MedianFilterParams(_SharedFilter):
    """Median filter."""

    kind: Literal["median_filter"] = "median_filter"
    window: str = "0.01"  # stored as filter_window
    samples: bool = False
    mode: str = "reflect"
    cval: float = 0.0


class HampelFilterParams(_SharedFilter):
    """Hampel outlier filter."""

    kind: Literal["hampel_filter"] = "hampel_filter"
    window: str = "0.01"  # stored as filter_window
    threshold: float = 10.0
    samples: bool = False
    approximate: bool = True


class SavgolFilterParams(_SharedFilter):
    """Savitzky-Golay filter."""

    kind: Literal["savgol_filter"] = "savgol_filter"
    window: str = "0.01"  # stored as filter_window
    polyorder: int = 3
    samples: bool = False
    mode: str = "interp"  # savgol modes differ from the other filters
    cval: float = 0.0


class WienerFilterParams(_SharedFilter):
    """Wiener filter."""

    kind: Literal["wiener_filter"] = "wiener_filter"
    window: str = "0.01"  # stored as filter_window
    noise: str = ""
    samples: bool = False


class GaussianWindow(BaseModel):
    """One dimension/window pair for the Gaussian filter."""

    dim: str = ""
    window: str = "0.01"


class GaussianFilterParams(_SharedFilter):
    """Gaussian filter (per-dimension windows)."""

    kind: Literal["gaussian_filter"] = "gaussian_filter"
    # one empty row by default, matching the widget's initial Gaussian table
    windows: list[GaussianWindow] = Field(
        default_factory=lambda: [GaussianWindow(window="")]
    )
    samples: bool = False
    mode: str = "reflect"
    cval: float = 0.0
    truncate: float = 4.0


class SobelFilterParams(_SharedFilter):
    """Sobel edge filter."""

    kind: Literal["sobel_filter"] = "sobel_filter"
    mode: str = "reflect"
    cval: float = 0.0


class SlopeFilterParams(_SharedFilter):
    """Slope (2D dip) filter."""

    kind: Literal["slope_filter"] = "slope_filter"
    slope_filt: str = ""
    slope_dim0: str = "distance"
    slope_dim1: str = "time"
    directional: bool = False
    notch: bool = False
    invert: bool = False


FilterParams = Annotated[
    PassFilterParams
    | NotchFilterParams
    | MedianFilterParams
    | HampelFilterParams
    | SavgolFilterParams
    | WienerFilterParams
    | GaussianFilterParams
    | SobelFilterParams
    | SlopeFilterParams,
    Field(discriminator="kind"),
]

#: Every filter-type model, used to seed defaults for all of Filter's
#: attributes (which span all types) under authoritative storage.
_FILTER_MODELS: tuple[type[BaseModel], ...] = (
    PassFilterParams,
    NotchFilterParams,
    MedianFilterParams,
    HampelFilterParams,
    SavgolFilterParams,
    WienerFilterParams,
    GaussianFilterParams,
    SobelFilterParams,
    SlopeFilterParams,
)
