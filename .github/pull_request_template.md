<!--
PR template for the AgenticSkillstoAgents registry. CI (`validate-manifests`)
runs the automated Register gate. This template is the Certify gate.
-->

## What this PR does

<!-- One sentence. -->

## Type of change

- [ ] New skill manifest (`examples/*.manifest.json`)
- [ ] Schema change (`schemas/`)
- [ ] Chassis change (`prototype/` or `prototype-lite/`)
- [ ] Infra / workflow change (`.github/`, `infra/`)
- [ ] Docs only

## New-skill checklist (delete if not adding a skill)

- [ ] Copied from `docs/skill-manifest-template.json` and every field filled in
- [ ] `capabilityTags` are dotted, lowercase, action-noun (e.g. `invoice.extract`)
- [ ] `lifecycle.stage` is `"draft"` (reviewer flips to `"published"`)
- [ ] Ran `python prototype-lite/lite.py dupes` locally and got `no duplicates`
- [ ] `scoring.determinism`, `scoring.risk`, and `scoring.rationale` are honest
- [ ] `mcp.namespace` matches a real, verified MCP server

## Reviewer / Certify-gate checklist

- [ ] CI `validate-manifests` is green
- [ ] No duplicate capability against an already-published skill
- [ ] `governance.dataClassification` and `rbac` reflect actual data sensitivity
- [ ] On merge: set `lifecycle.stage` to `"published"` and `certifiedBy` to your handle
