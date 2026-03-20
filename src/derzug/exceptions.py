"""
Exceptions and warnings specific to DerZug.
"""

from __future__ import annotations


class DerZugError(Exception):
    """
    Raised by a DerZugModel to signal a named error condition.

    The ``key`` must match a key in the model's ``errors`` dict so the widget
    can route it to the right Orange ``Msg`` slot.

    Parameters
    ----------
    key : str
        Name of the error, matching a key in the model's ``errors`` dict.
    fmt_args
        Positional arguments forwarded to the message format string.

    Examples
    --------
    >>> raise DerZugError("load_failed", "my_file.hdf5", "not found")
    """

    def __init__(self, key: str, *fmt_args):
        self.key = key
        self.fmt_args = fmt_args
        super().__init__(key, *fmt_args)


class DerZugWarning(UserWarning):
    """
    Issued by a DerZugModel to signal a named warning condition.

    The ``key`` must match a key in the model's ``warnings`` dict so the
    widget can route it to the right Orange ``Msg`` slot.

    Parameters
    ----------
    key : str
        Name of the warning, matching a key in the model's ``warnings`` dict.
    fmt_args
        Positional arguments forwarded to the message format string.

    Examples
    --------
    >>> warnings.warn(DerZugWarning("no_examples"))
    """

    def __init__(self, key: str, *fmt_args):
        self.key = key
        self.fmt_args = fmt_args
        super().__init__(key, *fmt_args)
