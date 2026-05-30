"""Small CLI to make the chassis prototype runnable.

Usage:
    python -m chassis.cli validate <manifest.json> [<manifest.json> ...]
    python -m chassis.cli walkthrough   # graduate the bundled example skills
    python -m chassis.cli intake <root> [--register] [--watch]
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

from .intake import build_manifest, discover
from .intake.watcher import IntakeWatcher
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


def _print_intake_result(manifest, report, *, register: bool, registry) -> None:
    counts = {k: len(v) for k, v in report.assets.items()}
    print(f"\n[{report.skill_id}]  <- {report.source_path}")
    print(f"  schema-valid: {report.schema_valid}")
    print(
        f"  assets: scripts={counts.get('scripts', 0)} "
        f"assets={counts.get('assets', 0)} knowledge={counts.get('knowledge', 0)}"
    )
    print(
        f"  determinism: {manifest['scoring']['determinism']}  "
        f"skillType: {manifest['identity'].get('skillType')}"
    )
    if report.inferred:
        print(f"  inferred: {', '.join(sorted(set(report.inferred)))}")
    if report.missing:
        print(f"  needs human: {', '.join(report.missing)}")
    if report.warnings:
        print(f"  warnings: {'; '.join(report.warnings)}")
    if report.errors:
        print(f"  schema errors: {'; '.join(report.errors)}")
    if register and registry is not None:
        if not report.schema_valid:
            print("  register: skipped (manifest not schema-valid)")
            return
        try:
            registered = registry.register(manifest)
            print(f"  register  -> {registered['lifecycle']['stage']}")
        except GateError as exc:
            print(f"  register  -- blocked: {exc}")


def _cmd_intake(root: str, *, register: bool, watch: bool, interval: float) -> int:
    if not os.path.isdir(root):
        print(f"INVALID  {root}: not a directory")
        return 1

    registry = Registry() if register else None

    def handle(source) -> None:
        manifest, report = build_manifest(source)
        _print_intake_result(manifest, report, register=register, registry=registry)

    if watch:
        print(f"== Watching {root} for skill changes (Ctrl-C to stop) ==")
        watcher = IntakeWatcher()
        try:
            watcher.watch(root, handle, interval=interval)
        except KeyboardInterrupt:  # pragma: no cover - interactive only
            print("\nstopped.")
        return 0

    sources = discover(root)
    print(f"== Intake: discovered {len(sources)} skill folder(s) under {root} ==")
    for source in sources:
        handle(source)
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chassis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate manifests against the schema")
    p_validate.add_argument("paths", nargs="+")

    sub.add_parser("walkthrough", help="run the bundled six-gate walkthrough")

    p_intake = sub.add_parser(
        "intake", help="scan a tree of SKILL.md folders into draft manifests"
    )
    p_intake.add_argument("root", help="root directory to scan for SKILL.md folders")
    p_intake.add_argument(
        "--register",
        action="store_true",
        help="register schema-valid drafts into an in-memory registry (Gate 1)",
    )
    p_intake.add_argument(
        "--watch",
        action="store_true",
        help="poll the tree and re-emit when a skill or its files change",
    )
    p_intake.add_argument(
        "--interval", type=float, default=1.0, help="watch poll interval in seconds"
    )

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.paths)
    if args.command == "walkthrough":
        return _cmd_walkthrough()
    if args.command == "intake":
        return _cmd_intake(
            args.root, register=args.register, watch=args.watch, interval=args.interval
        )
    parser.error("unknown command")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
