"""Shared helpers for widgets operating on one patch and one selected dimension."""

from __future__ import annotations

import dascore as dc

from derzug.core.zugwidget import ZugWidget


class PatchDimWidget(ZugWidget, openclass=True):
    """Base for non-visual widgets that act on one patch along one dimension."""

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None
        self._available_dims: tuple[str, ...] = ()

    def _set_patch_input(self, patch: dc.Patch | None) -> None:
        """Store the current patch and refresh the dimension chooser."""
        self._patch = patch
        self._refresh_dims()

    def _refresh_dims(self) -> None:
        """Sync dimension choices from the current patch."""
        dims = (
            tuple(sorted(self._patch.dims, key=str.casefold))
            if self._patch is not None
            else ()
        )
        self._available_dims = dims

        self._dim_combo.blockSignals(True)
        self._dim_combo.clear()
        self._dim_combo.addItems(dims)
        if dims:
            if self.selected_dim not in dims:
                self.selected_dim = self._default_dim(dims)
            self._dim_combo.setCurrentText(self.selected_dim)
        self._dim_combo.setEnabled(bool(dims))
        self._dim_combo.blockSignals(False)

    def _default_dim(self, dims: tuple[str, ...]) -> str:
        """Choose a default dimension, preferring time when available."""
        return "time" if "time" in dims else dims[0]

    def _get_dim(self) -> str | None:
        """Return the currently selected dimension when available."""
        if not self._available_dims:
            return None
        dim = (
            self.selected_dim
            if self.selected_dim in self._available_dims
            else self._default_dim(self._available_dims)
        )
        if dim != self.selected_dim:
            self.selected_dim = dim
            self._dim_combo.blockSignals(True)
            self._dim_combo.setCurrentText(dim)
            self._dim_combo.blockSignals(False)
        return dim

    def _on_result(self, result: dc.Patch | None) -> None:
        """Send the output patch."""
        self.Outputs.patch.send(result)
