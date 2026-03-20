"""Runtime helpers and widget classes for grouped composite workflows."""

from __future__ import annotations

import io
import uuid
from copy import deepcopy
from typing import Any

from AnyQt.QtWidgets import QApplication, QLabel
from Orange.widgets.widget import OWWidget
from orangecanvas.registry import InputSignal, OutputSignal, WidgetDescription
from orangecanvas.scheme import readwrite

from derzug.orange import Setting

COMPOSITE_PAYLOAD_KEY = "composite_payload"
NODE_ID_KEY = "__derzug_node_id"
INTERNAL_NODE_ID_KEY = "__derzug_composite_internal_node_id"
COMPOSITE_QNAME_PREFIX = "derzug.widgets.composite.DynamicComposite_"
_COMPOSITE_ICON = "icons/FolderGroup.svg"


def is_composite_qualified_name(qualified_name: str) -> bool:
    """Return True when one qualified name belongs to a dynamic composite."""
    return str(qualified_name).startswith(COMPOSITE_QNAME_PREFIX)


def ensure_node_id(node) -> str:
    """Return a stable DerZug node id, creating it when missing."""
    properties = dict(node.properties or {})
    node_id = str(properties.get(NODE_ID_KEY, "")).strip()
    if node_id:
        return node_id
    node_id = uuid.uuid4().hex
    properties[NODE_ID_KEY] = node_id
    node.properties = properties
    return node_id


def get_node_id(node) -> str | None:
    """Return the persisted DerZug node id when available."""
    properties = node.properties or {}
    value = properties.get(NODE_ID_KEY)
    return str(value).strip() or None if value is not None else None


def get_internal_node_id(node) -> str | None:
    """Return the composite-internal node id when available."""
    properties = node.properties or {}
    value = properties.get(INTERNAL_NODE_ID_KEY)
    return str(value).strip() or None if value is not None else None


def composite_payload_from_properties(properties: object) -> dict[str, Any] | None:
    """Return the composite payload from a properties dict when present."""
    if not isinstance(properties, dict):
        return None
    payload = properties.get(COMPOSITE_PAYLOAD_KEY)
    return payload if isinstance(payload, dict) else None


def composite_properties(
    payload: dict[str, Any], *, node_id: str | None = None
) -> dict[str, Any]:
    """Return initial node properties for one composite node."""
    properties = {COMPOSITE_PAYLOAD_KEY: deepcopy(payload)}
    properties[NODE_ID_KEY] = node_id or uuid.uuid4().hex
    return properties


def _clone_input_signal(
    signal: InputSignal,
    *,
    name: str,
    handler: str,
) -> InputSignal:
    """Return one input signal cloned with a new public name/handler."""
    return InputSignal(
        name=name,
        type=signal.type,
        handler=handler,
        flags=signal.flags,
        id=signal.id,
        doc=signal.doc,
        replaces=signal.replaces,
    )


def _clone_output_signal(signal: OutputSignal, *, name: str) -> OutputSignal:
    """Return one output signal cloned with a new public name."""
    return OutputSignal(
        name=name,
        type=signal.type,
        flags=signal.flags,
        id=signal.id,
        doc=signal.doc,
        replaces=signal.replaces,
    )


def _sanitize_token(text: str) -> str:
    """Return one ASCII-ish identifier fragment for generated class names."""
    return "".join(ch if ch.isalnum() else "_" for ch in str(text)).strip("_") or "x"


def _composite_class_name(payload: dict[str, Any]) -> str:
    """Return the generated composite widget class name for one payload."""
    composite_id = str(payload["composite_id"])
    return f"DynamicComposite_{_sanitize_token(composite_id)}"


def _bridge_input_class_name(payload: dict[str, Any]) -> str:
    """Return the generated internal input-bridge class name."""
    composite_id = str(payload["composite_id"])
    return f"DynamicCompositeInputBridge_{_sanitize_token(composite_id)}"


def _bridge_output_class_name(payload: dict[str, Any]) -> str:
    """Return the generated internal output-bridge class name."""
    composite_id = str(payload["composite_id"])
    return f"DynamicCompositeOutputBridge_{_sanitize_token(composite_id)}"


