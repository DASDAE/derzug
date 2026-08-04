"""The Annotations node: a bound source serving one stored annotation set."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from derzug.models.annotations import AnnotationSet
from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.annotations import load_store, selected_annotation_set
from derzug.workflow.task import Task


class AnnotationsTask(Task):
    """Return the selected annotation set from persisted store state."""

    output_variables: ClassVar[dict[str, object]] = {"annotation_set": object}

    store_directory: str = ""
    stored_entries: tuple[dict, ...] = ()
    selected_entry_id: str = ""

    def run(self):
        """Load persisted entries and return the selected annotation set."""
        directory = self.store_directory.strip()
        entries = load_store(
            directory=directory,
            state_entries=list(self.stored_entries),
        )
        return selected_annotation_set(entries, self.selected_entry_id.strip() or None)


class AnnotationsParams(BaseModel):
    """Parameters for the Annotations store node."""

    store_directory: str = ""
    stored_entries: list = Field(default_factory=list)
    selected_entry_id: str = ""


def annotations_task_from_params(
    params: AnnotationsParams | None = None,
) -> AnnotationsTask:
    """Build the configured annotation-store source task."""
    params = AnnotationsParams() if params is None else params
    return AnnotationsTask(
        store_directory=str(params.store_directory or ""),
        stored_entries=tuple(params.stored_entries or ()),
        selected_entry_id=str(params.selected_entry_id or ""),
    )


NODE_SPEC = NodeSpec(
    name="Annotations",
    widget_qualified_name="derzug.widgets.annotations.Annotations",
    inputs=(
        PortSpec(
            name="annotation_set",
            display_name="Annotations",
            type=AnnotationSet,
            context_only=True,
        ),
    ),
    outputs=(
        PortSpec(name="annotation_set", display_name="Annotations", type=AnnotationSet),
    ),
    params_model=AnnotationsParams,
    task_factory=annotations_task_from_params,
    is_source=True,
    category="IO",
    description="Store and persist annotation sets",
    keywords=("annotations", "store", "persist", "table"),
    icon="icons/Annotations.svg",
    priority=27,
)
