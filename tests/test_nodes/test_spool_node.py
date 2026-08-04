"""The Spool node reproduces its source from persisted settings alone.

A canvas Spool widget resolves its saved selection against a live table and
migrates legacy settings during setup. A headless caller gets neither, so the
node has to do both itself or a saved workflow silently emits the wrong patch.
"""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.nodes.spool import (
    NODE_SPEC,
    SpoolParams,
    contents_identity_token,
    ordered_contents_df,
    resolved_select_filters,
    spool_task_from_params,
)


@pytest.fixture(scope="module")
def directory_spool(tmp_path_factory) -> dc.BaseSpool:
    """Return a multi-patch directory spool whose row order is meaningful."""
    directory = tmp_path_factory.mktemp("spool_node")
    dc.examples.spool_to_directory(dc.get_example_spool("diverse_das"), directory)
    return dc.spool(directory)


class TestLegacySelectFilters:
    """The pre-row-list select settings still filter when the node runs."""

    def test_legacy_single_select_is_folded_into_the_filter_rows(self):
        """``select_col``/``select_val`` become one filter row."""
        assert resolved_select_filters([], "tag", "some_tag") == [
            {"key": "tag", "raw": "some_tag"}
        ]

    def test_explicit_rows_win_over_the_legacy_pair(self):
        """A populated row list is authoritative; the legacy pair is ignored."""
        rows = [{"key": "station", "raw": "01"}]
        assert resolved_select_filters(rows, "tag", "some_tag") == rows

    def test_the_task_factory_applies_the_legacy_pair(self):
        """Building through the spec carries the legacy filter into the task."""
        params = SpoolParams(select_col="tag", select_val="some_tag")
        task = NODE_SPEC.build_task(params)
        assert task.select_filters == ({"key": "tag", "raw": "some_tag"},)


class TestPatchNameSelection:
    """A saved row selection survives the source being reordered."""

    def test_patch_name_beats_a_stale_row_index(self, directory_spool):
        """The recorded token selects its patch, not whatever row 0 now holds."""
        df = ordered_contents_df(directory_spool)
        assert len(df) > 1, "need at least two rows to tell the two apart"
        wanted_row = len(df) - 1
        token = contents_identity_token(df, wanted_row)

        params = SpoolParams(
            file_input=str(directory_spool.spool_path),
            selected_source_row=0,
            selected_source_patch_name=token,
            unpack_single_patch=False,
        )
        result = spool_task_from_params(params).run()

        selected = ordered_contents_df(result["spool"])
        assert len(selected) == 1
        assert contents_identity_token(selected, 0) == token

    def test_row_index_is_used_when_no_token_was_saved(self, directory_spool):
        """Without a token the persisted row index still applies."""
        df = ordered_contents_df(directory_spool)
        params = SpoolParams(
            file_input=str(directory_spool.spool_path),
            selected_source_row=0,
            unpack_single_patch=False,
        )
        result = spool_task_from_params(params).run()

        selected = ordered_contents_df(result["spool"])
        assert len(selected) == 1
        assert contents_identity_token(selected, 0) == contents_identity_token(df, 0)
