"""Packaging / distribution contract tests.

These guard the "installable, import-clean" guarantees: the schema bundled in the
package must stay identical to the canonical one, the version must track the
manifest apiVersion, and the schema loader must honour the env override.
"""

from __future__ import annotations

import importlib
import json
import os

import chassis
from chassis import manifest as manifest_mod

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CANONICAL = os.path.join(_REPO_ROOT, "schemas", "skill-manifest.schema.json")
_PACKAGED = os.path.join(os.path.dirname(manifest_mod.__file__), "data", "skill-manifest.schema.json")


def test_packaged_schema_matches_canonical():
    with open(_CANONICAL, "r", encoding="utf-8") as a, open(_PACKAGED, "r", encoding="utf-8") as b:
        assert json.load(a) == json.load(b), (
            "packaged chassis/data schema has drifted from schemas/skill-manifest.schema.json"
        )


def test_version_tracks_api_version():
    assert chassis.__version__.split(".")[0] == "1"
    assert chassis.API_VERSION == "skills.dev/v1"


def test_console_entry_point_importable():
    from chassis.cli import main

    assert callable(main)


def test_schema_path_env_override(tmp_path, monkeypatch):
    # A bogus override path should change what the loader resolves to.
    bogus = os.path.join(tmp_path, "schema.json")
    monkeypatch.setenv("CHASSIS_SCHEMA_PATH", bogus)
    importlib.reload(manifest_mod)
    assert manifest_mod._resolve_schema_path() == bogus
    monkeypatch.delenv("CHASSIS_SCHEMA_PATH")
    importlib.reload(manifest_mod)
    # Back to the packaged copy (which exists in a source checkout / install).
    assert os.path.exists(manifest_mod._resolve_schema_path())
