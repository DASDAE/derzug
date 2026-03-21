"""Helpers for annotation-set operations, summaries, and store persistence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from derzug.models.annotations import Annotation, AnnotationSet

_TYPE_ORDER = ("point", "span", "box", "path", "polygon")


@dataclass(frozen=True)
class AnnotationStoreEntry:
    """One stored annotation-set row."""

    id: str
    name: str
    annotation_set: AnnotationSet
    file_path: str | None = None


@dataclass(frozen=True)
class AnnotationStoreSummary:
    """Display summary for one stored annotation-set row."""

    id: str
    name: str
    dims_text: str
    annotation_count: int
    point_count: int
    span_count: int
    box_count: int
    path_count: int
    polygon_count: int
    size_bytes: int | None
    size_text: str
    file_path: str | None


@dataclass(frozen=True)
class AnnotationImportResult:
    """Result of importing one incoming annotation set."""

    entries: tuple[AnnotationStoreEntry, ...]
    selected_id: str | None


@dataclass(frozen=True)
class AnnotationStoreState:
    """Serializable widget state for workflow persistence."""

    directory: str = ""
    selected_id: str = ""
    entries: tuple[dict, ...] = field(default_factory=tuple)


def annotation_id_map(annotation_set: AnnotationSet) -> dict[str, Annotation]:
    """Return annotations keyed by id."""
    return {annotation.id: annotation for annotation in annotation_set.annotations}


def replace_annotation_sequence(
    annotation_set: AnnotationSet,
    annotations: tuple[Annotation, ...] | list[Annotation],
) -> AnnotationSet:
    """Return an annotation set with a replaced annotation tuple."""
    return annotation_set.model_copy(update={"annotations": tuple(annotations)})


def upsert_annotation(
    annotation_set: AnnotationSet,
    annotation: Annotation,
) -> AnnotationSet:
    """Insert or replace one annotation by id."""
    annotations = list(annotation_set.annotations)
    for index, existing in enumerate(annotations):
        if existing.id == annotation.id:
            annotations[index] = annotation
            break
    else:
        annotations.append(annotation)
    return replace_annotation_sequence(annotation_set, annotations)


def delete_annotation_by_id(
    annotation_set: AnnotationSet,
    annotation_id: str,
) -> AnnotationSet:
    """Return an annotation set without one annotation id."""
    annotations = tuple(
        item for item in annotation_set.annotations if item.id != annotation_id
    )
    return replace_annotation_sequence(annotation_set, annotations)


def annotation_type_counts(annotation_set: AnnotationSet) -> dict[str, int]:
    """Return per-geometry-type counts for one annotation set."""
    counts = {name: 0 for name in _TYPE_ORDER}
    for annotation in annotation_set.annotations:
        counts[annotation.geometry.type] = counts.get(annotation.geometry.type, 0) + 1
    return counts


def format_file_size(size_bytes: int | None) -> str:
    """Return a compact human-readable file size."""
    if size_bytes is None:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    value = float(size_bytes)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PiB"


def next_entry_name(entries: tuple[AnnotationStoreEntry, ...]) -> str:
    """Return the next default display name for a new row."""
    prefix = "Annotations "
    used: set[int] = set()
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        suffix = entry.name[len(prefix) :].strip()
        if suffix.isdigit():
            used.add(int(suffix))
    index = 1
    while index in used:
        index += 1
    return f"{prefix}{index}"


def make_entry(
    annotation_set: AnnotationSet,
    *,
    name: str | None = None,
    file_path: str | None = None,
    entry_id: str | None = None,
    existing_entries: tuple[AnnotationStoreEntry, ...] = (),
) -> AnnotationStoreEntry:
    """Create one store entry for an annotation set."""
    display_name = (name or "").strip() or next_entry_name(existing_entries)
    return AnnotationStoreEntry(
        id=entry_id or uuid4().hex,
        name=display_name,
        annotation_set=annotation_set,
        file_path=file_path,
    )


def replace_entry(
    entries: tuple[AnnotationStoreEntry, ...],
    updated: AnnotationStoreEntry,
) -> tuple[AnnotationStoreEntry, ...]:
    """Return entries with one row replaced."""
    return tuple(updated if entry.id == updated.id else entry for entry in entries)


def selected_annotation_set(
    entries: tuple[AnnotationStoreEntry, ...], selected_id: str | None
) -> AnnotationSet | None:
    """Return the selected annotation set, if any."""
    if not selected_id:
        return None
    for entry in entries:
        if entry.id == selected_id:
            return entry.annotation_set
    return None


def rename_entry(
    entries: tuple[AnnotationStoreEntry, ...],
    entry_id: str,
    name: str,
) -> tuple[AnnotationStoreEntry, ...]:
    """Return entries with one row renamed."""
    cleaned = name.strip()
    if not cleaned:
        return entries
    return tuple(
        AnnotationStoreEntry(
            id=entry.id,
            name=cleaned if entry.id == entry_id else entry.name,
            annotation_set=entry.annotation_set,
            file_path=entry.file_path,
        )
        for entry in entries
    )


def delete_entry(
    entries: tuple[AnnotationStoreEntry, ...],
    entry_id: str,
    *,
    selected_id: str | None = None,
) -> tuple[tuple[AnnotationStoreEntry, ...], str | None]:
    """Delete one entry and return (entries, next_selected_id)."""
    kept = tuple(entry for entry in entries if entry.id != entry_id)
    if selected_id and selected_id != entry_id:
        return kept, selected_id
    next_selected = kept[0].id if kept else None
    return kept, next_selected


def merge_annotation_sets(current: AnnotationSet, incoming: AnnotationSet) -> AnnotationSet:
    """Append incoming annotations, replacing entries with colliding ids."""
    existing = annotation_id_map(current)
    current_ids = set(existing)
    for annotation in incoming.annotations:
        existing[annotation.id] = annotation
    ordered_ids = [annotation.id for annotation in current.annotations]
    ordered_ids.extend(
        annotation.id
        for annotation in incoming.annotations
        if annotation.id not in current_ids
    )
    merged_annotations = tuple(existing[annotation_id] for annotation_id in ordered_ids)
    return replace_annotation_sequence(current, merged_annotations)


def import_annotation_set(
    entries: tuple[AnnotationStoreEntry, ...],
    incoming: AnnotationSet,
    *,
    selected_id: str | None,
    directory: str = "",
) -> AnnotationImportResult:
    """Import an annotation set according to the widget's merge rules."""
    if not incoming.annotations:
        normalized_selected = normalize_selected_id(entries, selected_id)
        return AnnotationImportResult(
            entries=entries,
            selected_id=normalized_selected,
        )
    selected_entry = next((entry for entry in entries if entry.id == selected_id), None)
    if selected_entry is None or selected_entry.annotation_set.dims != incoming.dims:
        entry = make_entry(incoming, existing_entries=entries)
        entry = _entry_with_directory_path(entry, directory)
        return AnnotationImportResult(entries=(*entries, entry), selected_id=entry.id)
    merged = merge_annotation_sets(selected_entry.annotation_set, incoming)
    updated = AnnotationStoreEntry(
        id=selected_entry.id,
        name=selected_entry.name,
        annotation_set=merged,
        file_path=selected_entry.file_path,
    )
    updated = _entry_with_directory_path(updated, directory)
    return AnnotationImportResult(
        entries=replace_entry(entries, updated),
        selected_id=updated.id,
    )


