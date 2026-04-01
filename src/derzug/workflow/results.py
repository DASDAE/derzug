"""
Result container for workflow execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .provenance import Provenance


@dataclass
class Results:
    """Container for workflow run outputs."""

    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    error_map: dict[str, Any] = field(default_factory=dict)
    skipped_map: dict[str, str] = field(default_factory=dict)
    provenance: Provenance | None = None
    node_names: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Return True when the run completed without recorded task errors."""
        return not self.error_map

    @property
    def errors(self) -> dict[str, Any]:
        """Return task errors keyed by stable node names when available."""
        reverse_names = {handle: name for name, handle in self.node_names.items()}
        return {
            reverse_names.get(handle, handle): exc
            for handle, exc in self.error_map.items()
        }

    @property
    def skipped(self) -> dict[str, str]:
        """Return skipped-node reasons keyed by stable node names."""
        reverse_names = {handle: name for name, handle in self.node_names.items()}
        return {
            reverse_names.get(handle, handle): reason
            for handle, reason in self.skipped_map.items()
        }

    def _resolve_handle(self, key: str) -> str:
        """Resolve a stable node name to its internal handle."""
        handle = self.node_names.get(key)
        if handle is not None:
            return handle
        prefix, _, _suffix = key.rpartition(".")
        if prefix:
            handle = self.node_names.get(prefix)
            if handle is not None:
                return handle
        return key

    def has_output(self, key: str, port: str | None = None) -> bool:
        """Return True when one output is available for the given node/port."""
        handle = self._resolve_handle(key)
        outputs = self.node_outputs.get(handle)
        if not outputs:
            return False
        if port is None:
            return len(outputs) == 1
        return port in outputs

    def get(self, key: str, port: str | None = None, default: Any = None) -> Any:
        """Return an output value or a default when it is unavailable."""
        try:
            if port is None:
                return self[key]
            return self[key, port]
        except (KeyError, ValueError):
            return default

    def __getitem__(self, key):
        """Return one node output, requiring a port for multi-output nodes."""
        if isinstance(key, tuple):
            node, port = key
            handle = self._resolve_handle(node)
            return self.node_outputs[handle][port]
        handle = self._resolve_handle(key)
        outputs = self.node_outputs[handle]
        if len(outputs) != 1:
            raise ValueError(f"node {key!r} exposes multiple outputs; specify a port")
        return next(iter(outputs.values()))
