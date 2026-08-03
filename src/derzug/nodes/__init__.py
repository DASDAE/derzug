"""Qt-free node library: what each DerZug node is, and how it runs.

``derzug.workflow`` is the execution engine; ``derzug.nodes`` is the node
library built on top of it. A node module owns its ``Task`` classes, its
pydantic parameter models, and a module-level ``NODE_SPEC`` describing the
node's identity. Nothing here imports Qt, Orange, or ``derzug.widgets``, so a
headless host can introspect a node type and run its task without a display.

This module stays import-light on purpose: it re-exports the spec and registry
API but never the individual node modules, which the registry loads lazily
through the ``derzug.nodes`` entry-point group.
"""

from __future__ import annotations

from .registry import (
    load_node_specs,
    spec_by_name,
    spec_for_widget_qname,
    validate_spec,
)
from .spec import NodeSpec, PortSpec

__all__ = (
    "NodeSpec",
    "PortSpec",
    "load_node_specs",
    "spec_by_name",
    "spec_for_widget_qname",
    "validate_spec",
)
