"""Registry MCP server — thin adapter over prototype-lite's Registry.

Exposes read-only discovery tools, MCP resources for skill payloads, and one
write-side tool that opens a GitHub PR to register a new skill:

    find_skill_by_capability(tag, published_only=True) -> [SkillSummary]
    describe_skill(skill_id)                            -> Manifest + payloadFiles
    list_capabilities()                                 -> {tag: [skill_id, ...]}
    query_ontology(seed, relation, max_hops)            -> {paths, totalPaths, ...}
    submit_skill_draft(manifest, payload=None, ...)     -> {pr_url, branch, ...}

    skill://<slug>/<rel_path>                           -> raw payload file bytes

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

import base64
import json
import mimetypes
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Reuse the chassis instead of reimplementing — single source of truth for
# manifest loading, validation, and capability indexing.
_HERE = os.path.dirname(os.path.abspath(__file__))
_LITE_DIR = os.path.join(os.path.dirname(_HERE), "prototype-lite")
if _LITE_DIR not in sys.path:
    sys.path.insert(0, _LITE_DIR)

import lite  # noqa: E402  (sys.path manipulation above)


class CatalogError(RuntimeError):
    pass


class SubmitError(RuntimeError):
    pass


# Hard cap on payload file size we will serve over MCP. Anything bigger should
# live in object storage and be referenced by URL from the manifest.
_PAYLOAD_MAX_BYTES = 256 * 1024  # 256 KB

# Ensure markdown is recognised as text on every platform — the stdlib's
# mimetypes mapping for .md varies between OSes and Docker base images.
mimetypes.add_type("text/markdown", ".md")


def _examples_dir(override: Optional[str] = None) -> str:
    if override is not None:
        return override
    return os.path.join(os.path.dirname(_HERE), "examples")


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
        ttl = float(os.environ.get("REGISTRY_CATALOG_TTL", "60"))
        return _load_remote_registry(url, ttl_seconds=ttl)
    raise CatalogError(f"unknown REGISTRY_CATALOG_MODE: {mode!r}")


# Module-level cache for the remote catalog. The Stage 2 blob barely changes
# (publish-catalog.yml runs on push to main), so a 60s TTL keeps the MCP server
# responsive without hammering blob storage on every tool call.
_REMOTE_CACHE: Dict[str, Tuple[float, lite.Registry]] = {}


def _load_remote_registry(
    url: str,
    *,
    ttl_seconds: float = 60.0,
    http_client: Optional[Any] = None,
    now: Optional[float] = None,
) -> lite.Registry:
    """GET the catalog.json blob and build a Registry from it.

    ``http_client`` and ``now`` are injected by tests; production paths use
    httpx + time.monotonic().
    """
    current = now if now is not None else time.monotonic()
    cached = _REMOTE_CACHE.get(url)
    if cached and (current - cached[0]) < ttl_seconds:
        return cached[1]

    own_client = False
    if http_client is None:
        import httpx

        # When the catalog blob lives behind AAD (private container + managed
        # identity), attach a Bearer token. Storage's REST API requires
        # x-ms-version on AAD-authenticated requests.
        extra_headers: Dict[str, str] = {}
        if os.environ.get("REGISTRY_CATALOG_AUTH", "").lower() == "managed_identity":
            from azure.identity import DefaultAzureCredential

            token = DefaultAzureCredential().get_token("https://storage.azure.com/.default")
            extra_headers["Authorization"] = f"Bearer {token.token}"
            extra_headers["x-ms-version"] = "2021-12-02"

        http_client = httpx.Client(timeout=15.0, headers=extra_headers or None)
        own_client = True
    try:
        try:
            r = http_client.get(url)
        except Exception as exc:
            raise CatalogError(f"remote catalog GET failed: {exc}") from exc
        if getattr(r, "status_code", 0) != 200:
            raise CatalogError(
                f"remote catalog GET returned {getattr(r, 'status_code', '?')}: "
                f"{getattr(r, 'text', '')[:200]}"
            )
        try:
            catalog = r.json()
        except Exception as exc:
            raise CatalogError(f"remote catalog is not valid JSON: {exc}") from exc
    finally:
        if own_client:
            http_client.close()

    try:
        registry = lite.Registry.from_catalog(catalog)
    except lite.ManifestError as exc:
        raise CatalogError(f"remote catalog rejected: {exc}") from exc

    _REMOTE_CACHE[url] = (current, registry)
    return registry


def _clear_remote_cache() -> None:
    """Test helper — wipes the module-level TTL cache."""
    _REMOTE_CACHE.clear()


# --- Skill payload conventions ------------------------------------------------
#
# Each skill <slug> = skill_id.replace("/", "-"). The payload folder is
# examples/<slug>/ alongside examples/<filename>.manifest.json. Files inside
# that folder are exposed as MCP resources at skill://<slug>/<rel_path>.
#
# Resources let an agent read SKILL.md + assets WITHOUT the contents being
# injected into the system prompt — i.e. they don't count against Cowork's
# 20-tool / context-window cap.


def _slug(skill_id: str) -> str:
    return skill_id.replace("/", "-")


def _payload_dir(examples_dir: str, skill_id: str) -> str:
    return os.path.join(examples_dir, _slug(skill_id))


def _list_payload_files(examples_dir: str, skill_id: str) -> List[str]:
    """Return rel-path strings (sorted, POSIX-style) for the skill's payload."""
    root = _payload_dir(examples_dir, skill_id)
    if not os.path.isdir(root):
        return []
    out: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out.append(rel)
    return sorted(out)