def composite_widget_description(payload: dict[str, Any]) -> WidgetDescription:
    """Return the runtime widget description for one composite payload."""
    qname = payload.get("qualified_name") or (
        f"{COMPOSITE_QNAME_PREFIX}{payload['composite_id']}"
    )
    payload["qualified_name"] = qname
    klass = ensure_composite_widget_class(payload)
    return WidgetDescription(
        name=str(payload.get("display_name") or "Composite"),
        id=f"derzug.dynamic-composite.{payload['composite_id']}",
        category="Processing",
        description="Composite workflow widget",
        qualified_name=f"{klass.__module__}.{klass.__name__}",
        package="derzug",
        project_name="derzug",
        icon=_COMPOSITE_ICON,
        inputs=list(klass.inputs),
        outputs=list(klass.outputs),
    )


class _CompositeInputBridgeBase(OWWidget, openclass=True):
    """Base class for composite runtime input bridges."""

    name = "Composite Input Bridge"
    want_main_area = False
    want_control_area = False
    resizing_enabled = False

    def __init__(self) -> None:
        super().__init__()


class _CompositeOutputBridgeBase(OWWidget, openclass=True):
    """Base class for composite runtime output bridges."""

    name = "Composite Output Bridge"
    want_main_area = False
    want_control_area = False
    resizing_enabled = False

    def __init__(self) -> None:
        super().__init__()
        self._composite = None

    def attach_composite(self, composite) -> None:
        """Attach the owning composite widget for forwarded outputs."""
        self._composite = composite


class _BaseCompositeWidget(OWWidget, openclass=True):
    """Base class for runtime composite widgets."""

    name = "Composite"
    description = "Composite workflow widget"
    icon = _COMPOSITE_ICON
    category = "Processing"
    want_main_area = False
    resizing_enabled = False

    composite_payload = Setting({})

    def __init__(self) -> None:
        super().__init__()
        self._runtime_scheme = None
        self._input_bridge = None
        self._output_bridge = None
        layout = self.controlArea.layout()
        summary = str(self.composite_payload.get("summary") or "Composite widget")
        self._summary_label = QLabel(summary, self.controlArea)
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)
        layout.addStretch(1)
        self._initialize_runtime()

    def _initialize_runtime(self) -> None:
        """Build the internal hidden workflow runtime for this composite."""
        payload = self.composite_payload or {}
        if not payload:
            return
        registry = _runtime_registry()
        if registry is None:
            return

        from derzug.views.orange import DerZugWidgetsScheme

        workflow = DerZugWidgetsScheme()
        xml_text = str(payload.get("internal_scheme_xml") or "")
        if xml_text:
            readwrite.scheme_load(
                workflow,
                io.BytesIO(xml_text.encode("utf-8")),
                registry=registry,
            )

        input_bridge_desc = _bridge_input_description(payload)
        output_bridge_desc = _bridge_output_description(payload)
        input_bridge_node = workflow.new_node(
            input_bridge_desc,
            title="Composite Inputs",
            position=(-240.0, 0.0),
        )
        output_bridge_node = workflow.new_node(
            output_bridge_desc,
            title="Composite Outputs",
            position=(240.0, 0.0),
        )

        internal_nodes_by_id = {
            get_internal_node_id(node): node
            for node in workflow.nodes
            if get_internal_node_id(node) is not None
        }

        for spec in payload.get("input_specs", []):
            target = internal_nodes_by_id.get(spec["internal_node_id"])
            if target is None:
                continue
            workflow.new_link(
                input_bridge_node,
                input_bridge_node.output_channel(spec["port_name"]),
                target,
                target.input_channel(spec["internal_channel_name"]),
            )

        for spec in payload.get("output_specs", []):
            source = internal_nodes_by_id.get(spec["internal_node_id"])
            if source is None:
                continue
            workflow.new_link(
                source,
                source.output_channel(spec["internal_channel_name"]),
                output_bridge_node,
                output_bridge_node.input_channel(spec["port_name"]),
            )

        for node in tuple(workflow.nodes):
            workflow.widget_manager.widget_for_node(node)

        self._runtime_scheme = workflow
        self._input_bridge = workflow.widget_manager.widget_for_node(input_bridge_node)
        self._output_bridge = workflow.widget_manager.widget_for_node(
            output_bridge_node
        )
        if self._output_bridge is not None:
            self._output_bridge.attach_composite(self)

    def _emit_internal_input(self, port_name: str, value: Any) -> None:
        """Push one external composite input into the hidden runtime."""
        if self._input_bridge is None:
            return
        handler = getattr(
            self._input_bridge,
            f"emit_{_sanitize_token(port_name)}",
            None,
        )
        if handler is None:
            return
        handler(value)

    def _forward_internal_output(self, port_name: str, value: Any) -> None:
        """Emit one exposed internal output to the outer Orange workflow."""
        self.send(port_name, value)


