"""Discovery - walk a directory tree and find skill folders.

A *skill folder* is any directory that directly contains a ``SKILL.md`` file
(matched case-insensitively, so ``Skill.md`` / ``skill.md`` also count). Every
other file in that directory subtree is treated as a *sidecar* - the deterministic
assets, scripts, and knowledge that travel alongside the skill.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

SKILL_FILE = "skill.md"


@dataclass(frozen=True)
class SkillSource:
    """A discovered skill folder and its on-disk artifacts.

    Attributes:
        skill_dir: Absolute path to the folder containing ``SKILL.md``.
        skill_md: Absolute path to the ``SKILL.md`` file itself.
        sidecars: Absolute paths to every other file in the folder subtree
            (scripts, assets, knowledge), sorted for determinism.
        root: The scan root this source was discovered under.
    """

    skill_dir: str
    skill_md: str
    sidecars: List[str]
    root: str

    @property
    def rel_dir(self) -> str:
        """Folder path relative to the scan root (POSIX-style)."""
        rel = os.path.relpath(self.skill_dir, self.root)
        return rel.replace(os.sep, "/")


def _find_skill_md(filenames: List[str]) -> str | None:
    """Return the actual ``SKILL.md`` filename in a dir, case-insensitively."""
    for name in filenames:
        if name.lower() == SKILL_FILE:
            return name
    return None


def discover(root: str) -> List[SkillSource]:
    """Discover every skill folder under ``root``.

    Walks ``root`` recursively. For each directory that directly contains a
    ``SKILL.md``, emits a :class:`SkillSource` whose sidecars are all other
    files in that directory's subtree. Results are sorted by folder path.
    """
    root = os.path.abspath(root)
    sources: List[SkillSource] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        skill_name = _find_skill_md(filenames)
        if skill_name is None:
            continue
        skill_md = os.path.join(dirpath, skill_name)
        sidecars: List[str] = []
        for sub_dir, _subs, sub_files in os.walk(dirpath):
            for fname in sub_files:
                full = os.path.join(sub_dir, fname)
                if os.path.abspath(full) == os.path.abspath(skill_md):
                    continue
                sidecars.append(full)
        sources.append(
            SkillSource(
                skill_dir=dirpath,
                skill_md=skill_md,
                sidecars=sorted(sidecars),
                root=root,
            )
        )
    sources.sort(key=lambda s: s.skill_dir)
    return sources
