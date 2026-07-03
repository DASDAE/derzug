"""Pydantic parameter models for the Filter widget.

Pilot for a widget-wide params-model layer. A discriminated union names each
filter type's real parameters (so ``filter_window`` reads as the notch
``frequency`` it actually is), gives a JSON schema an agent can consume via
``TypeAdapter(FilterParams).json_schema()``, and round-trips through the
widget's existing ``Setting`` persistence — no OWS format change required.

Only ``pass_filter`` and ``notch_filter`` are modeled here; the remaining filter
types follow the same shape and are added during rollout.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class PassFilterParams(BaseModel):
    """Parameters for a pass filter (band/low/high pass)."""

    kind: Literal["pass_filter"] = "pass_filter"
    dim: str = ""
    low_bound: str = ""
    high_bound: str = ""
    corners: int = 4
    zerophase: bool = True


class NotchFilterParams(BaseModel):
    """Parameters for a notch (band-stop) filter."""

    kind: Literal["notch_filter"] = "notch_filter"
    dim: str = ""
    frequency: str = ""  # notch center frequency (stored as filter_window)
    q: float = 35.0


FilterParams = Annotated[
    PassFilterParams | NotchFilterParams,
    Field(discriminator="kind"),
]