def _read_payload_file(examples_dir: str, skill_id: str, rel_path: str) -> Tuple[bytes, str]:
    """Return (bytes, mime_type) for a single payload file.

    Guards against path traversal: the resolved path must live inside the
    skill's payload directory.
    """
    root = os.path.abspath(_payload_dir(examples_dir, skill_id))
    target = os.path.abspath(os.path.join(root, rel_path))
    if os.path.commonpath([root, target]) != root:
        raise KeyError(f"path escapes payload directory: {rel_path!r}")
    if not os.path.isfile(target):
        raise KeyError(f"no such payload file: {skill_id}/{rel_path}")
    if os.path.getsize(target) > _PAYLOAD_MAX_BYTES:
        raise ValueError(
            f"payload file {skill_id}/{rel_path} exceeds {_PAYLOAD_MAX_BYTES} bytes"
        )
    with open(target, "rb") as fh:
        data = fh.read()
    mime, _enc = mimetypes.guess_type(rel_path)
    if mime is None:
        mime = "application/octet-stream"
    return data, mime


# Inlining cap per file. SKILL.md bodies are typically 5–15 KB; this leaves
# headroom for assets without blowing the describe_skill response budget.
_INLINE_MAX_BYTES = 64 * 1024  # 64 KB per file


def _is_text_mime(mime: str) -> bool:
    if mime.startswith("text/"):
        return True
    return mime in {
        "application/json",
        "application/yaml",
        "application/x-yaml",
        "application/xml",
        "application/javascript",
        "application/markdown",
    }


def _payload_summary(examples_dir: str, skill_id: str) -> List[Dict[str, Any]]:
    """Compact list of {path, uri, mimeType, sizeBytes, content?} for describe_skill.

    For text payloads <=_INLINE_MAX_BYTES, includes the file body inline under
    `content` so the calling agent can act on SKILL.md without a second fetch.
    The `uri` field is retained for backwards compatibility and for binary or
    oversized files that cannot be inlined.
    """
    files = _list_payload_files(examples_dir, skill_id)
    slug = _slug(skill_id)
    root = _payload_dir(examples_dir, skill_id)
    out: List[Dict[str, Any]] = []
    for rel in files:
        mime, _enc = mimetypes.guess_type(rel)
        mime = mime or "application/octet-stream"
        full = os.path.join(root, rel)
        try:
            size = os.path.getsize(full)
        except OSError:
            size = 0
        entry: Dict[str, Any] = {
            "path": rel,
            "uri": f"skill://{slug}/{rel}",
            "mimeType": mime,
            "sizeBytes": size,
        }
        if _is_text_mime(mime) and 0 < size <= _INLINE_MAX_BYTES:
            try:
                with open(full, "rb") as fh:
                    entry["content"] = fh.read().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                pass
        out.append(entry)
    return out


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


