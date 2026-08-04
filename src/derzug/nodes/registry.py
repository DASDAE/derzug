"""Discovery and validation for Qt-free node specs.

Node modules advertise themselves through the ``derzug.nodes`` entry-point
group, mirroring the ``derzug.widgets`` group that Orange's canvas uses. Each
entry point names a module exposing a module-level ``NODE_SPEC`` (or
``NODE_SPECS`` for modules contributing several).
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from functools import cache

import derzug.constants as constants
from derzug.utils.misc import load_entrypoints

from .spec import NodeSpec


def load_node_entrypoints():
    """Return the ``derzug.nodes`` entry points, DerZug's own first."""
    return load_entrypoints(constants.NODES_ENTRY)


def _module_specs(module: object) -> Iterator[NodeSpec]:
    """Yield the node specs advertised by one loaded module."""
    specs = getattr(module, "NODE_SPECS", None)
    if specs is None:
        spec = getattr(module, "NODE_SPEC", None)
        specs = () if spec is None else (spec,)
    for spec in specs:
        if not isinstance(spec, NodeSpec):
            raise TypeError(
                f"{getattr(module, '__name__', module)!r} exposes a non-NodeSpec "
                f"node spec: {spec!r}"
            )
        yield spec


def _is_first_party(entry_point) -> bool:
    """Return True when one entry point ships with DerZug itself."""
    dist = getattr(entry_point, "dist", None)
    return dist is not None and dist.name.lower() == constants.PKG_NAME


def _load_entrypoint_specs(entry_point) -> tuple[NodeSpec, ...]:
    """Return the validated specs from one entry point.

    A broken third-party provider must not take the built-in nodes down with
    it — the registry backs the Conductor's schema lookups, so an unrelated
    plugin failing to import would otherwise blind the whole app. DerZug's own
    entry points stay fatal, because there a failure is a real bug.
    """
    try:
        specs = tuple(_module_specs(entry_point.load()))
        for spec in specs:
            validate_spec(spec)
    except Exception as exc:
        if _is_first_party(entry_point):
            raise
        warnings.warn(
            f"ignoring node entry point {entry_point.name!r} from "
            f"{getattr(entry_point.dist, 'name', 'unknown')}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return ()
    return specs


@cache
def load_node_specs() -> tuple[NodeSpec, ...]:
    """Return every discoverable node spec, validated and uniquely named."""
    specs: list[NodeSpec] = []
    seen_names: dict[str, NodeSpec] = {}
    seen_qnames: dict[str, NodeSpec] = {}
    for entry_point in load_node_entrypoints():
        for spec in _load_entrypoint_specs(entry_point):
            if spec.name in seen_names:
                raise ValueError(f"duplicate node spec name {spec.name!r}")
            if spec.widget_qualified_name in seen_qnames:
                raise ValueError(
                    f"duplicate node spec widget {spec.widget_qualified_name!r}"
                )
            seen_names[spec.name] = spec
            seen_qnames[spec.widget_qualified_name] = spec
            specs.append(spec)
    return tuple(specs)


@cache
def _specs_by_widget_qname() -> dict[str, NodeSpec]:
    """Return every spec keyed by its widget qualified name.

    Indexed rather than scanned because the Conductor asks this question once
    per widget type every time it lists them.
    """
    return {spec.widget_qualified_name: spec for spec in load_node_specs()}


@cache
def _specs_by_name() -> dict[str, NodeSpec]:
    """Return every spec keyed by node name."""
    return {spec.name: spec for spec in load_node_specs()}


def spec_by_name(name: str) -> NodeSpec:
    """Return the node spec named ``name``, or raise ``KeyError``."""
    try:
        return _specs_by_name()[name]
    except KeyError:
        raise KeyError(f"no node spec named {name!r}") from None


def spec_for_widget_qname(qualified_name: str) -> NodeSpec | None:
    """Return the node spec for one widget qualified name, when discoverable."""
    return _specs_by_widget_qname().get(qualified_name)


def validate_spec(spec: NodeSpec) -> None:
    """Raise ``ValueError`` when one spec is internally inconsistent."""
    if not spec.name.strip():
        raise ValueError("node spec name must not be empty")
    if "." not in spec.widget_qualified_name:
        raise ValueError(
            f"node {spec.name!r} widget_qualified_name must be a dotted path, "
            f"got {spec.widget_qualified_name!r}"
        )
    for kind, ports in (("input", spec.inputs), ("output", spec.outputs)):
        names = [port.name for port in ports]
        if len(set(names)) != len(names):
            raise ValueError(f"node {spec.name!r} has duplicate {kind} port names")
        display = [port.display_name for port in ports]
        if len(set(display)) != len(display):
            raise ValueError(
                f"node {spec.name!r} has duplicate {kind} port display names"
            )
        for port in ports:
            if not port.name.strip() or not port.display_name.strip():
                raise ValueError(f"node {spec.name!r} has an unnamed {kind} port")
    if spec.task_factory is not None and not callable(spec.task_factory):
        raise ValueError(f"node {spec.name!r} task_factory is not callable")


def clear_caches() -> None:
    """Drop every discovery cache.

    Discovery is cached because entry points do not change within a process;
    tests that install a fake provider need all three caches dropped together,
    or an index survives its source.
    """
    load_node_specs.cache_clear()
    _specs_by_name.cache_clear()
    _specs_by_widget_qname.cache_clear()


__all__ = (
    "clear_caches",
    "load_node_entrypoints",
    "load_node_specs",
    "spec_by_name",
    "spec_for_widget_qname",
    "validate_spec",
)
