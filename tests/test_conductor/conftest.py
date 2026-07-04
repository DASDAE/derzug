"""Shared fixtures for Conductor tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def blank_canvas(derzug_app):
    """Return ``(window, scheme)`` for an emptied canvas."""
    window = derzug_app.window
    scheme = window.current_document().scheme()
    for node in list(scheme.nodes):
        scheme.remove_node(node)
    return window, scheme