def summarize_entry(entry: AnnotationStoreEntry) -> AnnotationStoreSummary:
    """Build one display summary for a stored annotation-set row."""
    counts = annotation_type_counts(entry.annotation_set)
    size_bytes = file_size_for_entry(entry)
    return AnnotationStoreSummary(
        id=entry.id,
        name=entry.name,
        dims_text=", ".join(entry.annotation_set.dims),
        annotation_count=len(entry.annotation_set.annotations),
        point_count=counts.get("point", 0),
        span_count=counts.get("span", 0),
        box_count=counts.get("box", 0),
        path_count=counts.get("path", 0),
        polygon_count=counts.get("polygon", 0),
        size_bytes=size_bytes,
        size_text=format_file_size(size_bytes),
        file_path=entry.file_path,
    )


def summarize_entries(
    entries: tuple[AnnotationStoreEntry, ...],
) -> tuple[AnnotationStoreSummary, ...]:
    """Summarize all entries for table display."""
    return tuple(summarize_entry(entry) for entry in entries)


def serialize_annotation_set(annotation_set: AnnotationSet) -> str:
    """Serialize one annotation set to formatted JSON."""
    return annotation_set.model_dump_json(indent=2)


def deserialize_annotation_set(text: str) -> AnnotationSet:
    """Deserialize one annotation set from JSON text."""
    return AnnotationSet.model_validate_json(text)


