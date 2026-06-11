"""Mapper - assemble a canonical draft manifest from a discovered skill folder.

This is the heart of intake. It reads a :class:`~chassis.intake.discovery.SkillSource`,
parses its ``SKILL.md`` frontmatter, classifies its sidecars, and assembles a
manifest that conforms to ``schemas/skill-manifest.schema.json``. Two firm rules
mirror the chassis's human-in-the-loop philosophy:

1. **Never invent IOPE.** Inputs/outputs are copied from frontmatter when present
   and left empty (and *flagged*) otherwise - the agent proposes structure, it
   does not fabricate it.
2. **Always draft.** ``lifecycle.stage`` is always ``draft``; graduation stays
   with the six gates.

Missing-but-required fields get conservative defaults plus a flag in the
:class:`IntakeReport`, so a maker sees exactly what to complete rather than
hitting a hard failure. Provenance (source path + per-file hashes) lives on the
report rather than the manifest, because the manifest schema forbids extra
properties.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..manifest import Manifest, validate_manifest
from .assets import AssetClassification, classify_assets
from .discovery import SkillSource
from .sanitize import scan_text
from .skillmd import SkillMd, parse_skill_md

API_VERSION = "skills.dev/v1"
DEFAULT_VERSION = "0.1.0"
DEFAULT_OWNER_HANDLE = "unknown"
DEFAULT_VISIBILITY = "private"

_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.\-]+)?$")
_ID_SEGMENT_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]*[a-z0-9])?$")
_TAG_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9]+)*$")


@dataclass
class IntakeReport:
    """What intake inferred, what it could not, and where it came from.

    The report is the transparency contract: ``inferred`` lists fields filled by
    heuristic, ``missing`` lists quality-critical fields a human must complete,
    ``schema_valid`` says whether the draft already passes the canonical schema,
    ``provenance`` records the source path + per-file SHA-256 for lineage, and
    ``security_flags`` records anything suspicious found while treating the
    ``SKILL.md`` as untrusted input (embedded HTML, invisible/bidi characters,
    prompt-injection phrases) for a human to review at the Certify gate.
    """

    skill_id: str
    source_path: str
    schema_valid: bool = False
    inferred: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    assets: Dict[str, List[str]] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    security_flags: List[str] = field(default_factory=list)


def _slug_segment(value: str) -> str:
    """Lowercase ``value`` into a schema-legal id segment, or '' if impossible."""
    slug = re.sub(r"[^a-z0-9.\-]+", "-", value.strip().lower()).strip("-.")
    return slug if _ID_SEGMENT_RE.match(slug) else ""


def _derive_id(source: SkillSource, frontmatter: Dict[str, Any]) -> str:
    """Return the skill id from frontmatter, else derive ``namespace/name``."""
    fm_id = frontmatter.get("id")
    if isinstance(fm_id, str) and fm_id:
        return fm_id
    name_seg = _slug_segment(os.path.basename(source.skill_dir)) or "skill"
    parent = os.path.basename(os.path.dirname(source.skill_dir))
    ns_seg = _slug_segment(parent) or "intake"
    return f"{ns_seg}/{name_seg}"


def _derive_tag(skill_id: str) -> str:
    """Derive a single capability tag from a skill id's name segment."""
    name = skill_id.split("/")[-1]
    tag = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")
    return tag if _TAG_RE.match(tag) else "intake.uncategorized"


def _normalise_owner(raw: Any, report: IntakeReport) -> Dict[str, Any]:
    """Coerce a frontmatter ``owner`` (string or mapping) into a manifest owner."""
    if isinstance(raw, str) and raw.strip():
        return {"handle": raw.strip()}
    if isinstance(raw, dict) and raw.get("handle"):
        owner = {"handle": str(raw["handle"])}
        if raw.get("team"):
            owner["team"] = str(raw["team"])
        if raw.get("contact"):
            owner["contact"] = str(raw["contact"])
        return owner
    report.inferred.append("identity.owner.handle")
    report.missing.append("identity.owner")
    return {"handle": DEFAULT_OWNER_HANDLE}


