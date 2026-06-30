"""Synthetic skill-manifest generator for stress-testing query_ontology.

Produces N valid manifests with a realistic dependency DAG so the resulting
ontology graph has multi-hop paths, mixed governance classifications, and
cross-domain edges — i.e. the shape we expect from a real enterprise
registry, not a flat star.

Topology
--------
Skills are organised into ``domains`` × ``tiers``. Within a domain, tier-K
skills depend on a small random sample of tier-<K skills, producing a DAG
that bottoms out at the tier-0 atomic operations. ~10% of skills also
depend on a capability from another domain so the graph isn't 10
disconnected stars.

Each skill provides 2-3 capability tags from a domain-specific pool,
consumes 1-2 typed inputs, produces 1 typed output, and carries a
governance classification weighted toward ``internal`` with a long tail
of ``confidential``/``restricted`` so classification gating has something
to gate.

Output is one ``*.manifest.json`` file per skill into ``out_dir`` —
schema-valid, ready for ``Registry.from_dir`` to load and
``fabric_export`` to project to parquet.

CLI::

    python -m prototype.chassis.synth_skills --count 1000 \\
        --out prototype/out/synth/manifests
"""

from __future__ import annotations

import argparse
import json
import os
import random
from typing import Any, Dict, List, Tuple

DOMAINS = [
    "finance", "legal", "hr", "dev", "design",
    "comms", "ops", "marketing", "security", "data",
]

# Capability tag pool per domain. Skills pick 2-3 of these to provide.
DOMAIN_CAPABILITIES: Dict[str, List[str]] = {
    "finance":   ["invoice.extract", "invoice.match", "ledger.post", "expense.classify", "tax.compute", "receipt.parse"],
    "legal":     ["contract.review", "clause.compare", "redline.apply", "compliance.check", "msa.draft", "ndansure.draft"],
    "hr":        ["candidate.screen", "offer.draft", "onboard.kit", "performance.review", "leave.calc", "policy.lookup"],
    "dev":       ["code.review", "test.generate", "doc.api", "build.ci", "release.notes", "lint.fix"],
    "design":    ["mock.generate", "asset.optimise", "palette.suggest", "layout.grid", "icon.find", "copy.tone"],
    "comms":     ["email.draft", "meeting.summarise", "slack.escalate", "newsletter.compose", "translation.apply", "tone.adjust"],
    "ops":       ["ticket.triage", "runbook.execute", "alert.cluster", "capacity.forecast", "incident.report", "sla.compute"],
    "marketing": ["campaign.brief", "lead.score", "ad.copy", "seo.audit", "persona.match", "funnel.report"],
    "security":  ["secret.scan", "vuln.assess", "access.review", "log.correlate", "phish.detect", "policy.enforce"],
    "data":      ["schema.infer", "data.profile", "pipeline.gen", "quality.check", "lineage.trace", "anonymise.apply"],
}

# Typed parameter pool. Inputs and outputs draw from these.
DOMAIN_DATATYPES: Dict[str, List[str]] = {
    "finance":   ["InvoicePdf", "ReceiptImage", "LedgerEntry", "ExpenseRow", "TaxReturn"],
    "legal":     ["ContractDocx", "RedlineDocx", "ClauseList", "ComplianceReport", "MsaDraft"],
    "hr":        ["Cv", "OfferLetter", "OnboardingKit", "ReviewForm", "PolicyDoc"],
    "dev":       ["PullRequest", "TestSuite", "ApiSpec", "BuildArtifact", "ReleaseNotes"],
    "design":    ["FigmaFrame", "ImageAsset", "PaletteSpec", "GridLayout", "IconBundle"],
    "comms":     ["EmailDraft", "MeetingTranscript", "SlackThread", "NewsletterMd", "TranslatedText"],
    "ops":       ["Ticket", "Runbook", "AlertGroup", "ForecastChart", "IncidentReport"],
    "marketing": ["CampaignBrief", "LeadList", "AdCopy", "SeoReport", "PersonaProfile"],
    "security":  ["SecretFinding", "VulnReport", "AccessMatrix", "LogBundle", "PhishSignal"],
    "data":      ["TableSchema", "ProfileReport", "PipelineSpec", "QualityScore", "LineageGraph"],
}

PRECONDITIONS = [
    "user.authenticated", "tenant.licensed", "storage.available",
    "model.loaded", "rate.budget.ok", "data.classified",
]

EFFECTS_SUFFIXES = [
    "file.written", "record.created", "notification.sent",
    "metric.emitted", "lineage.updated", "audit.logged",
]

CLASSIFICATIONS = ["public", "internal", "internal", "internal", "internal", "confidential", "confidential", "restricted"]
DETERMINISM = ["high", "high", "medium", "medium", "low"]
RISK = ["low", "low", "low", "medium", "medium", "high", "critical"]
STAGES = ["published"] * 8 + ["certified", "deprecated"]


def _slug(s: str) -> str:
    return s.lower().replace("_", "-")


