"""Build the Cowork plugin zip — fill the mcpServerUrl placeholder, zip cowork-plugin/.

Usage:
    python tools/build-cowork-plugin.py https://ca-skills-registry-mcp.<region>.azurecontainerapps.io/api/mcp
    python tools/build-cowork-plugin.py --out custom-plugin.zip <url>

The zip layout matches what Teams Developer Portal / M365 admin centre
expect: manifest.json at the root (NOT nested in a folder). The script
also rewrites validDomains to match the host in the URL so the connector
isn't blocked by the host firewall.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import zipfile
from typing import List
from urllib.parse import urlparse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO_ROOT, "cowork-plugin")


def _wildcard_domain(host: str) -> str:
    """`ca-skills-registry-mcp.<region>.azurecontainerapps.io` -> `*.azurecontainerapps.io`.

    Falls back to the literal host if it doesn't look like a multi-label name.
    """
    parts = host.split(".")
    if len(parts) >= 3:
        return "*." + ".".join(parts[-3:])
    return host


def _validate_url(url: str) -> None:
    if not url.startswith("https://"):
        raise SystemExit(f"mcpServerUrl must be https://, got: {url!r}")
    if "REPLACE-ME" in url:
        raise SystemExit("Refusing to bake the placeholder host into the manifest.")
    if not url.endswith("/api/mcp"):
        print(
            f"WARNING: URL doesn't end with /api/mcp ({url!r}). The Cowork "
            "connector expects that path — continuing anyway.",
            file=sys.stderr,
        )


def _list_plugin_files() -> List[str]:
    """Files in cowork-plugin/ that must end up at the root of the zip."""
    keep = []
    for dirpath, _dirnames, filenames in os.walk(PLUGIN_DIR):
        # skip __pycache__ / .DS_Store etc.
        for name in filenames:
            if name.startswith(".") or name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, PLUGIN_DIR).replace(os.sep, "/")
            keep.append(rel)
    keep.sort()
    return keep


def build(url: str, out_path: str) -> str:
    _validate_url(url)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise SystemExit(f"could not parse host from URL: {url!r}")

    with open(os.path.join(PLUGIN_DIR, "manifest.json"), "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    # Inject the URL into agentConnectors[0].toolSource.remoteMcpServer.mcpServerUrl.
    # Manifest v1.28 nests it that way (mirrors the TomTom Map MCP POC).
    connectors = manifest.get("agentConnectors") or []
    if not connectors:
        raise SystemExit("cowork-plugin/manifest.json has no agentConnectors entry")
    tool_source = connectors[0].setdefault("toolSource", {})
    remote = tool_source.setdefault("remoteMcpServer", {})
    remote["mcpServerUrl"] = url

    # Manifest v1.28 has no top-level validDomains for MCP connectors; the
    # allowed host is implied by mcpServerUrl. Strip any stale entry to avoid
    # "additional property not allowed" rejection from the Teams validator.
    manifest.pop("validDomains", None)

    with tempfile.TemporaryDirectory() as tmp:
        baked = os.path.join(tmp, "manifest.json")
        with open(baked, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
            fh.write("\n")

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in _list_plugin_files():
                src = os.path.join(PLUGIN_DIR, rel)
                if rel == "manifest.json":
                    zf.write(baked, "manifest.json")
                else:
                    zf.write(src, rel)

    return out_path


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url", help="mcpServerUrl from `az deployment group show ...mcpServerUrl`")
    p.add_argument(
        "--out",
        default=os.path.join(REPO_ROOT, "skills-registry-plugin.zip"),
        help="path to write the zip (default: ./skills-registry-plugin.zip)",
    )
    args = p.parse_args(argv)

    out = build(args.url, args.out)
    size_kb = os.path.getsize(out) / 1024
    print(f"Wrote {out} ({size_kb:.1f} KB)")
    print(f"  mcpServerUrl: {args.url}")
    print("")
    print("Next: upload the zip via Teams Developer Portal (https://dev.teams.microsoft.com)")
    print("      or the M365 admin centre under Custom apps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
