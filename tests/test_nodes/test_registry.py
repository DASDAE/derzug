"""Tests for node spec discovery, validation, and widget consistency."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import dascore as dc
import pytest
from derzug.nodes import NodeSpec, PortSpec, load_node_specs, validate_spec
from derzug.nodes.registry import spec_by_name, spec_for_widget_qname
from pydantic import TypeAdapter


@pytest.fixture(scope="module")
def specs() -> tuple[NodeSpec, ...]:
    """Return every discoverable node spec."""
    return load_node_specs()


class TestDiscovery:
    """The ``derzug.nodes`` entry-point group resolves to valid specs."""

    def test_specs_are_discovered(self, specs):
        """At least the pilot nodes are registered."""
        names = {spec.name for spec in specs}
        assert {"Filter", "Taper"} <= names

    def test_names_and_widgets_are_unique(self, specs):
        """No two specs share a name or a widget qualified name."""
        names = [spec.name for spec in specs]
        qnames = [spec.widget_qualified_name for spec in specs]
        assert len(set(names)) == len(names)
        assert len(set(qnames)) == len(qnames)

    def test_spec_by_name_round_trips(self, specs):
        """Every spec is retrievable by its name."""
        for spec in specs:
            assert spec_by_name(spec.name) is spec

    def test_spec_by_name_raises_for_unknown(self):
        """An unknown node name raises ``KeyError``."""
        with pytest.raises(KeyError, match="no node spec named"):
            spec_by_name("NotANode")

    def test_spec_for_widget_qname(self, specs):
        """Every spec is retrievable by its widget qualified name."""
        for spec in specs:
            assert spec_for_widget_qname(spec.widget_qualified_name) is spec
        assert spec_for_widget_qname("derzug.widgets.nope.Nope") is None


class TestSpecContents:
    """Each discovered spec is internally consistent."""

    def test_validate_spec_passes(self, specs):
        """Every registered spec validates."""
        for spec in specs:
            validate_spec(spec)

    def test_schemas_are_json_serializable(self, specs):
        """Params and view schemas survive a JSON round trip."""
        for spec in specs:
            for schema in (spec.params_schema(), spec.view_schema()):
                if schema is not None:
                    assert json.loads(json.dumps(schema)) == schema

    def test_default_task_ports_cover_workflow_ports(self, specs):
        """Non-context spec ports exist on the task the factory builds."""
        for spec in specs:
            if spec.task_factory is None:
                continue
            task = spec.build_task()
            task_inputs = set(task.resolved_scalar_input_variables())
            task_outputs = set(task.resolved_scalar_output_variables())
            assert {port.name for port in spec.workflow_inputs()} <= task_inputs
            assert {port.name for port in spec.workflow_outputs()} <= task_outputs

    def test_widget_qualified_name_resolves_back_to_the_spec(self, specs):
        """Each spec names a real widget class that points back at it."""
        for spec in specs:
            module = importlib.import_module(spec.module_name)
            widget = getattr(module, spec.widget_qualified_name.rpartition(".")[2])
            assert widget.node_spec is spec

    def test_default_task_runs_on_an_example_patch(self, specs):
        """Every default task runs, without the caller naming a dimension.

        ``example_event_2`` has dims ``(distance, time)``, so a node that
        silently fell back to the first dimension instead of the widget's
        ``time`` preference would diverge here.
        """
        patch = dc.get_example_patch("example_event_2")
        assert patch.dims[0] != "time", "example patch no longer exercises the fallback"
        for spec in specs:
            if spec.task_factory is None:
                continue
            result = spec.build_task().run(patch)
            assert isinstance(result, dc.Patch), (spec.name, type(result))


class TestValidateSpec:
    """``validate_spec`` rejects malformed specs."""

    def _spec(self, **kwargs) -> NodeSpec:
        """Return a minimal valid spec with ``kwargs`` overridden."""
        base = {
            "name": "Example",
            "widget_qualified_name": "derzug.widgets.example.Example",
        }
        return NodeSpec(**(base | kwargs))

    def test_empty_name_rejected(self):
        """A blank node name is an error."""
        with pytest.raises(ValueError, match="name must not be empty"):
            validate_spec(self._spec(name="  "))

    def test_undotted_widget_name_rejected(self):
        """A widget qualified name must be a dotted path."""
        with pytest.raises(ValueError, match="dotted path"):
            validate_spec(self._spec(widget_qualified_name="Example"))

    def test_duplicate_port_names_rejected(self):
        """Two input ports may not share a name."""
        ports = (
            PortSpec(name="patch", display_name="Patch"),
            PortSpec(name="patch", display_name="Other"),
        )
        with pytest.raises(ValueError, match="duplicate input port names"):
            validate_spec(self._spec(inputs=ports))

    def test_duplicate_display_names_rejected(self):
        """Two output ports may not share a display name."""
        ports = (
            PortSpec(name="first", display_name="Patch"),
            PortSpec(name="second", display_name="Patch"),
        )
        with pytest.raises(ValueError, match="duplicate output port display names"):
            validate_spec(self._spec(outputs=ports))

    def test_unnamed_port_rejected(self):
        """A port needs both a name and a display name."""
        ports = (PortSpec(name="patch", display_name=" "),)
        with pytest.raises(ValueError, match="unnamed input port"):
            validate_spec(self._spec(inputs=ports))

    def test_non_callable_factory_rejected(self):
        """``task_factory`` must be callable when set."""
        with pytest.raises(ValueError, match="task_factory is not callable"):
            validate_spec(self._spec(task_factory="nope"))


class TestFilterKinds:
    """Every Filter kind builds and runs from its params alone."""

    KINDS = (
        {"kind": "pass_filter", "low_bound": "10", "high_bound": "100"},
        {"kind": "notch_filter", "frequency": "60"},
        {"kind": "median_filter", "window": "3", "samples": True},
        {"kind": "hampel_filter", "window": "5", "samples": True},
        {"kind": "savgol_filter", "window": "5", "samples": True, "polyorder": 2},
        {"kind": "wiener_filter", "window": "5", "samples": True},
        {
            "kind": "gaussian_filter",
            "windows": [{"dim": "time", "window": "3"}],
            "samples": True,
        },
        {"kind": "sobel_filter"},
        {"kind": "slope_filter", "slope_filt": "1000,2000,3000,4000"},
    )

    @pytest.mark.parametrize("payload", KINDS, ids=lambda item: item["kind"])
    def test_kind_runs_headless(self, payload):
        """Each filter kind produces a patch from a params dict."""
        spec = spec_by_name("Filter")
        params = TypeAdapter(spec.params_model).validate_python(
            {"dim": "time"} | payload
        )
        result = spec.build_task(params).run(dc.get_example_patch("example_event_2"))
        assert isinstance(result, dc.Patch), (payload["kind"], type(result))

    def test_every_kind_is_covered(self):
        """Keep pace with the filters the node actually supports."""
        from derzug.nodes.filter import _FILTER_NAMES

        assert {item["kind"] for item in self.KINDS} == set(_FILTER_NAMES)

    def test_task_carries_only_the_active_kind(self):
        """A task holds no state its own filter kind will never read.

        `FilterTask` has a field for every kind at once, but the params model
        only describes the active one, so building through the spec narrows the
        task to what it actually uses — a smaller fingerprint, and no spurious
        re-run when an inactive kind's field changes.
        """
        spec = spec_by_name("Filter")
        params = TypeAdapter(spec.params_model).validate_python(
            {"kind": "pass_filter", "dim": "time", "low_bound": "10"}
        )
        task = spec.build_task(params)
        assert task.gaussian_dim_windows == ()
        assert task.slope_filt == ""

    def test_gaussian_windows_survive_the_params_round_trip(self):
        """Gaussian rows reach the task as dim/window mappings."""
        spec = spec_by_name("Filter")
        params = TypeAdapter(spec.params_model).validate_python(
            {
                "kind": "gaussian_filter",
                "dim": "time",
                "windows": [{"dim": "time", "window": "3"}],
            }
        )
        task = spec.build_task(params)
        assert task.gaussian_dim_windows == ({"dim": "time", "window": "3"},)


class TestExternalProviderIsolation:
    """A broken third-party provider must not take the built-in nodes down."""

    def test_broken_external_entry_point_is_skipped(self, monkeypatch):
        """A failing external entry point warns and is dropped."""
        from derzug.nodes import registry

        class _BrokenEntryPoint:
            name = "Broken"
            dist = SimpleNamespace(name="some-plugin")

            def load(self):
                raise ImportError("boom")

        real = registry.load_node_entrypoints
        monkeypatch.setattr(
            registry,
            "load_node_entrypoints",
            lambda: (*real(), _BrokenEntryPoint()),
        )
        registry.clear_caches()
        try:
            with pytest.warns(RuntimeWarning, match="ignoring node entry point"):
                names = {spec.name for spec in registry.load_node_specs()}
            assert {"Filter", "Taper"} <= names
        finally:
            registry.clear_caches()

    def test_broken_first_party_entry_point_raises(self, monkeypatch):
        """DerZug's own entry points stay fatal — there a failure is a bug."""
        from derzug.nodes import registry

        class _BrokenEntryPoint:
            name = "Broken"
            dist = SimpleNamespace(name="derzug")

            def load(self):
                raise ImportError("boom")

        monkeypatch.setattr(
            registry, "load_node_entrypoints", lambda: (_BrokenEntryPoint(),)
        )
        registry.clear_caches()
        try:
            with pytest.raises(ImportError, match="boom"):
                registry.load_node_specs()
        finally:
            registry.clear_caches()


class TestBuildTask:
    """``NodeSpec.build_task`` is the single entry point to a node's task."""

    def test_view_only_spec_refuses_to_build(self):
        """A spec with no factory raises rather than returning ``None``."""
        spec = NodeSpec(
            name="Viewer", widget_qualified_name="derzug.widgets.viewer.Viewer"
        )
        with pytest.raises(TypeError, match="does not build a workflow task"):
            spec.build_task()

    def test_params_reach_the_task(self):
        """Passing params changes the resulting task."""
        spec = spec_by_name("Taper")
        default = spec.build_task()
        custom = spec.build_task(spec.params_model(dim="time", p=0.2))
        assert default.dim == ""
        assert custom.dim == "time"
        assert custom.dim_value == pytest.approx(0.2)
