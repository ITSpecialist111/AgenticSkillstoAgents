"""Part A - the Skill Manifest: loading, schema validation, IOPE signatures.

A manifest is represented as a plain ``dict`` (the parsed JSON document). Thin
helpers wrap it so the rest of the prototype can talk in domain terms without a
heavyweight model layer.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from jsonschema import Draft202012Validator

# Repo layout: <repo>/prototype/chassis/manifest.py -> <repo>/schemas/...
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A copy of the canonical schema is bundled inside the package so the manifest
# loader works when ``chassis`` is pip-installed away from the repo tree. The
# packaged copy is kept byte-identical to ``schemas/skill-manifest.schema.json``
# (enforced by a contract test) so there is a single source of truth.
_PACKAGED_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "skill-manifest.schema.json")
_REPO_SCHEMA = os.path.join(_REPO_ROOT, "schemas", "skill-manifest.schema.json")


def _resolve_schema_path() -> str:
    """Locate the manifest schema in an import-clean, overridable way.

    Resolution order:

    1. ``CHASSIS_SCHEMA_PATH`` environment variable (explicit override).
    2. The copy packaged inside the installed ``chassis`` distribution.
    3. The canonical ``schemas/`` file in a source checkout (dev fallback).
    """
    override = os.environ.get("CHASSIS_SCHEMA_PATH")
    if override:
        return override
    if os.path.exists(_PACKAGED_SCHEMA):
        return _PACKAGED_SCHEMA
    return _REPO_SCHEMA


# Backwards-compatible module attribute (some callers/tests read it directly).
SCHEMA_PATH = _resolve_schema_path()

Manifest = Dict[str, Any]


class ManifestError(ValueError):
    """Raised when a manifest is malformed or fails schema validation."""


_validator: Draft202012Validator | None = None


def _get_validator() -> Draft202012Validator:
    """Return a cached validator built from the canonical schema."""
    global _validator
    if _validator is None:
        with open(_resolve_schema_path(), "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        Draft202012Validator.check_schema(schema)
        _validator = Draft202012Validator(schema)
    return _validator


def validate_manifest(manifest: Manifest) -> None:
    """Validate ``manifest`` against the canonical schema.

    Raises :class:`ManifestError` describing every violation if invalid.
    """
    errors = sorted(_get_validator().iter_errors(manifest), key=lambda e: list(e.path))
    if errors:
        joined = "; ".join(
            f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in errors
        )
        raise ManifestError(f"manifest is not schema-valid: {joined}")


def load_manifest(path: str, *, validate: bool = True) -> Manifest:
    """Load a manifest from ``path``; validate against the schema by default."""
    with open(path, "r", encoding="utf-8") as handle:
        try:
            manifest = json.load(handle)
        except json.JSONDecodeError as exc:  # pragma: no cover - trivial wrap
            raise ManifestError(f"{path}: invalid JSON: {exc}") from exc
    if validate:
        validate_manifest(manifest)
    return manifest


def skill_id(manifest: Manifest) -> str:
    """Return the immutable ``namespace/name`` id of a manifest."""
    return manifest["identity"]["id"]


def capability_tags(manifest: Manifest) -> List[str]:
    """Return the manifest's canonical capability tags (possibly empty)."""
    return list(manifest.get("capability", {}).get("capabilityTags", []))


def _param_types(params: List[Dict[str, Any]]) -> Tuple[str, ...]:
    """Return the sorted tuple of logical types from a list of IOPE params."""
    return tuple(sorted(p["type"] for p in params))


def iope_signature(manifest: Manifest) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Return the (inputs, outputs) type signature used for duplicate detection.

    Two skills with the same input-type set and output-type set are candidate
    duplicates (same IOPE signature) per the Ontology Builder Agent contract.
    """
    capability = manifest.get("capability", {})
    return (
        _param_types(capability.get("inputs", [])),
        _param_types(capability.get("outputs", [])),
    )
