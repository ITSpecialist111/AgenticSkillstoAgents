"""Parse ``SKILL.md`` - YAML frontmatter + markdown body.

``SKILL.md`` follows the Anthropic Agent Skill convention: an optional YAML
frontmatter block delimited by ``---`` fences, followed by a markdown body that
documents the skill. The frontmatter is the structured signal the mapper uses;
the body provides a fallback summary (its first heading).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import yaml

_FENCE = "---"


@dataclass
class SkillMd:
    """A parsed ``SKILL.md`` document."""

    frontmatter: Dict[str, Any] = field(default_factory=dict)
    body: str = ""

    def first_heading(self) -> str | None:
        """Return the text of the first markdown ``#`` heading in the body."""
        for line in self.body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or None
        return None


def parse_skill_md(text: str) -> SkillMd:
    """Parse ``SKILL.md`` text into frontmatter + body.

    A frontmatter block is recognised only when the document *starts* with a
    ``---`` fence and a closing ``---`` fence is found. The YAML must parse to a
    mapping; anything else raises :class:`ValueError`. When no frontmatter is
    present the whole document is treated as the body.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return SkillMd(frontmatter={}, body=text)

    # Find the closing fence.
    closing = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FENCE:
            closing = idx
            break
    if closing is None:
        # Unterminated frontmatter: treat the entire document as body.
        return SkillMd(frontmatter={}, body=text)

    raw_fm = "\n".join(lines[1:closing])
    body = "\n".join(lines[closing + 1 :]).strip("\n")

    loaded = yaml.safe_load(raw_fm) if raw_fm.strip() else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")
    return SkillMd(frontmatter=loaded, body=body)
