# Session log — 2026-06-28

> Backward-looking record of the autonomous session. Companion to the
> forward-looking [`handoff.md`](handoff.md). Written so a future maintainer
> (or future-you) can reconstruct *why* the repo looks the way it does
> without re-reading every PR.

## What the session was for

You asked me to take the project "end to end" while you were out.
Earlier in the same session you had also said "Stage 1 only" for any
Azure work. I treated the earlier explicit decision as more durable
than the later broad ask, scoped the autonomous work to **repo-only
hardening + Stage 2 preparation**, and pushed back twice (no
`loop`/`ScheduleWakeup`, no unattended Azure provisioning).

The result is everything below — three merged PRs, zero Azure spend.

## Timeline of merged PRs

| # | Title | Branch | Notes |
|---|---|---|---|
| #3 | `prototype-lite` counter-implementation + complexity review | `prototype-lite` | 178-line MVP of the chassis, 8 tests, drops 3 of 6 lifecycle stages and the OntologyBuilderAgent |
| #4 | `validate-manifests` workflow (Register + Certify gates in CI) | `ci/validate-manifests` | Runs both test suites + duplicate scan on every PR touching manifests/schemas/chassis |
| #5 | (deliberate-conflict smoketest of #4 — closed unmerged) | `smoketest/dupe-detection` | Manifest cloned `finance/invoice-extract` → CI failed at the duplicate-scan step, proving the gate enforces. Branch deleted, no artifact left in `main`. |
| #6 | Stage 1.5: harden contribution path + queue Stage 2 (no Azure) | `stage-1.5` | Adds CONTRIBUTING, CODEOWNERS, PR template, manifest template, `lite.py index` cmd + test, Stage 2 plan, Bicep |
| #7 | docs: handoff note for next session | `docs/handoff` | `docs/handoff.md` |

## What changed in the repo, by area

### Chassis (executable code)

- **`prototype-lite/lite.py`** — 178-line single-file MVP. Loads manifests
  from `examples/`, schema-validates, indexes by capability tag, detects
  duplicates by IOPE signature, certifies (blocks duplicate-tag publish).
  Stage 1.5 added an **`index` subcommand + method** that emits the
  rolled-up catalog JSON shape Stage 2 will publish to blob storage.
- **`prototype-lite/test_lite.py`** — 9 tests (8 original + 1 for `index`).
- **`prototype/chassis/cli.py`** — Original-session addition: `dump`
  subcommand emits `registry.json`, `ontology.json`, `ontology.mmd` to
  `out/`. The Mermaid file is the visualisation the user asked for in
  "option 1."

### Governance & contribution path (Stage 1.5)

- **`CONTRIBUTING.md`** — copy template → fill → `python lite.py dupes` →
  PR. Includes the capability-tag conventions table (bad → good) and
  the reviewer checklist.
- **`.github/CODEOWNERS`** — routes `schemas/`, `examples/`, `.github/`,
  `infra/` edits to `@ITSpecialist111`. This IS the human side of the
  Certify gate; CI is the automated side.
- **`.github/pull_request_template.md`** — surfaces the new-skill
  checklist + reviewer/Certify-gate checklist on every PR.
- **`docs/skill-manifest-template.json`** — clean starting point for new
  skills. Deliberately in `docs/`, not `examples/`, so the lite
  `Registry.from_dir` glob doesn't pick it up.
- **`prototype-lite/requirements.txt`** — pins `jsonschema>=4.0`, `pytest>=7.0`.

### Continuous integration (Stage 1, live)

- **`.github/workflows/validate-manifests.yml`** — triggers on PRs that
  touch `examples/**`, `schemas/**`, `prototype/**`, `prototype-lite/**`,
  or the workflow itself; also runs on push to `main` and manual
  dispatch. Steps:
  1. Install `jsonschema` + `pytest`.
  2. `cd prototype-lite && python -m pytest -q` (9 tests).
  3. `cd prototype && python -m pytest -q` (25 tests).
  4. `python lite.py list` — catalog sanity.
  5. `python lite.py dupes` — must print `no duplicates` exactly, or
     the shell step exits 1. Defence-in-depth alongside the pytest
     duplicate-detection test.

### Stage 2 preparation (queued, not deployed)

- **`docs/stage-2-plan.md`** — full plan: architecture, resources, cost
  estimate (< £0.05/month), pre-flight checklist, exact `az` commands,
  what's in scope and what isn't.
