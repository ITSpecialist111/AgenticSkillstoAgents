"""Tests for the published volume catalog (Phase 1 exit gate)."""

from __future__ import annotations

import os

from chassis.gatecheck import check_manifests
from chassis.manifest import load_manifest, skill_id
from chassis.registry import Stage

EXAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "examples",
)
CATALOG_DIR = os.path.join(EXAMPLES_DIR, "catalog")


def _load_dir(path):
    files = sorted(f for f in os.listdir(path) if f.endswith(".manifest.json"))
    return [(f, load_manifest(os.path.join(path, f))) for f in files]


def test_catalog_meets_phase1_published_volume():
    loaded = _load_dir(CATALOG_DIR)
    published = [m for _, m in loaded if m["lifecycle"]["stage"] == Stage.PUBLISHED.value]
    # Roadmap Phase 1 exit gate: >= 20 published skills.
    assert len(published) >= 20


def test_catalog_plus_examples_pass_the_gate():
    loaded = _load_dir(CATALOG_DIR) + [
        (f, load_manifest(os.path.join(EXAMPLES_DIR, f)))
        for f in sorted(os.listdir(EXAMPLES_DIR))
        if f.endswith(".manifest.json")
    ]
    checks = check_manifests(loaded)
    failed = [c for c in checks if not c.passed]
    assert not failed, [(c.skill_id, c.errors) for c in failed]


def test_catalog_skill_ids_are_unique():
    ids = [skill_id(m) for _, m in _load_dir(CATALOG_DIR)]
    assert len(ids) == len(set(ids))
