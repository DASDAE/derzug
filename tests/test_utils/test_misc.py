"""Tests for derzug.utils.misc."""

from __future__ import annotations

import derzug.constants as constants
from derzug.utils.misc import (
    load_example_workflow_entrypoints,
    load_widget_entrypoints,
)


class TestLoadWidgetEntrypoints:
    """Simple tests for loading derzug entry points."""

    def test_expected_eps_loaded(self):
        """Only DerZug widget entry points are loaded."""
        result = list(load_widget_entrypoints())
        dist_names = {ep.dist.name.lower() for ep in result}
        groups = {ep.group for ep in result}

        # At least one derzug widget should be registered.
        assert constants.PKG_NAME in dist_names
        assert dist_names == {constants.PKG_NAME}
        assert groups == {constants.WIDGETS_ENTRY}


class TestLoadExampleWorkflowEntrypoints:
    """Simple tests for loading DerZug example workflows."""

    def test_expected_example_workflows_loaded(self):
        """Only DerZug example workflow entry points are loaded."""
        result = list(load_example_workflow_entrypoints())
        loaded = [(ep.name, ep.group, ep.dist.name.lower()) for ep in result]

        assert loaded, f"Loaded example workflow entry points: {loaded}"
        assert all(
            group == "orange.widgets.tutorials" for _, group, _ in loaded
        ), loaded
        assert all(dist == constants.PKG_NAME for _, _, dist in loaded), loaded
        assert "000-Orange3" not in {name for name, _, _ in loaded}