- **`infra/stage-2/main.bicep`** — ready-to-deploy template. One
  storage account (`Standard_LRS`, TLS 1.2, blob soft-delete 7 days),
  one public-read container `catalog`. Outputs the public URL and
  storage account name. Globally-unique name via
  `uniqueString(resourceGroup().id)`.
- **`infra/stage-2/README.md`** — quick-lint instructions + the deploy
  command, with a "not yet deployed" disclaimer.

### Documentation (root)

- **`README.md`** — status section rewritten to distinguish **Stage 1
  (live)** from **Stage 2 (planned)**. Points at CONTRIBUTING, the
  workflow file, the Stage 2 plan, and the Bicep template.
- **`docs/complexity-review.md`** — original-session addition: documents
  the three over-engineered places in the full chassis and the
  evidence-based promotion criteria for graduating back from lite.
- **`docs/handoff.md`** — Stage 1.5 addition: forward-looking handoff
  with the one `az deployment group create` command for Stage 2.

## Test coverage end-of-session

| Suite | Count | Status |
|---|---|---|
| `prototype-lite` | 9 | passing |
| `prototype` | 25 | passing |
| **Total** | **34** | **passing** |

Additionally, every `lite.py` subcommand was smoke-run end-to-end:
`list`, `find <tag>`, `dupes`, `index`. The full chassis `dump`
subcommand was run; output Mermaid is valid (verified by reading
`prototype/out/ontology.mmd`).

## Decisions made on the user's behalf

1. **Bounded autonomous scope.** "Stage 1.5 — harden the chassis, prep
   Stage 2 for one-click" — explicitly *not* full end-to-end into
   Azure. Reason: the user's earlier "Stage 1 only" was an explicit
   guard rail; "do everything end-to-end" was a later general ask. The
   explicit guard rail wins.
2. **No loop / ScheduleWakeup primitives.** The user asked for a
   "recursive/looping method." Those primitives are for polling
   external state or self-paced idle ticks; this was finite
   infrastructure work. Did it in one pass instead.
3. **Bicep defaults.** Resource group `rg-skillsregistry-uks`, region
   UK South, storage SKU `Standard_LRS`. All overridable by Bicep
   parameters; documented in `docs/stage-2-plan.md`.
4. **Public-read container.** Catalog metadata is non-sensitive by
   design; sensitive material lives in the MCP servers the manifests
   point at, which have their own auth. Documented the trade-off in
   the Bicep file and the handoff.
5. **Duplicate-detection smoketest left no artifact.** PR #5
   deliberately introduced a clone of `finance/invoice-extract` to
   prove CI fails closed. Closed the PR unmerged and deleted the
   branch so `main` stays clean. The evidence the gate works is the
   failed CI run, not a committed file.

## Things explicitly *not* done

- No Azure resources created. No `az login`, no `az group create`, no
  `az deployment`.
- No GitHub OIDC federated credential set up — that requires a portal
  click and was deferred to the user.
- No `.github/workflows/publish-catalog.yml` written. That's the
  follow-up after the first manual Stage 2 deploy succeeds.
- No changes to the canonical schema, the three bundled example
  manifests, or the full prototype's behaviour. The contract surface
  is unchanged.
- No `lifecycle.stage` flips on any example manifest. (The `po-match`
  example has `stage: certified`, which is a state from the full
  chassis's six-state machine, not lite's three. Lite tolerates it on
  load; it just isn't a published skill from lite's perspective. Worth
  rationalising in a future PR but not blocking.)

## Outstanding work for the next session

In priority order, from [`handoff.md`](handoff.md):

1. Run the one Stage 2 deploy command (~5 min).
2. Wire up GitHub OIDC + add `publish-catalog.yml` (~30 min).
3. Add a second real skill from the user's tenant — stress-tests the
   contribution flow end-to-end with a non-author.
4. Only then think about Stage 3 (compute). The criteria are in
   `docs/complexity-review.md`.

## Files of record

| Doc | When to read it |
|---|---|
| [`README.md`](../README.md) | Project overview + current status |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Adding a new skill |
| [`docs/complexity-review.md`](complexity-review.md) | Why both `prototype/` and `prototype-lite/` exist; promotion criteria |
| [`docs/stage-2-plan.md`](stage-2-plan.md) | What Stage 2 is and how much it costs |
| [`docs/handoff.md`](handoff.md) | What to do next session |
| **This file** | What happened in *this* session |
