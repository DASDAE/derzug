"""DerZug-specific Orange widget utilities."""

from __future__ import annotations

from Orange.widgets.settings import Setting as _OrangeSetting


class Setting(_OrangeSetting):
    """
    Orange Setting subclass that persists into workflows by default.

    ``schema_only=True`` is the default so values are saved in workflow files
    but do not become remembered widget defaults across sessions. Pass
    ``schema_only=False`` only for settings that should also update the
    widget's global remembered defaults.

    Parameters
    ----------
    default
        The default value for this setting.
    schema_only
        When True (the default), the setting is stored only in workflows.
        When False, it is also persisted as a remembered widget default.
    **kwargs
        Forwarded to ``Orange.widgets.settings.Setting``.

    Examples
    --------
    >>> class MyWidget(ZugWidget):
    ...     colormap = Setting("CET-D1")  # persists in workflows only
    """

    def __init__(self, default, *, schema_only: bool = True, **kwargs) -> None:
        super().__init__(default, schema_only=schema_only, **kwargs)
