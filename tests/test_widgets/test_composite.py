"""Tests for composite widget utility functions."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from derzug.widgets.composite import (
    COMPOSITE_PAYLOAD_KEY,
    COMPOSITE_QNAME_PREFIX,
    INTERNAL_NODE_ID_KEY,
    NODE_ID_KEY,
    _sanitize_token,
    composite_payload_from_properties,
    composite_properties,
    ensure_bridge_input_class,
    ensure_bridge_output_class,
    ensure_composite_widget_class,
    get_internal_node_id,
    get_node_id,
    is_composite_qualified_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_node(properties: dict | None = None):
    """Return a mock node object with settable .properties."""
    node = MagicMock()
    node.properties = properties
    return node


def _simple_payload(composite_id: str = "test-id") -> dict:
    """Return a minimal composite payload dict."""
    return {
        "composite_id": composite_id,
        "input_specs": [],
        "output_specs": [],
    }


# ---------------------------------------------------------------------------
# is_composite_qualified_name
# ---------------------------------------------------------------------------


class TestIsCompositeQualifiedName:
    """Tests for is_composite_qualified_name."""

    def test_returns_true_for_dynamic_prefix(self):
        """Dynamic prefix returns True."""
        qname = f"{COMPOSITE_QNAME_PREFIX}abc123"
        assert is_composite_qualified_name(qname) is True

    def test_returns_false_for_regular_widget(self):
        """Regular widget qualified name returns False."""
        assert is_composite_qualified_name("derzug.widgets.spool.Spool") is False

    def test_returns_false_for_empty_string(self):
        """Empty string returns False."""
        assert is_composite_qualified_name("") is False


# ---------------------------------------------------------------------------
# get_node_id / get_internal_node_id
# ---------------------------------------------------------------------------


class TestGetNodeId:
    """Tests for get_node_id."""

    def test_returns_none_when_missing(self):
        """Returns None when NODE_ID_KEY is absent."""
        node = _mock_node({})
        assert get_node_id(node) is None

    def test_returns_stored_id(self):
        """Returns the stored node id."""
        node_id = uuid.uuid4().hex
        node = _mock_node({NODE_ID_KEY: node_id})
        assert get_node_id(node) == node_id

    def test_returns_none_for_blank_value(self):
        """Returns None when the stored id is blank."""
        node = _mock_node({NODE_ID_KEY: "  "})
        assert get_node_id(node) is None

    def test_none_properties_returns_none(self):
        """Returns None when node properties is None."""
        node = _mock_node(None)
        assert get_node_id(node) is None


class TestGetInternalNodeId:
    """Tests for get_internal_node_id."""

    def test_returns_none_when_missing(self):
        """Returns None when INTERNAL_NODE_ID_KEY is absent."""
        node = _mock_node({})
        assert get_internal_node_id(node) is None

    def test_returns_stored_internal_id(self):
        """Returns the stored internal node id."""
        iid = uuid.uuid4().hex
        node = _mock_node({INTERNAL_NODE_ID_KEY: iid})
        assert get_internal_node_id(node) == iid


# ---------------------------------------------------------------------------
# composite_payload_from_properties
# ---------------------------------------------------------------------------


class TestCompositePayloadFromProperties:
    """Tests for composite_payload_from_properties."""

    def test_returns_none_for_non_dict(self):
        """Returns None when properties is not a dict."""
        assert composite_payload_from_properties("not a dict") is None
        assert composite_payload_from_properties(None) is None

    def test_returns_none_when_key_absent(self):
        """Returns None when the composite payload key is absent."""
        assert composite_payload_from_properties({}) is None

    def test_returns_none_when_value_not_dict(self):
        """Returns None when the payload value is not a dict."""
        assert composite_payload_from_properties({COMPOSITE_PAYLOAD_KEY: "foo"}) is None

    def test_returns_payload_dict(self):
        """Returns the payload dict when present."""
        payload = {"composite_id": "x"}
        props = {COMPOSITE_PAYLOAD_KEY: payload}
        assert composite_payload_from_properties(props) == payload


# ---------------------------------------------------------------------------
# composite_properties
# ---------------------------------------------------------------------------


class TestCompositeProperties:
    """Tests for composite_properties."""

    def test_contains_payload(self):
        """Result contains the composite payload."""
        payload = {"composite_id": "abc"}
        props = composite_properties(payload)
        assert COMPOSITE_PAYLOAD_KEY in props
        assert props[COMPOSITE_PAYLOAD_KEY]["composite_id"] == "abc"

    def test_auto_generates_node_id(self):
        """Auto-generates a node id when none is provided."""
        payload = {"composite_id": "abc"}
        props = composite_properties(payload)
        assert NODE_ID_KEY in props
        assert props[NODE_ID_KEY]

    def test_uses_provided_node_id(self):
        """Uses the provided node id."""
        props = composite_properties({"composite_id": "abc"}, node_id="my-id")
        assert props[NODE_ID_KEY] == "my-id"

    def test_payload_is_deep_copied(self):
        """Mutations to the original payload must not affect stored properties."""
        original = {"composite_id": "abc", "extra": [1, 2, 3]}
        props = composite_properties(original)
        original["extra"].append(999)
        assert 999 not in props[COMPOSITE_PAYLOAD_KEY]["extra"]


# ---------------------------------------------------------------------------
# _sanitize_token
# ---------------------------------------------------------------------------


class TestSanitizeToken:
    """Tests for _sanitize_token."""

    def test_alphanumeric_unchanged(self):
        """Alphanumeric tokens pass through unchanged."""
        assert _sanitize_token("abc123") == "abc123"

    def test_replaces_special_chars(self):
        """Special characters are replaced."""
        result = _sanitize_token("foo-bar.baz")
        assert "-" not in result
        assert "." not in result

    def test_strips_leading_trailing_underscores(self):
        """Leading and trailing underscores are stripped."""
        result = _sanitize_token("---abc---")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_empty_string_returns_fallback(self):
        """Empty string returns the fallback value."""
        assert _sanitize_token("") == "x"


# ---------------------------------------------------------------------------
# Dynamic class generation (smoke tests)
# ---------------------------------------------------------------------------


class TestEnsureCompositeWidgetClass:
    """Tests for ensure_composite_widget_class."""

    def test_returns_class_for_empty_payload(self):
        """Returns a named DynamicComposite class for a given payload."""
        payload = _simple_payload("smoke-test-cls")
        klass = ensure_composite_widget_class(payload)
        assert klass is not None
        assert klass.__name__.startswith("DynamicComposite_")

    def test_same_payload_returns_same_class(self):
        """Same payload always returns the same class."""
        payload = _simple_payload("idempotent-cls")
        klass1 = ensure_composite_widget_class(payload)
        klass2 = ensure_composite_widget_class(payload)
        assert klass1 is klass2


class TestEnsureBridgeClasses:
    """Tests for ensure_bridge_input_class and ensure_bridge_output_class."""

    def test_input_bridge_returns_class(self):
        """Input bridge returns a class."""
        klass = ensure_bridge_input_class(_simple_payload("bridge-in"))
        assert klass is not None

    def test_output_bridge_returns_class(self):
        """Output bridge returns a class."""
        klass = ensure_bridge_output_class(_simple_payload("bridge-out"))
        assert klass is not None
