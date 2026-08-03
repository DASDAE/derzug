"""Tests for node spec discovery, validation, and widget consistency."""

from __future__ import annotations

import json

import pytest
from derzug.nodes import NodeSpec, PortSpec, load_node_specs, validate_spec
from derzug.nodes.registry import spec_by_name, spec_for_widget_qname


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

    def test_module_name_is_the_widget_module(self, specs):
        """``module_name`` strips the class off the widget qualified name."""
        for spec in specs:
            assert spec.widget_qualified_name.startswith(f"{spec.module_name}.")


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