def _runtime_registry():
    """Return the live DerZug widget registry when available."""
    from orangecanvas.registry import global_registry

    try:
        import derzug.views.orange as orange_module
    except Exception:
        derzug_main_window_cls = None
    else:
        derzug_main_window_cls = orange_module.DerZugMainWindow
    if derzug_main_window_cls is not None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, derzug_main_window_cls):
                return widget.widget_registry
    return global_registry()


def ensure_composite_widget_class(payload: dict[str, Any]):
    """Return the generated composite widget class for one payload."""
    class_name = _composite_class_name(payload)
    existing = globals().get(class_name)
    if existing is not None:
        return existing

    input_specs = payload.get("input_specs", [])
    output_specs = payload.get("output_specs", [])
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "name": str(payload.get("display_name") or "Composite"),
        "description": "Composite workflow widget",
        "icon": _COMPOSITE_ICON,
        "category": "Composite",
        "inputs": [
            _clone_input_signal(
                spec["signal"],
                name=spec["port_name"],
                handler=f"set_{_sanitize_token(spec['port_name'])}",
            )
            for spec in input_specs
        ],
        "outputs": [
            _clone_output_signal(spec["signal"], name=spec["port_name"])
            for spec in output_specs
        ],
    }

    for spec in input_specs:
        port_name = spec["port_name"]

        def _handler(self, value, *, _port_name=port_name):
            self._emit_internal_input(_port_name, value)

        attrs[f"set_{_sanitize_token(port_name)}"] = _handler

    klass = type(class_name, (_BaseCompositeWidget,), attrs)
    globals()[class_name] = klass
    ensure_bridge_input_class(payload)
    ensure_bridge_output_class(payload)
    return klass


def ensure_bridge_input_class(payload: dict[str, Any]):
    """Return the generated internal input-bridge class for one payload."""
    class_name = _bridge_input_class_name(payload)
    existing = globals().get(class_name)
    if existing is not None:
        return existing

    output_specs = payload.get("input_specs", [])
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "outputs": [
            _clone_output_signal(spec["signal"], name=spec["port_name"])
            for spec in output_specs
        ],
        "inputs": [],
    }
    for spec in output_specs:
        port_name = spec["port_name"]

        def _emit(self, value, *, _port_name=port_name):
            self.send(_port_name, value)

        attrs[f"emit_{_sanitize_token(port_name)}"] = _emit

    klass = type(class_name, (_CompositeInputBridgeBase,), attrs)
    globals()[class_name] = klass
    return klass


def ensure_bridge_output_class(payload: dict[str, Any]):
    """Return the generated internal output-bridge class for one payload."""
    class_name = _bridge_output_class_name(payload)
    existing = globals().get(class_name)
    if existing is not None:
        return existing

    input_specs = payload.get("output_specs", [])
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "inputs": [
            _clone_input_signal(
                spec["signal"],
                name=spec["port_name"],
                handler=f"set_{_sanitize_token(spec['port_name'])}",
            )
            for spec in input_specs
        ],
        "outputs": [],
    }
    for spec in input_specs:
        port_name = spec["port_name"]

        def _handler(self, value, *, _port_name=port_name):
            if self._composite is not None:
                self._composite._forward_internal_output(_port_name, value)

        attrs[f"set_{_sanitize_token(port_name)}"] = _handler

    klass = type(class_name, (_CompositeOutputBridgeBase,), attrs)
    globals()[class_name] = klass
    return klass


def _bridge_input_description(payload: dict[str, Any]) -> WidgetDescription:
    """Return the synthetic description for the internal input bridge."""
    klass = ensure_bridge_input_class(payload)
    return WidgetDescription(
        name="Composite Inputs",
        id=f"derzug.dynamic-composite-input.{payload['composite_id']}",
        category="Processing",
        qualified_name=f"{klass.__module__}.{klass.__name__}",
        package="derzug",
        project_name="derzug",
        outputs=list(klass.outputs),
        icon=_COMPOSITE_ICON,
    )


def _bridge_output_description(payload: dict[str, Any]) -> WidgetDescription:
    """Return the synthetic description for the internal output bridge."""
    klass = ensure_bridge_output_class(payload)
    return WidgetDescription(
        name="Composite Outputs",
        id=f"derzug.dynamic-composite-output.{payload['composite_id']}",
        category="Processing",
        qualified_name=f"{klass.__module__}.{klass.__name__}",
        package="derzug",
        project_name="derzug",
        inputs=list(klass.inputs),
        icon=_COMPOSITE_ICON,
    )
