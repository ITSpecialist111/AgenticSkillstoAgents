"""Ontology query layer — DuckDB local backend + Fabric SQL endpoint stub.

The MCP ``query_ontology`` tool talks to whichever backend ``make_ontology()``
returns. Both implement the same ``OntologyQuery`` protocol so swapping is an
env-var flip:

    ONTOLOGY_BACKEND=local   -> DuckDBOntology (default, reads parquet locally)
    ONTOLOGY_BACKEND=fabric  -> FabricOntology (calls Fabric SQL endpoint)

The local backend reads the parquet files emitted by
``prototype/chassis/fabric_export.py``. The Fabric backend will hit the same
parquet uploaded to OneLake via the Fabric SQL endpoint — same schema, same
queries, different engine. That's the whole point of an interface here.

A "path" is a list of hops; each hop carries provenance (source, edge type,
target, confidence, data classification) so the agent can explain *why* it
recommended what it recommended.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

# Cap server-side. Recursive traversal is fast on a 10k-node graph but
# unbounded depth invites pathological queries.
MAX_HOPS_CEILING = 5


@dataclass
class Hop:
    src_id: str
    edge_type: str
    dst_id: str
    confidence: float
    data_classification: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "src": self.src_id,
            "edge": self.edge_type,
            "dst": self.dst_id,
            "confidence": self.confidence,
            "data_classification": self.data_classification,
        }


@dataclass
class Path:
    hops: List[Hop] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return len(self.hops)

    @property
    def endpoint(self) -> Optional[str]:
        return self.hops[-1].dst_id if self.hops else None

    @property
    def max_classification(self) -> str:
        """Highest-sensitivity classification on any hop in the path."""
        if not self.hops:
            return "public"
        order = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
        return max(self.hops, key=lambda h: order.get(h.data_classification, 1)).data_classification

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hops": [h.to_dict() for h in self.hops],
            "depth": self.depth,
            "endpoint": self.endpoint,
            "max_classification": self.max_classification,
        }


class OntologyQuery(Protocol):
    """Both DuckDB and Fabric implementations satisfy this."""

    def paths(
        self,
        seed: str,
        relation: Optional[str],
        max_hops: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Path]:
        ...


# --- DuckDB (local parquet) ---------------------------------------------------


class DuckDBOntology:
    """Reads the parquet files emitted by ``fabric_export``.

    Uses a recursive CTE over the edges table. The traversal is breadth-first
    and stops at ``max_hops`` or when a cycle is detected (path containment).
    """

    def __init__(self, parquet_dir: str):
        self.parquet_dir = parquet_dir
        nodes_path = os.path.join(parquet_dir, "nodes.parquet")
        edges_path = os.path.join(parquet_dir, "edges.parquet")
        if not os.path.exists(edges_path):
            raise FileNotFoundError(
                f"edges.parquet missing in {parquet_dir!r}; run "
                f"`python -m prototype.chassis.fabric_export --out {parquet_dir}` first"
            )
        self._nodes_path = nodes_path
        self._edges_path = edges_path

    def paths(
        self,
        seed: str,
        relation: Optional[str],
        max_hops: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Path]:
        max_hops = max(1, min(int(max_hops), MAX_HOPS_CEILING))
        import duckdb

        con = duckdb.connect(":memory:")
        try:
            con.execute(
                f"CREATE VIEW edges AS SELECT * FROM read_parquet('{self._edges_path}')"
            )
            relation_clause = "AND e.edge_type = ?" if relation else ""
            params: List[Any] = [seed]
            if relation:
                params.append(relation)
            params.append(max_hops)

            query = f"""
                WITH RECURSIVE walk AS (
                    SELECT
                        e.src_id            AS root,
                        1                   AS depth,
                        list_value(struct_pack(
                            src := e.src_id,
                            edge := e.edge_type,
                            dst := e.dst_id,
                            confidence := e.confidence,
                            data_classification := e.data_classification
                        )) AS hops,
                        e.dst_id            AS frontier
                    FROM edges e
                    WHERE e.src_id = ? {relation_clause}

                    UNION ALL

                    SELECT
                        w.root,
                        w.depth + 1,
                        list_append(w.hops, struct_pack(
                            src := e.src_id,
                            edge := e.edge_type,
                            dst := e.dst_id,
                            confidence := e.confidence,
                            data_classification := e.data_classification
                        )),
                        e.dst_id
                    FROM walk w
                    JOIN edges e ON e.src_id = w.frontier
                    WHERE w.depth < ?
                      AND NOT list_contains([h.dst FOR h IN w.hops], e.dst_id)
                      AND e.dst_id <> w.root
                )
                SELECT hops FROM walk ORDER BY depth, frontier
            """
            rows = con.execute(query, params).fetchall()
        finally:
            con.close()

        results: List[Path] = []
        for (hops_struct,) in rows:
            results.append(
                Path(
                    hops=[
                        Hop(
                            src_id=h["src"],
                            edge_type=h["edge"],
                            dst_id=h["dst"],
                            confidence=float(h["confidence"]),
                            data_classification=h["data_classification"],
                        )
                        for h in hops_struct
                    ]
                )
            )
        return results


# --- Fabric SQL endpoint (stub) ----------------------------------------------


class FabricOntology:
    """Queries a Fabric Lakehouse SQL endpoint over the same schema.

    Stubbed for now — the wiring happens once the user runs the runbook in
    ``docs/fabric-iq-setup.md`` and uploads the parquet to OneLake. The query
    text is byte-identical to the DuckDB path because Fabric SQL also supports
    ``WITH RECURSIVE``; the only diff is connection + auth.
    """

    def __init__(self, sql_endpoint: str, *, database: str = "skills_ontology"):
        self.sql_endpoint = sql_endpoint
        self.database = database

    def paths(
        self,
        seed: str,
        relation: Optional[str],
        max_hops: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Path]:
        raise NotImplementedError(
            "Fabric backend is wired up by docs/fabric-iq-setup.md. "
            "Once you have a SQL endpoint URI, set FABRIC_SQL_ENDPOINT and "
            "implement this method with pyodbc + ManagedIdentityCredential."
        )


# --- selector -----------------------------------------------------------------


def default_parquet_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    return os.path.join(repo_root, "prototype", "out", "fabric")


def make_ontology() -> OntologyQuery:
    """Pick the backend off ONTOLOGY_BACKEND. Defaults to local DuckDB."""
    backend = os.environ.get("ONTOLOGY_BACKEND", "local").lower()
    if backend == "local":
        parquet_dir = os.environ.get("ONTOLOGY_PARQUET_DIR", default_parquet_dir())
        return DuckDBOntology(parquet_dir)
    if backend == "fabric":
        endpoint = os.environ.get("FABRIC_SQL_ENDPOINT")
        if not endpoint:
            raise RuntimeError(
                "ONTOLOGY_BACKEND=fabric requires FABRIC_SQL_ENDPOINT (see "
                "docs/fabric-iq-setup.md)"
            )
        return FabricOntology(endpoint)
    raise RuntimeError(f"unknown ONTOLOGY_BACKEND: {backend!r}")
