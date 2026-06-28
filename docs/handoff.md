# Handoff — where the project is and what you do next

> **Audience:** Graham, returning to the laptop. Written 2026-06-28.

## Where we ended up

Three PRs merged into `main` while you were out:

| # | What | Branch |
|---|---|---|
| #3 | `prototype-lite/` — 178-line counter-implementation of the chassis + complexity review | `prototype-lite` |
| #4 | `validate-manifests` GitHub Actions workflow — the Stage 1 Register gate | `ci/validate-manifests` |
| #6 | Stage 1.5 — contributor docs, CODEOWNERS, PR template, Stage 2 plan + Bicep | `stage-1.5` |

Nothing in Azure was created. Stage 1 (Register gate in CI) is the only
production system live.

## What's running

**Stage 1 — live.** Every PR that touches `examples/`, `schemas/`,
`prototype/`, `prototype-lite/`, or the workflow file runs:
- 9 lite tests + 25 chassis tests (34 total)
- `python lite.py list` (catalog sanity)
- `python lite.py dupes` (must report `no duplicates`, otherwise CI fails)

The Certify gate is enforced by `.github/CODEOWNERS` — any change to
`/schemas/`, `/examples/`, `/.github/`, or `/infra/` requires
`@ITSpecialist111` review.

**Contribution flow** is documented in [`CONTRIBUTING.md`](../CONTRIBUTING.md)
and surfaced on every PR via [`.github/pull_request_template.md`](../.github/pull_request_template.md).

## What's queued and ready

**Stage 2 — planned, not deployed.** Everything below already exists in
the repo; no `az` command has been run.

- [`docs/stage-2-plan.md`](stage-2-plan.md) — full plan, cost estimate (< £0.05/mo)
- [`infra/stage-2/main.bicep`](../infra/stage-2/main.bicep) — ready-to-deploy template
- `python prototype-lite/lite.py index --out /tmp/catalog.json` — produces the artifact Stage 2 will publish

## The one command to run Stage 2 when you're ready

Pre-flight: confirm `az` is logged into the correct tenant.

```bash
az login
az account show --query "{tenant:tenantId, sub:name}"
```

Then, from the repo root:

```bash
az group create --name rg-skillsregistry-uks --location uksouth && \
az deployment group create \
  --resource-group rg-skillsregistry-uks \
  --template-file infra/stage-2/main.bicep \
  --query properties.outputs
```

That creates a resource group + one storage account + one public-read
container. Read [`docs/stage-2-plan.md`](stage-2-plan.md) before you run
it — it covers the GitHub OIDC federated credential you'll need for
auto-publish in CI (the only step that requires a portal click).

The first manual publish (until the workflow is added):

```bash
python prototype-lite/lite.py index --out /tmp/catalog.json
az storage blob upload \
  --account-name <storageAccountName from deployment output> \
  --container-name catalog \
  --name catalog.json \
  --file /tmp/catalog.json \
  --auth-mode login \
  --overwrite
```

After that publish succeeds, the follow-up PR adds
`.github/workflows/publish-catalog.yml` to automate it on every push to
`main`. That workflow is **not yet written** — it's the first thing for
the next session, after Stage 2 infra is real.

## Decisions I made on your behalf (worth confirming)

1. **Scoped to repo-only work.** You said "do all of this project end to
   end" but earlier in the session you'd also said "Stage 1 only" for
   Azure. I treated the explicit earlier decision as more durable than
   the broad later one, and limited autonomous work to repo artifacts +
   Stage 2 *preparation*. No Azure resources exist.
2. **No `loop` / `ScheduleWakeup`.** You asked for a "recursive/looping
   method." Those primitives are for polling external state or
   self-paced idle ticks; this was finite infrastructure work. I just
   did it in one pass.
3. **Resource names + region** in the Bicep template default to
   `rg-skillsregistry-uks` / UK South / `Standard_LRS`. Change in
   [`infra/stage-2/main.bicep`](../infra/stage-2/main.bicep) before
   deploying if you want something else.
4. **Container is public-read.** Catalog metadata is non-sensitive by
   design; sensitive material lives in the MCP servers the manifests
   point at, which have their own auth. If you want catalog auth too,
   flip `allowBlobPublicAccess` to `false` in the Bicep and add SAS-token
   handling to the publish workflow — adds complexity for no current win.

## If something looks wrong

- Run `cd prototype-lite && python -m pytest -q` — 9/9 must pass
- Run `cd prototype && python -m pytest -q` — 25/25 must pass
- Run `python prototype-lite/lite.py dupes` — must print `no duplicates`
- Check `gh run list --workflow validate-manifests -L 3` — recent green runs

If any of those is red, the chassis is broken and Stage 2 isn't the
problem to chase.

## Suggested next sessions (in order)

1. Run the Stage 2 deploy command above. ~5 minutes.
2. Wire up GitHub OIDC + add `publish-catalog.yml`. ~30 minutes.
3. Add a second real skill from your tenant — this stress-tests the
   contribution flow with someone other than me.
4. Only then think about Stage 3 (compute). The promotion criteria are
   in `docs/complexity-review.md`.
