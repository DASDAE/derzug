"""Shared helpers for widgets operating on one patch and one selected dimension."""

from __future__ import annotations

import dascore as dc

from derzug.core.patchwidget import PatchWidget
from derzug.workflow.dims import default_patch_dim


class PatchDimWidget(PatchWidget, openclass=True):
    """Base for non-visual widgets that act on one patch along one dimension.

    ``PatchDimWidget`` owns the common dynamic-control rebinding for the dim
    combo so descendants only need to restore any additional controls they add.
    """

    def __init__(self) -> None:
        super().__init__()
        self._available_dims: tuple[str, ...] = ()

    def _set_patch_input(self, patch: dc.Patch | None) -> None:
        """Store the current patch and refresh the dimension chooser."""
        self._patch = patch
        self._rebind_dynamic_controls()

    def _rebind_dynamic_controls(self) -> None:
        """Rebuild patch-dependent controls after a new patch arrives."""
        self._refresh_dims()

    def _refresh_dims(self) -> None:
        """Sync dimension choices from the current patch."""
        patch_dims = tuple(self._patch.dims) if self._patch is not None else ()
        # The combo displays dims sorted for scanning; the default is chosen
        # from patch order so canvas and headless (resolve_patch_dim) agree.
        dims = tuple(sorted(patch_dims, key=str.casefold))
        self._available_dims = dims

        self._dim_combo.blockSignals(True)
        self._dim_combo.clear()
        self._dim_combo.addItems(dims)
        if dims:
            if self.selected_dim not in dims:
                self.selected_dim = self._default_dim(patch_dims)
            self._set_combo_value(self._dim_combo, self.selected_dim)
        else:
            self._dim_combo.setCurrentIndex(-1)
        self._dim_combo.setEnabled(bool(dims))
        self._dim_combo.blockSignals(False)

    def _default_dim(self, dims: tuple[str, ...]) -> str:
        """Choose a default dimension, preferring time when available."""
        return default_patch_dim(dims)

    def _dims_in_patch_order(self) -> tuple[str, ...]:
        """Return the available dims in patch order, matching headless resolution."""
        patch_dims = tuple(self._patch.dims) if self._patch is not None else ()
        ordered = tuple(dim for dim in patch_dims if dim in self._available_dims)
        return ordered or self._available_dims

    def _get_dim(self) -> str | None:
        """Return the currently selected dimension when available."""
        if not self._available_dims:
            return None
        dim = (
            self.selected_dim
            if self.selected_dim in self._available_dims
            else self._default_dim(self._dims_in_patch_order())
        )
        if dim != self.selected_dim:
            self.selected_dim = dim
            self._dim_combo.blockSignals(True)
            self._dim_combo.setCurrentText(dim)
            self._dim_combo.blockSignals(False)
        return dim
