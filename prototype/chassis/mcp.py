"""MCP-compatible publish surface - ride MCP, don't rebuild it.

The roadmap's Phase 1 calls for an *MCP-compatible publish step* so published
skills are discoverable by MCP clients/agents. The chassis already carries an
``mcp`` block on each manifest (server / namespace / toolName / transport); this
module projects the **published** catalog into the shape an MCP ``tools/list``
response uses, deriving a JSON-Schema ``inputSchema`` from the manifest's IOPE
inputs.

This is a *projection*, not a server: it produces the catalog document so an MCP
transport (or the HTTP API) can serve it. Keeping it pure makes it trivial to
test and free of any MCP SDK dependency.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .manifest import Manifest, skill_id
from .registry import Stage

# Map the manifest's logical IOPE type names onto JSON-Schema primitives. Unknown
# logical types fall back to ``string`` but keep their logical name in a hint, so
# no information is lost for consumers that understand the domain types.
_JSON_PRIMITIVES = {"string", "number", "integer", "boolean", "object", "array"}


def _input_schema(manifest: Manifest) -> Dict[str, Any]:
    cap = manifest.get("capability", {})
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for param in cap.get("inputs", []):
        name = param["name"]
        logical = param["type"]
        json_type = logical if logical in _JSON_PRIMITIVES else "string"
        prop: Dict[str, Any] = {"type": json_type}
        if logical not in _JSON_PRIMITIVES:
            prop["x-logicalType"] = logical
        if param.get("description"):
            prop["description"] = param["description"]
        properties[name] = prop
        if param.get("required"):
            required.append(name)
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _tool_name(manifest: Manifest) -> str:
    mcp = manifest.get("mcp", {})
    if mcp.get("toolName"):
        return str(mcp["toolName"])
    # Derive a stable tool name from namespace + skill name segment.
    namespace = mcp.get("namespace", "")
    name_seg = skill_id(manifest).split("/")[-1]
    return f"{namespace}.{name_seg}" if namespace else name_seg


def to_mcp_tool(manifest: Manifest) -> Dict[str, Any]:
    """Project a single manifest into an MCP ``tools/list`` entry."""
    cap = manifest.get("capability", {})
    mcp = manifest.get("mcp", {})
    return {
        "name": _tool_name(manifest),
        "description": cap.get("summary", ""),
        "inputSchema": _input_schema(manifest),
        # Non-standard but namespaced metadata MCP clients may ignore or use.
        "_meta": {
            "skillId": skill_id(manifest),
            "namespace": mcp.get("namespace"),
            "server": mcp.get("server"),
            "transport": mcp.get("transport"),
            "capabilityTags": cap.get("capabilityTags", []),
            "determinism": manifest.get("scoring", {}).get("determinism"),
            "risk": manifest.get("scoring", {}).get("risk"),
        },
    }


def published_catalog(manifests: List[Manifest]) -> Dict[str, Any]:
    """Return an MCP ``tools/list``-shaped catalog of *published* skills only."""
    tools = [
        to_mcp_tool(m)
        for m in manifests
        if m.get("lifecycle", {}).get("stage") == Stage.PUBLISHED.value
    ]
    tools.sort(key=lambda t: t["name"])
    return {"tools": tools}


__all__ = ["to_mcp_tool", "published_catalog"]
