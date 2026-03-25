"""Tests for DerZug's dascore namespace integration."""

from __future__ import annotations

import importlib.util
from importlib.metadata import entry_points

import dascore as dc
import numpy as np
import pytest
from AnyQt.QtCore import QTimer
from AnyQt.QtWidgets import QApplication, QWidget
from derzug import dascore as dz_dascore
from derzug.dascore import ZugPatchNameSpace, ZugSpoolNameSpace
from derzug.widgets.spool import Spool
from derzug.widgets.waterfall import Waterfall
from derzug.widgets.wiggle import Wiggle

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("dascore.utils.namespace") is None,
    reason="Installed dascore build does not expose namespace support yet.",
)


def _test_patch() -> dc.Patch:
    """Return one small in-memory patch for namespace tests."""
    data = np.arange(12, dtype=float).reshape(3, 4)
    coords = {
        "distance": np.arange(3, dtype=float),
        "time": np.arange(4, dtype=float),
    }
    attrs = {"tag": "namespace-test"}
    return dc.Patch(data=data, coords=coords, dims=("distance", "time"), attrs=attrs)


class TestPatchZugNamespace:
    """Tests for the Patch.zug namespace."""

    def test_patch_entry_point_metadata_is_registered(self):
        """Package metadata should expose the patch zug namespace entry point."""
        group = entry_points(group="dascore.patch_namespace")
        zug = {ep.name: ep.value for ep in group}

        assert zug["zug"] == "derzug.dascore:ZugPatchNameSpace"

    def test_namespace_registers_on_patch_class(self):
        """Importing derzug.dascore should register the zug namespace."""
        namespaces = dc.Patch.get_registered_namespaces()

        assert namespaces["zug"] is ZugPatchNameSpace

    def test_canvas_delegates_to_canvas_launcher(self, monkeypatch):
        """Patch canvas launch should delegate to the shared canvas helper."""
        patch = _test_patch()
        seen: list[tuple[object, bool, bool]] = []
        sentinel = object()

        monkeypatch.setattr(
            "derzug.dascore._launch_canvas_window",
            lambda value, *, show, block: seen.append((value, show, block)) or sentinel,
        )

        window = patch.zug.canvas(show=False)

        assert window is sentinel
        assert seen == [(patch, False, True)]

    def test_canvas_forwards_non_blocking_option(self, monkeypatch):
        """Patch canvas launch should forward block=False to the shared helper."""
        patch = _test_patch()
        seen: list[tuple[object, bool, bool]] = []
        sentinel = object()

        monkeypatch.setattr(
            "derzug.dascore._launch_canvas_window",
            lambda value, *, show, block: seen.append((value, show, block)) or sentinel,
        )

        window = patch.zug.canvas(show=True, block=False)

        assert window is sentinel
        assert seen == [(patch, True, False)]

    def test_waterfall_show_false_returns_loaded_widget(self, qapp):
        """show=False should return a Waterfall widget with the patch loaded."""
        patch = _test_patch()

        widget = patch.zug.waterfall(show=False)

        assert isinstance(widget, Waterfall)
        assert widget._patch is patch
        widget.close()
        qapp.processEvents()

    def test_wiggle_show_false_returns_loaded_widget(self, qapp):
        """show=False should return a Wiggle widget with the patch loaded."""
        patch = _test_patch()

        widget = patch.zug.wiggle(show=False)

        assert isinstance(widget, Wiggle)
        assert widget._patch is patch
        widget.close()
        qapp.processEvents()

    def test_show_true_invokes_blocking_launch_path(self, monkeypatch, qapp):
        """show=True should show the widget and use the blocking close loop."""
        patch = _test_patch()
        shown: list[Waterfall] = []
        blocked: list[Waterfall] = []

        monkeypatch.setattr(
            "derzug.dascore._block_until_closed",
            lambda widget: blocked.append(widget),
        )
        monkeypatch.setattr(
            Waterfall,
            "show",
            lambda self: shown.append(self),
        )

        widget = patch.zug.waterfall(show=True)

        assert isinstance(widget, Waterfall)
        assert shown == [widget]
        assert blocked == [widget]
        widget.close()
        qapp.processEvents()

    def test_show_true_block_false_returns_after_show(self, monkeypatch, qapp):
        """show=True, block=False should show the widget without blocking."""
        patch = _test_patch()
        shown: list[Waterfall] = []
        blocked: list[Waterfall] = []

        monkeypatch.setattr(
            "derzug.dascore._block_until_closed",
            lambda widget: blocked.append(widget),
        )
        monkeypatch.setattr(
            Waterfall,
            "show",
            lambda self: shown.append(self),
        )

        widget = patch.zug.waterfall(show=True, block=False)

        assert isinstance(widget, Waterfall)
        assert shown == [widget]
        assert blocked == []
        widget.close()
        qapp.processEvents()

    def test_wiggle_show_true_block_false_returns_after_show(self, monkeypatch, qapp):
        """Wiggle should also support non-blocking show semantics."""
        patch = _test_patch()
        shown: list[Wiggle] = []
        blocked: list[Wiggle] = []

        monkeypatch.setattr(
            "derzug.dascore._block_until_closed",
            lambda widget: blocked.append(widget),
        )
        monkeypatch.setattr(
            Wiggle,
            "show",
            lambda self: shown.append(self),
        )

        widget = patch.zug.wiggle(show=True, block=False)

        assert isinstance(widget, Wiggle)
        assert shown == [widget]
        assert blocked == []
        widget.close()
        qapp.processEvents()

    def test_namespace_launch_collapses_control_area(self, qapp):
        """Namespace-launched viewers should start with the control area hidden."""
        patch = _test_patch()

        widget = patch.zug.waterfall(show=False)

        assert widget.controlAreaVisible is False
        widget.close()
        qapp.processEvents()


