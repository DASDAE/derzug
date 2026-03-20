# Annotation Design

## Summary

DerZug annotations should start from a small, durable core model rather than a
fully generalized interpretation framework.

The design should optimize for:

- simple drawing and rendering in widgets
- stable persistence across ordinary workflow changes
- low implementation complexity in both 1D and 2D viewers

Annotations should remain reusable across DAS, seismic, and tap-test
workflows, but that reuse should come from a small generic geometry layer plus
a light semantic layer. The model should avoid speculative abstractions until a
real workflow proves they are needed.

This document is a design/spec only. It does not describe an implemented
system.

All persisted field names should use `snake_case`.

## Goals

- Keep the persisted model small and easy to reason about.
- Support both 1D and 2D visual widgets with one shared schema.
- Make annotations renderable from their own stored geometry.
- Preserve annotations as-authored unless an explicit transform is requested.
- Allow domain meaning without baking domain-specific fields into geometry.

## Non-Goals

- A complete abstraction for every future interpretation workflow.
- Automatic remapping across arbitrary upstream data changes.
- A first-class schema for every possible fitted model.
- Persisting widget-local editing state.

## Core Model

The persisted model should start with only three first-class concepts:

- `annotation_set`
- `annotation`
- `geometry`

Everything else should be optional metadata rather than a separate required
subsystem.

### annotation_set

Top-level container for one annotation collection.

Recommended fields:

- `schema_version`
- `dims: tuple[str, ...]`
- `basis: Literal["coord", "index"]`
- `annotations: list[annotation]`
- `provenance: dict[str, Any]`

Notes:

- `dims` describes the interpreted dimensions for the set as a whole.
- `basis` applies to the whole set. Mixed-basis annotation sets should not be
  supported in the initial design.
- `provenance` is optional metadata for authorship and compatibility warnings.
  It must not be required for rendering.

Recommended initial rule:

- one annotation set has one coordinate basis
- all annotations in the set are interpreted under that basis

### annotation

Recommended fields:

- `id`
- `geometry`
- `semantic_type`
- `text`
- `tags`
- `group`
- `properties`
- `ui`

Suggested interpretation:

- `geometry` says where the annotation is
- `semantic_type` says what it means
- `properties` stores user-authored or derived metadata
- `ui` stores explicit persisted presentation settings only when needed

Notes:

- `semantic_type` should be a plain string such as `arrival_pick`,
  `ringdown_window`, `mute_polygon`, or `generic`.
- `tags` are optional and should be used for filtering or search, not as the
  primary semantic carrier.
- `group` is a lightweight way to associate related annotations without
  introducing a separate group model.
- `ui` should remain minimal. Theme-derived style, selection state, hover
  state, and editing handles should remain widget-local and transient.

## Geometry Model

The geometry layer should be explicit, typed, and minimal.

Recommended primitive geometries:

- `point`
- `span`
- `box`
- `path`
- `polygon`

The initial model should avoid multiple primitives that express the same basic
idea.

Examples of simplification:

- a 1D interval is a `span`
- a 2D rectangle is a `box`
- a line segment is a two-point `path`
- a multi-point trace is a `path`

This keeps the geometry vocabulary small while still covering the common use
cases.

### Geometry-owned dims

Each geometry should declare the dimensions it actually uses.

This is important because an annotation set may describe a 2D view while some
annotations only occupy one dimension.

Examples:

- a point in a 2D viewer may use `("distance", "time")`
- a ringing window may use only `("time",)`
- a mute region may use `("offset", "time")`

Recommended geometry shapes:

- `point`
  - `dims`
  - `values`
- `span`
  - `dim`
  - `start`
  - `end`
- `box`
  - `dims`
  - `min_corner`
  - `max_corner`
- `path`
  - `dims`
  - `points`
- `polygon`
  - `dims`
  - `points`

Important rule:

- annotations should render from their own geometry plus the set-level
  `basis`
- rendering must not depend on provenance metadata

## Semantics

The semantic layer should stay simple.

Recommended rule:

- use one primary semantic field: `semantic_type`

