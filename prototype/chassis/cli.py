"""Small CLI to make the chassis prototype runnable.

Usage:
    python -m chassis.cli validate <manifest.json> [<manifest.json> ...]
    python -m chassis.cli walkthrough   # graduate the bundled example skills
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .manifest import ManifestError, load_manifest, skill_id
from .ontology import OntologyBuilderAgent
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


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chassis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate manifests against the schema")
    p_validate.add_argument("paths", nargs="+")

    sub.add_parser("walkthrough", help="run the bundled six-gate walkthrough")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.paths)
    if args.command == "walkthrough":
        return _cmd_walkthrough()
    parser.error("unknown command")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
