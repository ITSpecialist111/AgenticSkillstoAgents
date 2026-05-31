"""``chassis`` - a runnable CLI over the graduation chassis.

Installed as a console script (``chassis ...``); also runnable as
``python -m chassis.cli``. Commands map 1:1 to the chassis verbs and, where they
mutate state, persist it via ``--db`` so the registry survives between
invocations (the difference between a demo and a product):

    chassis validate <manifest.json> ...           # schema check (Register gate)
    chassis register <manifest.json> [--db DSN]     # Gate 1
    chassis certify <id> --approver WHO [--db DSN]  # Gate 2
    chassis publish <id> [--db DSN]                 # Gate 3
    chassis list [--db DSN]                         # show the catalog
    chassis gate <manifest.json> ...                # headless gate checks (CI)
    chassis metrics [--db DSN]                      # program telemetry snapshot
    chassis walkthrough                             # bundled six-gate demo
    chassis intake <root> [--register] [--watch]    # SKILL.md folders -> drafts
    chassis serve [--host H --port P] [--db DSN]    # run the HTTP API

``--db`` accepts ``memory`` (default), a ``sqlite:///path.db`` URL, or a bare
file path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from .gatecheck import check_manifests, summarize
from .intake import build_manifest, discover
from .intake.watcher import IntakeWatcher
from .manifest import ManifestError, load_manifest, skill_id
from .metrics import snapshot
from .ontology import OntologyBuilderAgent
from .registry import GateError, Registry
from .store import open_store

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLES_DIR = os.path.join(_REPO_ROOT, "examples")


def _registry(db: Optional[str]) -> Registry:
    return Registry(open_store(db))


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


def _cmd_register(path: str, db: Optional[str]) -> int:
    registry = _registry(db)
    try:
        manifest = load_manifest(path)
        registered = registry.register(manifest)
    except ManifestError as exc:
        print(f"INVALID  {path}: {exc}")
        return 1
    except GateError as exc:
        print(f"blocked  {path}: {exc}")
        return 1
    print(f"registered {skill_id(registered)} -> {registered['lifecycle']['stage']}")
    return 0


def _cmd_certify(sid: str, approver: str, db: Optional[str]) -> int:
    registry = _registry(db)
    try:
        certified = registry.certify(sid, approver=approver)
    except KeyError as exc:
        print(f"unknown  {exc}")
        return 1
    except GateError as exc:
        print(f"blocked  {sid}: {exc}")
        return 1
    print(f"certified {sid} -> {certified['lifecycle']['stage']} (by {approver})")
    return 0


def _cmd_publish(sid: str, db: Optional[str]) -> int:
    registry = _registry(db)
    try:
        published = registry.publish(sid)
    except KeyError as exc:
        print(f"unknown  {exc}")
        return 1
    except GateError as exc:
        print(f"blocked  {sid}: {exc}")
        return 1
    print(f"published {sid} -> {published['lifecycle']['stage']}")
    return 0


def _cmd_list(db: Optional[str]) -> int:
    registry = _registry(db)
    skills = sorted(registry.all(), key=skill_id)
    if not skills:
        print("(registry is empty)")
        return 0
    for manifest in skills:
        print(f"{manifest['lifecycle']['stage']:<11} {skill_id(manifest)}")
    return 0


def _cmd_gate(paths: List[str]) -> int:
    loaded = []
    for path in paths:
        try:
            loaded.append((path, load_manifest(path, validate=False)))
        except ManifestError as exc:
            print(f"INVALID  {path}: {exc}")
            return 1
    checks = check_manifests(loaded)
    report = summarize(checks)
    if report:
        print(report)
    failed = sum(1 for c in checks if not c.passed)
    print(f"\n{len(checks) - failed}/{len(checks)} manifests passed the gate checks")
    return 1 if failed else 0


def _cmd_metrics(db: Optional[str]) -> int:
    registry = _registry(db)
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning(registry.all())
    print(json.dumps(snapshot(registry.all(), result), indent=2, sort_keys=True))
    return 0


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
    if report.security_flags:
        print(f"  security: {'; '.join(report.security_flags)}")
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


def _cmd_intake(
    root: str, *, register: bool, watch: bool, interval: float, db: Optional[str]
) -> int:
    if not os.path.isdir(root):
        print(f"INVALID  {root}: not a directory")
        return 1

    registry = _registry(db) if register else None

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


def _cmd_serve(host: str, port: int, db: Optional[str]) -> int:  # pragma: no cover - server
    try:
        import uvicorn
    except Exception as exc:  # noqa: BLE001
        print(
            "uvicorn is not installed. Install the API extra:\n"
            "    pip install 'chassis[api]'\n"
            f"(import error: {exc})"
        )
        return 1
    from .api import create_app

    app = create_app(_registry(db))
    uvicorn.run(app, host=host, port=port)
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chassis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate manifests against the schema")
    p_validate.add_argument("paths", nargs="+")

    p_register = sub.add_parser("register", help="register a manifest (Gate 1)")
    p_register.add_argument("path")
    p_register.add_argument("--db", default=None, help="store DSN (default: in-memory)")

    p_certify = sub.add_parser("certify", help="certify a registered skill (Gate 2)")
    p_certify.add_argument("id")
    p_certify.add_argument("--approver", required=True, help="human approver handle")
    p_certify.add_argument("--db", default=None, help="store DSN (default: in-memory)")

    p_publish = sub.add_parser("publish", help="publish a certified skill (Gate 3)")
    p_publish.add_argument("id")
    p_publish.add_argument("--db", default=None, help="store DSN (default: in-memory)")

    p_list = sub.add_parser("list", help="list the registry catalog")
    p_list.add_argument("--db", default=None, help="store DSN (default: in-memory)")

    p_gate = sub.add_parser("gate", help="run headless gate checks over manifests (CI)")
    p_gate.add_argument("paths", nargs="+")

    p_metrics = sub.add_parser("metrics", help="print a program telemetry snapshot")
    p_metrics.add_argument("--db", default=None, help="store DSN (default: in-memory)")

    sub.add_parser("walkthrough", help="run the bundled six-gate walkthrough")

    p_intake = sub.add_parser(
        "intake", help="scan a tree of SKILL.md folders into draft manifests"
    )
    p_intake.add_argument("root", help="root directory to scan for SKILL.md folders")
    p_intake.add_argument(
        "--register",
        action="store_true",
        help="register schema-valid drafts into the registry (Gate 1)",
    )
    p_intake.add_argument(
        "--watch",
        action="store_true",
        help="poll the tree and re-emit when a skill or its files change",
    )
    p_intake.add_argument(
        "--interval", type=float, default=1.0, help="watch poll interval in seconds"
    )
    p_intake.add_argument("--db", default=None, help="store DSN for --register")

    p_serve = sub.add_parser("serve", help="run the HTTP API (needs the api extra)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--db", default=None, help="store DSN (default: in-memory)")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args.paths)
    if args.command == "register":
        return _cmd_register(args.path, args.db)
    if args.command == "certify":
        return _cmd_certify(args.id, args.approver, args.db)
    if args.command == "publish":
        return _cmd_publish(args.id, args.db)
    if args.command == "list":
        return _cmd_list(args.db)
    if args.command == "gate":
        return _cmd_gate(args.paths)
    if args.command == "metrics":
        return _cmd_metrics(args.db)
    if args.command == "walkthrough":
        return _cmd_walkthrough()
    if args.command == "intake":
        return _cmd_intake(
            args.root,
            register=args.register,
            watch=args.watch,
            interval=args.interval,
            db=args.db,
        )
    if args.command == "serve":  # pragma: no cover - server
        return _cmd_serve(args.host, args.port, args.db)
    parser.error("unknown command")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
