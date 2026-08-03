"""Helpers for DerZug's disabled-widget bypass behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .compiler import widget_signal_name_map

DISABLED_NODE_KEY = "__derzug_widget_disabled"


@dataclass(frozen=True)
class DisabledPortPair:
    """One compatible disabled-widget passthrough mapping."""

    display_name: str
    input_name: str
    output_name: str
    input_channel: object | None = None
    output_channel: object | None = None


def is_node_disabled(node_or_properties: object) -> bool:
    """Return True when one node or properties mapping is marked disabled."""
    properties = getattr(node_or_properties, "properties", node_or_properties)
    if not isinstance(properties, dict):
        return False
    return bool(properties.get(DISABLED_NODE_KEY, False))


def set_node_disabled(
    properties: dict[str, object] | None, disabled: bool
) -> dict[str, object]:
    """Return one updated properties mapping with disabled-node metadata set."""
    out = dict(properties or {})
    if disabled:
        out[DISABLED_NODE_KEY] = True
    else:
        out.pop(DISABLED_NODE_KEY, None)
    return out


def disabled_passthrough_pairs(
    node: object, widget: object
) -> tuple[DisabledPortPair, ...]:
    """Return compatible input/output passthrough mappings for one disabled node."""
    input_names = widget_signal_name_map(widget, "Inputs")
    output_names = widget_signal_name_map(widget, "Outputs")
    if not input_names or not output_names:
        return ()

    input_channels = _channels_by_display_name(node, "input_channels")
    output_channels = _channels_by_display_name(node, "output_channels")

    pairs: list[DisabledPortPair] = []
    for display_name, input_name in input_names.items():
        output_name = output_names.get(display_name)
        if output_name is None:
            continue
        input_channel = input_channels.get(display_name)
        output_channel = output_channels.get(display_name)
        if (
            input_channel is not None
            and output_channel is not None
            and not _compatible_channels(output_channel, input_channel)
        ):
            continue
        pairs.append(
            DisabledPortPair(
                display_name=display_name,
                input_name=input_name,
                output_name=output_name,
                input_channel=input_channel,
                output_channel=output_channel,
            )
        )
    return tuple(pairs)


def disabled_output_names(node: object, widget: object) -> tuple[str, ...]:
    """Return all output attr names exposed by one node/widget pair."""
    output_names = widget_signal_name_map(widget, "Outputs")
    if output_names:
        return tuple(output_names.values())
    channels = _channels_by_display_name(node, "output_channels")
    return tuple(str(name) for name in channels)


def _compatible_channels(output_channel: object, input_channel: object) -> bool:
    """Return True when one output channel may feed one input channel.

    Imported lazily: channel compatibility is only ever asked about live canvas
    nodes, and ``derzug.workflow`` must stay importable without Orange.
    """
    from orangecanvas.scheme.link import compatible_channels

    return bool(compatible_channels(output_channel, input_channel))


def _channels_by_display_name(node: object, method_name: str) -> dict[str, Any]:
    """Return node channels keyed by display name when available."""
    getter = getattr(node, method_name, None)
    if getter is None:
        return {}
    try:
        channels = getter()
    except Exception:
        return {}
    out: dict[str, Any] = {}
    for channel in channels:
        name = getattr(channel, "name", None)
        if isinstance(name, str):
            out[name] = channel
    return out
