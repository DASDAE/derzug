"""Tests for the generated Conductor skill files (no ``mcp`` dependency)."""

from __future__ import annotations

from derzug.conductor.skill import (
    GENERATED_MARKER,
    SKILL_DIRS,
    skill_text,
    write_skill_files,
)


def test_packaged_skill_is_readable_and_marked():
    """The asset ships in the package with frontmatter and our marker."""
    text = skill_text()
    assert text.startswith("---\n")
    assert "name: derzug-conductor" in text
    assert GENERATED_MARKER in text


def test_write_skill_files_covers_every_client_location(tmp_path):
    """Both the Claude Code and open-standard skill paths get the skill."""
    written = write_skill_files(tmp_path)
    expected = {tmp_path / skill_dir / "SKILL.md" for skill_dir in SKILL_DIRS}
    assert set(written) == expected
    assert (tmp_path / ".claude" / "skills" / "derzug-conductor") in {
        path.parent for path in written
    }
    for path in written:
        assert path.read_text() == skill_text()


def test_write_skill_files_overwrites_only_generated_copies(tmp_path):
    """A regenerated skill replaces ours; a user-edited file is left alone."""
    first = write_skill_files(tmp_path)
    stale = first[0]
    stale.write_text(skill_text().replace("# Drive", "# Old generated content\n# Drive"))
    user_owned = first[1]
    user_owned.write_text("my own notes, marker removed")

    written = write_skill_files(tmp_path)

    assert written == [stale]
    assert stale.read_text() == skill_text()
    assert user_owned.read_text() == "my own notes, marker removed"
