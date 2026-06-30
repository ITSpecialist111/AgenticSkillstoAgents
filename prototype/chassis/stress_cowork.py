"""Stress-test the deployed :v7 MCP server with the same tool calls Cowork issues.

Hits the live Container Apps endpoint, captures per-call latency, envelope
fields, and writes a structured JSON record per task. Used to back the
ontology thesis (docs/ontology-skills-thesis.md).
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Set MCP_ENDPOINT to your deployed Container Apps URL, e.g.
#   export MCP_ENDPOINT=https://<your-mcp-fqdn>.azurecontainerapps.io/api/mcp
ENDPOINT = os.environ.get(
    "MCP_ENDPOINT",
    "https://<your-mcp-fqdn>.azurecontainerapps.io/api/mcp",
)
IMAGE_REF = os.environ.get("MCP_IMAGE_REF", "<your-acr>.azurecr.io/skills-registry-mcp:<tag>")
REVISION = os.environ.get("MCP_REVISION", "<your-container-app-revision>")
OUT = Path(__file__).resolve().parents[2] / "docs" / "stress-evidence.json"


async def call_tool(session: ClientSession, name: str, args: dict) -> tuple[dict, float]:
    t0 = time.perf_counter()
    result = await session.call_tool(name, args)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    payload: dict = {}
    for block in result.content:
        if getattr(block, "type", None) == "text":
            try:
                payload = json.loads(block.text)
            except json.JSONDecodeError:
                payload = {"raw_text": block.text[:500]}
            break
    return payload, dt_ms


async def run_task(session: ClientSession, label: str, calls: list[tuple[str, dict]]) -> dict:
    print(f"\n=== {label} ===")
    records = []
    for tool_name, args in calls:
        try:
            payload, dt = await call_tool(session, tool_name, args)
            summary = summarize(tool_name, payload)
            records.append(
                {"tool": tool_name, "args": args, "latency_ms": round(dt, 1), "summary": summary}
            )
            print(f"  {tool_name}({args})  ->  {dt:5.1f} ms  {summary}")
        except Exception as exc:
            records.append({"tool": tool_name, "args": args, "error": str(exc)})
            print(f"  {tool_name}({args})  ERROR  {exc}")
    return {"task": label, "calls": records}


def summarize(tool: str, payload: dict) -> dict:
    keep = {}
    for k in (
        "totalPaths",
        "suppressedByClassification",
        "truncated",
        "maxHopsApplied",
        "maxHopsRequested",
        "resultCount",
        "capabilityCount",
        "seed",
        "callerClassification",
        "nodeTypeFilter",
        "relation",
    ):
        if k in payload:
            keep[k] = payload[k]
    paths = payload.get("paths")
    if isinstance(paths, list):
        keep["pathsReturned"] = len(paths)
        endpoints = set()
        for p in paths[:50]:
            edges = p.get("edges", [])
            if edges:
                endpoints.add(edges[-1].get("dst"))
        keep["uniqueEndpoints"] = len(endpoints)
    if "entities" in payload and isinstance(payload["entities"], list):
        keep["entityCount"] = len(payload["entities"])
    if "capabilities" in payload and isinstance(payload["capabilities"], list):
        keep["capabilityCount"] = len(payload["capabilities"])
    if "skills" in payload and isinstance(payload["skills"], list):
        keep["skillCount"] = len(payload["skills"])
    return keep


async def main() -> None:
    print(f"Connecting to {ENDPOINT}")
    async with streamablehttp_client(ENDPOINT) as (read, write, _close):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Tools advertised: {[t.name for t in tools.tools]}")

            # T1 — Capability inventory at scale.
            t1 = await run_task(
                session,
                "T1 capability inventory at scale (1000-skill catalog)",
                [
                    ("list_capabilities", {}),
                    ("find_skill_by_capability", {"capability_tag": "invoice.extract"}),
                    ("find_skill_by_capability", {"capability_tag": "msa.redline"}),
                    ("find_skill_by_capability", {"capability_tag": "redline.apply.t2"}),
                ],
            )

            # T2 — Cross-domain Person -> Skill walk.
            t2_people = await run_task(
                session,
                "T2a list 10 Person entities",
                [("list_org_entities", {"entity_type": "Person", "limit": 10})],
            )
            person_seed = None
            for r in t2_people["calls"]:
                # peek into raw payload via a re-call; harness above kept summary only — so re-run quickly
                pass
            # Discover a person seed deterministically by listing again and grabbing first id
            payload, _ = await call_tool(
                session, "list_org_entities", {"entity_type": "Person", "limit": 25}
            )
            person_ids = [
                e.get("id") for e in payload.get("entities", []) if e.get("id", "").startswith("person/")
            ]
            person_seed = person_ids[0] if person_ids else "person/architect-004"
            print(f"  -> seed: {person_seed}")

            t2 = await run_task(
                session,
                "T2 cross-domain Person->Skill walk (node_type_filter)",
                [
                    (
                        "query_ontology",
                        {
                            "seed": person_seed,
                            "max_hops": 4,
                            "node_type_filter": ["Skill"],
                            "caller_classification": "internal",
                        },
                    ),
                ],
            )

            # T3 — Governance gating proof (internal vs confidential vs public).
            t3 = await run_task(
                session,
                "T3 governance gating across three clearances on same seed",
                [
                    (
                        "query_ontology",
                        {
                            "seed": person_seed,
                            "max_hops": 4,
                            "node_type_filter": ["Skill"],
                            "caller_classification": "public",
                        },
                    ),
                    (
                        "query_ontology",
                        {
                            "seed": person_seed,
                            "max_hops": 4,
                            "node_type_filter": ["Skill"],
                            "caller_classification": "internal",
                        },
                    ),
                    (
                        "query_ontology",
                        {
                            "seed": person_seed,
                            "max_hops": 4,
                            "node_type_filter": ["Skill"],
                            "caller_classification": "confidential",
                        },
                    ),
                ],
            )

            # T4 — Multi-hop capability composition from a synth skill.
            t4 = await run_task(
                session,
                "T4 multi-hop composition (skill DEPENDS_ON)",
                [
                    (
                        "query_ontology",
                        {
                            "seed": "legal/t2-s000",
                            "relation": "DEPENDS_ON",
                            "max_hops": 3,
                            "caller_classification": "confidential",
                        },
                    ),
                    (
                        "query_ontology",
                        {
                            "seed": "legal/t2-s000",
                            "max_hops": 3,
                            "caller_classification": "confidential",
                        },
                    ),
                ],
            )

            # T5 — 5-hop org reach from a Project seed.
            proj_payload, _ = await call_tool(
                session, "list_org_entities", {"entity_type": "Project", "limit": 5}
            )
            proj_seed = "project/finance-rfp-001"
            for e in proj_payload.get("entities", []):
                if e.get("id", "").startswith("project/"):
                    proj_seed = e["id"]
                    break
            print(f"  -> project seed: {proj_seed}")

            t5 = await run_task(
                session,
                "T5 5-hop org reach from Project seed",
                [
                    (
                        "query_ontology",
                        {
                            "seed": proj_seed,
                            "max_hops": 5,
                            "node_type_filter": ["Skill"],
                            "caller_classification": "confidential",
                        },
                    ),
                ],
            )

            # T6 — Supersession surfacing.
            t6 = await run_task(
                session,
                "T6 supersession / duplicate surfacing",
                [
                    (
                        "query_ontology",
                        {
                            "seed": "legal/t2-s000",
                            "relation": "SUPERSEDES",
                            "max_hops": 2,
                            "caller_classification": "confidential",
                        },
                    ),
                    (
                        "query_ontology",
                        {
                            "seed": "dev/t2-s000",
                            "relation": "SUPERSEDES",
                            "max_hops": 2,
                            "caller_classification": "confidential",
                        },
                    ),
                ],
            )

            # T7 — repeated-call latency distribution (warm cache) — bonus signal.
            print("\n=== T7 warm-cache latency distribution (20x query_ontology) ===")
            latencies = []
            for _ in range(20):
                _, dt = await call_tool(
                    session,
                    "query_ontology",
                    {
                        "seed": person_seed,
                        "max_hops": 3,
                        "node_type_filter": ["Skill"],
                        "caller_classification": "internal",
                    },
                )
                latencies.append(dt)
            latencies.sort()
            t7 = {
                "task": "T7 warm-cache latency distribution (n=20)",
                "p50_ms": round(statistics.median(latencies), 1),
                "p95_ms": round(latencies[int(0.95 * len(latencies)) - 1], 1),
                "min_ms": round(min(latencies), 1),
                "max_ms": round(max(latencies), 1),
                "mean_ms": round(statistics.mean(latencies), 1),
                "samples": [round(x, 1) for x in latencies],
            }
            print(
                f"  p50={t7['p50_ms']} ms p95={t7['p95_ms']} ms "
                f"min={t7['min_ms']} ms max={t7['max_ms']} ms mean={t7['mean_ms']} ms"
            )

            evidence = {
                "endpoint": ENDPOINT,
                "image": IMAGE_REF,
                "revision": REVISION,
                "graph_scale": {"nodes": 2348, "edges": 20440, "skills": 1000, "people": 500},
                "tools_advertised": [t.name for t in tools.tools],
                "person_seed": person_seed,
                "project_seed": proj_seed,
                "tasks": [t1, t2_people, t2, t3, t4, t5, t6],
                "latency_distribution": t7,
            }
            OUT.write_text(json.dumps(evidence, indent=2))
            print(f"\nWrote evidence -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
