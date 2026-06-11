# Chassis prototype

An executable, dependency-light reference implementation of the graduation
**chassis** described in this repo's docs. It exists to make the specification
*runnable and testable* — it is a heuristic, in-memory reference, not a
production registry.

It maps 1:1 onto the three parts of the construct:

| Part | Spec | Module |
|---|---|---|
| **A — Manifest** | [`schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json), [`docs/technical-spec.md`](../docs/technical-spec.md) | [`chassis/manifest.py`](chassis/manifest.py) — load + JSON-Schema validation + IOPE signature |
| **B — Pipeline** | [`docs/architecture.md`](../docs/architecture.md) (six gates) | [`chassis/registry.py`](chassis/registry.py) — registry + state machine with gate exit checks |
| **C — Ontology Builder Agent** | [`docs/ontology-builder-agent.md`](../docs/ontology-builder-agent.md) | [`chassis/ontology.py`](chassis/ontology.py) — `sync_meaning(manifests, ontology)` |
| **Intake (on-ramp)** | [`docs/intake.md`](../docs/intake.md) | [`chassis/intake/`](chassis/intake) — `SKILL.md` folders → draft manifests + watcher |

It is packaged as an **installable product** — a Skill Registry & Graduation
service with a CLI, an optional HTTP/MCP API, and durable storage — without
changing those contracts. The productization modules sit *behind* Parts A–C:

| Concern | Module | What it adds |
|---|---|---|
| **Durable storage** | [`chassis/store.py`](chassis/store.py) | repository-pattern `SkillStore` with in-memory + SQLite backends |
| **HTTP service** | [`chassis/api.py`](chassis/api.py) | FastAPI app driving the six gates over the wire (optional `api` extra) |
| **MCP publish** | [`chassis/mcp.py`](chassis/mcp.py) | projects the published catalog into an MCP `tools/list` document |
| **Matchmaking** | [`chassis/matchmaking.py`](chassis/matchmaking.py) | Exact/Plug-in/Partial/Fail capability matching for the Composition layer |
| **Telemetry** | [`chassis/metrics.py`](chassis/metrics.py) | the roadmap's falsifiable program metrics, computed from registry state |
| **Phase 2 scorecard** | [`chassis/evaluation.py`](chassis/evaluation.py) | scores an agent run against the roadmap Phase 2 exit-gate targets vs the recorded baseline (`chassis evaluate`) |
| **Pipeline-as-CI** | [`chassis/gatecheck.py`](chassis/gatecheck.py) | headless Register/Certify checks for `chassis gate` and GitHub Actions |

## Install

```bash
cd prototype
pip install -e .            # core CLI (validate / register / ... / walkthrough)
pip install -e '.[api]'     # + the HTTP service (chassis serve)
pip install -e '.[dev]'     # + test/lint tooling
```

This installs a `chassis` console script (so `chassis ...` works anywhere) whose
package major version tracks the manifest `apiVersion` (`skills.dev/v1`). The
canonical schema is bundled as package data, so validation works even when the
package is installed away from this repo. The legacy
`pip install -r requirements.txt` still works for the dependency-light core.

## Run the CLI

```bash
# Validate manifests against the canonical schema (Register gate)
chassis validate ../examples/*.manifest.json

# Graduate one skill through the gates against a PERSISTENT registry.
# --db accepts `memory` (default), `sqlite:///path.db`, or a bare file path.
chassis register ../examples/invoice-extract.manifest.json --db sqlite:///registry.db
chassis certify finance/invoice-extract --approver coe.reviewer --db sqlite:///registry.db
chassis publish finance/invoice-extract --db sqlite:///registry.db
chassis list --db sqlite:///registry.db          # state survives between invocations

# Headless gate checks (the machine-checkable half of Certify) for CI:
chassis gate ../examples/*.manifest.json

# Program telemetry snapshot (the roadmap's falsifiable metrics):
chassis metrics --db sqlite:///registry.db

# Score the Phase 2 exit gate (the falsifiable bet) over a labelled corpus:
#   acceptance, duplicate precision/recall, maintenance effort vs the recorded
#   Phase 1 baseline, and ontology drift. Exit code is non-zero if the gate is
#   not met. --labels supplies the ground-truth duplicate pairs.
chassis evaluate ../examples/evaluation --labels ../examples/evaluation/labels.json

# Graduate the bundled example skills through all six gates + meaning-sync
chassis walkthrough

# Intake: turn a tree of real SKILL.md folders into draft manifests
# (add --register to admit schema-valid drafts at the Register gate,
#  or --watch to re-emit when a skill or its sidecar files change)
chassis intake ../prototype/tests/fixtures/skills
```

## Run the HTTP / MCP service

```bash
pip install -e '.[api]'
chassis serve --db sqlite:///registry.db        # http://127.0.0.1:8000

# Drive the six gates over the wire:
curl -X POST localhost:8000/skills -d @draft.manifest.json -H 'content-type: application/json'
curl -X POST localhost:8000/skills/finance/invoice-extract/certify -d '{"approver":"coe.reviewer"}'
curl -X POST localhost:8000/skills/finance/invoice-extract/publish

# Discover published skills the MCP way, match a capability, read metrics:
curl localhost:8000/mcp/tools
curl 'localhost:8000/capabilities?tag=invoice.extract'
curl localhost:8000/metrics
```

## Run it as a container

```bash
cd prototype
docker compose up --build          # service on :8000, registry persisted to a volume
```

Configuration is env-driven (`CHASSIS_HOST`, `CHASSIS_PORT`, `CHASSIS_DB`,
`CHASSIS_ONTOLOGY_CONFIDENCE`). Point `CHASSIS_DB` at a hosted backend later to
swap SQLite for OneLake/Fabric IQ without touching the gate logic.

## Run the smoke tests

```bash
cd prototype
python -m pytest -q
```

The smoke tests cover manifest validation, the six-gate state machine (including
the duplicate-capability scan and dependency resolution at the Certify gate),
the Ontology Builder Agent contract (entity/relationship proposals,
duplicate + determinism/risk conflict flags, and the human-review queue), and the
intake layer (discovery, `SKILL.md` parsing, asset classification, the
untrusted-input security scan, draft-manifest mapping, the content-hash watcher,
and an end-to-end intake → six-gate path).

## Intake: from real skill folders to draft manifests

Real skills arrive as a folder — an Anthropic-style `SKILL.md` plus the
deterministic scripts/assets/knowledge beside it — not as hand-authored JSON.
The [`chassis/intake/`](chassis/intake) package is the on-ramp **upstream of the
Register gate**: it discovers those folders, parses the frontmatter, classifies
the sidecars, and emits a **draft** manifest plus an `IntakeReport` of what was
inferred vs. what a human must still complete. It never invents IOPE and never
auto-publishes. See [`docs/intake.md`](../docs/intake.md) for the source format,
the full mapping table, and the watch (monitoring) layer.

## Ontology Builder Agent contract

```
sync_meaning(manifests, ontology) -> SyncResult(
    proposals,     # GraphChange[]  (entities + relationships)
    confidence,    # float[]        (per-proposal, 0..1)
    flags,         # {duplicates, conflicts}
    review_queue,  # GraphChange[]  (held for human approval)
)
```

`DUPLICATE_OF` proposals, determinism/risk conflicts, `restricted`-scope changes,
and any proposal below the confidence threshold are routed to the review queue
— everything else is available via `result.auto_merge`. The implementation is a
deterministic heuristic and is freely replaceable (LLM/hybrid) because the
chassis depends on this contract, not the implementation.
