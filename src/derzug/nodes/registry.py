"""Discovery and validation for Qt-free node specs.

Node modules advertise themselves through the ``derzug.nodes`` entry-point
group, mirroring the ``derzug.widgets`` group that Orange's canvas uses. Each
entry point names a module exposing a module-level ``NODE_SPEC`` (or
``NODE_SPECS`` for modules contributing several).
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import cache
from importlib.metadata import entry_points

import derzug.constants as constants

from .spec import NodeSpec


@cache
def load_node_entrypoints():
    """Return the ``derzug.nodes`` entry points, DerZug's own first.

    The entry point group is the whole contract. Do not also filter by
    distribution name, or external providers such as SlanRod's ``derzug.nodes``
    entry point disappear from discovery.
    """
    return tuple(
        sorted(
            entry_points(group=constants.NODES_ENTRY),
            key=lambda ep: (0 if ep.dist.name.lower() == constants.PKG_NAME else 1),
        )
    )


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


@cache
def load_node_specs() -> tuple[NodeSpec, ...]:
    """Return every discoverable node spec, validated and uniquely named."""
    specs: list[NodeSpec] = []
    for entry_point in load_node_entrypoints():
        specs.extend(_module_specs(entry_point.load()))
    seen_names: dict[str, NodeSpec] = {}
    seen_qnames: dict[str, NodeSpec] = {}
    for spec in specs:
        validate_spec(spec)
        if spec.name in seen_names:
            raise ValueError(f"duplicate node spec name {spec.name!r}")
        if spec.widget_qualified_name in seen_qnames:
            raise ValueError(
                f"duplicate node spec widget {spec.widget_qualified_name!r}"
            )
        seen_names[spec.name] = spec
        seen_qnames[spec.widget_qualified_name] = spec
    return tuple(specs)


def spec_by_name(name: str) -> NodeSpec:
    """Return the node spec named ``name``, or raise ``KeyError``."""
    for spec in load_node_specs():
        if spec.name == name:
            return spec
    raise KeyError(f"no node spec named {name!r}")


def spec_for_widget_qname(qualified_name: str) -> NodeSpec | None:
    """Return the node spec for one widget qualified name, when discoverable."""
    for spec in load_node_specs():
        if spec.widget_qualified_name == qualified_name:
            return spec
    return None


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


__all__ = (
    "load_node_entrypoints",
    "load_node_specs",
    "spec_by_name",
    "spec_for_widget_qname",
    "validate_spec",
)