def tool_describe_skill(
    registry: lite.Registry, skill_id: str, *, examples_dir: Optional[str] = None
) -> Dict[str, Any]:
    if skill_id not in registry.skills:
        raise KeyError(f"unknown skill_id: {skill_id!r}")
    manifest = dict(registry.skills[skill_id])
    manifest["payloadFiles"] = _payload_summary(_examples_dir(examples_dir), skill_id)
    return manifest


def tool_list_capabilities(registry: lite.Registry) -> Dict[str, List[str]]:
    return {tag: sorted(sids) for tag, sids in sorted(registry.list_capabilities().items())}


# --- query_ontology -----------------------------------------------------------
#
# Stage D: graph traversal over the skills registry. Reads parquet emitted by
# ``prototype/chassis/fabric_export.py`` via DuckDB locally; the same query
# runs against the Fabric SQL endpoint once the runbook is followed.

# Classification ranking used to suppress paths the caller isn't cleared for.
_CLASSIFICATION_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def tool_query_ontology(
    seed: str,
    relation: Optional[str] = None,
    max_hops: int = 3,
    caller_classification: str = "internal",
    *,
    ontology: Optional[Any] = None,
    result_limit: int = 50,
) -> Dict[str, Any]:
    """Return graph paths from ``seed`` up to ``max_hops`` deep.

    ``relation`` filters the first hop (e.g. ``DEPENDS_ON``, ``PROVIDES``).
    ``caller_classification`` gates paths whose max-sensitivity edge exceeds
    the caller's clearance — defaults to ``internal`` (suppresses confidential
    and restricted) until Stage E wires real principals.
    """
    from ontology_query import make_ontology, MAX_HOPS_CEILING

    if ontology is None:
        ontology = make_ontology()

    requested = max(1, int(max_hops))
    effective = min(requested, MAX_HOPS_CEILING)
    paths = ontology.paths(seed, relation, effective)

    caller_rank = _CLASSIFICATION_RANK.get(caller_classification.lower(), 1)
    visible = [
        p for p in paths
        if _CLASSIFICATION_RANK.get(p.max_classification, 1) <= caller_rank
    ]
    suppressed = len(paths) - len(visible)

    truncated = False
    if len(visible) > result_limit:
        visible = visible[:result_limit]
        truncated = True

    return {
        "seed": seed,
        "relation": relation,
        "maxHopsRequested": requested,
        "maxHopsApplied": effective,
        "callerClassification": caller_classification,
        "totalPaths": len(paths),
        "suppressedByClassification": suppressed,
        "truncated": truncated,
        "paths": [p.to_dict() for p in visible],
    }


# --- submit_skill_draft -------------------------------------------------------
#
# Two-way registration: an agent (or human via Cowork) can propose a new skill
# without leaving the chat. The tool validates the manifest against the schema,
# then opens a GitHub PR. The PR review IS the Register gate — nothing lands on
# main without a human approver, which keeps the "trust" pillar intact.

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _validate_manifest(manifest: Dict[str, Any]) -> None:
    """Schema-validate the submitted manifest. Raises SubmitError on failure."""
    try:
        errors = sorted(
            lite._get_validator().iter_errors(manifest), key=lambda e: list(e.path)
        )
    except Exception as exc:  # pragma: no cover — schema file missing is a bug
        raise SubmitError(f"could not load manifest schema: {exc}") from exc
    if errors:
        joined = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors
        )
        raise SubmitError(f"manifest failed schema validation: {joined}")