class TestQApplicationLifecycle:
    """Regression tests for namespace Qt bootstrap behavior."""

    def test_ensure_qapplication_keeps_created_app_alive(self, monkeypatch):
        """A newly created QApplication must be retained at module scope."""
        sentinel = object()
        app_calls: list[list[str]] = []

        class FakeQApplication:
            @staticmethod
            def instance():
                return None

            def __new__(cls, argv):
                app_calls.append(argv)
                return sentinel

        monkeypatch.setattr("derzug.dascore._APP", None)
        monkeypatch.setattr("derzug.dascore.QApplication", FakeQApplication)
        monkeypatch.setattr("derzug.dascore.install_sigint_handler", lambda app: app)

        from derzug import dascore as dz_dascore

        app = dz_dascore._ensure_qapplication()

        assert app is sentinel
        assert dz_dascore._APP is sentinel
        assert app_calls == [["derzug"]]


class TestSpoolZugNamespace:
    """Tests for the BaseSpool.zug namespace."""

    def test_spool_entry_point_metadata_is_registered(self):
        """Package metadata should expose the spool zug namespace entry point."""
        group = entry_points(group="dascore.spool_namespace")
        zug = {ep.name: ep.value for ep in group}

        assert zug["zug"] == "derzug.dascore:ZugSpoolNameSpace"

    def test_namespace_registers_on_base_spool_class(self):
        """Importing derzug.dascore should register the spool zug namespace."""
        namespaces = dc.BaseSpool.get_registered_namespaces()

        assert namespaces["zug"] is ZugSpoolNameSpace

    def test_canvas_delegates_to_canvas_launcher(self, monkeypatch):
        """Spool canvas launch should delegate to the shared canvas helper."""
        patch = _test_patch()
        spool = dc.spool(patch)
        seen: list[tuple[object, bool, bool]] = []
        sentinel = object()

        monkeypatch.setattr(
            "derzug.dascore._launch_canvas_window",
            lambda value, *, show, block: seen.append((value, show, block)) or sentinel,
        )

        window = spool.zug.canvas(show=False)

        assert window is sentinel
        assert seen == [(spool, False, True)]

    def test_canvas_forwards_non_blocking_option(self, monkeypatch):
        """Spool canvas launch should forward block=False to the shared helper."""
        patch = _test_patch()
        spool = dc.spool(patch)
        seen: list[tuple[object, bool, bool]] = []
        sentinel = object()

        monkeypatch.setattr(
            "derzug.dascore._launch_canvas_window",
            lambda value, *, show, block: seen.append((value, show, block)) or sentinel,
        )

        window = spool.zug.canvas(show=True, block=False)

        assert window is sentinel
        assert seen == [(spool, True, False)]


