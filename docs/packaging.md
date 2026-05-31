# Packaging: from prototype to a working product

This document records how the executable chassis in [`prototype/`](../prototype)
is packaged into a deployable **Skill Registry & Graduation service** — and,
importantly, what deliberately stays unchanged.

## What "a working product" means here

The reference prototype proved the construct was *runnable*. Packaging turns it
into something an org can **install, run persistently, and call over the wire**:

1. **Installable** — a real Python distribution with a `chassis` console script.
2. **Persistent** — registry state survives restarts via a pluggable store.
3. **Serviceable** — an optional HTTP API (incl. an MCP-compatible catalog).
4. **Governable in CI** — the gate checks run on every manifest change.
5. **Deployable** — a container image + compose stack with env-driven config.
6. **Measurable** — the roadmap's falsifiable metrics are emitted as telemetry.

## What stays unchanged (the stable interfaces)

Productization swaps **implementations**, never the contracts the docs pin down:

- the **Manifest schema** ([`schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json)),
- the **six gates** (Register → Certify → Publish → Meaning-sync → Compose → Retire),
- the **Ontology Builder Agent contract** (`sync_meaning(...)`).

Every new module sits *behind* those seams. The registry now talks to a
`SkillStore` instead of a dict; the agent is still freely replaceable because
callers depend on its contract, not its heuristic body.

## The pieces

| Capability | Where | Notes |
|---|---|---|
| Packaging + entry point | [`prototype/pyproject.toml`](../prototype/pyproject.toml) | `agentic-chassis` dist, `chassis` script, `api`/`dev` extras. Major version tracks `apiVersion` `skills.dev/v1`. |
| Import-clean schema | [`prototype/chassis/data/`](../prototype/chassis/data) | the canonical schema is bundled as package data; a contract test keeps it byte-identical to `schemas/`. Override with `CHASSIS_SCHEMA_PATH`. |
| Durable storage | [`prototype/chassis/store.py`](../prototype/chassis/store.py) | `SkillStore` protocol + `InMemoryStore` + `SqliteStore`; `open_store(dsn)` routes `memory` / `sqlite:///path` / bare path. |
| HTTP service | [`prototype/chassis/api.py`](../prototype/chassis/api.py) | FastAPI app over an injected `Registry`. Optional `api` extra. |
| MCP publish | [`prototype/chassis/mcp.py`](../prototype/chassis/mcp.py) | `published_catalog()` → MCP `tools/list` with a JSON-Schema `inputSchema` derived from IOPE. |
| Matchmaking | [`prototype/chassis/matchmaking.py`](../prototype/chassis/matchmaking.py) | Exact/Plug-in/Partial/Fail grading, cost-ordered for the Composition layer. |
| Telemetry | [`prototype/chassis/metrics.py`](../prototype/chassis/metrics.py) | breadth/reuse/trust + meaning-layer health from registry + sync results. |
| Pipeline-as-CI | [`prototype/chassis/gatecheck.py`](../prototype/chassis/gatecheck.py) | headless Register/Certify checks; wired into `chassis gate` and a GitHub workflow. |
| Deployment | [`prototype/Dockerfile`](../prototype/Dockerfile), [`prototype/docker-compose.yml`](../prototype/docker-compose.yml) | env-driven (`CHASSIS_DB`, `CHASSIS_PORT`, …); registry on a mounted volume. |
| CI | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`.github/workflows/manifest-gate.yml`](../.github/workflows/manifest-gate.yml) | lint + tests + wheel build; manifest gate on PRs. |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `CHASSIS_DB` | in-memory | registry store DSN (`memory`, `sqlite:///path.db`, or a path) |
| `CHASSIS_HOST` / `CHASSIS_PORT` | `0.0.0.0` / `8000` | service bind address (container) |
| `CHASSIS_ONTOLOGY_CONFIDENCE` | `0.75` | Ontology Builder Agent auto-merge confidence threshold |
| `CHASSIS_SCHEMA_PATH` | bundled copy | override the manifest schema location |

## GitHub as the system-of-record

The product keeps GitHub as the system-of-record for manifests: skills live as
manifest files in a repo and **PR review is the Certify human gate**. The
`manifest-gate` workflow runs the machine-checkable half (schema validity,
determinism/risk scored, dependency resolution, duplicate-capability scan) so a
red check blocks merge before a human reviewer (the certifier of record) spends
time on it. The SQLite store is the *derived, queryable* projection of that
record — the seam reserved for OneLake/Fabric IQ at scale.

## Sequencing

This mirrors the roadmap's "smallest viable product first" order:

1. **MVP** — packaging + persistent SQLite registry + CLI (an installable, stateful tool).
2. **Service** — HTTP/MCP API + container.
3. **Pipeline-as-CI** — gate checks on every manifest PR.
4. **Measurement** — telemetry for the Phase 2 falsifiable metrics.
5. **Scale** — swap the store for OneLake/Fabric IQ; enforce the agent cap at composition.

Steps 1–4 are implemented here; step 5 is intentionally a backend swap behind the
`SkillStore` seam, not a rewrite.
