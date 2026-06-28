"""Smoke-test the deployed MCP server: probe + JSON-RPC tools/list + a real call.

Usage:
    python tools/smoke-test-mcp.py https://ca-skills-registry-mcp.<region>.azurecontainerapps.io/api/mcp

Exits non-zero on any failure so it's safe to drop into CI later. Prints a
human-readable trace by default.

What it does (in order):
  1. GET /health     — Container App liveness.
  2. GET <mcpUrl>    — the friendly JSON probe we mount alongside the FastMCP app.
  3. POST <mcpUrl>   — JSON-RPC 2.0:
       a. initialize
       b. tools/list  (must include all four tools)
       c. tools/call  find_skill_by_capability(tag="invoice.extract")
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any, Dict
from urllib.parse import urlparse


def _client():
    try:
        import httpx
    except ImportError as exc:
        raise SystemExit(
            "smoke-test needs httpx: `pip install httpx`"
        ) from exc
    return httpx.Client(timeout=30.0, follow_redirects=True)


def _expect(condition: bool, msg: str) -> None:
    if not condition:
        print(f"FAIL: {msg}", file=sys.stderr)
        raise SystemExit(2)
    print(f"OK   {msg}")


def _post_rpc(client, url: str, method: str, params: Dict[str, Any], session_id: str | None = None):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    r = client.post(url, headers=headers, json=body)
    if r.status_code >= 400:
        raise SystemExit(f"POST {method} returned {r.status_code}: {r.text[:500]}")
    new_sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
    # FastMCP's streamable HTTP can reply as SSE or plain JSON.
    if "text/event-stream" in r.headers.get("content-type", ""):
        payload = _parse_sse(r.text)
    else:
        payload = r.json()
    return payload, new_sid


def _parse_sse(text: str) -> Dict[str, Any]:
    """Pull the first JSON payload out of an SSE response."""
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except Exception:
                continue
    raise SystemExit(f"could not parse SSE body: {text[:500]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url", help="Full mcpServerUrl, e.g. https://.../api/mcp")
    p.add_argument("--tag", default="invoice.extract", help="capability tag to look up (default: invoice.extract)")
    args = p.parse_args(argv)

    parsed = urlparse(args.url)
    if parsed.scheme != "https":
        raise SystemExit("URL must be https://")
    health_url = f"{parsed.scheme}://{parsed.netloc}/health"

    with _client() as c:
        # 1. /health
        r = c.get(health_url)
        _expect(r.status_code == 200, f"GET {health_url} -> 200")
        _expect(r.json().get("status") == "ok", "/health returns {status: ok}")

        # 2. GET probe
        r = c.get(args.url, headers={"Accept": "application/json"})
        _expect(r.status_code == 200, f"GET {args.url} -> 200")
        probe = r.json()
        _expect(probe.get("service") == "skills-registry-mcp", "probe service = skills-registry-mcp")
        wanted_tools = {"find_skill_by_capability", "describe_skill", "list_capabilities", "submit_skill_draft"}
        _expect(set(probe.get("tools", [])) >= wanted_tools, "probe lists all four tools")

        # 3a. initialize
        init, sid = _post_rpc(
            c,
            args.url,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test-mcp", "version": "0.1.0"},
            },
        )
        _expect("result" in init, "initialize returned a result")
        if sid:
            # MCP requires a "notifications/initialized" notification after init.
            c.post(
                args.url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Mcp-Session-Id": sid,
                },
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )

        # 3b. tools/list
        listed, sid = _post_rpc(c, args.url, "tools/list", {}, session_id=sid)
        names = {t["name"] for t in listed.get("result", {}).get("tools", [])}
        _expect(names >= wanted_tools, f"tools/list contains all four tools (saw {sorted(names)})")

        # 3c. tools/call find_skill_by_capability
        called, _ = _post_rpc(
            c,
            args.url,
            "tools/call",
            {"name": "find_skill_by_capability", "arguments": {"tag": args.tag}},
            session_id=sid,
        )
        result = called.get("result", {})
        content = result.get("content", [])
        _expect(bool(content), f"tools/call find_skill_by_capability returned content for tag={args.tag!r}")
        # Content is a list of {type: text, text: "..."}; the text is JSON.
        first_text = next((c["text"] for c in content if c.get("type") == "text"), None)
        if first_text:
            try:
                payload = json.loads(first_text)
                ids = [hit.get("id") for hit in payload] if isinstance(payload, list) else []
                print(f"     hits: {ids}")
            except Exception:
                print(f"     raw: {first_text[:200]}")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
