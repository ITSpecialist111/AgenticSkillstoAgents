"""Single-file MVP of the AgenticSkillstoAgents chassis.

Delivers the README's core thesis ("centralise capabilities + meaning + trust,
let agents compose from a governed registry") in one short module:

    * Manifests are JSON files on disk, validated against the canonical schema.
    * The registry is the contents of a directory; git history is the audit log.
    * "Meaning" is the capability tags carried in the manifest.
    * "Trust" is the GitHub PR review that flips lifecycle.stage to published.
    * Duplicate detection is a single pass over tags + IOPE signature.

Deliberately absent vs. ``prototype/chassis/``:
    - No 6-state ``Stage`` enum.        (We keep: draft | published | archived.)
    - No ``OntologyBuilderAgent``.       (Tags ARE the meaning; sufficient <50 skills.)
    - No 4-layer architecture.           (Storage + caller composition is enough.)
    - No GraphChange / SyncResult / auto-merge / review-queue contract surface.
    - No Mermaid emitter; ``list_capabilities()`` is enough to "see" the catalog.

See prototype-lite/README.md for the full cut-list and rationale.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple

from jsonschema import Draft202012Validator

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(_REPO_ROOT, "schemas", "skill-manifest.schema.json")
EXAMPLES_DIR = os.path.join(_REPO_ROOT, "examples")

PUBLISHED = "published"
DRAFT = "draft"
ARCHIVED = "archived"

Manifest = Dict[str, object]


class ManifestError(ValueError):
    pass


_validator: Draft202012Validator | None = None


def _get_validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
            _validator = Draft202012Validator(json.load(handle))
    return _validator


def load(path: str) -> Manifest:
    """Load + schema-validate a manifest file."""
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    errors = sorted(_get_validator().iter_errors(manifest), key=lambda e: list(e.path))
    if errors:
        joined = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors
        )
        raise ManifestError(f"{path}: {joined}")
    return manifest


def _id(m: Manifest) -> str:
    return m["identity"]["id"]


def _tags(m: Manifest) -> List[str]:
    return list(m.get("capability", {}).get("capabilityTags", []))


def _iope(m: Manifest) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    cap = m.get("capability", {})
    ins = tuple(sorted(p["type"] for p in cap.get("inputs", [])))
    outs = tuple(sorted(p["type"] for p in cap.get("outputs", [])))
    return ins, outs


@dataclass
class Registry:
    """A folder of manifests. That's it."""

    skills: Dict[str, Manifest]

    @classmethod
    def from_dir(cls, path: str = EXAMPLES_DIR) -> "Registry":
        skills = {}
        for f in sorted(glob.glob(os.path.join(path, "*.manifest.json"))):
            m = load(f)
            skills[_id(m)] = m
        return cls(skills=skills)

    def find_by_capability(self, tag: str, *, published_only: bool = True) -> List[Manifest]:
        return [
            m for m in self.skills.values()
            if tag in _tags(m)
            and (not published_only or m["lifecycle"]["stage"] == PUBLISHED)
        ]

    def list_capabilities(self) -> Dict[str, List[str]]:
        """capability tag -> [skill ids that provide it]."""
        out: Dict[str, List[str]] = {}
        for sid, m in self.skills.items():
            for tag in _tags(m):
                out.setdefault(tag, []).append(sid)
        return out

    def duplicates(self) -> List[Tuple[str, str, str]]:
        """Return (skill_a, skill_b, shared_tag) triples for same-IOPE pairs."""
        by_sig: Dict[Tuple, List[str]] = {}
        for sid, m in self.skills.items():
            by_sig.setdefault(_iope(m), []).append(sid)
        dupes: List[Tuple[str, str, str]] = []
        for sids in by_sig.values():
            for i in range(len(sids)):
                for j in range(i + 1, len(sids)):
                    shared = set(_tags(self.skills[sids[i]])) & set(_tags(self.skills[sids[j]]))
                    for tag in sorted(shared):
                        dupes.append((sids[i], sids[j], tag))
        return dupes

    def index(self) -> Dict[str, object]:
        """Catalog snapshot — the artifact a Stage 2 deployment would publish to
        blob storage so agents can discover skills without cloning the repo."""
        from datetime import datetime, timezone

        return {
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "schemaVersion": "skills.dev/v1",
            "skills": [
                {
                    "id": _id(m),
                    "name": m["identity"]["name"],
                    "version": m["identity"]["version"],
                    "stage": m["lifecycle"]["stage"],
                    "capabilityTags": _tags(m),
                    "mcp": m.get("mcp", {}),
                }
                for m in sorted(self.skills.values(), key=_id)
            ],
            "capabilityIndex": {
                tag: sorted(sids)
                for tag, sids in sorted(self.list_capabilities().items())
            },
        }

    def certify(self, sid: str, approver: str) -> Manifest:
        """The Certify gate. In production this is a GitHub PR approval that
        edits the manifest file; here we mutate in-memory for parity with the
        full prototype's API."""
        if not approver:
            raise ManifestError("certify requires an approver")
        m = self.skills[sid]
        # Duplicate scan against everything else already published.
        my_tags = set(_tags(m))
        for other_sid, other in self.skills.items():
            if other_sid == sid or other["lifecycle"]["stage"] != PUBLISHED:
                continue
            clash = my_tags & set(_tags(other))
            if clash:
                raise ManifestError(
                    f"duplicate capability tag(s) {sorted(clash)} already published by {other_sid}"
                )
        m["lifecycle"]["stage"] = PUBLISHED
        m["lifecycle"]["certifiedBy"] = approver
        return m


def _cli() -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list capabilities -> providers")
    sub.add_parser("dupes", help="report duplicate-capability candidates")
    s = sub.add_parser("find", help="find skills providing a capability tag")
    s.add_argument("tag")
    i = sub.add_parser("index", help="emit catalog JSON (Stage 2 artifact)")
    i.add_argument("--out", help="write JSON to this file (default: stdout)")
    args = p.parse_args()

    reg = Registry.from_dir()
    if args.cmd == "list":
        for tag, sids in sorted(reg.list_capabilities().items()):
            print(f"{tag:30s} {', '.join(sids)}")
    elif args.cmd == "dupes":
        for a, b, tag in reg.duplicates():
            print(f"DUPLICATE  {a}  <->  {b}  (tag: {tag})")
        if not reg.duplicates():
            print("no duplicates")
    elif args.cmd == "find":
        for m in reg.find_by_capability(args.tag):
            print(f"{_id(m):35s} {m['lifecycle']['stage']}")
    elif args.cmd == "index":
        payload = json.dumps(reg.index(), indent=2, sort_keys=False)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
            print(f"wrote {args.out}")
        else:
            print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
