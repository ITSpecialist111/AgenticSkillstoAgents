"""Minimal HTTP API for the registry prototype.

Implements the technical-spec registry surface with stdlib HTTP only.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, unquote, urlparse

from .registry import GateError, Registry
from .store import open_store


def _json(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8"))


def make_handler(registry: Registry) -> type[BaseHTTPRequestHandler]:
    """Build a request handler class bound to ``registry``."""

    class RegistryAPIHandler(BaseHTTPRequestHandler):
        server_version = "chassis-api/0.1"

        def log_message(self, format: str, *args: object) -> None:  # pragma: no cover
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if path == "/health":
                    _json(self, HTTPStatus.OK, {"ok": True})
                    return

                if path == "/skills":
                    _json(self, HTTPStatus.OK, {"skills": registry.all()})
                    return

                if path == "/capabilities":
                    tag = (query.get("tag") or [None])[0]
                    if not tag:
                        _json(self, HTTPStatus.BAD_REQUEST, {"error": "missing query parameter: tag"})
                        return
                    _json(self, HTTPStatus.OK, {"skills": registry.find_by_capability(tag)})
                    return

                if path.startswith("/skills/") and path.endswith("/lineage"):
                    encoded_sid = path[len("/skills/") : -len("/lineage")].rstrip("/")
                    sid = unquote(encoded_sid)
                    _json(self, HTTPStatus.OK, registry.lineage(sid))
                    return

                if path.startswith("/skills/"):
                    sid = unquote(path[len("/skills/") :])
                    _json(self, HTTPStatus.OK, registry.get(sid))
                    return

                _json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown route: {path}"})
            except KeyError as exc:
                _json(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except GateError as exc:
                _json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                _json(self, HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc}"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/skills":
                    manifest = _read_json(self)
                    stored = registry.register(manifest)
                    _json(self, HTTPStatus.CREATED, stored)
                    return

                if path.startswith("/skills/") and path.endswith("/certify"):
                    encoded_sid = path[len("/skills/") : -len("/certify")].rstrip("/")
                    sid = unquote(encoded_sid)
                    payload = _read_json(self)
                    approver = payload.get("approver", "")
                    certified = registry.certify(sid, approver=approver)
                    _json(self, HTTPStatus.OK, certified)
                    return

                if path.startswith("/skills/") and path.endswith("/publish"):
                    encoded_sid = path[len("/skills/") : -len("/publish")].rstrip("/")
                    sid = unquote(encoded_sid)
                    published = registry.publish(sid)
                    _json(self, HTTPStatus.OK, published)
                    return

                _json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown route: {path}"})
            except KeyError as exc:
                _json(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except GateError as exc:
                _json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                _json(self, HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc}"})

    return RegistryAPIHandler


def create_server(host: str, port: int, registry: Registry) -> ThreadingHTTPServer:
    """Create a threaded HTTP server bound to a registry."""
    return ThreadingHTTPServer((host, port), make_handler(registry))


def run_server(host: str = "127.0.0.1", port: int = 8080, dsn: str | None = None) -> None:
    """Run the API server until interrupted."""
    registry = Registry(open_store(dsn))
    server = create_server(host, port, registry)
    print(f"chassis api listening on http://{host}:{port} (store={dsn or 'memory'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - manual usage
        pass
    finally:
        server.server_close()