def _coerce_params(raw: Any) -> List[Dict[str, Any]]:
    """Copy IOPE parameter dicts from frontmatter, keeping only legal fields."""
    params: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return params
    for item in raw:
        if not isinstance(item, dict) or "name" not in item or "type" not in item:
            continue
        param: Dict[str, Any] = {"name": str(item["name"]), "type": str(item["type"])}
        if "required" in item:
            param["required"] = bool(item["required"])
        if item.get("description"):
            param["description"] = str(item["description"])
        params.append(param)
    return params


def _string_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _infer_scoring(assets: AssetClassification, report: IntakeReport) -> Dict[str, Any]:
    """Heuristic determinism/risk from the asset mix (always human-overridable)."""
    if assets.has_scripts:
        determinism = "high"
        rationale = "Backed by deterministic scripts; inferred by intake (verify at Certify)."
    elif assets.knowledge and not assets.assets:
        determinism = "low"
        rationale = "Knowledge/prose only, no deterministic scripts; inferred by intake."
    else:
        determinism = "medium"
        rationale = "Mixed assets without scripts; inferred by intake."
    report.inferred.append("scoring.determinism")
    report.inferred.append("scoring.risk")
    # Risk cannot be inferred safely from files - default conservative + flag.
    report.missing.append("scoring.risk")
    return {
        "determinism": determinism,
        "risk": "low",
        "reversible": True,
        "rationale": rationale,
    }


def _infer_skill_type(assets: AssetClassification) -> str:
    return "deterministic-tool" if assets.has_scripts else "anthropic-agent-skill"


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_provenance(source: SkillSource) -> Dict[str, Any]:
    files: Dict[str, str] = {}
    for path in [source.skill_md, *source.sidecars]:
        rel = os.path.relpath(path, source.skill_dir).replace(os.sep, "/")
        files[rel] = _hash_file(path)
    return {"sourceDir": source.skill_dir, "skillMd": source.skill_md, "files": files}


