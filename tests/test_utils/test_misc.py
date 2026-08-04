"""Tests for derzug.utils.misc."""

from __future__ import annotations

from types import SimpleNamespace

import derzug.constants as constants
import numpy as np
from derzug.utils.misc import (
    load_entrypoints,
    load_example_workflow_entrypoints,
    load_widget_entrypoints,
    ordered_pair,
)


class TestLoadWidgetEntrypoints:
    """Simple tests for loading derzug entry points."""

    def test_expected_eps_loaded(self):
        """DerZug widget entry points are loaded from the widget group."""
        result = list(load_widget_entrypoints())
        dist_names = {ep.dist.name.lower() for ep in result}
        groups = {ep.group for ep in result}

        # At least one derzug widget should be registered.
        assert constants.PKG_NAME in dist_names
        assert groups == {constants.WIDGETS_ENTRY}

    def test_external_widget_providers_are_loaded(self, monkeypatch):
        """External providers registered in derzug.widgets are not filtered out."""
        load_entrypoints.cache_clear()

        local = SimpleNamespace(
            name="Spool",
            value="derzug.widgets.spool",
            group=constants.WIDGETS_ENTRY,
            dist=SimpleNamespace(name=constants.PKG_NAME),
        )
        external = SimpleNamespace(
            name="SlanRod",
            value="slanrod.zug.discovery:widget_discovery",
            group=constants.WIDGETS_ENTRY,
            dist=SimpleNamespace(name="slanrod"),
        )

        monkeypatch.setattr(
            "derzug.utils.misc.entry_points",
            lambda group: (local, external) if group == constants.WIDGETS_ENTRY else (),
        )
        try:
            result = list(load_widget_entrypoints())
        finally:
            load_entrypoints.cache_clear()
        values = {ep.value for ep in result}

        assert "slanrod.zug.discovery:widget_discovery" in values


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


class TestOrderedPair:
    """Tests for the shared low-to-high ordering kernel."""

    def test_orders_ascending(self):
        """A reversed pair is returned low-to-high."""
        assert ordered_pair(3, 1) == (1, 3)
        assert ordered_pair(1, 3) == (1, 3)

    def test_orders_comparable_non_numeric(self):
        """Comparable non-numeric values (e.g. datetimes) are ordered."""
        later = np.datetime64("2020-01-02")
        earlier = np.datetime64("2020-01-01")
        assert ordered_pair(later, earlier) == (earlier, later)

    def test_incomparable_values_returned_unchanged(self):
        """Values that cannot be compared are returned in their original order."""
        assert ordered_pair(1, "a") == (1, "a")
