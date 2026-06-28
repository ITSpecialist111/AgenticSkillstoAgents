"""Registry MCP server — thin adapter over prototype-lite's Registry.

Exposes three read-only discovery tools to any MCP client (Microsoft Copilot
Cowork plugin, Claude Desktop, Copilot Studio agent, etc.):

    find_skill_by_capability(tag, published_only=True) -> [SkillSummary]
    describe_skill(skill_id)                            -> Manifest
    list_capabilities()                                 -> {tag: [skill_id, ...]}

Two catalog backends (selected via env):
    REGISTRY_CATALOG_MODE=local       -> glob ../examples/*.manifest.json  (default)
    REGISTRY_CATALOG_MODE=remote      -> GET REGISTRY_CATALOG_URL          (Stage 2)

Two transports (selected via env):
    MCP_TRANSPORT=stdio               (default — dev, Claude Desktop, tests)
    MCP_TRANSPORT=http                (Cowork: Streamable HTTP at POST /api/mcp)

Run:
    python -m server                  # stdio
    MCP_TRANSPORT=http python -m server   # HTTP on $PORT (default 8000)

See docs/cowork-plugin-spike.md for the full contract.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

# Reuse the chassis instead of reimplementing — single source of truth for
# manifest loading, validation, and capability indexing.
_HERE = os.path.dirname(os.path.abspath(__file__))
_LITE_DIR = os.path.join(os.path.dirname(_HERE), "prototype-lite")
if _LITE_DIR not in sys.path:
    sys.path.insert(0, _LITE_DIR)

import lite  # noqa: E402  (sys.path manipulation above)


class CatalogError(RuntimeError):
    pass


def load_registry(*, examples_dir: Optional[str] = None) -> lite.Registry:
    """Load the registry from the configured backend.

    ``examples_dir`` overrides everything (useful for tests). Otherwise the
    REGISTRY_CATALOG_MODE env var picks the backend.
    """
    if examples_dir is not None:
        return lite.Registry.from_dir(examples_dir)

    mode = os.environ.get("REGISTRY_CATALOG_MODE", "local").lower()
    if mode == "local":
        return lite.Registry.from_dir()
    if mode == "remote":
        url = os.environ.get("REGISTRY_CATALOG_URL")
        if not url:
            raise CatalogError("REGISTRY_CATALOG_MODE=remote needs REGISTRY_CATALOG_URL")
        raise CatalogError(
            "remote catalog backend not yet implemented — Stage 2 must be deployed first"
        )
    raise CatalogError(f"unknown REGISTRY_CATALOG_MODE: {mode!r}")


# --- Pure tool implementations (testable without an MCP client) ---------------


def _summary(manifest: lite.Manifest) -> Dict[str, Any]:
    """Compact view returned by find_skill_by_capability — enough for the agent
    to decide whether to call describe_skill for the full manifest."""
    return {
        "id": manifest["identity"]["id"],
        "name": manifest["identity"]["name"],
        "version": manifest["identity"]["version"],
        "stage": manifest["lifecycle"]["stage"],
        "capabilityTags": list(manifest.get("capability", {}).get("capabilityTags", [])),
        "mcp": dict(manifest.get("mcp", {})),
    }


def tool_find_skill_by_capability(
    registry: lite.Registry, tag: str, published_only: bool = True
) -> List[Dict[str, Any]]:
    return [_summary(m) for m in registry.find_by_capability(tag, published_only=published_only)]


def tool_describe_skill(registry: lite.Registry, skill_id: str) -> Dict[str, Any]:
    if skill_id not in registry.skills:
        raise KeyError(f"unknown skill_id: {skill_id!r}")
    return registry.skills[skill_id]


def tool_list_capabilities(registry: lite.Registry) -> Dict[str, List[str]]:
    return {tag: sorted(sids) for tag, sids in sorted(registry.list_capabilities().items())}


# --- MCP transport wrapper ----------------------------------------------------


# Cowork's remoteMcpServer.mcpServerUrl points at this path. Keep it stable.
MCP_HTTP_PATH = "/api/mcp"


def build_server():
    """Build a FastMCP server with the three discovery tools registered.

    Kept in a function so tests can import the pure ``tool_*`` functions above
    without booting the MCP SDK.
    """
    from mcp.server.fastmcp import FastMCP

    registry = load_registry()
    server = FastMCP("skills-registry")
    # Mount the streamable-HTTP endpoint at /api/mcp so the Cowork connector
    # spec lines up with the TomTom POC pattern (and any other client that
    # already speaks Streamable HTTP).
    server.settings.streamable_http_path = MCP_HTTP_PATH

    @server.tool(
        description=(
            "Find skills that provide a given capability tag (e.g. 'invoice.extract'). "
            "Returns a list of skill summaries including the MCP binding needed to call "
            "each skill. By default only returns published skills."
        )
    )
    def find_skill_by_capability(tag: str, published_only: bool = True) -> List[Dict[str, Any]]:
        return tool_find_skill_by_capability(registry, tag, published_only=published_only)

    @server.tool(
        description=(
            "Return the full manifest for a skill, including governance (RBAC, data "
            "classification), scoring (determinism, risk), preconditions, and effects."
        )
    )
    def describe_skill(skill_id: str) -> Dict[str, Any]:
        return tool_describe_skill(registry, skill_id)

    @server.tool(
        description=(
            "List every capability tag in the registry mapped to the skills that "
            "provide it. Use this for catalog discovery before you have a specific task."
        )
    )
    def list_capabilities() -> Dict[str, List[str]]:
        return tool_list_capabilities(registry)

    return server


def build_http_app(server=None):
    """Wrap the FastMCP streamable-HTTP app with a friendly GET probe + /health.

    Cowork only needs POST /api/mcp, but a GET probe makes manual testing and
    Container Apps health checks much less mysterious.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route, Mount

    server = server or build_server()
    mcp_app = server.streamable_http_app()

    async def probe(_request):
        return JSONResponse(
            {
                "service": "skills-registry-mcp",
                "transport": "streamable-http",
                "endpoint": MCP_HTTP_PATH,
                "method": "POST (JSON-RPC 2.0)",
                "tools": ["find_skill_by_capability", "describe_skill", "list_capabilities"],
            }
        )

    async def health(_request):
        return JSONResponse({"status": "ok"})

    # Order matters: GET probe is registered first so it wins for GET /api/mcp;
    # the FastMCP app handles POST + the rest of the protocol surface.
    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route(MCP_HTTP_PATH, probe, methods=["GET"]),
            Mount("/", app=mcp_app),
        ]
    )


def main() -> int:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport == "stdio":
        build_server().run()  # stdio transport
        return 0
    if transport in {"http", "streamable-http"}:
        import uvicorn

        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "8000"))
        uvicorn.run(build_http_app(), host=host, port=port, log_level="info")
        return 0
    print(f"unknown MCP_TRANSPORT: {transport!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