def entry_to_state(entry: AnnotationStoreEntry) -> dict:
    """Serialize one store entry into workflow-safe state."""
    return {
        "id": entry.id,
        "name": entry.name,
        "file_path": entry.file_path or "",
        "annotation_set": entry.annotation_set.model_dump(mode="json"),
    }


def entry_from_state(data: dict) -> AnnotationStoreEntry:
    """Restore one store entry from workflow-safe state."""
    annotation_set = AnnotationSet.model_validate(data["annotation_set"])
    file_path = str(data.get("file_path", "")).strip() or None
    return AnnotationStoreEntry(
        id=str(data["id"]),
        name=str(data["name"]),
        annotation_set=annotation_set,
        file_path=file_path,
    )


def build_state(
    entries: tuple[AnnotationStoreEntry, ...],
    *,
    directory: str,
    selected_id: str | None,
) -> AnnotationStoreState:
    """Build serializable widget state."""
    return AnnotationStoreState(
        directory=directory,
        selected_id=selected_id or "",
        entries=tuple(entry_to_state(entry) for entry in entries),
    )


def state_to_dict(state: AnnotationStoreState) -> dict:
    """Return a plain dict for Orange settings persistence."""
    return asdict(state)


def entries_from_state_items(items: object) -> tuple[AnnotationStoreEntry, ...]:
    """Restore entries from a workflow settings payload."""
    if not isinstance(items, list):
        return ()
    out: list[AnnotationStoreEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            out.append(entry_from_state(item))
        except Exception:
            continue
    return tuple(out)


def entry_file_path(directory: str | Path, entry_id: str) -> Path:
    """Return the disk path for one entry id."""
    return Path(directory) / f"{entry_id}.json"


def persist_entries(
    entries: tuple[AnnotationStoreEntry, ...],
    directory: str | Path,
) -> tuple[AnnotationStoreEntry, ...]:
    """Persist all entries into a backing directory and return updated entries."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    valid_paths: set[Path] = set()
    updated: list[AnnotationStoreEntry] = []
    for entry in entries:
        path = entry_file_path(root, entry.id)
        path.write_text(serialize_annotation_set(entry.annotation_set), encoding="utf-8")
        valid_paths.add(path)
        updated.append(
            AnnotationStoreEntry(
                id=entry.id,
                name=entry.name,
                annotation_set=entry.annotation_set,
                file_path=str(path),
            )
        )
    for path in root.glob("*.json"):
        if path not in valid_paths:
            path.unlink()
    return tuple(updated)


def load_entries_from_directory(directory: str | Path) -> tuple[AnnotationStoreEntry, ...]:
    """Load all JSON-backed annotation sets from one directory."""
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return ()
    entries: list[AnnotationStoreEntry] = []
    for path in sorted(root.glob("*.json")):
        try:
            annotation_set = deserialize_annotation_set(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entries.append(
            AnnotationStoreEntry(
                id=path.stem,
                name=path.stem,
                annotation_set=annotation_set,
                file_path=str(path),
            )
        )
    return tuple(entries)


def persist_entry_name_metadata(
    entry: AnnotationStoreEntry,
    directory: str | Path,
) -> AnnotationStoreEntry:
    """Persist one entry payload and keep file identity stable."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = entry_file_path(root, entry.id)
    payload = {"name": entry.name, "annotation_set": entry.annotation_set.model_dump(mode="json")}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return AnnotationStoreEntry(
        id=entry.id,
        name=entry.name,
        annotation_set=entry.annotation_set,
        file_path=str(path),
    )


def load_entries_with_metadata(directory: str | Path) -> tuple[AnnotationStoreEntry, ...]:
    """Load annotation entries from directory, supporting stored row names."""
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return ()
    entries: list[AnnotationStoreEntry] = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and "annotation_set" in payload:
            try:
                annotation_set = AnnotationSet.model_validate(payload["annotation_set"])
            except Exception:
                continue
            name = str(payload.get("name", "")).strip() or path.stem
        else:
            try:
                annotation_set = AnnotationSet.model_validate(payload)
            except Exception:
                continue
            name = path.stem
        entries.append(
            AnnotationStoreEntry(
                id=path.stem,
                name=name,
                annotation_set=annotation_set,
                file_path=str(path),
            )
        )
    return tuple(entries)


def persist_entries_with_metadata(
    entries: tuple[AnnotationStoreEntry, ...],
    directory: str | Path,
) -> tuple[AnnotationStoreEntry, ...]:
    """Persist all entries, including editable display names."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    valid_paths: set[Path] = set()
    updated: list[AnnotationStoreEntry] = []
    for entry in entries:
        updated_entry = persist_entry_name_metadata(entry, root)
        updated.append(updated_entry)
        valid_paths.add(Path(updated_entry.file_path))
    for path in root.glob("*.json"):
        if path not in valid_paths:
            path.unlink()
    return tuple(updated)


def file_size_for_entry(entry: AnnotationStoreEntry) -> int | None:
    """Return the persisted file size for one entry."""
    if not entry.file_path:
        return None
    path = Path(entry.file_path)
    if not path.exists():
        return None
    return path.stat().st_size


def normalize_selected_id(
    entries: tuple[AnnotationStoreEntry, ...], selected_id: str | None
) -> str | None:
    """Return a valid selected id present in entries."""
    if selected_id and any(entry.id == selected_id for entry in entries):
        return selected_id
    return entries[0].id if entries else None


def sync_directory_state(
    entries: tuple[AnnotationStoreEntry, ...],
    directory: str,
) -> tuple[AnnotationStoreEntry, ...]:
    """Persist or de-persist entries depending on whether directory is active."""
    if not directory:
        return tuple(
            AnnotationStoreEntry(
                id=entry.id,
                name=entry.name,
                annotation_set=entry.annotation_set,
                file_path=None,
            )
            for entry in entries
        )
    return persist_entries_with_metadata(entries, directory)


def load_store(
    *,
    directory: str,
    state_entries: object,
) -> tuple[AnnotationStoreEntry, ...]:
    """Load entries from disk when configured, else from workflow state."""
    if directory:
        loaded = load_entries_with_metadata(directory)
        if loaded:
            return loaded
    return entries_from_state_items(state_entries)


def _entry_with_directory_path(
    entry: AnnotationStoreEntry,
    directory: str,
) -> AnnotationStoreEntry:
    """Assign the directory-backed path for one entry when relevant."""
    if not directory:
        return AnnotationStoreEntry(
            id=entry.id,
            name=entry.name,
            annotation_set=entry.annotation_set,
            file_path=None,
        )
    return AnnotationStoreEntry(
        id=entry.id,
        name=entry.name,
        annotation_set=entry.annotation_set,
        file_path=str(entry_file_path(directory, entry.id)),
    )


__all__ = (
    "annotation_id_map",
    "annotation_type_counts",
    "AnnotationImportResult",
    "AnnotationStoreEntry",
    "AnnotationStoreState",
    "AnnotationStoreSummary",
    "build_state",
    "delete_annotation_by_id",
    "delete_entry",
    "deserialize_annotation_set",
    "entry_to_state",
    "format_file_size",
    "import_annotation_set",
    "load_store",
    "merge_annotation_sets",
    "normalize_selected_id",
    "persist_entries_with_metadata",
    "rename_entry",
    "replace_entry",
    "replace_annotation_sequence",
    "selected_annotation_set",
    "state_to_dict",
    "summarize_entries",
    "sync_directory_state",
    "upsert_annotation",
)