class TestCanvasLaunchHelpers:
    """Tests for the shared canvas launch helpers."""

    def test_launch_canvas_window_show_false_returns_seeded_window(self, monkeypatch):
        """show=False should return the seeded window without showing it."""

        class FakeWindow:
            def __init__(self):
                self.shown = False

            def show(self):
                self.shown = True

        sentinel = FakeWindow()
        monkeypatch.setattr(
            "derzug.dascore._seed_canvas_window",
            lambda value: sentinel,
        )

        out = dz_dascore._launch_canvas_window(_test_patch(), show=False, block=True)

        assert out is sentinel
        assert sentinel.shown is False

    def test_launch_canvas_window_show_true_shows_and_blocks(self, monkeypatch):
        """show=True should show the seeded window and enter the close loop."""

        class FakeWindow:
            def __init__(self):
                self.shown = False

            def show(self):
                self.shown = True

        sentinel = FakeWindow()
        blocked: list[object] = []
        monkeypatch.setattr(
            "derzug.dascore._seed_canvas_window",
            lambda value: sentinel,
        )
        monkeypatch.setattr(
            "derzug.dascore._block_until_closed",
            lambda widget: blocked.append(widget),
        )

        out = dz_dascore._launch_canvas_window(_test_patch(), show=True, block=True)

        assert out is sentinel
        assert sentinel.shown is True
        assert blocked == [sentinel]

    def test_launch_canvas_window_show_true_block_false_shows_without_blocking(
        self, monkeypatch
    ):
        """show=True, block=False should return after showing the seeded window."""

        class FakeWindow:
            def __init__(self):
                self.shown = False

            def show(self):
                self.shown = True

        sentinel = FakeWindow()
        blocked: list[object] = []
        monkeypatch.setattr(
            "derzug.dascore._seed_canvas_window",
            lambda value: sentinel,
        )
        monkeypatch.setattr(
            "derzug.dascore._block_until_closed",
            lambda widget: blocked.append(widget),
        )

        out = dz_dascore._launch_canvas_window(_test_patch(), show=True, block=False)

        assert out is sentinel
        assert sentinel.shown is True
        assert blocked == []

    def test_block_until_closed_tolerates_delete_on_close_widget(self, qapp):
        """Closing a delete-on-close widget should not touch it after deletion."""
        widget = QWidget()
        widget.setAttribute(dz_dascore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        widget.show()
        qapp.processEvents()

        QTimer.singleShot(0, widget.close)

        dz_dascore._block_until_closed(widget)

    def test_get_canvas_spool_description_prefers_public_spool_widget(self):
        """Canvas seeding should resolve the registered public Spool widget."""
        description = type(
            "Description",
            (),
            {
                "name": "Spool",
                "qualified_name": "derzug.widgets.spool.Spool",
                "icon": "icons/Spool.svg",
            },
        )()
        window = type(
            "Window",
            (),
            {
                "widget_registry": type(
                    "Registry",
                    (),
                    {"widgets": staticmethod(lambda: [description])},
                )()
            },
        )()

        out = dz_dascore._get_canvas_spool_description(window)

        assert out is description


class TestCanvasSourceWidget:
    """Tests for the canvas-seeded public Spool widget."""

    def test_set_canvas_source_from_patch_exposes_patch_and_spool(
        self, monkeypatch, qapp
    ):
        """Patch inputs should seed the widget and lock source-entry controls."""
        patch = _test_patch()
        monkeypatch.setattr(Spool, "run", lambda self: None)
        widget = Spool()

        widget.set_canvas_source(patch)

        assert widget._source_spool is not None
        assert list(widget._source_spool) == [patch]
        assert widget.spool_input is None
        assert widget.file_input == ""
        assert widget.raw_input == ""
        assert widget.example_combo.isEnabled() is False
        assert widget.file_path_edit.isEnabled() is False
        assert widget.open_button.isEnabled() is False
        assert widget.raw_edit.isEnabled() is False
        assert widget._inputs_group.isChecked() is False
        widget.close()
        qapp.processEvents()

    def test_set_canvas_source_from_spool_extracts_single_patch(
        self, monkeypatch, qapp
    ):
        """Spool inputs should replace the source spool without changing identity."""
        patch = _test_patch()
        spool = dc.spool(patch)
        monkeypatch.setattr(Spool, "run", lambda self: None)
        widget = Spool()

        widget.set_canvas_source(spool)

        assert widget._source_spool is spool
        widget.close()
        qapp.processEvents()


class TestNonBlockingNamespaceLaunches:
    """Regression tests for multi-window non-blocking namespace launches."""

    def test_patch_viewers_share_qapplication_when_shown_non_blocking(self, qapp):
        """Multiple non-blocking viewers should coexist on one shared QApplication."""
        patch = _test_patch()
        dz_dascore._LIVE_WIDGETS.clear()

        waterfall = patch.zug.waterfall(show=True, block=False)
        wiggle = patch.zug.wiggle(show=True, block=False)
        qapp.processEvents()

        assert waterfall is not wiggle
        assert waterfall.isVisible() is True
        assert wiggle.isVisible() is True
        assert waterfall in dz_dascore._LIVE_WIDGETS.values()
        assert wiggle in dz_dascore._LIVE_WIDGETS.values()
        assert QApplication.instance() is qapp
        assert dz_dascore._APP is qapp

        waterfall.close()
        wiggle.close()
        qapp.processEvents()
        assert waterfall not in dz_dascore._LIVE_WIDGETS.values()
        assert wiggle not in dz_dascore._LIVE_WIDGETS.values()
