# Intake — the front door to the Register gate

Real-world skills are not born as JSON manifests. They arrive the way makers
actually produce them: a **folder** containing an Anthropic-style `SKILL.md`
alongside the deterministic **scripts**, **assets**, and **knowledge** the skill
relies on. **Intake** is the adapter that turns those folders into the canonical
[Skill Manifest](../schemas/skill-manifest.schema.json) (Part A) so the same unit
can travel the [six-gate pipeline](architecture.md) (Part B) unchanged.

Intake sits strictly **upstream of Gate 1 (Register)**. It does not change the
schema, the pipeline, or the ontology — it only *authors* the manifest that those
already-built components consume.

```
   skill folder                    intake                     chassis
┌───────────────────┐      ┌──────────────────────┐     ┌──────────────────┐
│ SKILL.md          │      │ discover → parse →   │     │ Register → …     │
│ summarize.py      │ ───▶ │ classify → map →     │ ──▶ │ six gates        │
│ reference.md      │      │ validate → report    │     │ (manifest unit)  │
│ config.json       │      └──────────────────────┘     └──────────────────┘
└───────────────────┘         draft manifest + IntakeReport
```

## Two guarantees

1. **Never invent IOPE.** Inputs/outputs/preconditions/effects are copied from
   `SKILL.md` frontmatter when present and left **empty + flagged** otherwise.
   Intake proposes structure; it never fabricates a skill's contract.
2. **Always draft.** Generated manifests are always `lifecycle.stage: draft`.
   Graduation stays with the six gates and their human-in-the-loop Certify step.

Missing-but-required fields get conservative defaults plus a flag in the
**`IntakeReport`**, so a maker sees exactly what to complete instead of hitting a
hard failure — mirroring the chassis's "propose, don't auto-merge" philosophy.

## Source format

A skill folder is any directory that directly contains a `SKILL.md` (matched
case-insensitively). Every other file in that subtree is a **sidecar**, classified
by extension into the three deterministic-action categories:

| Category | Examples | Signal |
|---|---|---|
| **scripts** | `.py`, `.sh`, `.sql`, `.js`, `.ps1`, `.go`, … | Deterministic, runnable actions |
| **assets** | `.json`, `.csv`, `.yaml`, `.html`, templates | Config/data the skill references |
| **knowledge** | `.md`, `.txt`, `.pdf`, `.rst`, … | Reference material the skill leans on |

The `SKILL.md` carries optional YAML frontmatter (the structured signal) followed
by a markdown body (whose first heading is a fallback summary).

## Mapping: `SKILL.md` → manifest

