"""Part B - the six-gate pipeline state machine and the in-memory registry.

The registry is the system-of-record stand-in. ``lifecycle.stage`` is the single
source of truth for where a skill sits, and each gate enforces explicit exit
criteria before advancing the stage. Gates map 1:1 to ``docs/architecture.md``:

    Register -> Certify -> Publish -> (Meaning-sync / Compose) -> Retire/version
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from .manifest import (
    Manifest,
    capability_tags,
    skill_id,
    validate_manifest,
)
from .store import InMemoryStore, SkillStore


class Stage(str, Enum):
    """Lifecycle stages, mirroring the schema enum and the pipeline."""

    DRAFT = "draft"
    REGISTERED = "registered"
    CERTIFIED = "certified"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class GateError(RuntimeError):
    """Raised when a gate's entry/exit criteria are not met."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Registry:
    """An MCP-shaped catalog of manifests keyed by skill id."""

    def __init__(self, store: SkillStore | None = None) -> None:
        self._store = store or InMemoryStore()

    # ----- helpers --------------------------------------------------------
    def get(self, sid: str) -> Manifest:
        if not self._store.exists(sid):
            raise KeyError(f"unknown skill: {sid}")
        return self._store.get(sid)

    def all(self) -> List[Manifest]:
        return self._store.all()

    def _stage(self, manifest: Manifest) -> Stage:
        return Stage(manifest["lifecycle"]["stage"])

    def _published_tags(self, exclude: Optional[str] = None) -> Dict[str, str]:
        """Map capability tag -> skill id for published skills (for dedupe scan)."""
        seen: Dict[str, str] = {}
        for manifest in self._store.all():
            sid = skill_id(manifest)
            if sid == exclude:
                continue
            if self._stage(manifest) != Stage.PUBLISHED:
                continue
            for tag in capability_tags(manifest):
                seen.setdefault(tag, sid)
        return seen

    # ----- Gate 1: Register ----------------------------------------------
    def register(self, manifest: Manifest) -> Manifest:
        """Validate the manifest and admit it to the registry (-> registered)."""
        validate_manifest(manifest)
        manifest = copy.deepcopy(manifest)
        sid = skill_id(manifest)
        if self._store.exists(sid):
            raise GateError(f"skill already registered: {sid}")
        if self._stage(manifest) not in (Stage.DRAFT, Stage.REGISTERED):
            raise GateError(
                f"register requires stage draft/registered, got "
                f"'{manifest['lifecycle']['stage']}'"
            )
        manifest["lifecycle"]["stage"] = Stage.REGISTERED.value
        self._store.put(manifest)
        return manifest

    # ----- Gate 2: Certify -----------------------------------------------
    def certify(self, sid: str, approver: str) -> Manifest:
        """Run automated checks + record the mandatory human approval.

        Automated exit checks: schema valid, determinism/risk scored,
        duplicate-capability scan, dependency refs resolve. ``approver`` is the
        human-in-the-loop signature (sets ``certifiedBy``/``certifiedAt``).
        """
        if not approver:
            raise GateError("certify requires a human approver (certifiedBy)")
        manifest = self.get(sid)
        if self._stage(manifest) != Stage.REGISTERED:
            raise GateError(f"certify requires stage registered, got '{manifest['lifecycle']['stage']}'")

        validate_manifest(manifest)  # schema still valid
        scoring = manifest.get("scoring", {})
        if "determinism" not in scoring or "risk" not in scoring:
            raise GateError("certify requires determinism and risk to be scored")

        # Duplicate-capability scan against already-published skills.
        dupes = set(capability_tags(manifest)) & set(self._published_tags(exclude=sid))
        if dupes:
            raise GateError(
                "duplicate-capability scan failed; tags already provided by a "
                f"published skill: {sorted(dupes)}"
            )

        # Dependency refs must resolve to a known skill id or a known capability tag.
        unresolved = self._unresolved_dependencies(manifest)
        if unresolved:
            raise GateError(f"unresolved dependency refs: {sorted(unresolved)}")

        manifest["lifecycle"]["stage"] = Stage.CERTIFIED.value
        manifest["lifecycle"]["certifiedBy"] = approver
        manifest["lifecycle"]["certifiedAt"] = _utcnow_iso()
        self._store.put(manifest)
        return manifest

    def _unresolved_dependencies(self, manifest: Manifest) -> List[str]:
        known_ids = {skill_id(m) for m in self._store.all()}
        known_tags = {
            tag for m in self._store.all() for tag in capability_tags(m)
        }
        unresolved = []
        for dep in manifest.get("dependencies", []):
            if dep.get("optional"):
                continue
            ref = dep["ref"]
            if ref not in known_ids and ref not in known_tags:
                unresolved.append(ref)
        return unresolved

    # ----- Gate 3: Publish -----------------------------------------------
    def publish(self, sid: str) -> Manifest:
        """Promote a certified skill into the catalog (-> published)."""
        manifest = self.get(sid)
        if self._stage(manifest) != Stage.CERTIFIED:
            raise GateError(f"publish requires stage certified, got '{manifest['lifecycle']['stage']}'")
        mcp = manifest.get("mcp", {})
        if not mcp.get("namespace"):
            raise GateError("publish requires a verified mcp.namespace")
        manifest["lifecycle"]["stage"] = Stage.PUBLISHED.value
        self._store.put(manifest)
        return manifest

    # ----- Gate 6: Retire / version --------------------------------------
    def deprecate(self, sid: str, superseded_by: Optional[str] = None) -> Manifest:
        """Deprecate a published skill, optionally recording its successor."""
        manifest = self.get(sid)
        if self._stage(manifest) != Stage.PUBLISHED:
            raise GateError(f"deprecate requires stage published, got '{manifest['lifecycle']['stage']}'")
        manifest["lifecycle"]["stage"] = Stage.DEPRECATED.value
        if superseded_by:
            manifest["lifecycle"]["supersededBy"] = superseded_by
        self._store.put(manifest)
        return manifest

    def retire(self, sid: str) -> Manifest:
        """Retire a deprecated skill (terminal stage)."""
        manifest = self.get(sid)
        if self._stage(manifest) != Stage.DEPRECATED:
            raise GateError(f"retire requires stage deprecated, got '{manifest['lifecycle']['stage']}'")
        manifest["lifecycle"]["stage"] = Stage.RETIRED.value
        self._store.put(manifest)
        return manifest

    # ----- Query surface (Reasoning Layer) -------------------------------
    def find_by_capability(self, tag: str, *, published_only: bool = True) -> List[Manifest]:
        """Matchmaking query: skills providing ``tag`` (GET /capabilities?tag=)."""
        out = []
        for manifest in self._store.all():
            if published_only and self._stage(manifest) != Stage.PUBLISHED:
                continue
            if tag in capability_tags(manifest):
                out.append(manifest)
        return out

    def lineage(self, sid: str) -> Dict[str, object]:
        """Return the supersede chain + dependency refs for ``sid``."""
        manifest = self.get(sid)
        lifecycle = manifest.get("lifecycle", {})
        return {
            "id": sid,
            "supersedes": lifecycle.get("supersedes"),
            "supersededBy": lifecycle.get("supersededBy"),
            "dependsOn": [d["ref"] for d in manifest.get("dependencies", [])],
        }