def build_manifest(source: SkillSource) -> tuple[Manifest, IntakeReport]:
    """Assemble a draft manifest + :class:`IntakeReport` from a skill folder.

    The returned manifest is validated against the canonical schema; validation
    errors are captured on the report (``schema_valid`` / ``errors``) rather than
    raised, so callers can surface them to a human without crashing the scan.
    """
    with open(source.skill_md, "r", encoding="utf-8") as handle:
        raw_skill_md = handle.read()
    skill_md: SkillMd = parse_skill_md(raw_skill_md)
    frontmatter = skill_md.frontmatter
    assets = classify_assets(
        [os.path.relpath(p, source.skill_dir).replace(os.sep, "/") for p in source.sidecars]
    )

    skill_id = _derive_id(source, frontmatter)
    report = IntakeReport(skill_id=skill_id, source_path=source.skill_dir)
    report.assets = assets.as_dict()
    report.provenance = _build_provenance(source)
    # Treat the SKILL.md (frontmatter + body) as untrusted input: flag, don't fix.
    report.security_flags = scan_text(raw_skill_md)

    if not frontmatter.get("id"):
        report.inferred.append("identity.id")

    # ----- identity -------------------------------------------------------
    name = frontmatter.get("name") or skill_md.first_heading() or skill_id.split("/")[-1]
    version = frontmatter.get("version")
    if not (isinstance(version, str) and _VERSION_RE.match(version)):
        if version is not None:
            report.warnings.append(f"version '{version}' is not semver; using {DEFAULT_VERSION}")
        version = DEFAULT_VERSION
        report.inferred.append("identity.version")

    identity: Dict[str, Any] = {
        "id": skill_id,
        "name": str(name),
        "version": version,
        "owner": _normalise_owner(frontmatter.get("owner"), report),
        "skillType": _infer_skill_type(assets),
    }
    report.inferred.append("identity.skillType")
    description = frontmatter.get("description")
    if description:
        identity["description"] = str(description)
    tags = _string_list(frontmatter.get("tags"))
    if tags:
        identity["tags"] = sorted(set(tags))

    # ----- capability (IOPE) ---------------------------------------------
    summary = (
        frontmatter.get("summary")
        or frontmatter.get("description")
        or skill_md.first_heading()
        or f"Capability provided by {identity['name']}"
    )
    capability_tags = [t for t in _string_list(frontmatter.get("capabilityTags")) if _TAG_RE.match(t)]
    if not capability_tags:
        capability_tags = [_derive_tag(skill_id)]
        report.inferred.append("capability.capabilityTags")

    inputs = _coerce_params(frontmatter.get("inputs"))
    outputs = _coerce_params(frontmatter.get("outputs"))
    if not inputs and not outputs:
        report.missing.append("capability.inputs/outputs (IOPE not declared in SKILL.md)")

    capability: Dict[str, Any] = {
        "summary": str(summary)[:256],
        "capabilityTags": capability_tags,
        "inputs": inputs,
        "outputs": outputs,
    }
    preconditions = _string_list(frontmatter.get("preconditions"))
    if preconditions:
        capability["preconditions"] = preconditions
    effects = _string_list(frontmatter.get("effects"))
    if effects:
        capability["effects"] = effects

    # ----- scoring --------------------------------------------------------
    scoring = _infer_scoring(assets, report)
    fm_scoring = frontmatter.get("scoring")
    if isinstance(fm_scoring, dict):
        for key in ("determinism", "risk", "reversible", "rationale"):
            if key in fm_scoring:
                scoring[key] = fm_scoring[key]
                _discard(report.inferred, f"scoring.{key}")
                _discard(report.missing, f"scoring.{key}")

    # ----- governance -----------------------------------------------------
    governance: Dict[str, Any] = {"visibility": DEFAULT_VISIBILITY}
    fm_gov = frontmatter.get("governance")
    if isinstance(fm_gov, dict):
        for key in ("visibility", "rbac", "dataClassification", "cost", "audit"):
            if key in fm_gov:
                governance[key] = fm_gov[key]
    if governance["visibility"] == DEFAULT_VISIBILITY and not (
        isinstance(fm_gov, dict) and "visibility" in fm_gov
    ):
        report.inferred.append("governance.visibility")

    # ----- lifecycle (always draft) --------------------------------------
    lifecycle = {"stage": "draft"}

    manifest: Manifest = {
        "apiVersion": API_VERSION,
        "kind": "Skill",
        "identity": identity,
        "capability": capability,
        "scoring": scoring,
        "governance": governance,
        "lifecycle": lifecycle,
    }

    # ----- optional dependencies / mcp passthrough -----------------------
    dependencies = _coerce_dependencies(frontmatter.get("dependencies"))
    if dependencies:
        manifest["dependencies"] = dependencies
    fm_mcp = frontmatter.get("mcp")
    if isinstance(fm_mcp, dict):
        mcp = {k: v for k, v in fm_mcp.items() if k in ("server", "toolName", "namespace", "transport")}
        if mcp:
            manifest["mcp"] = mcp

    # ----- validate (capture, don't raise) -------------------------------
    try:
        validate_manifest(manifest)
        report.schema_valid = True
    except Exception as exc:  # noqa: BLE001 - intentionally captured for the report
        report.schema_valid = False
        report.errors.append(str(exc))

    return manifest, report


def _coerce_dependencies(raw: Any) -> List[Dict[str, Any]]:
    deps: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return deps
    for item in raw:
        if isinstance(item, str) and item.strip():
            deps.append({"ref": item.strip()})
        elif isinstance(item, dict) and item.get("ref"):
            dep: Dict[str, Any] = {"ref": str(item["ref"])}
            if item.get("versionRange"):
                dep["versionRange"] = str(item["versionRange"])
            if "optional" in item:
                dep["optional"] = bool(item["optional"])
            deps.append(dep)
    return deps


def _discard(items: List[str], value: str) -> None:
    while value in items:
        items.remove(value)
