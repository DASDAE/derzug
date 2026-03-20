"""Qt-specific utility helpers shared across widgets."""

from __future__ import annotations

from pathlib import Path

from AnyQt.QtWidgets import QDialog, QFileDialog


class FileOrDirDialog(QFileDialog):
    """
    QFileDialog that accepts directory selections on the Open button.

    In standard file dialogs, pressing Open on a selected directory often
    navigates into it. This dialog accepts the selected directory path instead.
    Double-click on a directory still performs normal navigation.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._accepted_path: str = ""

    def accept(self) -> None:
        """Accept selected directory path directly; otherwise defer to base logic."""
        selected = self.selectedFiles()
        path = selected[0] if selected else ""
        if path and Path(path).is_dir():
            self._accepted_path = path
            self.done(QDialog.DialogCode.Accepted)
            return
        super().accept()

    def chosen_path(self) -> str:
        """Return the path accepted by the dialog."""
        if self._accepted_path:
            return self._accepted_path
        selected = self.selectedFiles()
        return selected[0] if selected else ""