def _safe_payload_paths(payload: Dict[str, str]) -> None:
    """Reject absolute paths, traversal segments, or empty file contents."""
    for rel, content in payload.items():
        if not rel or rel.startswith("/") or ".." in rel.replace("\\", "/").split("/"):
            raise SubmitError(f"unsafe payload path: {rel!r}")
        if not isinstance(content, str):
            raise SubmitError(f"payload {rel!r} must be a string (UTF-8 text)")


def tool_submit_skill_draft(
    *,
    manifest: Dict[str, Any],
    payload: Optional[Dict[str, str]] = None,
    title: str = "",
    body: str = "",
    github_token: Optional[str] = None,
    github_repo: Optional[str] = None,
    base_branch: str = "main",
    http_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Open a GitHub PR adding a new skill manifest (+ optional payload files).

    Returns ``{pr_url, branch, files_added}``. Raises ``SubmitError`` on bad
    input or GitHub API failure. Pass ``http_client`` (an ``httpx.Client``-like
    object) to make this testable without network access.
    """
    _validate_manifest(manifest)
    payload = payload or {}
    _safe_payload_paths(payload)

    skill_id = manifest["identity"]["id"]
    if "/" not in skill_id:
        raise SubmitError(f"skill_id must contain a '/': {skill_id!r}")
    slug_parts = [p for p in skill_id.split("/") if p]
    for part in slug_parts:
        if not _SLUG_RE.match(part):
            raise SubmitError(f"skill_id segment {part!r} must match {_SLUG_RE.pattern}")
    slug = _slug(skill_id)
    filename_slug = slug_parts[-1]  # mirror examples/<last>.manifest.json convention

    token = github_token or os.environ.get("GITHUB_TOKEN")
    repo = github_repo or os.environ.get("GITHUB_REPO", "ITSpecialist111/AgenticSkillstoAgents")
    if not token:
        raise SubmitError("GITHUB_TOKEN is not set; cannot open a PR")

    if http_client is None:
        import httpx

        http_client = httpx.Client(timeout=30.0)
        _own_client = True
    else:
        _own_client = False

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api = f"https://api.github.com/repos/{repo}"
    branch = f"agent/submit-{slug}-{os.urandom(4).hex()}"

    files_to_write: Dict[str, str] = {
        f"examples/{filename_slug}.manifest.json": json.dumps(manifest, indent=2) + "\n",
    }
    for rel, content in payload.items():
        files_to_write[f"examples/{slug}/{rel}"] = content

    try:
        # 1. Resolve base ref SHA so we can branch off it.
        r = http_client.get(f"{api}/git/refs/heads/{base_branch}", headers=headers)
        if r.status_code != 200:
            raise SubmitError(f"GET base ref failed ({r.status_code}): {r.text}")
        base_sha = r.json()["object"]["sha"]

        # 2. Create the new branch.
        r = http_client.post(
            f"{api}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if r.status_code not in (200, 201):
            raise SubmitError(f"create branch failed ({r.status_code}): {r.text}")

        # 3. PUT each file onto the new branch.
        files_added: List[str] = []
        for path, content in files_to_write.items():
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            r = http_client.put(
                f"{api}/contents/{path}",
                headers=headers,
                json={
                    "message": f"submit_skill_draft: add {path}",
                    "content": encoded,
                    "branch": branch,
                },
            )
            if r.status_code not in (200, 201):
                raise SubmitError(f"PUT {path} failed ({r.status_code}): {r.text}")
            files_added.append(path)

        # 4. Open the PR.
        pr_title = title or f"Register skill: {skill_id}"
        pr_body = body or (
            f"Submitted via `submit_skill_draft` MCP tool.\n\n"
            f"- skill id: `{skill_id}`\n"
            f"- version: `{manifest['identity'].get('version', '?')}`\n"
            f"- capability tags: {manifest.get('capability', {}).get('capabilityTags', [])}\n\n"
            f"This PR is the **Register gate** — a human reviewer must approve before merge."
        )
        r = http_client.post(
            f"{api}/pulls",
            headers=headers,
            json={"title": pr_title, "head": branch, "base": base_branch, "body": pr_body},
        )
        if r.status_code not in (200, 201):
            raise SubmitError(f"create PR failed ({r.status_code}): {r.text}")
        pr = r.json()
        return {
            "pr_url": pr.get("html_url"),
            "pr_number": pr.get("number"),
            "branch": branch,
            "files_added": files_added,
        }
    finally:
        if _own_client:
            http_client.close()


# --- finance-tools stub MCP server -------------------------------------------
#
# Wires the second half of the registry pattern: an actual skill server that
# the agent dials via the binding the registry returned. Mounted in the same
# container at /api/skills/finance-tools/mcp so the spike has zero extra infra.
# Real deployments would run each skill server as its own service.


def build_finance_tools_server():
    """A minimal FastMCP server exposing the invoice_extract tool that the
    finance/invoice-extract skill manifest binds to."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    server = FastMCP("finance-tools")
    server.settings.streamable_http_path = "/mcp"
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    @server.tool(
        description=(
            "Extract structured fields from an invoice document. Pass the URL of a "
            "PDF or image invoice; returns vendor, invoice number, dates, line items, "
            "subtotal/tax/total. Deterministic OCR+rules pipeline (stubbed in this spike)."
        )
    )
    def invoice_extract(document_url: str) -> Dict[str, Any]:
        # Stub: a real implementation would fetch + OCR the document. The point
        # of the spike is to prove the registry → binding → invoke loop, not to
        # build OCR. The shape matches examples/invoice-extract/sample-output.json.
        return {
            "vendor": "Acme Widgets Ltd",
            "invoice_number": "INV-2026-04829",
            "issue_date": "2026-06-15",
            "due_date": "2026-07-15",
            "currency": "GBP",
            "subtotal": 1240.00,
            "tax": 248.00,
            "total": 1488.00,
            "line_items": [
                {"sku": "WIDGET-A", "qty": 10, "unit_price": 49.00, "amount": 490.00},
                {"sku": "WIDGET-B", "qty": 15, "unit_price": 50.00, "amount": 750.00},
            ],
            "_source_url": document_url,
            "_extraction_method": "stub-spike-v1",
        }

    return server


# --- MCP transport wrapper ----------------------------------------------------


# Cowork's remoteMcpServer.mcpServerUrl points at this path. Keep it stable.
MCP_HTTP_PATH = "/api/mcp"


def build_server(*, examples_dir: Optional[str] = None):
    """Build a FastMCP server with discovery tools + skill:// resources registered.

    Kept in a function so tests can import the pure ``tool_*`` functions above
    without booting the MCP SDK.
    """
    from mcp.server.fastmcp import FastMCP

    registry = load_registry(examples_dir=examples_dir)
    ex_dir = _examples_dir(examples_dir)
    server = FastMCP("skills-registry")

    # Stage E: one append-only event per tool call. Backend selected by
    # TELEMETRY_BACKEND env var (null/stdout/jsonl). Default null keeps
    # tests quiet; Container Apps deploys set it to ``stdout`` so events
    # surface in Log Analytics with no extra wiring.
    from telemetry import make_telemetry, record_call
    tel = make_telemetry()

    # Mount the streamable-HTTP endpoint at /api/mcp so the Cowork connector
    # spec lines up with the TomTom POC pattern (and any other client that
    # already speaks Streamable HTTP).
    server.settings.streamable_http_path = MCP_HTTP_PATH
    # The MCP SDK's DNS-rebinding protection rejects any Host header it hasn't
    # been told about (returns 421 "Invalid Host header"). For a public Cowork-
    # facing endpoint the Host arrives as whatever fqdn the client called, so
    # we either need to enumerate every caller or disable the check. The spike
    # has no auth either way — relaxing this is the smaller risk.
    from mcp.server.transport_security import TransportSecuritySettings

    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    @server.tool(
        description=(
            "Find skills that provide a given capability tag (e.g. 'invoice.extract'). "
            "Returns a list of skill summaries including the MCP binding needed to call "
            "each skill. By default only returns published skills."
        )
    )
    def find_skill_by_capability(tag: str, published_only: bool = True) -> List[Dict[str, Any]]:
        args = {"tag": tag, "published_only": published_only}
        with record_call(
            tel,
            tool="find_skill_by_capability",
            args=args,
            extras_factory=lambda r: {"resultCount": len(r) if r else 0},
        ) as ctx:
            ctx["result"] = tool_find_skill_by_capability(
                registry, tag, published_only=published_only
            )
            return ctx["result"]

    @server.tool(
        description=(
            "Return the full manifest for a skill, including governance (RBAC, data "
            "classification), scoring (determinism, risk), preconditions, effects, and "
            "a 'payloadFiles' list of skill:// resource URIs (SKILL.md, asset schemas) "
            "the agent can read on demand without burning context."
        )
    )
    def describe_skill(skill_id: str) -> Dict[str, Any]:
        args = {"skill_id": skill_id}
        with record_call(
            tel,
            tool="describe_skill",
            args=args,
            extras_factory=lambda r: {
                "payloadFileCount": len(r.get("payloadFiles", [])) if r else 0,
            },
        ) as ctx:
            ctx["result"] = tool_describe_skill(registry, skill_id, examples_dir=ex_dir)
            return ctx["result"]

    @server.tool(
        description=(
            "List every capability tag in the registry mapped to the skills that "
            "provide it. Use this for catalog discovery before you have a specific task."
        )
    )
    def list_capabilities() -> Dict[str, List[str]]:
        with record_call(
            tel,
            tool="list_capabilities",
            args={},
            extras_factory=lambda r: {"capabilityCount": len(r) if r else 0},
        ) as ctx:
            ctx["result"] = tool_list_capabilities(registry)
            return ctx["result"]

    @server.tool(
        description=(
            "Traverse the skills ontology graph from a seed node (skill id, capability "
            "tag, data type, or condition). Returns paths up to max_hops deep, each "
            "with per-hop provenance (source, edge type, target, confidence, data "
            "classification). Optional `relation` filters the first hop "
            "(PROVIDES, CONSUMES, PRODUCES, REQUIRES, CAUSES, DEPENDS_ON, SUPERSEDES). "
            "Server-side hop cap = 5. Use this to answer questions like 'what depends "
            "on legal.redline?' or 'which skills produce DocxDocument?'."
        )
    )
    def query_ontology(
        seed: str,
        relation: Optional[str] = None,
        max_hops: int = 3,
        caller_classification: str = "internal",
    ) -> Dict[str, Any]:
        args = {
            "seed": seed,
            "relation": relation,
            "max_hops": max_hops,
            "caller_classification": caller_classification,
        }
        with record_call(
            tel,
            tool="query_ontology",
            args=args,
            extras_factory=lambda r: {
                "totalPaths": r.get("totalPaths", 0) if r else 0,
                "suppressedByClassification": r.get("suppressedByClassification", 0) if r else 0,
                "truncated": r.get("truncated", False) if r else False,
                "maxHopsApplied": r.get("maxHopsApplied", 0) if r else 0,
            },
        ) as ctx:
            ctx["result"] = tool_query_ontology(
                seed=seed,
                relation=relation,
                max_hops=max_hops,
                caller_classification=caller_classification,
            )
            return ctx["result"]

    @server.tool(
        description=(
            "Propose a new skill by opening a GitHub PR against the registry. Pass the "
            "manifest dict (validated against schemas/skill-manifest.schema.json) and an "
            "optional `payload` mapping {'SKILL.md': '...', 'assets/foo.json': '...'}. "
            "Returns {pr_url, branch, files_added}. The PR review is the Register gate — "
            "a human approver must merge before the skill becomes discoverable."
        )
    )
    def submit_skill_draft(
        manifest: Dict[str, Any],
        payload: Optional[Dict[str, str]] = None,
        title: str = "",
        body: str = "",
    ) -> Dict[str, Any]:
        # We do NOT log the manifest body — just the skill id + a hash for
        # de-dup of repeated identical drafts.
        args = {
            "skill_id": (manifest or {}).get("id"),
            "version": (manifest or {}).get("version"),
            "has_payload": bool(payload),
            "title": title,
        }
        with record_call(
            tel,
            tool="submit_skill_draft",
            args=args,
            extras_factory=lambda r: {
                "filesAdded": len(r.get("files_added", [])) if r else 0,
                "prOpened": bool(r and r.get("pr_url")),
            },
        ) as ctx:
            ctx["result"] = tool_submit_skill_draft(
                manifest=manifest, payload=payload, title=title, body=body
            )
            return ctx["result"]

    # Register every payload file as a concrete MCP resource. Resources don't
    # count against Cowork's tool cap, so this scales with the catalog.
    _register_payload_resources(server, registry, ex_dir)

    return server


def _register_payload_resources(server, registry: lite.Registry, examples_dir: str) -> None:
    """Walk each skill's payload folder and register one resource per file."""
    from mcp.server.fastmcp.resources import FunctionResource
    from pydantic import AnyUrl

    for skill_id in registry.skills:
        for rel in _list_payload_files(examples_dir, skill_id):
            uri = f"skill://{_slug(skill_id)}/{rel}"
            mime, _enc = mimetypes.guess_type(rel)
            mime = mime or "application/octet-stream"

            def _make_reader(sid: str = skill_id, rp: str = rel, mt: str = mime):
                is_text = mt.startswith("text/") or mt in {
                    "application/json",
                    "application/xml",
                    "image/svg+xml",
                }

                def _read():
                    data, _ = _read_payload_file(examples_dir, sid, rp)
                    if is_text:
                        return data.decode("utf-8")
                    return data

                return _read

            server.add_resource(
                FunctionResource(
                    uri=AnyUrl(uri),
                    name=f"{skill_id}:{rel}",
                    description=f"Payload file {rel} for skill {skill_id}.",
                    mime_type=mime,
                    fn=_make_reader(),
                )
            )


def build_http_app(server=None):
    """Wrap the FastMCP streamable-HTTP app with a friendly GET probe + /health.

    Also mounts the finance-tools stub server at /api/skills/finance-tools so
    the registry's binding URL (returned by find_skill_by_capability) actually
    resolves end-to-end in the same container.
    """
    from contextlib import AsyncExitStack, asynccontextmanager

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route, Mount

    server = server or build_server()
    mcp_app = server.streamable_http_app()

    finance_tools = build_finance_tools_server()
    finance_app = finance_tools.streamable_http_app()

    async def probe(_request):
        return JSONResponse(
            {
                "service": "skills-registry-mcp",
                "transport": "streamable-http",
                "endpoint": MCP_HTTP_PATH,
                "method": "POST (JSON-RPC 2.0)",
                "tools": [
                    "find_skill_by_capability",
                    "describe_skill",
                    "list_capabilities",
                    "query_ontology",
                    "submit_skill_draft",
                ],
                "resources": "skill://<slug>/<path> (one per skill payload file)",
                "embedded_skill_servers": {
                    "finance-tools": "/api/skills/finance-tools/mcp",
                },
            }
        )

    async def finance_probe(_request):
        return JSONResponse(
            {
                "service": "finance-tools",
                "transport": "streamable-http",
                "endpoint": "/api/skills/finance-tools/mcp",
                "method": "POST (JSON-RPC 2.0)",
                "tools": ["invoice_extract"],
            }
        )

    async def health(_request):
        return JSONResponse({"status": "ok"})

    # Both FastMCP apps need their lifespans entered so their session managers
    # have a running task group. Without this, POST returns 500 with
    # "Task group is not initialized".
    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_app.router.lifespan_context(app))
            await stack.enter_async_context(finance_app.router.lifespan_context(app))
            yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/health", health, methods=["GET"]),
            Route(MCP_HTTP_PATH, probe, methods=["GET"]),
            Route("/api/skills/finance-tools/mcp", finance_probe, methods=["GET"]),
            Mount("/api/skills/finance-tools", app=finance_app),
            Mount("/", app=mcp_app),
        ],
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
