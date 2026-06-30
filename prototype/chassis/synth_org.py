"""Synthetic org-graph generator for Stage F Phase 1.

Produces a deterministic Person / Project / Training / Certification dataset
that sits *alongside* a skill catalog (typically produced by
``synth_skills``) and projects into the same parquet store the
``query_ontology`` MCP tool reads. Together they let an agent walk
Person → HOLDS_SKILL → Skill → DEPENDS_ON → Capability — the cross-domain
multi-hop shape Stage F is built for.

Topology
--------
- People: assigned a role (PM / Eng / Designer / Analyst / Architect /
  Legal / Finance / Ops) and a team. Roles weight which domains they hold
  skills in (PMs hold few, broad; Engs hold many, deep in dev/data).
- Projects: belong to a domain, list 2-5 required capability tags drawn
  from the synth-skills capability pool. 3-8 people work on each.
- Training: granted by a provider, covers 1-3 capability tags. ~40%
  grant a Certification.
- Certifications: long-lived, imply 1-3 capability tags.

Edges emitted (written to ``_edges.json`` for the projection step):
    PERSON   --HAS_ROLE-->     ROLE
    PERSON   --MEMBER_OF-->    TEAM
    PERSON   --WORKED_ON-->    PROJECT
    PROJECT  --EMPLOYED-->     PERSON  (symmetric to WORKED_ON)
    PROJECT  --REQUIRED-->     CAPABILITY
    CAPABILITY --SATISFIED_BY--> SKILL  (derived from existing PROVIDES)
    PERSON   --HOLDS_SKILL-->  SKILL
    PERSON   --COMPLETED-->    TRAINING
    TRAINING --GRANTS-->       CERTIFICATION
    PERSON   --HOLDS_CERT-->   CERTIFICATION  (derived from COMPLETED + GRANTS)

Output layout::

    out/
      person/eng-042.json
      project/dev-platform-007.json
      training/dev-python-advanced.json
      cert/aws-architect.json
      _edges.json
      _summary.json

CLI::

    python -m prototype.chassis.synth_org \\
        --count-people 500 --count-projects 200 \\
        --out prototype/out/synth/org \\
        --skills-dir prototype/out/synth/manifests
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
from typing import Any, Dict, List, Tuple

# Roles weight role × domain skill density. Each entry is
# (role, [(domain, weight)]). Weights drive sampling of HOLDS_SKILL edges.
ROLE_DOMAIN_WEIGHTS: Dict[str, List[Tuple[str, float]]] = {
    "PM":         [("ops", 3), ("comms", 3), ("marketing", 2), ("dev", 1), ("data", 1)],
    "Eng":        [("dev", 5), ("data", 3), ("security", 2), ("ops", 1)],
    "Designer":   [("design", 5), ("marketing", 2), ("comms", 1)],
    "Analyst":    [("data", 4), ("finance", 3), ("marketing", 2), ("ops", 1)],
    "Architect":  [("dev", 3), ("data", 3), ("security", 3), ("ops", 2)],
    "Legal":      [("legal", 5), ("comms", 1)],
    "Finance":    [("finance", 5), ("ops", 1), ("data", 1)],
    "Ops":        [("ops", 5), ("security", 2), ("dev", 1)],
    "HR":         [("hr", 5), ("comms", 1), ("legal", 1)],
    "Marketing":  [("marketing", 5), ("comms", 3), ("design", 1)],
}

# Skill-count distribution by role (mean, stddev). PMs hold few skills broadly,
# Engs hold many deeply.
ROLE_SKILL_COUNT: Dict[str, Tuple[int, int]] = {
    "PM":         (5, 2),
    "Eng":        (12, 3),
    "Designer":   (7, 2),
    "Analyst":    (9, 3),
    "Architect":  (14, 3),
    "Legal":      (6, 2),
    "Finance":    (7, 2),
    "Ops":        (8, 3),
    "HR":         (5, 2),
    "Marketing":  (7, 2),
}

ROLES = list(ROLE_DOMAIN_WEIGHTS.keys())

TEAMS = [
    "Platform", "Apps", "Data Platform", "Security", "Design Systems",
    "Marketing Cloud", "Sales Ops", "People Ops", "Finance Ops",
    "Legal Ops", "Customer Success", "Research",
]

PROJECT_STATUSES = ["active"] * 6 + ["complete"] * 3 + ["archived"]
PROJECT_DOMAINS = [
    "finance", "legal", "hr", "dev", "design",
    "comms", "ops", "marketing", "security", "data",
]

TRAINING_PROVIDERS = [
    "Pluralsight", "Coursera", "Udemy", "LinkedIn Learning",
    "Internal Academy", "O'Reilly", "A Cloud Guru",
]

CERT_ISSUERS = [
    "AWS", "Microsoft", "Google", "ISC2", "PMI",
    "Scaled Agile", "Linux Foundation", "Internal",
]

# Classifications are weighted toward internal; ~5% of execs (PMs +
# Architects + Legal) hit confidential.
CLASSIFICATIONS_DEFAULT = ["internal"] * 18 + ["public"] * 1 + ["confidential"] * 1
CLASSIFICATIONS_EXEC = ["internal"] * 12 + ["confidential"] * 6 + ["restricted"] * 2


def _slug(s: str) -> str:
    return s.lower().replace(" ", "-").replace("_", "-")


def _load_capability_pool(skills_dir: str) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Walk ``skills_dir`` and build:
      - per-domain capability pool (capability_tag -> list of skill_ids)
      - per-skill capability list (skill_id -> list of capability_tags)
    """
    cap_to_skills: Dict[str, List[str]] = {}
    skill_to_caps: Dict[str, List[str]] = {}
    domain_caps: Dict[str, List[str]] = {}

    for path in sorted(glob.glob(os.path.join(skills_dir, "*.manifest.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            m = json.load(fh)
        sid = m.get("identity", {}).get("id")
        if not sid:
            continue
        caps = list(m.get("capability", {}).get("capabilityTags", []))
        skill_to_caps[sid] = caps
        # Domain is the namespace prefix of the skill id (e.g. "dev" in "dev/t2-s003").
        domain = sid.split("/", 1)[0]
        for c in caps:
            cap_to_skills.setdefault(c, []).append(sid)
            domain_caps.setdefault(domain, [])
            if c not in domain_caps[domain]:
                domain_caps[domain].append(c)
    return domain_caps, cap_to_skills


def _classification_for(role: str, rng: random.Random) -> str:
    pool = CLASSIFICATIONS_EXEC if role in ("PM", "Architect", "Legal") else CLASSIFICATIONS_DEFAULT
    return rng.choice(pool)


def _gen_person(
    idx: int,
    role: str,
    team: str,
    manager_id: str | None,
    rng: random.Random,
) -> Tuple[str, Dict[str, Any]]:
    pid = f"person/{_slug(role)}-{idx:03d}"
    classification = _classification_for(role, rng)
    return pid, {
        "id": pid,
        "kind": "Person",
        "name": f"{role} #{idx:03d}",
        "role": role,
        "team": team,
        "manager": manager_id,
        "hireDate": f"20{rng.randint(15, 25):02d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        "governance": {
            "dataClassification": classification,
            "visibility": "org",
        },
    }


def _gen_project(
    idx: int,
    domain: str,
    rng: random.Random,
    capability_pool: List[str],
) -> Tuple[str, Dict[str, Any], List[str]]:
    slug = f"{domain}-p{idx:03d}"
    pid = f"project/{slug}"
    required_caps = rng.sample(capability_pool, k=min(rng.randint(2, 5), len(capability_pool)))
    status = rng.choice(PROJECT_STATUSES)
    year = rng.randint(2024, 2026)
    return pid, {
        "id": pid,
        "kind": "Project",
        "name": f"{domain.title()} Project {idx:03d}",
        "domain": domain,
        "status": status,
        "startDate": f"{year}-{rng.randint(1, 12):02d}-01",
        "endDate": f"{year + 1}-{rng.randint(1, 12):02d}-01" if status != "active" else None,
        "requiredCapabilities": required_caps,
        "governance": {
            "dataClassification": rng.choice(CLASSIFICATIONS_DEFAULT),
            "visibility": "org",
        },
    }, required_caps


def _gen_training(
    idx: int,
    domain: str,
    rng: random.Random,
    capability_pool: List[str],
    cert_id: str | None,
) -> Tuple[str, Dict[str, Any]]:
    slug = f"{domain}-c{idx:03d}"
    tid = f"training/{slug}"
    covers = rng.sample(capability_pool, k=min(rng.randint(1, 3), len(capability_pool)))
    return tid, {
        "id": tid,
        "kind": "Training",
        "title": f"{domain.title()} Course {idx:03d}",
        "provider": rng.choice(TRAINING_PROVIDERS),
        "durationHours": rng.choice([2, 4, 8, 16, 24, 40]),
        "domain": domain,
        "coversCapabilities": covers,
        "grantsCertification": cert_id,
        "governance": {
            "dataClassification": "internal",
            "visibility": "org",
        },
    }


def _gen_cert(idx: int, domain: str, rng: random.Random, capability_pool: List[str]) -> Tuple[str, Dict[str, Any]]:
    issuer = rng.choice(CERT_ISSUERS)
    slug = f"{_slug(issuer)}-{domain}-{idx:03d}"
    cid = f"cert/{slug}"
    implies = rng.sample(capability_pool, k=min(rng.randint(1, 3), len(capability_pool)))
    return cid, {
        "id": cid,
        "kind": "Certification",
        "title": f"{issuer} {domain.title()} Certified",
        "issuer": issuer,
        "domain": domain,
        "validityYears": rng.choice([1, 2, 3]),
        "impliesCapabilities": implies,
        "governance": {
            "dataClassification": "internal",
            "visibility": "org",
        },
    }


def generate(
    count_people: int,
    count_projects: int,
    count_training: int,
    count_certs: int,
    out_dir: str,
    skills_dir: str,
    *,
    seed: int = 42,
) -> Dict[str, Any]:
    """Build the synthetic org graph. Returns a summary dict."""
    rng = random.Random(seed)
    domain_caps, cap_to_skills = _load_capability_pool(skills_dir)
    if not domain_caps:
        raise SystemExit(f"No capability tags found in {skills_dir} — did you run synth_skills first?")

    # Directory layout: one subdir per entity kind for readability.
    for sub in ("person", "project", "training", "cert"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)

    edges: List[Dict[str, Any]] = []

    # --- Certifications first (training references them).
    certs_by_id: Dict[str, Dict[str, Any]] = {}
    cert_caps: Dict[str, List[str]] = {}
    for i in range(count_certs):
        domain = rng.choice(PROJECT_DOMAINS)
        pool = domain_caps.get(domain, [])
        if not pool:
            continue
        cid, cert = _gen_cert(i, domain, rng, pool)
        certs_by_id[cid] = cert
        cert_caps[cid] = cert["impliesCapabilities"]
        with open(os.path.join(out_dir, "cert", f"{cid.split('/', 1)[1]}.json"), "w", encoding="utf-8") as fh:
            json.dump(cert, fh, indent=2)

    # --- Training. ~40% grant a cert.
    trainings_by_id: Dict[str, Dict[str, Any]] = {}
    training_grants: Dict[str, str] = {}
    cert_ids = list(certs_by_id.keys())
    for i in range(count_training):
        domain = rng.choice(PROJECT_DOMAINS)
        pool = domain_caps.get(domain, [])
        if not pool:
            continue
        cert_id = rng.choice(cert_ids) if cert_ids and rng.random() < 0.4 else None
        tid, training = _gen_training(i, domain, rng, pool, cert_id)
        trainings_by_id[tid] = training
        if cert_id:
            training_grants[tid] = cert_id
            edges.append({"src": tid, "type": "GRANTS", "dst": cert_id, "classification": "internal"})
        with open(os.path.join(out_dir, "training", f"{tid.split('/', 1)[1]}.json"), "w", encoding="utf-8") as fh:
            json.dump(training, fh, indent=2)

    # --- Projects.
    projects_by_id: Dict[str, Dict[str, Any]] = {}
    project_caps: Dict[str, List[str]] = {}
    for i in range(count_projects):
        domain = rng.choice(PROJECT_DOMAINS)
        pool = domain_caps.get(domain, [])
        if not pool:
            continue
        pid, project, required = _gen_project(i, domain, rng, pool)
        projects_by_id[pid] = project
        project_caps[pid] = required
        for cap in required:
            edges.append({
                "src": pid, "type": "REQUIRED", "dst": cap,
                "classification": project["governance"]["dataClassification"],
            })
        with open(os.path.join(out_dir, "project", f"{pid.split('/', 1)[1]}.json"), "w", encoding="utf-8") as fh:
            json.dump(project, fh, indent=2)

    # --- People. Distribute roughly evenly across roles; first 10% are managers.
    persons_by_id: Dict[str, Dict[str, Any]] = {}
    manager_pool: List[str] = []
    for i in range(count_people):
        role = ROLES[i % len(ROLES)]
        team = rng.choice(TEAMS)
        manager_id = rng.choice(manager_pool) if manager_pool and rng.random() < 0.85 else None
        pid, person = _gen_person(i, role, team, manager_id, rng)
        persons_by_id[pid] = person
        if i < count_people // 10:
            manager_pool.append(pid)
        with open(os.path.join(out_dir, "person", f"{pid.split('/', 1)[1]}.json"), "w", encoding="utf-8") as fh:
            json.dump(person, fh, indent=2)

        # HAS_ROLE / MEMBER_OF.
        role_node = f"role/{_slug(role)}"
        team_node = f"team/{_slug(team)}"
        edges.append({"src": pid, "type": "HAS_ROLE", "dst": role_node, "classification": person["governance"]["dataClassification"]})
        edges.append({"src": pid, "type": "MEMBER_OF", "dst": team_node, "classification": person["governance"]["dataClassification"]})

        # HOLDS_SKILL — weighted by role × domain.
        mean, sd = ROLE_SKILL_COUNT[role]
        n_skills = max(1, int(rng.gauss(mean, sd)))
        weighted_domains = ROLE_DOMAIN_WEIGHTS[role]
        chosen_skills: List[str] = []
        attempts = 0
        while len(chosen_skills) < n_skills and attempts < n_skills * 5:
            attempts += 1
            domain = rng.choices(
                [d for d, _ in weighted_domains],
                weights=[w for _, w in weighted_domains],
            )[0]
            pool = domain_caps.get(domain, [])
            if not pool:
                continue
            cap = rng.choice(pool)
            candidate_skills = cap_to_skills.get(cap, [])
            if not candidate_skills:
                continue
            sid = rng.choice(candidate_skills)
            if sid not in chosen_skills:
                chosen_skills.append(sid)
        for sid in chosen_skills:
            edges.append({
                "src": pid, "type": "HOLDS_SKILL", "dst": sid,
                "classification": person["governance"]["dataClassification"],
            })

        # COMPLETED training + derived HOLDS_CERT.
        n_training = rng.randint(0, 6)
        training_ids = list(trainings_by_id.keys())
        if training_ids:
            chosen = rng.sample(training_ids, k=min(n_training, len(training_ids)))
            for tid in chosen:
                edges.append({
                    "src": pid, "type": "COMPLETED", "dst": tid,
                    "classification": "internal",
                })
                cert_id = training_grants.get(tid)
                if cert_id:
                    edges.append({
                        "src": pid, "type": "HOLDS_CERT", "dst": cert_id,
                        "classification": "internal",
                    })

    # --- WORKED_ON / EMPLOYED. 3-8 people per project (or fewer if archived).
    person_ids = list(persons_by_id.keys())
    for pid, project in projects_by_id.items():
        cap = 8 if project["status"] == "active" else 4
        n_workers = rng.randint(3, cap)
        workers = rng.sample(person_ids, k=min(n_workers, len(person_ids)))
        for w in workers:
            cls = persons_by_id[w]["governance"]["dataClassification"]
            edges.append({"src": w, "type": "WORKED_ON", "dst": pid, "classification": cls})
            edges.append({"src": pid, "type": "EMPLOYED", "dst": w, "classification": cls})

    # --- CAPABILITY --SATISFIED_BY--> SKILL — derived from PROVIDES.
    # The projection step already emits PROVIDES (Skill→Capability); SATISFIED_BY
    # is the inverse view a Project→Capability traversal needs to reach a Skill.
    for cap, sids in cap_to_skills.items():
        for sid in sids:
            edges.append({"src": cap, "type": "SATISFIED_BY", "dst": sid, "classification": "internal"})

    # Stable ordering for deterministic projection output.
    edges.sort(key=lambda e: (e["src"], e["type"], e["dst"]))

    with open(os.path.join(out_dir, "_edges.json"), "w", encoding="utf-8") as fh:
        json.dump(edges, fh, indent=2)

    summary = {
        "out_dir": out_dir,
        "people": len(persons_by_id),
        "projects": len(projects_by_id),
        "training": len(trainings_by_id),
        "certs": len(certs_by_id),
        "edges": len(edges),
        "skills_source": skills_dir,
        "domains": sorted(domain_caps.keys()),
        "capability_pool_size": sum(len(v) for v in domain_caps.values()),
    }
    with open(os.path.join(out_dir, "_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    return summary


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count-people", type=int, default=500)
    p.add_argument("--count-projects", type=int, default=200)
    p.add_argument("--count-training", type=int, default=150)
    p.add_argument("--count-certs", type=int, default=60)
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--skills-dir", required=True, help="manifests directory the org graph cross-links into")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    summary = generate(
        args.count_people,
        args.count_projects,
        args.count_training,
        args.count_certs,
        args.out,
        args.skills_dir,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
