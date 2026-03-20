"""Tests for pytest harness helpers."""

from __future__ import annotations

from conftest import _should_suppress_qt_message


class TestQtMessageFilter:
    """Tests for headless Qt message suppression."""

    def test_known_offscreen_plugin_noise_is_suppressed(self):
        """Known offscreen platform-plugin chatter should be filtered."""
        assert _should_suppress_qt_message(
            "This plugin does not support propagateSizeHints()"
        )
        assert _should_suppress_qt_message("This plugin does not support raise()")
        assert _should_suppress_qt_message(
            "This plugin does not support grabbing the keyboard"
        )

    def test_unrelated_qt_messages_are_not_suppressed(self):
        """Non-noise Qt messages should continue to surface."""
        assert not _should_suppress_qt_message("Real Qt warning")
