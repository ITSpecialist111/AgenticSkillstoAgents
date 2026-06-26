"""Tests for the minimal HTTP registry API."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from chassis.api import create_server
from chassis.registry import Registry
from chassis.store import open_store


def _request(url: str, method: str = "GET", payload: dict | None = None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, method=method, headers=headers)
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_api_happy_path(invoice_extract, as_draft):
    reg = Registry()
    server = create_server("127.0.0.1", 0, reg)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    sid = invoice_extract["identity"]["id"]
    encoded_sid = quote(sid, safe="")
    manifest = as_draft(invoice_extract)

    try:
        status, payload = _request(f"{base}/health")
        assert status == 200
        assert payload["ok"] is True

        status, payload = _request(f"{base}/skills", method="POST", payload=manifest)
        assert status == 201
        assert payload["lifecycle"]["stage"] == "registered"

        status, payload = _request(
            f"{base}/skills/{encoded_sid}/certify",
            method="POST",
            payload={"approver": "coe.reviewer"},
        )
        assert status == 200
        assert payload["lifecycle"]["stage"] == "certified"

        status, payload = _request(f"{base}/skills/{encoded_sid}/publish", method="POST")
        assert status == 200
        assert payload["lifecycle"]["stage"] == "published"

        status, payload = _request(f"{base}/capabilities?tag=invoice.extract")
        assert status == 200
        assert [m["identity"]["id"] for m in payload["skills"]] == [sid]

        status, payload = _request(f"{base}/skills/{encoded_sid}/lineage")
        assert status == 200
        assert payload["id"] == sid
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_persists_with_sqlite_dsn(invoice_extract, as_draft, tmp_path: Path):
    db = tmp_path / "skills.db"
    dsn = f"sqlite:///{db}"
    sid = invoice_extract["identity"]["id"]
    manifest = as_draft(invoice_extract)

    reg = Registry(open_store(dsn))
    server = create_server("127.0.0.1", 0, reg)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    encoded_sid = quote(sid, safe="")

    try:
        _request(f"{base}/skills", method="POST", payload=manifest)
        _request(
            f"{base}/skills/{encoded_sid}/certify",
            method="POST",
            payload={"approver": "coe.reviewer"},
        )
        _request(f"{base}/skills/{encoded_sid}/publish", method="POST")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    reg2 = Registry(open_store(dsn))
    assert reg2.get(sid)["lifecycle"]["stage"] == "published"


def test_api_returns_400_on_gate_error(invoice_extract, as_draft):
    reg = Registry()
    server = create_server("127.0.0.1", 0, reg)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    sid = invoice_extract["identity"]["id"]
    encoded_sid = quote(sid, safe="")
    manifest = as_draft(invoice_extract)
    manifest["mcp"]["namespace"] = ""

    try:
        _request(f"{base}/skills", method="POST", payload=manifest)
        _request(
            f"{base}/skills/{encoded_sid}/certify",
            method="POST",
            payload={"approver": "coe.reviewer"},
        )
        try:
            _request(f"{base}/skills/{encoded_sid}/publish", method="POST")
        except HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode("utf-8"))
            assert "verified mcp.namespace" in body["error"]
        else:  # pragma: no cover - defensive
            raise AssertionError("expected HTTP 400")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
