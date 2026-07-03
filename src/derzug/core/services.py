"""Registry for the app-shell service that widgets call into.

Core widgets occasionally need app-window behaviors — promoting a widget as the
active source, or raising the canvas window. Rather than import the views layer
(which would invert the intended dependency direction), they call through this
registry. The views layer registers a concrete implementation when the main
window is created; when nothing is registered (e.g. interactive use without the
canvas app), the calls are silent no-ops.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AppShellService(Protocol):
    """Behaviors the widget layer delegates to the running canvas app."""

    def promote_source(self, widget: object) -> None:
        """Select ``widget`` as the active source when appropriate."""
        ...

    def raise_canvas(self) -> None:
        """Bring the canvas window to the front and activate it."""
        ...


_SERVICE: AppShellService | None = None


def register_app_shell_service(service: AppShellService | None) -> None:
    """Register (or clear, with ``None``) the active app-shell service."""
    global _SERVICE
    _SERVICE = service


def get_app_shell_service() -> AppShellService | None:
    """Return the registered app-shell service, or ``None`` when unset."""
    return _SERVICE
