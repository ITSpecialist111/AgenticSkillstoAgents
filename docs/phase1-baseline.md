# Phase 1 hand-curation baseline

> The roadmap's [Phase 1 exit gate](roadmap.md#phase-1--registry--certify-manual-meaning)
> requires a **recorded baseline maintenance effort** — human minutes per 100 skills to
> hand-curate the ontology. This is the number the [Ontology Builder
> Agent](ontology-builder-agent.md) must beat in Phase 2. Without it, the falsifiable bet
> cannot be judged, so it is recorded as data, not prose.

## The recorded baseline

The machine-readable baseline ships with the prototype at
[`../prototype/chassis/data/phase1-baseline.json`](../prototype/chassis/data/phase1-baseline.json):

| Field | Value |
|---|---|
| Metric | `maintenance_effort` |
| Unit | `human-minutes-per-100-skills` |
| Value | **210.0** |
| Skills curated | 24 (the 3 worked examples + 21 in [`../examples/catalog/`](../examples/catalog)) |
| Method | hand-curation |
| Minutes per review action | 3.0 |

### How it was measured

The baseline is the timed cost of **manually** maintaining the meaning layer for the 24
published skills in [`../examples/`](../examples) and [`../examples/catalog/`](../examples/catalog):
entering Skill / Capability / DataType / Condition entities and their relationships,
cross-checking determinism and risk against peers, and reviewing capability overlaps for
duplicates. The total is normalised to 100 skills so it is directly comparable regardless
of catalog size.

### How to re-record it

As the catalog grows, re-time a representative hand-curation pass and update the JSON
file. Keep the `unit` fixed (`human-minutes-per-100-skills`) so historical comparisons
hold, and record `skills_curated`, `recorded_at` and a one-line `provenance` for audit.
An alternative baseline can be supplied at evaluation time without editing the package:

```bash
chassis evaluate ../examples/evaluation \
  --labels ../examples/evaluation/labels.json \
  --baseline path/to/your-baseline.json
```

`chassis evaluate` resolves the baseline in this order: an explicit `--baseline` path, the
`CHASSIS_BASELINE_PATH` environment variable, then the packaged copy.

## Scoring against the baseline (Phase 2)

[`chassis/evaluation.py`](../prototype/chassis/evaluation.py) turns an Ontology Builder
Agent run into the five gated numbers from [`roadmap.md`](roadmap.md) and scores each
against its target:

| Metric | Definition | Target |
|---|---|---|
| `proposal_acceptance_rate` | share of proposals not held for human review | ≥ 0.80 |
| `duplicate_precision` | correct `DUPLICATE_OF` flags / all flagged | ≥ 0.90 |
| `duplicate_recall` | correct `DUPLICATE_OF` flags / all true duplicates | ≥ 0.70 |
| `maintenance_effort_ratio` | agent minutes-per-100 ÷ this baseline | < 0.50 |
| `ontology_drift` | published skills whose `Skill` node is still pending review | < 0.05 |

**Agent-assisted maintenance effort** is modelled as the human time spent only on the
review queue: `review_queue × minutes_per_review`, normalised to 100 skills. Auto-merged
proposals cost nothing. The gate is met only when *every* metric passes.

### The labelled evaluation corpus

Duplicate precision/recall need a ground truth, so
[`../examples/evaluation/`](../examples/evaluation) holds a small corpus of fixtures with
intentional near-duplicates and [`labels.json`](../examples/evaluation/labels.json) listing
the human-judged duplicate pairs. These fixtures deliberately share capability tags (true
duplicates) and so are **excluded from `chassis gate`** — they exist to measure the agent,
not to be published. Running the harness on this corpus exposes the current heuristic's
behaviour: it detects same-signature duplicates precisely (precision 1.0) but misses a
semantically-equal pair whose input types differ (recall 0.75), which is exactly the kind
of gap a stronger LLM/hybrid implementation would be expected to close.
