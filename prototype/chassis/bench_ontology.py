"""Stress-test query_ontology against an arbitrary parquet directory.

Picks 100 random Skill seeds from the manifests table and runs query_ontology
across a sweep of (relation, max_hops) combinations. Reports per-query
latency percentiles and average path counts.

Run after generating + exporting a synthetic catalog::

    python -m prototype.chassis.synth_skills --count 1000 --out prototype/out/synth/manifests
    python -m prototype.chassis.fabric_export --out prototype/out/synth/parquet --examples prototype/out/synth/manifests
    python -m prototype.chassis.bench_ontology --parquet prototype/out/synth/parquet
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import List, Tuple

# Make the MCP server's ontology_query importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_MCP = os.path.join(_REPO_ROOT, "mcp-server")
if _MCP not in sys.path:
    sys.path.insert(0, _MCP)

import duckdb  # noqa: E402
import ontology_query  # noqa: E402


def _seeds(parquet_dir: str, n: int) -> List[str]:
    """Pick N skill ids from manifests.parquet. Deterministic."""
    con = duckdb.connect(":memory:")
    try:
        rows = con.execute(
            f"SELECT id FROM read_parquet('{os.path.join(parquet_dir, 'manifests.parquet')}') ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    ids = [r[0] for r in rows]
    if len(ids) <= n:
        return ids
    # Even stride so we sample across all domains/tiers.
    stride = len(ids) // n
    return [ids[i * stride] for i in range(n)]


def _org_seeds(parquet_dir: str, node_type: str, n: int) -> List[str]:
    """Pick N node ids of a given type from nodes.parquet. Deterministic stride."""
    nodes_path = os.path.join(parquet_dir, "nodes.parquet")
    if not os.path.exists(nodes_path):
        return []
    con = duckdb.connect(":memory:")
    try:
        rows = con.execute(
            f"SELECT node_id FROM read_parquet('{nodes_path}') WHERE node_type = ? ORDER BY node_id",
            [node_type],
        ).fetchall()
    finally:
        con.close()
    ids = [r[0] for r in rows]
    if len(ids) <= n:
        return ids
    stride = len(ids) // n
    return [ids[i * stride] for i in range(n)]


def _bench_one(ont: ontology_query.OntologyQuery, seed: str, relation: str | None, max_hops: int, node_type_filter: list[str] | None = None) -> Tuple[float, int]:
    t0 = time.perf_counter()
    paths = ont.paths(seed=seed, relation=relation, max_hops=max_hops, node_type_filter=node_type_filter)
    dt = (time.perf_counter() - t0) * 1000.0  # ms
    return dt, len(paths)


def run(parquet_dir: str, seed_count: int = 100, include_org: bool = False) -> None:
    print(f"== ontology bench ==  parquet={parquet_dir}  seeds={seed_count}  include_org={include_org}")
    ont = ontology_query.DuckDBOntology(parquet_dir)
    seeds = _seeds(parquet_dir, seed_count)

    sweeps: List[Tuple[str, str | None, int, list[str] | None]] = [
        ("skill",  "DEPENDS_ON", 1, None),
        ("skill",  "DEPENDS_ON", 2, None),
        ("skill",  "DEPENDS_ON", 3, None),
        ("skill",  "DEPENDS_ON", 5, None),
        ("skill",  "PROVIDES",   1, None),
        ("skill",  None,         2, None),
        ("skill",  None,         3, None),
    ]

    if include_org:
        # Stage F Phase 1 sweep — cross-domain seeds with Person/Project starts.
        # Pass criterion: p95 < 500ms per sweep on a 1k-skill + 500-person catalog.
        sweeps.extend([
            ("person",  "HOLDS_SKILL", 1, None),
            ("person",  "HOLDS_SKILL", 2, None),
            ("person",  "WORKED_ON",   1, None),
            ("person",  "WORKED_ON",   2, None),
            ("person",  "WORKED_ON",   3, None),
            ("person",  None,          5, ["Skill"]),  # 5-hop Person→Skill (filtered)
            ("project", None,          5, ["Skill"]),  # 5-hop Project→Skill
        ])

    person_seeds = _org_seeds(parquet_dir, "Person", seed_count) if include_org else []
    project_seeds = _org_seeds(parquet_dir, "Project", seed_count) if include_org else []

    for seed_kind, relation, max_hops, ntf in sweeps:
        if seed_kind == "skill":
            chosen = seeds
        elif seed_kind == "person":
            chosen = person_seeds
        elif seed_kind == "project":
            chosen = project_seeds
        else:
            continue
        if not chosen:
            print(f"  rel={(relation or 'ANY'):<11} hops={max_hops}  seed_kind={seed_kind}  SKIPPED (no seeds)")
            continue

        latencies: List[float] = []
        path_counts: List[int] = []
        for sid in chosen:
            dt, n = _bench_one(ont, sid, relation, max_hops, ntf)
            latencies.append(dt)
            path_counts.append(n)
        rel_label = relation or "ANY"
        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
        p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
        mean = statistics.mean(latencies)
        avg_paths = statistics.mean(path_counts)
        max_paths = max(path_counts)
        ntf_label = f" ntf={','.join(ntf)}" if ntf else ""
        print(
            f"  seed={seed_kind:<7} rel={rel_label:<11} hops={max_hops}{ntf_label}  "
            f"p50={p50:6.1f}ms  p95={p95:7.1f}ms  p99={p99:7.1f}ms  mean={mean:6.1f}ms  "
            f"avg_paths={avg_paths:7.1f}  max_paths={max_paths}"
        )


def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet", required=True, help="parquet directory (nodes/edges/manifests)")
    p.add_argument("--seeds", type=int, default=100, help="seed count (default 100)")
    p.add_argument("--include-org", action="store_true",
                   help="add Stage F cross-domain sweeps (Person/Project seeds)")
    args = p.parse_args()
    run(args.parquet, seed_count=args.seeds, include_org=args.include_org)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
