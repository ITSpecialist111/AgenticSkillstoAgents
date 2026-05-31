"""Pipeline-as-CI: run the automated graduation-gate checks over manifest files.

This is the headless form of the Register/Certify exit criteria so the same
checks that guard the registry can guard a *pull request*. Given a set of
manifest files (the GitHub system-of-record), it loads them all, then for each
one reports the automated checks that gate Register and Certify:

* schema validity (Register),
* determinism/risk scored (Certify),
* dependency refs resolve within the changed set (Certify),
* duplicate-capability scan against the rest of the set (Certify).

It is deliberately *advisory about the human gate*: certification still requires
a human approver (the PR reviewer); this only runs the machine-checkable part so
a red check blocks merge before a human spends time reviewing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .manifest import (
    Manifest,
    ManifestError,
    capability_tags,
    skill_id,
    validate_manifest,
)


@dataclass
class GateCheck:
    """The result of running the automated gate checks for one manifest."""

    skill_id: str
    source: str
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.passed = False
        self.errors.append(message)


def _index(manifests: Dict[str, Manifest]):
    known_ids = set(manifests.keys())
    known_tags = {tag for m in manifests.values() for tag in capability_tags(m)}
    return known_ids, known_tags


def check_manifests(loaded: List[tuple]) -> List[GateCheck]:
    """Run automated gate checks over ``[(source_path, manifest), ...]``.

    Returns one :class:`GateCheck` per manifest. The set is treated as a single
    changeset: duplicate and dependency checks are evaluated *within* the set,
    mirroring what a PR introducing/updating these manifests would do.
    """
    by_id: Dict[str, Manifest] = {}
    checks: List[GateCheck] = []

    # First pass: schema validity + build the id index.
    for source, manifest in loaded:
        try:
            sid = skill_id(manifest)
        except (KeyError, TypeError):
            sid = "<unknown>"
        check = GateCheck(skill_id=sid, source=source)
        try:
            validate_manifest(manifest)
        except ManifestError as exc:
            check.fail(f"schema: {exc}")
        else:
            if sid in by_id:
                check.fail(f"duplicate skill id in changeset: {sid}")
            else:
                by_id[sid] = manifest
        checks.append(check)

    known_ids, known_tags = _index(by_id)

    # Second pass: certify-grade checks for schema-valid manifests.
    tag_owner: Dict[str, str] = {}
    for check in checks:
        if not check.passed:
            continue
        manifest = by_id[check.skill_id]

        scoring = manifest.get("scoring", {})
        if "determinism" not in scoring or "risk" not in scoring:
            check.fail("certify: determinism and risk must be scored")

        for dep in manifest.get("dependencies", []):
            if dep.get("optional"):
                continue
            ref = dep["ref"]
            if ref not in known_ids and ref not in known_tags:
                check.warnings.append(
                    f"dependency '{ref}' not resolved within changeset "
                    "(must exist in the registry at Certify)"
                )

        for tag in capability_tags(manifest):
            if tag in tag_owner and tag_owner[tag] != check.skill_id:
                check.fail(
                    f"duplicate-capability: tag '{tag}' also provided by "
                    f"'{tag_owner[tag]}' in this changeset"
                )
            else:
                tag_owner.setdefault(tag, check.skill_id)

    return checks


def summarize(checks: List[GateCheck]) -> str:
    """Render a compact, CI-friendly report; empty string if all passed."""
    lines: List[str] = []
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"[{status}] {check.skill_id}  ({check.source})")
        for err in check.errors:
            lines.append(f"    error: {err}")
        for warn in check.warnings:
            lines.append(f"    warn:  {warn}")
    return "\n".join(lines)


__all__ = ["GateCheck", "check_manifests", "summarize"]
