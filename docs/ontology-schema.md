# Ontology Schema (the Meaning Layer)

> The entity-relationship model that lets a *small number* of agents reason over a *large
> pool* of governed skills. Modelled on **OWL-S/WSMO IOPE** (Inputs, Outputs,
> Preconditions, Effects) and capability matchmaking — but kept **lightweight and
> query-first** to avoid the scalability trap that stalled the Semantic Web Services era
> (see [`prior-art.md`](prior-art.md)).

This schema is what the **Ontology Builder Agent**
([`ontology-builder-agent.md`](ontology-builder-agent.md)) populates from Skill Manifests
([`technical-spec.md`](technical-spec.md)).

## Design principles

1. **Manifest-derived.** Every entity/edge is traceable back to a field in a Skill
   Manifest. No hand-authored meaning that cannot be regenerated.
2. **Query-first, not inference-heavy.** Discovery is graph traversal, not expensive
   description-logic reasoning. This is the deliberate departure from OWL-S.
3. **Capability is the join key.** `CapabilityTag` is the canonical concept used for
   matchmaking, duplicate detection, and composition.

## Entities

| Entity | Derived from manifest | Purpose |
|---|---|---|
| **Skill** | `identity.*`, `lifecycle.*` | A registered, versioned unit of capability. |
| **Capability** | `capability.capabilityTags[]` | A canonical, reusable functional concept (e.g. `invoice.extract`). Many skills may provide the same capability. |
| **DataType** | `capability.inputs[].type`, `capability.outputs[].type` | A logical input/output type (e.g. `InvoiceFields`). Enables compatibility chaining. |
| **Condition** | `capability.preconditions[]`, `capability.effects[]` | A precondition or effect (P/E in IOPE). |
| **Agent** | composition config (capped set) | An org agent that composes certified skills. |
| **Scope** | `governance.*` | Visibility, RBAC, data classification — the trust boundary. |
| **Owner** | `identity.owner.*` | Accountable maker/team (lineage, hand-off). |

### Stage F Phase 1 — cross-domain entities

Projected alongside the skill graph by `fabric_export.py --org-dir`. These
six entity types extend the ontology into adjacent enterprise graphs and
let an agent traverse `Person → Project → Capability → Skill` without
leaving the same query layer. Per-entity sources today are synthetic
(`prototype/chassis/synth_org.py`); Phase 3 replaces them with real
adapters (Entra, Project/Planner, Viva Learning, etc.).

| Entity | Derived from | Purpose |
|---|---|---|
| **Person** | org adapter (Entra in Phase 3; `synth_org` in Phase 1) | An individual maker, contributor, or stakeholder. Carries role, team, manager, `dataClassification`. |
| **Project** | project/work adapter | A scoped delivery (RFP, programme, internal initiative). Required capabilities + employed people. |
| **Training** | LMS adapter | A learning artifact (course, module). Covers capability tags; may grant a Certification. |
| **Certification** | credential adapter | A holdable credential issued by some authority. Implies one or more capability tags. |
| **Role** | derived from Person.role | A named role (PM, Eng, Architect, …). One per Person. |
| **Team** | derived from Person.team | An organisational unit. One MEMBER_OF edge per Person. |

## Relationships

```
(Skill) ─PROVIDES▶ (Capability)
(Skill) ─CONSUMES▶ (DataType)        // from capability.inputs[].type
(Skill) ─PRODUCES▶ (DataType)        // from capability.outputs[].type
(Skill) ─REQUIRES▶ (Condition)       // from capability.preconditions[]
(Skill) ─CAUSES▶   (Condition)       // from capability.effects[]
(Skill) ─DEPENDS_ON▶ (Skill|Capability) // from dependencies[]
(Skill) ─SUPERSEDES▶ (Skill)         // from lifecycle.supersedes/supersededBy
(Skill) ─OWNED_BY▶ (Owner)
(Skill) ─GOVERNED_BY▶ (Scope)
(Agent) ─MAY_COMPOSE▶ (Capability)   // capped agents bind to capabilities, not skills
(Capability) ─DUPLICATE_OF▶ (Capability) // proposed by the Ontology Builder Agent

// Stage F Phase 1 — cross-domain edges
(Person)       ─HAS_ROLE▶     (Role)
(Person)       ─MEMBER_OF▶    (Team)
(Person)       ─WORKED_ON▶    (Project)
(Project)      ─EMPLOYED▶     (Person)        // symmetric to WORKED_ON
(Project)      ─REQUIRED▶     (Capability)
(Capability)   ─SATISFIED_BY▶ (Skill)         // derived from PROVIDES inverse
(Person)       ─HOLDS_SKILL▶  (Skill)
(Person)       ─COMPLETED▶    (Training)
(Training)     ─GRANTS▶       (Certification)
(Person)       ─HOLDS_CERT▶   (Certification) // derived from COMPLETED + GRANTS
```

### Composition chaining rule

Two skills `A` and `B` are **composable in sequence** when:

```
A PRODUCES DataType T  AND  B CONSUMES DataType T
AND every Condition in B.REQUIRES is satisfied by (context ∪ A.CAUSES)
AND Scope(B) permits the requesting Agent
```

This is the matchmaking query the Reasoning Layer runs — the modern, lightweight analogue
of OWL-S Exact/Plug-in/Subsume/Fail matching.

## Capability matchmaking grades

Borrowed from Paolucci et al., simplified to a traversal result:

| Grade | Meaning |
|---|---|
| **Exact** | Requested capability tag == provided capability tag, types equal. |
| **Plug-in** | Provided output type is a subtype of / satisfies the requested type. |
| **Partial** | Capability matches but a precondition/scope is unmet (candidate for composition to fill). |
| **Fail** | No path. |

## Worked example (from the bundled manifests)

From [`../examples/`](../examples):

```
(finance/invoice-extract) ─PROVIDES▶ (invoice.extract)
(finance/invoice-extract) ─PRODUCES▶ (InvoiceFields)

(finance/po-match) ─PROVIDES▶ (invoice.match)
(finance/po-match) ─CONSUMES▶ (InvoiceFields)
(finance/po-match) ─DEPENDS_ON▶ (invoice.extract)

(finance/ap-intake) ─PROVIDES▶ (ap.intake)
(finance/ap-intake) ─DEPENDS_ON▶ (invoice.extract), (invoice.match)
```

Composition query "give me `ap.intake`" resolves to the chain
`invoice-extract ─(InvoiceFields)▶ po-match`, because `invoice-extract PRODUCES
InvoiceFields` and `po-match CONSUMES InvoiceFields` — a clean Plug-in match.

## What is intentionally NOT modelled

- No heavyweight OWL/description-logic axioms. Types are nominal tags, compatibility is a
  declared subtype edge, not an inferred one.
- No global upper ontology. Capability tags are namespaced and grown bottom-up from real
  manifests by the Ontology Builder Agent.
