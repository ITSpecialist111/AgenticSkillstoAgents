# Complexity review — is the chassis over-engineered?

Date: 2026-06-28
Branch: `prototype-lite`
Counter-implementation: [`prototype-lite/`](../prototype-lite)

## TL;DR

> The current prototype builds the entire chassis **around** the Ontology
> Builder Agent — a component the docs themselves describe as "the unproven
> part." This inverts the right load-bearing assumption.
>
> **Reverse it:** build a registry that delivers value *without* the agent.
> Add the agent later, behind a measurable contract, only if hand-curation
> actually breaks down at scale.

`prototype-lite/lite.py` is a 178-line counter-implementation of the same
construct, against the same canonical manifest and the same bundled example
skills. It exists so the trade-off is concrete instead of theoretical.

## The three over-engineered places

### 1. The Ontology Builder Agent is the foundation, but it's also the bet

From `docs/ontology-builder-agent.md`: *"the unproven part — isolated with a
measurable contract behind a human gate."* Honest framing — but the rest of
the architecture is then shaped to feed it: the 4-layer model, the
Meaning-sync gate, the `GraphChange`/`SyncResult` contract, confidence
thresholds, the human review queue.

The registry should **work without the agent**. Adoption shouldn't depend on
adopters believing in an unproven component.

**Lite's stance:** capability tags ARE the meaning, until ≥50 skills prove
otherwise. Duplicate detection is one pass over `(IOPE signature, tags)`,
returned as data; the caller decides what to escalate. No agent contract
surface.

### 2. Six gates and four layers are mostly ceremony at this stage

Load-bearing gates:

- **Register** — schema validation. Genuinely required.
- **Certify** — human approval + duplicate scan against published skills. Genuinely required.

Ceremony at this stage:

- **Publish** — just flips a flag. Fold into Certify's exit.
- **Meaning-sync** — depends on an unproven agent. Optional bolt-on.
- **Compose** — the caller's job, not the registry's. Not a pipeline stage.
- **Retire** — deprecation is a manifest field, not a state.

Four layers (Storage / Meaning / Reasoning / Composition) collapse to two
once you notice that "Reasoning" is graph queries over Meaning, and
"Composition" lives in the calling agent, not in the registry.

**Lite's stance:** Register + Certify, three lifecycle states
(`draft` / `published` / `archived`).

### 3. IOPE signature and capability tags are doing the same job

The duplicate scanner in `prototype/chassis/ontology.py:172-189` uses **both**
an IOPE signature **and** overlapping tags. They're two encodings of the same
"what does this skill do" concept. One concept suffices: a *capability
signature* of `(tags, input types, output types)`.

**Lite's stance:** keep both fields on the manifest (they're cheap), use them
together as one signature for duplicate detection, don't model them as
separate ontology citizens.

## What survives unchanged

- `schemas/skill-manifest.schema.json` — the real artifact.
- `examples/*.manifest.json` — used by both implementations.
- The README's thesis: centralise capabilities + meaning + trust, cap the
  number of agents, let them compose from a registry. **This is right.**
  Lite delivers ~80% of it in 178 lines.

## Single most valuable simplification

**Reverse the load-bearing assumption.** Today, the chassis is designed to
serve the Ontology Builder Agent. Flip it: design the registry so it's
useful with manifests + tags + git PRs *alone*. The agent becomes an
optional accelerator that earns its place by measurable improvement over
human review — exactly as the docs promise, but applied to the chassis
itself rather than only to the agent's adoption.

## Promotion criteria (when to graduate from lite to the full chassis)

Promote on evidence, not on principle.

| Reintroduce… | …when |
|---|---|
| `OntologyBuilderAgent` | Skill count ≥ ~50 **and** measurable evidence that humans miss duplicate/conflict cases at PR review. |
| Intermediate lifecycle stages | A required state can't be carried as a manifest flag (e.g. multi-sign-off certification). |
| The graph layer | Capability tags can't answer composition queries — callers need to reason over preconditions/effects, not just tag equality. |
| `Compose` and `Meaning-sync` as gates | Composition stops being the caller's responsibility (e.g. shared orchestrator service inside the registry). |

## Recommendation

Adopt `prototype-lite/` as the **default starting chassis**. Treat
`prototype/` as the *target end-state* documented for when scale demands it.
Update `README.md` to lead with the lite path; keep the full prototype as the
"and here's where it grows to" appendix.

This preserves the architectural ambition while removing the adoption tax.
