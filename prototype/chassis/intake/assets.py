"""Classify sidecar files into the three deterministic-action categories.

The categories are the evidence the mapper uses to infer ``skillType`` and the
``scoring.determinism`` heuristic:

* **scripts** - executable/deterministic actions (``.py``, ``.sh``, ``.sql`` ...).
  Their presence is the strongest signal a skill is a deterministic tool.
* **assets** - templates/config/data the skill references (``.json``, ``.csv`` ...).
* **knowledge** - reference docs the skill leans on (``.md``, ``.txt``, ``.pdf`` ...).

Classification is by file extension - a deliberately simple, deterministic
heuristic. Anything unrecognised falls back to ``assets``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List

# Deterministic, runnable actions.
SCRIPT_EXTS = frozenset(
    {
        ".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts",
        ".sql", ".ps1", ".rb", ".go", ".rs", ".java", ".bat", ".cmd",
        ".pl", ".php", ".r", ".lua", ".scala", ".kt",
    }
)

# Human-readable reference material.
KNOWLEDGE_EXTS = frozenset(
    {".md", ".markdown", ".txt", ".rst", ".adoc", ".pdf", ".docx", ".rtf"}
)

SCRIPTS = "scripts"
ASSETS = "assets"
KNOWLEDGE = "knowledge"


@dataclass
class AssetClassification:
    """Sidecar files grouped by category (paths kept as given to the classifier)."""

    scripts: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)
    knowledge: List[str] = field(default_factory=list)

    @property
    def has_scripts(self) -> bool:
        return bool(self.scripts)

    @property
    def is_empty(self) -> bool:
        return not (self.scripts or self.assets or self.knowledge)

    def as_dict(self) -> dict:
        return {
            SCRIPTS: list(self.scripts),
            ASSETS: list(self.assets),
            KNOWLEDGE: list(self.knowledge),
        }


def _ext(path: str) -> str:
    dot = path.rfind(".")
    slash = max(path.rfind("/"), path.rfind("\\"))
    if dot <= slash:  # no extension (or the dot is part of a directory name)
        return ""
    return path[dot:].lower()


def classify_file(path: str) -> str:
    """Return the category (``scripts``/``assets``/``knowledge``) for one path."""
    ext = _ext(path)
    if ext in SCRIPT_EXTS:
        return SCRIPTS
    if ext in KNOWLEDGE_EXTS:
        return KNOWLEDGE
    return ASSETS


def classify_assets(paths: Iterable[str]) -> AssetClassification:
    """Classify an iterable of sidecar paths into an :class:`AssetClassification`."""
    result = AssetClassification()
    for path in paths:
        category = classify_file(path)
        getattr(result, category).append(path)
    result.scripts.sort()
    result.assets.sort()
    result.knowledge.sort()
    return result
