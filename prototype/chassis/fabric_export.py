"""Part D - export manifests as parquet (Fabric IQ Ontology ingest format).

Walks every manifest in ``examples/`` and emits three parquet tables to
``prototype/out/fabric/``:

    * ``nodes.parquet``      — (node_id, node_type, label, properties_json)
                               covers Skill / Capability / DataType / Condition,
                               plus (when ``--org-dir`` is provided)
                               Person / Project / Training / Certification /
                               Role / Team.
    * ``edges.parquet``      — (src_id, edge_type, dst_id, confidence,
                               data_classification, properties_json) covers
                               PROVIDES / CONSUMES / PRODUCES / REQUIRES /
                               CAUSES / DEPENDS_ON / SUPERSEDES, plus (when
                               ``--org-dir`` is provided) HAS_ROLE / MEMBER_OF /
                               WORKED_ON / EMPLOYED / REQUIRED / SATISFIED_BY /
                               HOLDS_SKILL / COMPLETED / GRANTS / HOLDS_CERT.
    * ``manifests.parquet``  — flat denormalised view of each skill (id, name,
                               version, stage, tags, owner, governance class)
                               for Direct Lake reporting.
    * ``org_facts.parquet``  — (only when ``--org-dir`` is provided) one row per
                               person with role, team, skill / cert / project
                               counts for Direct Lake org dashboards.

These are the exact files the MCP server reads via ``ontology_query`` (local
DuckDB mode) and the exact files we upload to OneLake to back the Fabric SQL
endpoint (Fabric mode). Same bytes, two readers.

Idempotent — full rebuild each run. Small (<10 KB at current 23-skill catalog).
Single dependency: DuckDB (already used by the query layer).

CLI::

    python -m prototype.chassis.fabric_export --out prototype/out/fabric/

    # With the synthetic org graph projected in alongside skills:
    python -m prototype.chassis.fabric_export \\
        --out prototype/out/synth/parquet/ \\
        --examples prototype/out/synth/manifests/ \\
        --org-dir prototype/out/synth/org/
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Tuple

import duckdb

# Reuse the chassis loader (validates against the canonical schema).
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_LITE_DIR = os.path.join(_REPO_ROOT, "prototype-lite")
if _LITE_DIR not in sys.path:
    sys.path.insert(0, _LITE_DIR)

import lite  # noqa: E402

from .manifest import capability_tags, skill_id  # noqa: E402
from .ontology import (  # noqa: E402
    CAUSES,
    CONSUMES,
    DEPENDS_ON,
    PRODUCES,
    PROVIDES,
    REQUIRES,
    SUPERSEDES,
)

DEFAULT_OUT = os.path.join(_REPO_ROOT, "prototype", "out", "fabric")

# Bump when nodes/edges schema changes so query layer can refuse mismatches.
SCHEMA_VERSION = "ontology.parquet/v2"

# Org-graph edge type constants — Stage F Phase 1. Kept here (not in
# ontology.py) because they only matter at projection time; the recursive CTE
# in ontology_query.py is verb-agnostic.
HAS_ROLE = "HAS_ROLE"
MEMBER_OF = "MEMBER_OF"
WORKED_ON = "WORKED_ON"
EMPLOYED = "EMPLOYED"
REQUIRED = "REQUIRED"
SATISFIED_BY = "SATISFIED_BY"
HOLDS_SKILL = "HOLDS_SKILL"
COMPLETED = "COMPLETED"
GRANTS = "GRANTS"
HOLDS_CERT = "HOLDS_CERT"

ORG_EDGE_TYPES = {
    HAS_ROLE, MEMBER_OF, WORKED_ON, EMPLOYED, REQUIRED,
    SATISFIED_BY, HOLDS_SKILL, COMPLETED, GRANTS, HOLDS_CERT,
}


Node = Tuple[str, str, str, str]  # (id, type, label, properties_json)
Edge = Tuple[str, str, str, float, str, str]
#       (src_id, edge_type, dst_id, confidence, data_classification, props_json)


def _classification(manifest: Dict[str, Any]) -> str:
    return manifest.get("governance", {}).get("dataClassification", "internal")


def _extract(registry: lite.Registry) -> Tuple[List[Node], List[Edge], List[Dict[str, Any]]]:
    """Walk the registry once, return (nodes, edges, manifests_flat).

    Mirrors the entity/relationship emission rules in ``ontology.py`` so the
    parquet tables and the in-memory builder agent stay consistent. We *don't*
    invoke the builder here — we already have a closed catalog; this is a
    direct projection, not a proposal flow.
    """
    nodes: Dict[Tuple[str, str], Node] = {}
    edges: List[Edge] = []
    manifests_flat: List[Dict[str, Any]] = []

    def add_node(node_id: str, node_type: str, label: str = "", **props: Any) -> None:
        key = (node_type, node_id)
        if key in nodes:
            return
        nodes[key] = (node_id, node_type, label or node_id, json.dumps(props, sort_keys=True))

    def add_edge(src: str, edge_type: str, dst: str, confidence: float, classification: str, **props: Any) -> None:
        edges.append((src, edge_type, dst, confidence, classification, json.dumps(props, sort_keys=True)))

    for sid in sorted(registry.skills):
        m = registry.skills[sid]
        cls = _classification(m)
        identity = m.get("identity", {})
        lifecycle = m.get("lifecycle", {})

        add_node(
            sid,
            "Skill",
            label=identity.get("name", sid),
            version=identity.get("version", ""),
            stage=lifecycle.get("stage", ""),
        )

        for tag in capability_tags(m):
            add_node(tag, "Capability")
            add_edge(sid, PROVIDES, tag, 0.95, cls)

        capability = m.get("capability", {})
        for inp in capability.get("inputs", []):
            t = inp["type"]
            add_node(t, "DataType")
            add_edge(sid, CONSUMES, t, 0.9, cls, param=inp.get("name", ""))
        for out in capability.get("outputs", []):
            t = out["type"]
            add_node(t, "DataType")
            add_edge(sid, PRODUCES, t, 0.9, cls, param=out.get("name", ""))
        for cond in capability.get("preconditions", []):
            add_node(cond, "Condition")
            add_edge(sid, REQUIRES, cond, 0.85, cls)
        for eff in capability.get("effects", []):
            add_node(eff, "Condition")
            add_edge(sid, CAUSES, eff, 0.85, cls)

        for dep in m.get("dependencies", []):
            # Dependencies point at *capabilities* (e.g. "docx.create"); the
            # target Capability node already exists if any skill provides it,
            # otherwise we add a placeholder so the edge resolves.
            ref = dep["ref"]
            add_node(ref, "Capability")
            add_edge(sid, DEPENDS_ON, ref, 0.9, cls, optional=bool(dep.get("optional", False)))

        if lifecycle.get("supersedes"):
            add_edge(sid, SUPERSEDES, lifecycle["supersedes"], 0.95, cls)

        owner = identity.get("owner", {})
        manifests_flat.append(
            {
                "id": sid,
                "name": identity.get("name", sid),
                "version": identity.get("version", ""),
                "stage": lifecycle.get("stage", ""),
                "tags_json": json.dumps(capability_tags(m), sort_keys=True),
                "owner_handle": owner.get("handle", ""),
                "owner_team": owner.get("team", ""),
                "data_classification": cls,
                "determinism": m.get("scoring", {}).get("determinism", ""),
                "risk": m.get("scoring", {}).get("risk", ""),
            }
        )

    # Deterministic ordering so re-runs produce byte-identical parquet.
    node_rows = sorted(nodes.values(), key=lambda r: (r[1], r[0]))
    edge_rows = sorted(edges, key=lambda r: (r[0], r[1], r[2]))
    manifests_flat.sort(key=lambda r: r["id"])
    return node_rows, edge_rows, manifests_flat


def _extract_org(org_dir: str) -> Tuple[List[Node], List[Edge], List[Dict[str, Any]]]:
    """Walk a ``synth_org`` output directory and emit nodes/edges/facts.

    Layout expected (matches ``synth_org.generate``)::

        <org_dir>/
            person/*.json
            project/*.json
            training/*.json
            cert/*.json
            _edges.json

    Returns (nodes, edges, org_facts) where ``org_facts`` is one row per
    Person summarising their degree counts (used for Direct Lake reporting).
    """
    nodes: Dict[Tuple[str, str], Node] = {}
    edge_rows: List[Edge] = []

    def add_node(node_id: str, node_type: str, label: str = "", **props: Any) -> None:
        key = (node_type, node_id)
        if key in nodes:
            return
        nodes[key] = (node_id, node_type, label or node_id, json.dumps(props, sort_keys=True))

    entities_by_id: Dict[str, Dict[str, Any]] = {}

    def _load(sub: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for path in sorted(glob.glob(os.path.join(org_dir, sub, "*.json"))):
            with open(path, "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
        return out

    persons = _load("person")
    projects = _load("project")
    trainings = _load("training")
    certs = _load("cert")

    for p in persons:
        pid = p["id"]
        entities_by_id[pid] = p
        cls = p.get("governance", {}).get("dataClassification", "internal")
        add_node(
            pid, "Person",
            label=p.get("name", pid),
            role=p.get("role", ""),
            team=p.get("team", ""),
            data_classification=cls,
        )
        # Role and Team nodes get created from the edges below.

    for pr in projects:
        prid = pr["id"]
        entities_by_id[prid] = pr
        cls = pr.get("governance", {}).get("dataClassification", "internal")
        add_node(
            prid, "Project",
            label=pr.get("name", prid),
            domain=pr.get("domain", ""),
            status=pr.get("status", ""),
            data_classification=cls,
        )

    for t in trainings:
        tid = t["id"]
        entities_by_id[tid] = t
        add_node(
            tid, "Training",
            label=t.get("title", tid),
            provider=t.get("provider", ""),
            domain=t.get("domain", ""),
        )

    for c in certs:
        cid = c["id"]
        entities_by_id[cid] = c
        add_node(
            cid, "Certification",
            label=c.get("title", cid),
            issuer=c.get("issuer", ""),
            domain=c.get("domain", ""),
        )

    edges_path = os.path.join(org_dir, "_edges.json")
    raw_edges: List[Dict[str, Any]] = []
    if os.path.exists(edges_path):
        with open(edges_path, "r", encoding="utf-8") as fh:
            raw_edges = json.load(fh)

    # Counters for org_facts.
    person_skill_count: Dict[str, int] = {}
    person_cert_count: Dict[str, int] = {}
    person_project_count: Dict[str, int] = {}
    person_training_count: Dict[str, int] = {}

    for e in raw_edges:
        src = e["src"]
        dst = e["dst"]
        etype = e["type"]
        cls = e.get("classification", "internal")

        # Auto-create lightweight Role / Team nodes the first time they appear.
        if etype == HAS_ROLE:
            add_node(dst, "Role", label=dst.split("/", 1)[-1])
        elif etype == MEMBER_OF:
            add_node(dst, "Team", label=dst.split("/", 1)[-1])
        # Capability nodes already exist if the matching skill catalog was
        # projected first. If not (e.g. the projection is org-only) emit a
        # placeholder so edges still resolve.
        elif etype in (REQUIRED,):
            add_node(dst, "Capability")
        elif etype == SATISFIED_BY:
            add_node(src, "Capability")
            add_node(dst, "Skill")  # placeholder if not already projected

        edge_rows.append((src, etype, dst, 0.9, cls, "{}"))

        if etype == HOLDS_SKILL:
            person_skill_count[src] = person_skill_count.get(src, 0) + 1
        elif etype == HOLDS_CERT:
            person_cert_count[src] = person_cert_count.get(src, 0) + 1
        elif etype == WORKED_ON:
            person_project_count[src] = person_project_count.get(src, 0) + 1
        elif etype == COMPLETED:
            person_training_count[src] = person_training_count.get(src, 0) + 1

    org_facts: List[Dict[str, Any]] = []
    for p in persons:
        pid = p["id"]
        org_facts.append({
            "id": pid,
            "name": p.get("name", pid),
            "role": p.get("role", ""),
            "team": p.get("team", ""),
            "manager": p.get("manager") or "",
            "hire_date": p.get("hireDate", ""),
            "data_classification": p.get("governance", {}).get("dataClassification", "internal"),
            "skill_count": person_skill_count.get(pid, 0),
            "cert_count": person_cert_count.get(pid, 0),
            "project_count": person_project_count.get(pid, 0),
            "training_count": person_training_count.get(pid, 0),
        })

    node_rows = sorted(nodes.values(), key=lambda r: (r[1], r[0]))
    edge_rows.sort(key=lambda r: (r[0], r[1], r[2]))
    org_facts.sort(key=lambda r: r["id"])
    return node_rows, edge_rows, org_facts


def _merge_nodes(*node_lists: List[Node]) -> List[Node]:
    """De-dupe nodes across multiple extraction sources (by (type, id))."""
    seen: Dict[Tuple[str, str], Node] = {}
    for lst in node_lists:
        for row in lst:
            seen.setdefault((row[1], row[0]), row)
    return sorted(seen.values(), key=lambda r: (r[1], r[0]))


def _write_parquet(con: duckdb.DuckDBPyConnection, table: str, rows: Iterable[tuple], columns: List[str], out_path: str) -> None:
    """Materialise ``rows`` as a DuckDB table and COPY it to parquet.

    DuckDB writes parquet natively, so this avoids pulling in pyarrow.
    """
    rows = list(rows)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    col_defs = ", ".join(columns)
    con.execute(f"CREATE TABLE {table} ({col_defs})")
    if rows:
        placeholders = ", ".join(["?"] * len(rows[0]))
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    con.execute(f"COPY {table} TO '{out_path}' (FORMAT PARQUET)")


def export(out_dir: str = DEFAULT_OUT, *, examples_dir: str | None = None, org_dir: str | None = None) -> Dict[str, Any]:
    """Build the parquet tables. Returns a summary dict for callers/CLI.

    When ``org_dir`` is provided, additional Person/Project/Training/
    Certification/Role/Team nodes and the nine org-graph edge types are
    merged in alongside the skill projection, and ``org_facts.parquet`` is
    written. Without ``org_dir`` the output is byte-identical to the
    skill-only projection (modulo the v2 schema version sidecar).
    """
    registry = lite.Registry.from_dir(examples_dir or os.path.join(_REPO_ROOT, "examples"))
    skill_nodes, skill_edges, manifests_flat = _extract(registry)

    if org_dir:
        org_nodes, org_edges, org_facts = _extract_org(org_dir)
        nodes = _merge_nodes(skill_nodes, org_nodes)
        edges = sorted(skill_edges + org_edges, key=lambda r: (r[0], r[1], r[2]))
    else:
        nodes = skill_nodes
        edges = skill_edges
        org_facts = []

    os.makedirs(out_dir, exist_ok=True)
    con = duckdb.connect(":memory:")
    try:
        _write_parquet(
            con,
            "nodes",
            nodes,
            ["node_id VARCHAR", "node_type VARCHAR", "label VARCHAR", "properties_json VARCHAR"],
            os.path.join(out_dir, "nodes.parquet"),
        )
        _write_parquet(
            con,
            "edges",
            edges,
            [
                "src_id VARCHAR",
                "edge_type VARCHAR",
                "dst_id VARCHAR",
                "confidence DOUBLE",
                "data_classification VARCHAR",
                "properties_json VARCHAR",
            ],
            os.path.join(out_dir, "edges.parquet"),
        )
        manifest_rows = [
            (
                r["id"],
                r["name"],
                r["version"],
                r["stage"],
                r["tags_json"],
                r["owner_handle"],
                r["owner_team"],
                r["data_classification"],
                r["determinism"],
                r["risk"],
            )
            for r in manifests_flat
        ]
        _write_parquet(
            con,
            "manifests",
            manifest_rows,
            [
                "id VARCHAR",
                "name VARCHAR",
                "version VARCHAR",
                "stage VARCHAR",
                "tags_json VARCHAR",
                "owner_handle VARCHAR",
                "owner_team VARCHAR",
                "data_classification VARCHAR",
                "determinism VARCHAR",
                "risk VARCHAR",
            ],
            os.path.join(out_dir, "manifests.parquet"),
        )
        if org_dir:
            org_rows = [
                (
                    r["id"], r["name"], r["role"], r["team"], r["manager"],
                    r["hire_date"], r["data_classification"],
                    r["skill_count"], r["cert_count"], r["project_count"], r["training_count"],
                )
                for r in org_facts
            ]
            _write_parquet(
                con,
                "org_facts",
                org_rows,
                [
                    "id VARCHAR", "name VARCHAR", "role VARCHAR", "team VARCHAR", "manager VARCHAR",
                    "hire_date VARCHAR", "data_classification VARCHAR",
                    "skill_count INTEGER", "cert_count INTEGER", "project_count INTEGER", "training_count INTEGER",
                ],
                os.path.join(out_dir, "org_facts.parquet"),
            )
    finally:
        con.close()

    # Sidecar schema-version file so the query layer can refuse mismatches.
    with open(os.path.join(out_dir, "_schema_version.txt"), "w", encoding="utf-8") as fh:
        fh.write(SCHEMA_VERSION + "\n")

    summary = {
        "out_dir": out_dir,
        "schema_version": SCHEMA_VERSION,
        "nodes": len(nodes),
        "edges": len(edges),
        "skills": len(manifests_flat),
    }
    if org_dir:
        summary["org_people"] = len(org_facts)
        summary["org_dir"] = org_dir
    return summary


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=DEFAULT_OUT, help=f"output directory (default: {DEFAULT_OUT})")
    p.add_argument("--examples", default=None, help="override examples directory (test use)")
    p.add_argument("--org-dir", default=None, help="optional synth_org output dir to merge in (Stage F Phase 1)")
    args = p.parse_args()
    summary = export(args.out, examples_dir=args.examples, org_dir=args.org_dir)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
