"""Intake layer - the front door to the Register gate.

Real-world skills arrive as a *folder* (an Anthropic-style ``SKILL.md`` plus the
deterministic assets/scripts/knowledge that sit alongside it). This package turns
those folders into canonical chassis manifests (:mod:`chassis.manifest`) so the
same unit can travel the six-gate pipeline (:mod:`chassis.registry`) unchanged.

It sits strictly *upstream* of Gate 1: it only ever authors **draft** manifests
plus an :class:`IntakeReport` of what was inferred vs. what a human still needs to
complete. It never invents IOPE and never auto-publishes - propose, don't merge.

Layout (1:1 with the plan):

* :mod:`chassis.intake.discovery` - walk a tree, find skill folders + sidecars.
* :mod:`chassis.intake.skillmd`   - parse ``SKILL.md`` frontmatter + body.
* :mod:`chassis.intake.assets`    - classify sidecars into scripts/assets/knowledge.
* :mod:`chassis.intake.mapper`    - assemble + validate a draft manifest + report.
* :mod:`chassis.intake.watcher`   - content-hash poller that re-emits on change.
"""

from __future__ import annotations

from .assets import AssetClassification, classify_assets, classify_file
from .discovery import SkillSource, discover
from .mapper import IntakeReport, build_manifest
from .skillmd import SkillMd, parse_skill_md
from .watcher import IntakeWatcher, hash_source

__all__ = [
    "AssetClassification",
    "classify_assets",
    "classify_file",
    "SkillSource",
    "discover",
    "IntakeReport",
    "build_manifest",
    "SkillMd",
    "parse_skill_md",
    "IntakeWatcher",
    "hash_source",
]
