"""Tests for DerZug's Setting wrapper semantics."""

from __future__ import annotations

from derzug.orange import Setting


def test_setting_defaults_to_workflow_only_persistence():
    """DerZug settings should persist in workflows, not as global defaults."""
    setting = Setting("value")

    assert setting.schema_only is True


def test_setting_can_opt_into_global_default_persistence():
    """Explicit schema_only=False should still be available when needed."""
    setting = Setting("value", schema_only=False)

    assert setting.schema_only is False
