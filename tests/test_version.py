"""Tests for derzug.version."""

from __future__ import annotations

import importlib
import sys
from importlib.metadata import PackageNotFoundError


def _reload_version_module():
    """Reload and return the version module."""
    sys.modules.pop("derzug.version", None)
    return importlib.import_module("derzug.version")


def test_version_uses_installed_metadata(monkeypatch):
    """Installed package metadata should override the fallback version."""
    monkeypatch.setattr("importlib.metadata.version", lambda name: "1.2.3.4")

    module = _reload_version_module()

    assert module.__version__ == "1.2.3.4"
    assert module.__last_version__ == "1.2.3"


def test_version_falls_back_when_metadata_missing(monkeypatch):
    """Missing package metadata should keep the fallback version string."""

    def _raise(_name):
        raise PackageNotFoundError

    monkeypatch.setattr("importlib.metadata.version", _raise)

    module = _reload_version_module()

    assert module.__version__ == "0.0.0"
    assert module.__last_version__ == "0.0.0"