Examples:

- `arrival_pick`
- `first_break_pick`
- `tap_impact`
- `ringdown_window`
- `event_region`
- `mute_polygon`
- `generic`

This is simpler than splitting meaning across a broad `kind` enum plus a
second layer of required tags.

`tags` may still be useful, but they should remain optional secondary
metadata.

## Provenance and Compatibility

Annotations should be self-renderable. Provenance is only for context and soft
compatibility checks.

Recommended provenance contents:

- `source_id`
- `revision_id`
- `dims`
- `shape`
- other optional source metadata as needed

Recommended behavior:

- render annotations whenever their geometry is interpretable under the current
  viewer
- preserve annotations as-authored
- do not silently mutate stored coordinates
- do not discard annotations only because upstream data changed

Provenance may be used to detect stale or mismatched annotations, but not to
block rendering.

## Derived and Fitted Annotations

Derived annotations should not require a separate first-class fit schema in the
initial design.

A fitted or derived annotation should still be stored as a normal annotation
with normal geometry.

If derivation metadata is needed, it should live in `properties`.

Examples:

- `properties["fit_model"] = "line"`
- `properties["fit_parameters"] = {...}`
- `properties["derived_from"] = [...]`

This keeps the core schema smaller and avoids premature abstraction around fit
types.

## Upstream Data Changes

The default policy should be conservative.

Recommended behavior:

- preserve annotations as-authored
- keep stored geometry unchanged by default
- allow rendering when the current viewer can still interpret the geometry
- warn on obvious provenance mismatch when useful

Automatic remapping should be deferred until a concrete, deterministic
transform exists for a specific workflow.

## Persistence Boundary

The persistence model should exclude transient widget/editor state.

Do not persist:

- selection state
- hover state
- edit handles
- active tool state
- theme-derived colors or symbols
- screen-space coordinates

Persist only:

- geometry
- semantic meaning
- optional text/tags/group membership
- optional user-authored properties
- optional explicit presentation choices when they are intentionally authored

## Undo/Redo

Interactive annotation editing should support undo/redo when implemented.

Expected action granularity:

- create annotation
- delete annotation
- edit geometry
- change semantic type
- change text/tags/group/properties
- change explicit persisted presentation settings

## Cross-Domain Examples

### DAS

- an event pick as `point` with `semantic_type="arrival_pick"`
- an event region as `box` or `polygon`
- an interpreted trend as `path`

### Seismic

- a first-break pick as `point`
- a horizon as `path`
- a mute zone as `polygon`

### Tap Test

- an impact marker as `point`
- a ringing window as `span`
- several related tap annotations tied together through `group`

## UI Design Direction

Annotation-capable widgets should use a shared interaction pattern, but that UI
layer should remain separate from the persisted schema.

Recommended manual tools:

- select
- point
- span
- box
- path
- polygon

Recommended defaults:

- 1D widgets expose `point` and `span` first
- 2D widgets expose the full geometry toolset
- widgets may provide derived actions later, but derived outputs should still
  serialize as ordinary annotations

## Reusable Widget Architecture

The implementation should still be reusable across widgets, but the shared
machinery should stay focused on editing and rendering the small core schema.

### annotation_mixin responsibilities

- own the current `annotation_set`
- manage selected annotation ids
- manage tool state
- create/update/delete annotations
- convert between scene coordinates and annotation coordinates
- synchronize overlay items with model objects
- emit annotation outputs

### Widget-provided hooks

Widgets should provide only what is view-specific:

- access to the plot/drawing surface
- the current interpreted dimensions
- conversion between plot coordinates and annotation coordinates
- optional provenance metadata
- capability flags for 1D or 2D tools

## Schema Direction

The initial annotation schema should be intentionally small.

Recommended principles:

- keep only a few first-class model objects
- keep geometry primitive and minimal
- make geometry explicitly own its dimensions
- store meaning in `semantic_type`
- keep provenance soft and optional
- defer fit-specific abstractions until they are justified

That gives DerZug a practical annotation model that is simple to implement now
and still extensible later.
