# Plan: Debug Logging for Widget Runs, Inputs, Results, and Annotation Actions

## Context
DerZug currently has no package-level structured logging. Errors surface through dialogs, but normal widget activity and annotation interactions are hard to inspect during development. We want Python `logging`-based `DEBUG` output covering:
- widget run lifecycle
- Orange input arrivals
- result dispatch from `run()`
- annotation tool / snap / create / edit / delete / fit actions

Logging must be silent by default via the normal library `NullHandler` pattern.

---

## Files to Modify

| File | Change |
|---|---|
| `src/derzug/__init__.py` | Register package `NullHandler` |
| `src/derzug/log.py` | Add `enable_logging()` helper |
| `src/derzug/core/zugwidget.py` | Add widget logger, input-handler wrapping, run/result logging |
| `src/derzug/widgets/annotation_overlay.py` | Add annotation interaction log calls |
| `tests/test_core/test_zugwidget.py` | Add logging coverage for run/input/result behavior |
| `tests/test_widgets/test_annotation_overlay.py` | Add logging coverage for annotation interactions |

---

## Step 1 — Package Logger Baseline

In [`src/derzug/__init__.py`](/home/derrick/Gits/derzug/src/derzug/__init__.py), register:

```python
import logging as _logging

_logging.getLogger("derzug").addHandler(_logging.NullHandler())
```

This should live at module import time and not change any existing exports.

---

## Step 2 — `src/derzug/log.py`

Add a small helper module exposing:

```python
def enable_logging(
    level: int = logging.DEBUG,
    *,
    logger_name: str = "derzug",
    fmt: str = "%(levelname)s %(name)s: %(message)s",
) -> logging.Logger:
```

Behavior:
- get the named logger
- attach a `StreamHandler` only if the logger has no non-`NullHandler` handlers
- set the logger level
- return the configured logger

Developer-facing guarantee:
- calling `enable_logging()` after widgets already exist must still enable future `DEBUG` output for run, result, and input-arrival logging

---

## Step 3 — `src/derzug/core/zugwidget.py`

### 3a. Module logger

Add:

```python
import functools
import logging

_log = logging.getLogger("derzug.widget")
```

### 3b. Wrap input handlers during widget init

Call `self._wrap_input_handlers()` from `__init__()` before `_install_help_menu_actions()`.

### 3c. `_wrap_input_handlers()`

Add one private helper that replaces each declared `@Inputs.x` handler on the instance with a thin wrapper that logs and then delegates to the original class method.

Requirements:
- discover handlers from `type(self).Inputs` and each signal’s `handler` attribute
- bind wrappers on the instance so Orange dispatch via `getattr(widget, input.handler)` hits the wrapper
- support both single-input and multi-input signatures by forwarding `*args, **kwargs`
- mark wrapped handlers so repeated calls do not double-wrap
- do **not** gate wrapping on `isEnabledFor(DEBUG)` during `__init__`

Log format:

```python
"%s: input %r received (%s)"
```

with widget display name, signal label, and payload type name or `"None"`.

Reason for always wrapping:
- if wrapping is conditional on the logger level during construction, `enable_logging()` called later will not start input-arrival logging for already-created widgets

### 3d. `run()`

Add `DEBUG` logging inside `run()`:
- before `_run()`: `"%s: run started"`
- on exception: `"%s: run failed (%s: %s)"`
- immediately before `self._on_result(...)`: `"%s: _on_result (%s)"`
- after a successful `_run()`, before `_on_result(result)`: `"%s: run completed"`

Important placement:
- result logging must happen in `run()`, not only in `ZugWidget._on_result()`, because many widgets override `_on_result()` and do not call `super()`
- on failure, log the `_on_result(None)` dispatch before calling it

### 3e. `_on_result()`

Do not rely on a base `_on_result()` log hook as the primary mechanism. It may remain unchanged unless a small extra debug line is desired, but `run()` is the required logging point.

---

## Step 4 — `src/derzug/widgets/annotation_overlay.py`

### 4a. Module logger

Add:

```python
import logging as _logging

_ann_log = _logging.getLogger("derzug.annotation")
```

### 4b. Interaction logs

Add `DEBUG` logging in these methods:

| Method | Log intent |
|---|---|
| `set_tool` | tool changes |
| `hide_toolbox` | toolbox hidden |
| `set_snap_to_annotations` | snap enabled / disabled |
| `store_annotation` | annotation created vs edited |
| `delete_annotation` | annotation deleted |
| `fit_line_from_selection` | line fit requested |
| `fit_ellipse_from_selection` | ellipse fit requested |
| `fit_square_from_selection` | square fit requested |
| `fit_hyperbola_from_selection` | hyperbola fit requested |

Recommended message shapes:
- `set_tool`: `"tool changed to %r", tool`
- `hide_toolbox`: `"annotation toolbox hidden by user"`
- `set_snap_to_annotations`: `"snap to annotations: %s", "enabled" if enabled else "disabled"`
- fit methods: `"fit requested: shape=%r, n_selected=%d", shape_name, len(self.selected_annotation_ids)`
- `store_annotation`: `"annotation %s: id=%s type=%s", action, annotation.id, type(annotation.geometry).__name__`
- `delete_annotation`: `"annotation deleted: id=%s", annotation_id`

Rules:
- detect `action` in `store_annotation` from whether the annotation id already exists in the current set before upsert
- fit logging belongs in the concrete fit methods, not only `fit_shape_from_selection()`, because keyboard shortcuts call concrete fit methods directly

---

## Step 5 — Tests

### `tests/test_core/test_zugwidget.py`

Add logging tests using `caplog`.

Coverage:
- successful `run()` logs `run started`, `run completed`, and `_on_result (...)`
- failing `run()` logs `run failed (...)` and `_on_result (None)`
- input handler invocation logs the input signal name and payload type
- default package import / widget run emits no stderr noise without an explicit logging handler
- optional: enabling logging after widget construction still captures later input arrivals for that widget

Implementation notes:
- use existing `widget_context(...)`
- for input-arrival coverage, call a real input handler such as `Aggregate.set_patch(...)`
- if adding the late-enable regression, construct the widget first, then enter `caplog.at_level(...)`, then call the input handler

### `tests/test_widgets/test_annotation_overlay.py`

Add annotation logging tests using the existing `overlay_host` fixture.

Fixture usage:
- `overlay_host` already returns `(host, controller)`
- do not instantiate `AnnotationOverlayController(overlay_host)`

Coverage:
- tool change logged
- annotation creation logged
- annotation edit logged
- annotation deletion logged
- snap toggle logged
- fit request logged for at least one direct fit method and one `fit_shape_from_selection(...)` path

---

## Enabling Logging

Examples:

```python
from derzug.log import enable_logging

enable_logging()
enable_logging(logger_name="derzug.widget")
enable_logging(logger_name="derzug.annotation")
```

Standard-library fallback should also work:

```python
import logging

logging.basicConfig()
logging.getLogger("derzug").setLevel(logging.DEBUG)
```

---

## Verification

1. `pytest tests/test_core/test_zugwidget.py -k Logging -v`
2. `pytest tests/test_widgets/test_annotation_overlay.py -k Logging -v`
3. Manual: create a widget, then call `enable_logging()`, then trigger an input handler and confirm input-arrival logs appear
4. `pre-commit run --all-files`