| Manifest field | Source | Fallback when absent |
|---|---|---|
| `identity.id` | frontmatter `id` | derived `namespace/name` from the folder path (flagged) |
| `identity.name` | frontmatter `name` | first body heading, else folder name |
| `identity.version` | frontmatter `version` | `0.1.0` (flagged) |
| `identity.owner` | frontmatter `owner` (string or map) | `{handle: unknown}` (flagged) |
| `identity.skillType` | inferred | `deterministic-tool` if scripts present, else `anthropic-agent-skill` |
| `identity.tags` | frontmatter `tags` | omitted |
| `capability.summary` | frontmatter `summary`/`description` | first body heading |
| `capability.capabilityTags` | frontmatter `capabilityTags` | derived slug from the id (flagged) |
| `capability.inputs/outputs` | frontmatter `inputs`/`outputs` | **empty + flagged** (never invented) |
| `capability.preconditions/effects` | frontmatter | omitted |
| `scoring.determinism` | inferred from assets | `high` (scripts) / `medium` (mixed) / `low` (knowledge only) |
| `scoring.risk` | frontmatter `scoring.risk` | `low` (flagged — risk can't be inferred from files) |
| `governance.visibility` | frontmatter `governance` | `private` (most conservative, flagged) |
| `lifecycle.stage` | — | always `draft` |
| `mcp`, `dependencies` | frontmatter passthrough | omitted |

Provenance (source path + per-file SHA-256 hashes) is recorded on the
`IntakeReport`, **not** the manifest, because the manifest schema forbids extra
properties. It gives the registry/ontology a lineage link back to the source files.

## Security: untrusted `SKILL.md`

A skill folder is authored by a maker (or another agent) and then **read by our
agents**, so its `SKILL.md` is an attack surface. Even though we keep Markdown
(for its simplicity and low token cost), Markdown can smuggle payloads that an
LLM still reads:

| Threat | Examples |
|---|---|
| **Embedded raw HTML** | `<script>`, `<style>`, `<iframe>`, inline `onerror=` handlers, auto-fetching `<img src>` (exfiltration via the request URL), `javascript:`/`data:` URIs |
| **Invisible / bidi characters** | zero-width spaces/joiners, BOM, soft hyphen, RTL overrides — render as nothing yet hide instructions in plain sight |
| **Prompt-injection phrases** | "ignore previous instructions", "reveal your system prompt", "you are now …" in either frontmatter or body |

Intake treats the `SKILL.md` as untrusted and runs a **scan** over the whole
document ([`chassis/intake/sanitize.py`](../prototype/chassis/intake/sanitize.py)).
It is a **detector, not a sanitiser**: it never executes, fetches, or rewrites
the maker's content. Findings are recorded as `IntakeReport.security_flags` (and
printed under `security:` by `chassis intake`), so a human reviewer sees exactly
what to inspect at the Certify gate.

Consistent with the rest of intake, scanning **never hard-fails a draft** —
propose, don't auto-merge. A flagged skill still produces a `draft` manifest;
the flags travel on the report (not the manifest, whose schema forbids extra
properties) for a human to adjudicate.

## CLI

```bash
cd prototype

# Scan a tree of skill folders into draft manifests + reports.
python -m chassis.cli intake <root>

# Same, and register every schema-valid draft into an in-memory registry (Gate 1).
python -m chassis.cli intake <root> --register

# Watch the tree and re-emit whenever a SKILL.md or a sidecar changes.
python -m chassis.cli intake <root> --watch
```

Registration is **opt-in** (`--register`); by default intake only emits drafts for
a human to review and submit.

## Monitoring (the watch layer)

`IntakeWatcher` is a dependency-light **content-hash poller**: each scan hashes
every `SKILL.md` plus its sidecars and reports the folders whose digest changed
since the last scan. Scanning an unchanged tree is idempotent (no re-emit). The
poller is deliberately replaceable — a filesystem-events backend (watchdog,
inotify) or a GitHub webhook can swap in behind the same `scan(root) → changed[]`
interface without touching the mapper.

## Deliberately out of scope

- No OS filesystem-event daemon / service packaging yet (polling wrapper only).
- No execution or sandboxing of discovered scripts — intake only *classifies and
  references* them; running them belongs to the Compose layer.
- No content rewriting/quarantine — the security scan only *flags* untrusted
  `SKILL.md` content for human review; it never edits, strips, or blocks it.
- No git/GitHub webhook integration yet (the poller is the placeholder).

## Module map

| Module | Responsibility |
|---|---|
| [`chassis/intake/discovery.py`](../prototype/chassis/intake/discovery.py) | Walk a tree, find skill folders + sidecars |
| [`chassis/intake/skillmd.py`](../prototype/chassis/intake/skillmd.py) | Parse `SKILL.md` frontmatter + body |
| [`chassis/intake/assets.py`](../prototype/chassis/intake/assets.py) | Classify sidecars into scripts/assets/knowledge |
| [`chassis/intake/sanitize.py`](../prototype/chassis/intake/sanitize.py) | Scan untrusted `SKILL.md` for embedded HTML / invisible chars / injection phrases |
| [`chassis/intake/mapper.py`](../prototype/chassis/intake/mapper.py) | Assemble + validate a draft manifest + `IntakeReport` |
| [`chassis/intake/watcher.py`](../prototype/chassis/intake/watcher.py) | Content-hash poller that re-emits on change |
