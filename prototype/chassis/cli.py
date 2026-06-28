"""Small CLI to make the chassis prototype runnable.

Usage:
    python -m chassis.cli validate <manifest.json> [<manifest.json> ...]
    python -m chassis.cli walkthrough   # graduate the bundled example skills
    python -m chassis.cli dump [--out DIR]  # write registry + ontology + mermaid
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable, List

from .manifest import ManifestError, capability_tags, iope_signature, load_manifest, skill_id
from .ontology import Ontology, OntologyBuilderAgent
from .registry import GateError, Registry

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLES_DIR = os.path.join(_REPO_ROOT, "examples")


def _cmd_validate(paths: List[str]) -> int:
    rc = 0
    for path in paths:
        try:
            manifest = load_manifest(path)
        except ManifestError as exc:
            print(f"INVALID  {path}: {exc}")
            rc = 1
        else:
            print(f"valid    {path}  ({skill_id(manifest)})")
    return rc


def _cmd_walkthrough() -> int:
    registry = Registry()
    order = ["invoice-extract", "po-match", "ap-intake"]
    print("== Graduating bundled example skills through the six gates ==")
    for name in order:
        path = os.path.join(EXAMPLES_DIR, f"{name}.manifest.json")
        manifest = load_manifest(path)
        # Reset to draft so we can demonstrate every gate from the start.
        manifest["lifecycle"] = {"stage": "draft"}
        sid = skill_id(manifest)
        registered = registry.register(manifest)
        print(f"\n[{sid}]")
        print(f"  Register  -> {registered['lifecycle']['stage']}")
        try:
            certified = registry.certify(sid, approver="coe.reviewer")
            print(f"  Certify   -> {certified['lifecycle']['stage']} (by {certified['lifecycle']['certifiedBy']})")
            published = registry.publish(sid)
            print(f"  Publish   -> {published['lifecycle']['stage']}")
        except GateError as exc:
            print(f"  blocked   -- {exc}")

    print("\n== Meaning-sync: Ontology Builder Agent proposals ==")
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning(registry.all())
    print(f"  proposals: {len(result.proposals)}  auto-merge: {len(result.auto_merge)}  review: {len(result.review_queue)}")
    print(f"  duplicate flags: {result.flags['duplicates']}")
    print(f"  conflict flags:  {result.flags['conflicts']}")
    return 0


_NODE_STYLES = {
    "Skill": ("S", "fill:#1f6feb,stroke:#0b3d91,color:#fff"),
    "Capability": ("C", "fill:#2da44e,stroke:#0f5323,color:#fff"),
    "DataType": ("D", "fill:#bf8700,stroke:#7d5700,color:#fff"),
    "Condition": ("K", "fill:#8250df,stroke:#421a87,color:#fff"),
}


def _mermaid_id(prefix: str, key: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in key)
    return f"{prefix}_{safe}"


def _build_walkthrough() -> tuple[Registry, Ontology, "object"]:
    """Run the bundled walkthrough and return (registry, ontology, sync_result)."""
    registry = Registry()
    for name in ("invoice-extract", "po-match", "ap-intake"):
        path = os.path.join(EXAMPLES_DIR, f"{name}.manifest.json")
        manifest = load_manifest(path)
        manifest["lifecycle"] = {"stage": "draft"}
        sid = skill_id(manifest)
        registry.register(manifest)
        try:
            registry.certify(sid, approver="coe.reviewer")
            registry.publish(sid)
        except GateError:
            pass

    agent = OntologyBuilderAgent()
    result = agent.sync_meaning(registry.all())
    ontology = Ontology()
    for change in result.auto_merge:
        ontology.apply(change)
    return registry, ontology, result


def _registry_json(registry: Registry) -> dict:
    skills = []
    for manifest in registry.all():
        sid = skill_id(manifest)
        skills.append(
            {
                "id": sid,
                "stage": manifest["lifecycle"]["stage"],
                "certifiedBy": manifest["lifecycle"].get("certifiedBy"),
                "capabilityTags": capability_tags(manifest),
                "iopeSignature": list(iope_signature(manifest)),
                "scoring": manifest.get("scoring", {}),
                "dependencies": [d["ref"] for d in manifest.get("dependencies", [])],
            }
        )
    return {"skills": skills}


def _ontology_json(ontology: Ontology, result) -> dict:
    nodes = [{"type": t, "key": k} for (t, k) in sorted(ontology.nodes)]
    edges = [
        {"subject": s, "verb": v, "object": o} for (s, v, o) in sorted(ontology.edges)
    ]
    review = [
        {"kind": c.kind, "subject": c.subject, "predicate": c.predicate, "object": c.obj, "reason": c.reason}
        for c in result.review_queue
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "flags": result.flags,
        "reviewQueue": review,
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "proposals": len(result.proposals),
            "autoMerge": len(result.auto_merge),
            "review": len(result.review_queue),
        },
    }


def _ontology_mermaid(ontology: Ontology) -> str:
    lines = ["graph LR"]
    # Nodes grouped by type for legibility.
    for ntype in ("Skill", "Capability", "DataType", "Condition"):
        keys = sorted(k for (t, k) in ontology.nodes if t == ntype)
        if not keys:
            continue
        prefix, style = _NODE_STYLES[ntype]
        lines.append(f"  subgraph {ntype}s")
        for key in keys:
            nid = _mermaid_id(prefix, key)
            lines.append(f'    {nid}["{key}"]')
        lines.append("  end")
    # Edges.
    for subj, verb, obj in sorted(ontology.edges):
        # Subject is always a Skill; object type lookup.
        obj_type = next((t for (t, k) in ontology.nodes if k == obj), "Skill")
        s_prefix = "S"
        o_prefix = _NODE_STYLES.get(obj_type, ("S", ""))[0]
        lines.append(
            f"  {_mermaid_id(s_prefix, subj)} -- {verb} --> {_mermaid_id(o_prefix, obj)}"
        )
    # Class styling.
    for ntype, (prefix, style) in _NODE_STYLES.items():
        keys = [k for (t, k) in ontology.nodes if t == ntype]
        if not keys:
            continue
        ids = ",".join(_mermaid_id(prefix, k) for k in keys)
        lines.append(f"  classDef {ntype.lower()} {style}")
        lines.append(f"  class {ids} {ntype.lower()}")
    return "\n".join(lines) + "\n"


def _cmd_dump(out_dir: str) -> int:
    registry, ontology, result = _build_walkthrough()
    os.makedirs(out_dir, exist_ok=True)
    reg_path = os.path.join(out_dir, "registry.json")
    ont_path = os.path.join(out_dir, "ontology.json")
    mmd_path = os.path.join(out_dir, "ontology.mmd")
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(_registry_json(registry), f, indent=2)
    with open(ont_path, "w", encoding="utf-8") as f:
        json.dump(_ontology_json(ontology, result), f, indent=2)
    with open(mmd_path, "w", encoding="utf-8") as f:
        f.write(_ontology_mermaid(ontology))
    print(f"wrote {reg_path}")
    print(f"wrote {ont_path}")
    print(f"wrote {mmd_path}")
    print(
        "tip: paste ontology.mmd into https://mermaid.live, or render via "
        "`npx -y @mermaid-js/mermaid-cli -i out/ontology.mmd -o out/ontology.svg`"
    )
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chassis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate manifests against the schema")
    p_validate.add_argument("paths", nargs="+")

    sub.add_parser("walkthrough", help="run the bundled six-gate walkthrough")

    p_dump = sub.add_parser("dump", help="emit registry + ontology JSON and a Mermaid graph")
    p_dump.add_argument("--out", default=os.path.join(os.getcwd(), "out"))

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.paths)
    if args.command == "walkthrough":
        return _cmd_walkthrough()
    if args.command == "dump":
        return _cmd_dump(args.out)
    parser.error("unknown command")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
