"""Small CLI to make the chassis prototype runnable.

Usage:
    python -m chassis.cli validate <manifest.json> [<manifest.json> ...]
    python -m chassis.cli walkthrough   # graduate the bundled example skills
    python -m chassis.cli serve         # run minimal HTTP registry API
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .api import run_server
from .manifest import ManifestError, load_manifest, skill_id
from .ontology import OntologyBuilderAgent
from .registry import GateError, Registry
from .store import open_store

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


def _cmd_walkthrough(dsn: str | None = None) -> int:
    registry = Registry(open_store(dsn))
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

    p_walkthrough = sub.add_parser("walkthrough", help="run the bundled six-gate walkthrough")
    p_walkthrough.add_argument("--dsn", default="memory", help="store DSN (memory or sqlite:///abs/path.db)")

    p_serve = sub.add_parser("serve", help="run HTTP registry API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--dsn", default="memory", help="store DSN (memory or sqlite:///abs/path.db)")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.paths)
    if args.command == "walkthrough":
        return _cmd_walkthrough(args.dsn)
    if args.command == "serve":
        run_server(host=args.host, port=args.port, dsn=args.dsn)
        return 0
    parser.error("unknown command")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