def _gen_skill(
    domain: str,
    tier: int,
    idx: int,
    rng: random.Random,
    same_domain_lower: List[str],
    foreign_caps: List[str],
) -> Tuple[str, Dict[str, Any]]:
    """Build one manifest. Returns (skill_id, manifest_dict)."""
    name_suffix = f"t{tier}-s{idx:03d}"
    sid = f"{domain}/{name_suffix}"

    cap_pool = DOMAIN_CAPABILITIES[domain]
    caps = rng.sample(cap_pool, k=rng.randint(2, 3))
    # tier shapes a sub-namespace so capabilities don't all collide
    caps = [f"{c}.t{tier}" if tier > 0 else c for c in caps]

    dtype_pool = DOMAIN_DATATYPES[domain]
    inputs = [
        {"name": f"input_{i}", "type": rng.choice(dtype_pool), "required": True,
         "description": f"Input parameter {i} for {sid}"}
        for i in range(rng.randint(1, 2))
    ]
    outputs = [
        {"name": "result", "type": rng.choice(dtype_pool), "required": True,
         "description": f"Primary output of {sid}"}
    ]

    preconds = rng.sample(PRECONDITIONS, k=rng.randint(0, 2))
    effects = [f"{rng.choice(EFFECTS_SUFFIXES)}:{domain}/" for _ in range(rng.randint(0, 2))]

    # Dependencies: each tier-K skill depends on 0-3 capabilities from same-domain
    # lower tiers, plus ~10% chance of one cross-domain dependency.
    deps: List[Dict[str, Any]] = []
    if same_domain_lower:
        for ref in rng.sample(same_domain_lower, k=min(rng.randint(0, 3), len(same_domain_lower))):
            deps.append({"ref": ref, "optional": rng.random() < 0.15})
    if foreign_caps and rng.random() < 0.10:
        deps.append({"ref": rng.choice(foreign_caps), "optional": True})

    classification = rng.choice(CLASSIFICATIONS)

    manifest: Dict[str, Any] = {
        "apiVersion": "skills.dev/v1",
        "kind": "Skill",
        "identity": {
            "id": sid,
            "name": f"{domain.title()} {name_suffix}",
            "version": f"1.{tier}.{idx % 10}",
            "description": (
                f"Synthetic skill in the {domain} domain at composition tier {tier}. "
                f"Generated for ontology stress testing — not a real capability."
            ),
            "owner": {
                "handle": f"synth-{domain}",
                "team": f"{domain.title()} Synthetics",
                "contact": f"synth-{domain}@example.com",
            },
            "skillType": "deterministic-tool",
            "tags": [domain, f"tier-{tier}", "synthetic"],
        },
        "capability": {
            "summary": f"Synthetic {domain} capability tier {tier} #{idx}",
            "capabilityTags": caps,
            "inputs": inputs,
            "outputs": outputs,
            "preconditions": preconds,
            "effects": effects,
        },
        "scoring": {
            "determinism": rng.choice(DETERMINISM),
            "risk": rng.choice(RISK),
            "reversible": rng.random() < 0.7,
            "rationale": "Synthetic — score chosen randomly within domain norms.",
        },
        "dependencies": deps,
        "governance": {
            "visibility": "org",
            "rbac": [f"{domain}.reader"],
            "dataClassification": classification,
            "cost": {"unit": "usd-per-1k-calls", "estimate": round(rng.uniform(0.1, 5.0), 2)},
            "audit": {"logged": True, "retentionDays": 90},
        },
        "lifecycle": {
            "stage": rng.choice(STAGES),
        },
    }
    return sid, manifest


def generate(
    count: int,
    out_dir: str,
    *,
    seed: int = 42,
    tiers: int = 5,
) -> Dict[str, Any]:
    """Generate ``count`` manifests across ``DOMAINS`` × ``tiers``.

    Returns a summary dict. Files are written as ``{namespace}__{name}.manifest.json``
    (the ``/`` in skill ids is replaced with ``__`` for filesystem safety).
    """
    rng = random.Random(seed)
    os.makedirs(out_dir, exist_ok=True)

    per_domain = count // len(DOMAINS)
    per_tier = max(1, per_domain // tiers)

    # First pass: plan every (domain, tier, idx, sid) so we can wire
    # dependencies to known refs in a second pass.
    plan: Dict[str, List[List[str]]] = {d: [[] for _ in range(tiers)] for d in DOMAINS}
    cap_index_by_domain: Dict[str, List[str]] = {d: [] for d in DOMAINS}

    for d in DOMAINS:
        for t in range(tiers):
            for i in range(per_tier):
                sid = f"{d}/t{t}-s{i:03d}"
                plan[d][t].append(sid)

    # Build capability tag pool per domain (so foreign-domain deps reference real tags).
    for d in DOMAINS:
        for t in range(tiers):
            for cap in DOMAIN_CAPABILITIES[d]:
                tag = f"{cap}.t{t}" if t > 0 else cap
                if tag not in cap_index_by_domain[d]:
                    cap_index_by_domain[d].append(tag)

    written = 0
    for d in DOMAINS:
        # All capabilities in other domains, for cross-domain wiring.
        foreign_caps = [c for od in DOMAINS if od != d for c in cap_index_by_domain[od]]
        for t in range(tiers):
            # Lower-tier capability tags within this domain — what tier-t can depend on.
            same_domain_lower = []
            for lt in range(t):
                for cap in DOMAIN_CAPABILITIES[d]:
                    tag = f"{cap}.t{lt}" if lt > 0 else cap
                    same_domain_lower.append(tag)
            for idx, sid in enumerate(plan[d][t]):
                _, manifest = _gen_skill(d, t, idx, rng, same_domain_lower, foreign_caps)
                fname = sid.replace("/", "__") + ".manifest.json"
                with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as fh:
                    json.dump(manifest, fh, indent=2)
                written += 1
                if written >= count:
                    break
            if written >= count:
                break
        if written >= count:
            break

    return {
        "out_dir": out_dir,
        "count": written,
        "domains": len(DOMAINS),
        "tiers": tiers,
        "per_domain_target": per_domain,
    }


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count", type=int, default=1000, help="number of manifests to generate")
    p.add_argument("--out", required=True, help="output directory for manifests")
    p.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    p.add_argument("--tiers", type=int, default=5, help="composition tiers per domain (default 5)")
    args = p.parse_args()
    summary = generate(args.count, args.out, seed=args.seed, tiers=args.tiers)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
