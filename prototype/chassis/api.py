"""HTTP service - drive the six gates over the wire.

A thin FastAPI wrapper so non-CLI clients and agents can validate, register,
certify, publish, retire, intake, and meaning-sync against a *persistent*
registry. FastAPI is an optional dependency: importing this module without it
raises a clear, actionable error rather than failing at import time elsewhere.

The app is built by :func:`create_app` against an injected
:class:`~chassis.registry.Registry`, so tests can wire an in-memory store and
production can wire SQLite (or, later, a Fabric/OneLake-backed store) without
touching the handlers.

Routes intentionally mirror the chassis verbs:

    POST /skills                      register a manifest        (Gate 1)
    POST /skills/{id}/certify         certify (needs approver)   (Gate 2)
    POST /skills/{id}/publish         publish                    (Gate 3)
    POST /skills/{id}/deprecate       deprecate                  (Gate 6)
    POST /skills/{id}/retire          retire                     (Gate 6)
    GET  /skills                      list catalog
    GET  /skills/{id}                 fetch one
    GET  /capabilities?tag=           matchmaking (Reasoning)
    POST /meaning/sync                Ontology Builder Agent run
    GET  /mcp/tools                   MCP-compatible published catalog
    GET  /metrics                     program telemetry snapshot
    GET  /healthz                     liveness
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .manifest import ManifestError
from .matchmaking import Need, match
from .mcp import published_catalog
from .metrics import snapshot
from .ontology import OntologyBuilderAgent
from .registry import GateError, Registry

try:  # pragma: no cover - exercised indirectly via create_app
    from fastapi import Body, FastAPI, HTTPException, Query
except Exception as _exc:  # pragma: no cover - only hit when extra missing
    _FASTAPI_IMPORT_ERROR: Optional[Exception] = _exc
    FastAPI = None  # type: ignore[assignment]
else:
    _FASTAPI_IMPORT_ERROR = None


def _require_fastapi() -> None:
    if FastAPI is None:  # pragma: no cover - depends on env
        raise RuntimeError(
            "FastAPI is not installed. Install the API extra:\n"
            "    pip install 'chassis[api]'\n"
            f"(original import error: {_FASTAPI_IMPORT_ERROR})"
        )


def create_app(registry: Optional[Registry] = None) -> "FastAPI":
    """Build the FastAPI app around ``registry`` (in-memory if not supplied)."""
    _require_fastapi()
    registry = registry if registry is not None else Registry()
    agent = OntologyBuilderAgent()

    app = FastAPI(
        title="AgenticSkillstoAgents - Skill Registry & Graduation Service",
        version="1.0.0",
        summary="Register, certify, publish and compose governed skills.",
    )

    def _get_or_404(sid: str):
        try:
            return registry.get(sid)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown skill: {sid}")

    @app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/skills")
    def list_skills() -> List[Dict[str, Any]]:
        return registry.all()

    @app.get("/skills/{sid:path}")
    def get_skill(sid: str) -> Dict[str, Any]:
        return _get_or_404(sid)

    @app.post("/skills", status_code=201)
    def register_skill(manifest: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        try:
            return registry.register(manifest)
        except ManifestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except GateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/skills/{sid:path}/certify")
    def certify_skill(
        sid: str, payload: Dict[str, Any] = Body(default={})
    ) -> Dict[str, Any]:
        approver = payload.get("approver", "")
        _get_or_404(sid)
        try:
            return registry.certify(sid, approver=approver)
        except GateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/skills/{sid:path}/publish")
    def publish_skill(sid: str) -> Dict[str, Any]:
        _get_or_404(sid)
        try:
            return registry.publish(sid)
        except GateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/skills/{sid:path}/deprecate")
    def deprecate_skill(
        sid: str, payload: Dict[str, Any] = Body(default={})
    ) -> Dict[str, Any]:
        _get_or_404(sid)
        try:
            return registry.deprecate(sid, superseded_by=payload.get("supersededBy"))
        except GateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/skills/{sid:path}/retire")
    def retire_skill(sid: str) -> Dict[str, Any]:
        _get_or_404(sid)
        try:
            return registry.retire(sid)
        except GateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/capabilities")
    def capabilities(
        tag: str = Query(...),
        inputs: Optional[List[str]] = Query(default=None),
        outputs: Optional[List[str]] = Query(default=None),
    ) -> List[Dict[str, Any]]:
        need = Need(
            tag=tag,
            inputs=frozenset(inputs or []),
            outputs=frozenset(outputs or []),
        )
        published = registry.find_by_capability(tag, published_only=True)
        return [m.as_dict() for m in match(published, need)]

    @app.post("/meaning/sync")
    def meaning_sync() -> Dict[str, Any]:
        result = agent.sync_meaning(registry.all())
        return {
            "proposals": len(result.proposals),
            "autoMerge": len(result.auto_merge),
            "reviewQueue": len(result.review_queue),
            "flags": result.flags,
        }

    @app.get("/mcp/tools")
    def mcp_tools() -> Dict[str, Any]:
        return published_catalog(registry.all())

    @app.get("/metrics")
    def metrics() -> Dict[str, Any]:
        result = agent.sync_meaning(registry.all())
        return snapshot(registry.all(), result)

    return app


__all__ = ["create_app"]
