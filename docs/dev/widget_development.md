# Widget development

Widgets can be internal DerZug widgets or written in their own stand-along program and discrovered through entry points. 

## DerZug widgets

- Widgets go in src/derzug/widgets

- A widget's class `name` and its entry-point name in `pyproject.toml` should match.

- Processing widgets (those without visual components) should set `want_main_area = False`
- `ZugWidget` subclasses should separate state changes from visible UI work. Input handlers should store the latest state, emit outputs immediately, and trigger `_request_ui_refresh()` instead of directly redrawing plots, tables, or previews.
- Put visible refresh work in `_refresh_ui()`. `ZugWidget` defers `_refresh_ui()` while the widget window is hidden and flushes one coalesced refresh the next time the window is shown.
- Prefer pure builders for non-trivial UI state. If a widget derives labels, tables, or plot metadata from current settings and inputs, build that state in a plain helper/dataclass first, then have `_refresh_ui()` apply it to Qt.
- Hidden widgets should still keep outputs and internal state current. Only on-screen updates are deferred.
- When widget behavior depends on introspection, parsing, or generated controls, prefer extracting those pure rules into `src/derzug/utils` and keeping the widget focused on Qt wiring/state orchestration. The `Spool` example-parameter dialog is the model: signature inspection and value parsing live in a reusable utility, while the widget only opens the dialog and applies the resulting state.
- Widgets that need persistent overlay interpretation or picks should follow the
  shared annotation architecture in
  [annotations.md](/home/derrick/Gits/derzug/docs/dev/annotations.md) rather
  than inventing widget-local annotation formats.
- Always update the widget's keyboard shortcut reference when adding or changing
  widget interactions. Override `widget_shortcuts()` for widget-specific
  bindings so `Help -> Keyboard Shortcuts` stays accurate.
- Widgets should have an icon in the form of a small svg. Be sure to include the icon in the source, and specify its path.
- When code programmatically pushes scalar values into text boxes, format them with `derzug.utils.display.format_display()` rather than `str(...)`. The shared float precision is controlled by `derzug.constants.DISPLAY_SIGFIGS`. Do not use this to rewrite in-progress user input.

## Example workflows

- Help menu example workflows live in [src/derzug/workflows](/home/derrick/Gits/derzug/src/derzug/workflows).
- Add a new `.ows` file there to make it available under `Help -> Load Example Workflow`.
- These are exposed through the `orange.widgets.tutorials` entry point in `pyproject.toml`.

### Help messages

Every widget can provide human-readable descriptions. This is done in two places.

**Widget-level description** — the `description` class attribute appears in the
Orange widget catalog tooltip. Keep it to one sentence, present tense, no trailing period.

```python
class MyWidget(ZugWidget):
    description = "Apply a Foo transform to a patch"
```

**Channel descriptions** — every `Input()` and `Output()` should include a
`doc=` keyword argument. In the current Orange version used by DerZug
(`3.40.0`), `description=` is not a supported keyword. This text appears as a tooltip when the user
hovers over a connection point in the Orange canvas.

```python
class Inputs:
    patch = Input("Patch", dc.Patch, doc="DAS patch to transform")
    spool = Input("Spool", dc.BaseSpool, doc="Single-patch spool to transform")

class Outputs:
    patch = Output("Patch", dc.Patch, doc="Patch after Foo transform")
```

- Keep descriptions to one short phrase. No trailing period.

###  Testing

- Test files go in test/test_widgets (each widget must have a test file).
  - Each test file should implement at least the default tests. This is done by subclassing TestWidgetDefaults.
  - If a widget adds or changes keyboard-driven behavior, add or update tests for
    the shortcut handling and the `widget_shortcuts()` help text.
  - Plain `pytest` runs force `QT_QPA_PLATFORM=offscreen` so the suite passes headlessly.
  - Running `pytest path/to/my/file -m show` is intentionally interactive: only `@pytest.mark.show` tests run, Qt uses the real desktop backend when available, and each shown window stays open until you close it.
  - Do not change `-m show` back to an offscreen/non-interactive smoke test; it is the supported path for manual widget inspection.

```python
from derzug.utils.testing import TestWidgetDefaults

class TestMyWidgetDefaults(TestWidgetDefaults):
    """Default tests for this widget"""
    __test__ = True
    widget = MyWidget
    # The "happy path" init parameters. 
    inputs = (("patch", dc.get_example_patch("example_event_2")),)


class TestMyWidget:
    """Specific tests for this widget."""
```
