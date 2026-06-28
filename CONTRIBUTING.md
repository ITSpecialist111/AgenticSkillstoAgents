# Contributing a skill to the registry

This repo IS the skill registry (Stage 1 lite deployment). To add a skill,
open a PR that adds a manifest under `examples/`. CI is the Register gate
(schema validation + duplicate scan); your reviewer is the Certify gate.

## Quick start

1. Copy [`docs/skill-manifest-template.json`](docs/skill-manifest-template.json)
   to `examples/<your-skill-name>.manifest.json`.
2. Fill in every field. The schema is
   [`schemas/skill-manifest.schema.json`](schemas/skill-manifest.schema.json).
3. Set `lifecycle.stage` to `"draft"`. A reviewer flips it to `"published"`
   as part of the Certify gate.
4. Validate locally:
   ```bash
   cd prototype-lite
   pip install -r requirements.txt
   python -m pytest -q
   python lite.py list           # see your skill in the capability index
   python lite.py dupes          # must report "no duplicates"
   python lite.py find <tag>     # matchmaking query
   ```
5. Open a PR. The `validate-manifests` workflow runs the same checks. A red
   check blocks merge.

## What a good capability tag looks like

| Bad | Good |
|---|---|
| `extract` | `invoice.extract` |
| `match` | `po.invoice.match` |
| `do-stuff` | `payment.packet.assemble` |

Tags are the meaning layer. Lowercase, dotted, action-noun shape. Two skills
that legitimately offer the same capability should share the tag — the
Certify reviewer will block the duplicate as a policy decision, not a naming
accident.

## Reviewer checklist (the Certify gate)

A reviewer must confirm before merging:

- [ ] Manifest is schema-valid (CI proves this).
- [ ] No duplicate capability tag against an already-published skill (CI proves this).
- [ ] `scoring.determinism` and `scoring.risk` are honest, with a `rationale`.
- [ ] `mcp.namespace` is verified — this is the production binding.
- [ ] `governance.dataClassification` and `governance.rbac` reflect the real
      data the skill touches.
- [ ] `lifecycle.stage` set to `"published"` on the merge commit, with
      `certifiedBy` set to the reviewer's handle.

## Retiring a skill

Set `lifecycle.stage` to `"archived"` and (optionally) record the successor
in `lifecycle.supersededBy`. CI still validates archived manifests but they
no longer appear in `find_by_capability(... published_only=True)` results.

## When to graduate to the full chassis

See [`docs/complexity-review.md`](docs/complexity-review.md) for the evidence
thresholds. Until you hit them, lite is the chassis.
