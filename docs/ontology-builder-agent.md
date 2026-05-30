# The Ontology Builder Agent

> **The keystone.** Hand-maintained ontologies die — this is the documented reason the
> OWL-S / WSMO Semantic Web Services vision stalled (see [`prior-art.md`](prior-art.md)).
> The thing that makes this construct real is **agentic code that builds and maintains the
> ontology for you**. This is also the **one unproven bet** in the whole design, so it is
> isolated as a replaceable component with a **measurable contract** and kept **behind a
> human-in-the-loop gate**.

## Why this component exists

The Semantic Web Services era proved the vision (ontology-driven discovery and
composition) was right and the *maintenance cost* was fatal. We do not assume agentic
maintenance solves this — **we build the construct to test it.** Everything else in the
chassis is de-risked by prior art; this is the part we must prove.

## Contract (input → output)

The agent is a pure, replaceable function with an auditable contract:

```
INPUT:   Skill Manifests (newly published or changed)  +  current Ontology
OUTPUT:  - Proposed graph updates (entities + relationships)
         - A confidence/quality signal per proposal
         - Duplicate / conflict flags
         - A human-review queue (nothing is auto-merged above a risk threshold)
```

It **never** writes directly to the production ontology for non-trivial changes. It
proposes; a human (or a policy for low-risk, high-confidence changes) disposes.

## What it does at the Meaning-sync gate (Pipeline step 4)

1. **Ingest** the manifest's `capability` block (IOPE), `dependencies`, `identity`,
   `governance`.
2. **Propose entities**: Skill, Capability (from `capabilityTags`), DataType (from
   input/output `type`), Condition (from preconditions/effects). See
   [`ontology-schema.md`](ontology-schema.md).
3. **Propose relationships**: PROVIDES / CONSUMES / PRODUCES / REQUIRES / CAUSES /
   DEPENDS_ON / SUPERSEDES.
4. **Score determinism/risk consistency** — cross-check the manifest's `scoring` against
   peers providing the same capability; flag outliers.
5. **Detect duplicates**: propose `Capability DUPLICATE_OF Capability` when two capability
   tags are functionally equivalent (same IOPE signature, overlapping tags). This is the
   single most valuable output — it stops the registry sprawling into 10,000 near-copies.
6. **Emit** proposals + confidence + flags to the review queue.

## Human-in-the-loop policy

| Change class | Confidence | Risk | Disposition |
|---|---|---|---|
| New Skill/Capability node | high | low | Auto-merge, logged |
| New relationship | high | low | Auto-merge, logged |
| `DUPLICATE_OF` proposal | any | — | **Always** human review |
| Determinism/risk conflict | any | — | **Always** human review |
| Anything touching `restricted` data scope | any | — | **Always** human review |
| Below confidence threshold | low | any | Human review |

This mirrors the lesson that **hybrid beat full automation** in every prior attempt.

## Measurable success (the falsifiable bet)

The whole construct lives or dies on whether this component lowers maintenance cost below
hand-curation. Tracked metrics (targets in [`roadmap.md`](roadmap.md)):

| Metric | Definition | Why it matters |
|---|---|---|
| **Proposal acceptance rate** | % of auto-proposed entities/edges a human accepts unchanged | Measures proposal quality |
| **Duplicate-detection precision/recall** | Correct `DUPLICATE_OF` flags vs. ground truth | Measures the anti-sprawl payoff |
| **Maintenance effort** | Human minutes per 100 skills synced vs. hand-curation baseline | The core cost claim |
| **Ontology drift** | % of skills whose ontology view is stale > N days | Measures "stays in sync" |
| **Time-to-meaning** | Publish → in-ontology latency | Pipeline throughput |

If proposal acceptance and duplicate precision stay high **while** maintenance effort
stays below the hand-curation baseline, the bet is won. If not, the component is replaced
without disturbing the rest of the chassis — that is why it is isolated.

## Replaceability

Because the contract is `(manifests, ontology) → proposals`, the implementation can be a
heuristic matcher, an LLM, a fine-tuned model, or a hybrid — swapped freely. The chassis
depends on the **contract**, not the implementation.
