# Worked Graduation Walkthrough

> Proof that the flow is a **chassis, not a bespoke build**: a single skill travels all six
> gates of the pipeline ([`architecture.md`](architecture.md) Part B), and a second skill
> composes onto it. Only the `lifecycle` block of the manifest changes as the skill moves;
> the frame is identical for every skill.

The manifests referenced here are real and validate against the schema:
[`../examples/invoice-extract.manifest.json`](../examples/invoice-extract.manifest.json),
[`../examples/po-match.manifest.json`](../examples/po-match.manifest.json),
[`../examples/ap-intake.manifest.json`](../examples/ap-intake.manifest.json).

## The skill: `finance/invoice-extract`

A deterministic OCR+rules tool that turns an invoice document into structured
`InvoiceFields`. An individual maker built it as a personal Skill. We graduate it.

### Gate 1 — Register

The maker writes a Manifest and submits it. Entry: a manifest exists. The registry
validates it against
[`../schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json).

```diff
  "lifecycle": {
-   "stage": "draft"
+   "stage": "registered"
  }
```

**Exit:** schema-valid, `stage = registered`.

### Gate 2 — Certify (automated checks + human approval)

Automated checks run:
- Schema valid ✓
- `scoring.determinism = high`, `scoring.risk = low` — consistent with peers providing
  `invoice.extract` ✓
- Duplicate-capability scan: no existing skill provides `invoice.extract` ✓
- Dependency refs resolve: none ✓

A human reviewer (the CoE) approves — recorded in the manifest. This is the mandatory
human gate; in practice it is a GitHub PR approval.

```diff
  "lifecycle": {
-   "stage": "registered"
+   "stage": "certified",
+   "certifiedBy": "coe.reviewer",
+   "certifiedAt": "2026-03-11T09:30:00Z"
  }
```

**Exit:** `stage = certified`, `certifiedBy`/`certifiedAt` set.

### Gate 3 — Publish

Promoted into the MCP-compatible catalog. The `mcp` block is verified (server
`finance-tools`, tool `invoice_extract`, namespace `example-org`).

```diff
  "lifecycle": {
-   "stage": "certified"
+   "stage": "published"
  }
```

**Exit:** discoverable in the governed registry; `stage = published`. This is the state of
the bundled `invoice-extract` manifest.

### Gate 4 — Meaning-sync (Ontology Builder Agent)

The agent ingests the manifest and proposes graph updates (see
[`ontology-builder-agent.md`](ontology-builder-agent.md)):

```
(finance/invoice-extract) ─PROVIDES▶ (invoice.extract)        [confidence 0.98 → auto-merge]
(finance/invoice-extract) ─CONSUMES▶ (InvoiceDocument)        [confidence 0.97 → auto-merge]
(finance/invoice-extract) ─PRODUCES▶ (InvoiceFields)          [confidence 0.97 → auto-merge]
(finance/invoice-extract) ─OWNED_BY▶ (Finance Automation)
duplicate scan: no DUPLICATE_OF flag
```

High-confidence, low-risk → auto-merged and logged. No stage change.

### Gate 5 — Compose (capped org agents)

A capped org agent receives "process this invoice and reconcile it." It queries the
ontology for `ap.intake` and the Reasoning Layer finds a composition path:

```
need: ap.intake
  → finance/ap-intake PROVIDES ap.intake, DEPENDS_ON invoice.extract + invoice.match
      invoice.extract PRODUCES InvoiceFields ─┐  (Plug-in match)
      invoice.match  CONSUMES InvoiceFields ◀─┘
```

The agent composes `invoice-extract → po-match` at runtime. It binds to **capabilities**,
not hard-coded skills, and the agent **count stays under the cap** — we grew the registry,
not the agent fleet.

### Gate 6 — Retire / version

When `invoice-extract` v2 ships, lineage is recorded so consumers migrate cleanly:

```diff
  // invoice-extract v1.3.0
  "lifecycle": {
-   "stage": "published"
+   "stage": "deprecated",
+   "supersededBy": "finance/invoice-extract@2.0.0"
  }
```

**Exit:** `deprecated` → `retired`; the ontology and composition paths follow the
supersede edge.

## The repeatability proof

`po-match` and the composite `ap-intake` carry the **same manifest frame** and travel the
**same six gates** — `po-match` is currently at Gate 2 (`certified`) and `ap-intake` at
Gate 1 (`draft`) in the bundled examples. Nothing about the pipeline is skill-specific:
that is the chassis.

| Skill | Current stage | Next gate |
|---|---|---|
| `finance/invoice-extract` | `published` | Meaning-sync / Compose |
| `finance/po-match` | `certified` | Publish |
| `finance/ap-intake` | `draft` | Register |
