"""Part D - export manifests as parquet (Fabric IQ Ontology ingest format).

Walks every manifest in ``examples/`` and emits three parquet tables to
``prototype/out/fabric/``:

    * ``nodes.parquet``      — (node_id, node_type, label, properties_json)
                               covers Skill / Capability / DataType / Condition.
    * ``edges.parquet``      — (src_id, edge_type, dst_id, confidence,
                               data_classification, properties_json) covers
                               PROVIDES / CONSUMES / PRODUCES / REQUIRES /
                               CAUSES / DEPENDS_ON / SUPERSEDES.
    * ``manifests.parquet``  — flat denormalised view of each skill (id, name,
                               version, stage, tags, owner, governance class)
                               for Direct Lake reporting.

These are the exact files the MCP server reads via ``ontology_query`` (local
DuckDB mode) and the exact files we upload to OneLake to back the Fabric SQL
endpoint (Fabric mode). Same bytes, two readers.

Idempotent — full rebuild each run. Small (<10 KB at current 23-skill catalog).
Single dependency: DuckDB (already used by the query layer).

CLI::

    python -m prototype.chassis.fabric_export --out prototype/out/fabric/
"""

from __future__ import annotations

import argparse
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
SCHEMA_VERSION = "ontology.parquet/v1"


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


def export(out_dir: str = DEFAULT_OUT, *, examples_dir: str | None = None) -> Dict[str, Any]:
    """Build the parquet tables. Returns a summary dict for callers/CLI."""
    registry = lite.Registry.from_dir(examples_dir or os.path.join(_REPO_ROOT, "examples"))
    nodes, edges, manifests_flat = _extract(registry)

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
    finally:
        con.close()

    # Sidecar schema-version file so the query layer can refuse mismatches.
    with open(os.path.join(out_dir, "_schema_version.txt"), "w", encoding="utf-8") as fh:
        fh.write(SCHEMA_VERSION + "\n")

    return {
        "out_dir": out_dir,
        "schema_version": SCHEMA_VERSION,
        "nodes": len(nodes),
        "edges": len(edges),
        "skills": len(manifests_flat),
    }


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=DEFAULT_OUT, help=f"output directory (default: {DEFAULT_OUT})")
    p.add_argument("--examples", default=None, help="override examples directory (test use)")
    args = p.parse_args()
    summary = export(args.out, examples_dir=args.examples)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
