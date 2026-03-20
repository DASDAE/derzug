"""Shared helper for simple dynamic add/remove row widgets."""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

RowStateT = TypeVar("RowStateT")
RowWidgetT = TypeVar("RowWidgetT")


class DynamicRowManager(Generic[RowStateT, RowWidgetT]):
    """Manage a small list of dynamic UI rows backed by serialized state."""

    def __init__(
        self,
        *,
        blank_state_factory: Callable[[], RowStateT],
        create_row: Callable[
            [Callable[[], None], Callable[[RowWidgetT], None]], RowWidgetT
        ],
        apply_row_state: Callable[[RowWidgetT, RowStateT], None],
        serialize_row: Callable[[RowWidgetT], RowStateT],
        delete_row_widget: Callable[[RowWidgetT], None],
        set_row_remove_enabled: Callable[[RowWidgetT, bool], None],
        on_rows_changed: Callable[[], None] | None = None,
    ) -> None:
        self._blank_state_factory = blank_state_factory
        self._create_row = create_row
        self._apply_row_state = apply_row_state
        self._serialize_row = serialize_row
        self._delete_row_widget = delete_row_widget
        self._set_row_remove_enabled = set_row_remove_enabled
        self._on_rows_changed = on_rows_changed
        self.rows: list[RowWidgetT] = []

    def refresh(self, states: list[RowStateT]) -> None:
        """Refresh the visible rows from serialized states."""
        states = list(states) or [self._blank_state_factory()]
        while len(self.rows) < len(states):
            self.rows.append(self._create_row(self._emit_changed, self.remove_row))
        while len(self.rows) > len(states) and len(self.rows) > 1:
            stale = self.rows.pop()
            self._delete_row_widget(stale)
        for row, state in zip(self.rows, states):
            self._apply_row_state(row, state)
        self._sync_remove_enabled()

    def sync_from_ui(self) -> list[RowStateT]:
        """Serialize current UI row state."""
        states = [self._serialize_row(row) for row in self.rows]
        return states or [self._blank_state_factory()]

    def add_blank_row(self) -> None:
        """Append one blank row, preserving current UI state first."""
        states = self.sync_from_ui()
        states.append(self._blank_state_factory())
        self.refresh(states)
        self._emit_changed()

    def remove_row(self, row: RowWidgetT) -> None:
        """Remove one row while keeping one editable row available."""
        if len(self.rows) == 1:
            self._apply_row_state(row, self._blank_state_factory())
        else:
            self.rows.remove(row)
            self._delete_row_widget(row)
        self._sync_remove_enabled()
        self._emit_changed()

    def _sync_remove_enabled(self) -> None:
        """Enable remove controls only when more than one row exists."""
        enabled = len(self.rows) > 1
        for row in self.rows:
            self._set_row_remove_enabled(row, enabled)

    def _emit_changed(self) -> None:
        """Hook point passed to widgets; the manager itself is stateless."""
        if self._on_rows_changed is not None:
            self._on_rows_changed()
