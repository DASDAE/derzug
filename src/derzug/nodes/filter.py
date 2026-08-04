"""The Filter node: DASCore patch filter methods, without Qt.

Reference implementation of a hand-written node module. It owns everything the
Filter node *is* — its parameter models (a discriminated union keyed by
``kind``, so an agent gets an honest per-filter schema instead of one flat pile
of 25 settings), the portable :class:`FilterTask`, and the mapping between the
two — leaving ``derzug.widgets.filter`` to be nothing but controls.

The models are deliberately kept close to the task's stored values so the
bridge stays a trivial rename map. The one notable rename: the shared
``filter_window`` value becomes ``frequency`` for notch and ``window``
elsewhere, which is what it actually means per type.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, get_args

import dascore as dc
from pydantic import BaseModel, Field, TypeAdapter

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow import Task
from derzug.workflow.dims import resolve_patch_dim

_FILTER_NAMES: tuple[str, ...] = (
    "gaussian_filter",
    "hampel_filter",
    "median_filter",
    "notch_filter",
    "pass_filter",
    "savgol_filter",
    "slope_filter",
    "sobel_filter",
    "wiener_filter",
)

#: Boundary modes the general SciPy-backed filters accept. Savitzky-Golay
#: rejects ``reflect``, so it gets its own narrower set; typing the params
#: fields with these keeps a headless ``mode`` typo from surviving until SciPy.
FilterMode = Literal["reflect", "constant", "nearest", "wrap", "mirror", "interp"]
SavgolFilterMode = Literal["mirror", "constant", "nearest", "wrap", "interp"]
MODE_OPTIONS: tuple[str, ...] = get_args(FilterMode)
SAVGOL_MODE_OPTIONS: tuple[str, ...] = get_args(SavgolFilterMode)


# -- Parameter models ---------------------------------------------------------


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
    mode: FilterMode = "reflect"
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
    mode: SavgolFilterMode = "interp"  # savgol rejects reflect
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
    mode: FilterMode = "reflect"
    cval: float = 0.0
    truncate: float = 4.0


class SobelFilterParams(_SharedFilter):
    """Sobel edge filter."""

    kind: Literal["sobel_filter"] = "sobel_filter"
    mode: FilterMode = "reflect"
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

#: model field -> flat setting/task field, per filter type. The shared dim and
#: taper fields and the special Gaussian windows are handled separately.
_PARAM_FIELDS: dict[str, dict[str, str]] = {
    "pass_filter": {
        "low_bound": "low_bound",
        "high_bound": "high_bound",
        "corners": "corners",
        "zerophase": "zerophase",
    },
    "notch_filter": {"frequency": "filter_window", "q": "q"},
    "median_filter": {
        "window": "filter_window",
        "samples": "samples",
        "mode": "mode",
        "cval": "cval",
    },
    "hampel_filter": {
        "window": "filter_window",
        "threshold": "threshold",
        "samples": "samples",
        "approximate": "approximate",
    },
    "savgol_filter": {
        "window": "filter_window",
        "polyorder": "polyorder",
        "samples": "samples",
        "mode": "mode",
        "cval": "cval",
    },
    "wiener_filter": {
        "window": "filter_window",
        "noise": "noise",
        "samples": "samples",
    },
    "gaussian_filter": {
        "samples": "samples",
        "mode": "mode",
        "cval": "cval",
        "truncate": "truncate",
    },
    "sobel_filter": {"mode": "mode", "cval": "cval"},
    "slope_filter": {
        "slope_filt": "slope_filt",
        "slope_dim0": "slope_dim0",
        "slope_dim1": "slope_dim1",
        "directional": "slope_directional",
        "notch": "slope_notch",
        "invert": "slope_invert",
    },
}


# -- Gaussian rows ------------------------------------------------------------


def normalize_gaussian_windows(rows: object) -> list[dict[str, str]]:
    """Return serialized Gaussian dimension/window rows as clean mappings."""
    normalized: list[dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "dim": str(row.get("dim", "")).strip(),
                "window": str(row.get("window", "")).strip(),
            }
        )
    return normalized


def validated_gaussian_kwargs(
    rows: object, available_dims: tuple[str, ...]
) -> dict[str, object]:
    """Return DASCore kwargs for the active Gaussian rows.

    Shared by the task (which validates against the incoming patch's dims) and
    the widget (which pre-validates against the dims it is showing), so the
    canvas rejects exactly what a headless run would.
    """
    kwargs: dict[str, object] = {}
    seen_dims: set[str] = set()
    for row in normalize_gaussian_windows(rows):
        dim = row["dim"]
        window = row["window"]
        if not dim and not window:
            continue
        if not dim or not window:
            raise ValueError("each Gaussian row needs both a dimension and a window")
        if dim not in available_dims:
            raise ValueError(f"'{dim}' is not an available dimension")
        if dim in seen_dims:
            raise ValueError(f"duplicate Gaussian dimension '{dim}'")
        kwargs[dim] = parse_patch_text_value(window, required=True)
        seen_dims.add(dim)
    if not kwargs:
        raise ValueError("at least one Gaussian dimension/window is required")
    return kwargs


# -- Task ---------------------------------------------------------------------


class FilterTask(Task):
    """Portable filter task mirroring the widget's persisted settings."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    selected_filter: str = "pass_filter"
    selected_dim: str = ""
    low_bound: str = ""
    high_bound: str = ""
    corners: int = 4
    zerophase: bool = True
    filter_window: str = "0.01"
    apply_taper: bool = True
    taper_window: str = "0.01"
    samples: bool = False
    mode: str = "reflect"
    cval: float = 0.0
    truncate: float = 4.0
    gaussian_dim_windows: tuple[dict[str, str], ...] = ()
    threshold: float = 10.0
    approximate: bool = True
    q: float = 35.0
    polyorder: int = 3
    noise: str = ""
    slope_filt: str = ""
    slope_dim0: str = "distance"
    slope_dim1: str = "time"
    slope_directional: bool = False
    slope_notch: bool = False
    slope_invert: bool = False

    def run(self, patch):
        """Apply the selected persisted DASCore filter to one patch."""
        f = self.selected_filter
        if f not in _FILTER_NAMES:
            raise ValueError(f"Unknown filter: {f!r}")
        available_dims = tuple(patch.dims)
        dim = resolve_patch_dim(self.selected_dim, available_dims)
        if self.apply_taper and self.taper_window.strip() and dim is not None:
            patch = patch.taper(
                **{dim: parse_patch_text_value(self.taper_window, required=True)}
            )
        fn = getattr(patch, f)
        if f == "slope_filter":
            filt = [float(x) for x in self.slope_filt.split(",") if x.strip()]
            if not filt:
                return patch
            return fn(
                filt=filt,
                dims=(self.slope_dim0, self.slope_dim1),
                directional=bool(self.slope_directional),
                notch=bool(self.slope_notch) or None,
                invert=bool(self.slope_invert),
            )
        if dim is None:
            return patch
        if f == "pass_filter":
            low = parse_patch_text_value(
                self.low_bound,
                allow_none=True,
                allow_ellipsis=True,
            )
            high = parse_patch_text_value(
                self.high_bound,
                allow_none=True,
                allow_ellipsis=True,
            )
            if low is None and high is None:
                return patch
            return fn(
                corners=int(self.corners),
                zerophase=bool(self.zerophase),
                **{dim: (low, high)},
            )
        if f == "gaussian_filter":
            return fn(
                samples=bool(self.samples),
                mode=self.mode,
                cval=float(self.cval),
                truncate=float(self.truncate),
                **validated_gaussian_kwargs(self.gaussian_dim_windows, available_dims),
            )
        if f == "hampel_filter":
            return fn(
                threshold=float(self.threshold),
                samples=bool(self.samples),
                approximate=bool(self.approximate),
                **{dim: parse_patch_text_value(self.filter_window, required=True)},
            )
        if f == "median_filter":
            return fn(
                samples=bool(self.samples),
                mode=self.mode,
                cval=float(self.cval),
                **{dim: parse_patch_text_value(self.filter_window, required=True)},
            )
        if f == "notch_filter":
            return fn(
                q=float(self.q),
                **{dim: parse_patch_text_value(self.filter_window, required=True)},
            )
        if f == "savgol_filter":
            return fn(
                polyorder=int(self.polyorder),
                samples=bool(self.samples),
                mode=self.mode,
                cval=float(self.cval),
                **{dim: parse_patch_text_value(self.filter_window, required=True)},
            )
        if f == "sobel_filter":
            return fn(dim=dim, mode=self.mode, cval=float(self.cval))
        if f == "wiener_filter":
            return fn(
                noise=parse_patch_text_value(
                    self.noise,
                    allow_none=True,
                    allow_quantity=False,
                ),
                samples=bool(self.samples),
                **{dim: parse_patch_text_value(self.filter_window, required=True)},
            )
        raise ValueError(f"Unhandled filter: {f!r}")


# -- Params <-> task ----------------------------------------------------------


def filter_settings_from_params(params: object) -> dict[str, object]:
    """Return the flat field mapping backing one typed filter model.

    The keys are both :class:`FilterTask`'s field names and the widget's
    setting names — they are deliberately identical, so this one mapping serves
    the headless task factory and the widget's ``apply_params``.
    """
    if not isinstance(params, BaseModel):
        params = TypeAdapter(FilterParams).validate_python(params)
    kind = params.kind
    settings: dict[str, object] = {
        "selected_filter": kind,
        "selected_dim": params.dim,
        "apply_taper": params.apply_taper,
        "taper_window": params.taper_window,
    }
    for model_field, setting in _PARAM_FIELDS[kind].items():
        settings[setting] = getattr(params, model_field)
    if kind == "gaussian_filter":
        settings["gaussian_dim_windows"] = [
            window.model_dump() for window in params.windows
        ]
    return settings


def filter_task_from_params(params: object = None) -> FilterTask:
    """Return the filter task for one typed parameter model (or its dict form).

    ``None`` selects the node's default: an unconfigured pass filter.
    """
    if params is None:
        params = PassFilterParams()
    return FilterTask(**filter_settings_from_params(params))


NODE_SPEC = NodeSpec(
    name="Filter",
    widget_qualified_name="derzug.widgets.filter.Filter",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=FilterParams,
    task_factory=filter_task_from_params,
    category="Processing",
    description="Apply a DASCore filter function to a patch",
    keywords=("filter", "bandpass", "gaussian", "notch", "median", "sobel"),
    icon="icons/Filter.svg",
    priority=22,
)
