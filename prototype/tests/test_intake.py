"""Smoke tests for the intake layer - the front door to the Register gate.

Covers discovery, SKILL.md parsing, asset classification, manifest mapping
(including the "never invent IOPE" rule), the content-hash watcher, and an
end-to-end path proving intake plugs cleanly into Parts A/B/C.
"""

from __future__ import annotations

import os

import pytest

from chassis.intake import (
    build_manifest,
    classify_assets,
    classify_file,
    discover,
    parse_skill_md,
)
from chassis.intake.watcher import IntakeWatcher
from chassis.manifest import validate_manifest
from chassis.ontology import OntologyBuilderAgent
from chassis.registry import Registry, Stage

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "skills")


def _source(sources, suffix):
    for src in sources:
        if src.skill_dir.endswith(suffix):
            return src
    raise AssertionError(f"no discovered source ending in {suffix!r}")


# ----- discovery ---------------------------------------------------------
def test_discovery_finds_skill_folders():
    sources = discover(FIXTURES)
    dirs = {os.path.basename(s.skill_dir) for s in sources}
    assert dirs == {"text-summarize", "prose-helper"}


def test_discovery_enumerates_sidecars_excluding_skill_md():
    src = _source(discover(FIXTURES), "text-summarize")
    names = {os.path.basename(p) for p in src.sidecars}
    assert names == {"summarize.py", "reference.md", "config.json"}
    assert os.path.basename(src.skill_md).lower() == "skill.md"
    assert src.skill_md not in src.sidecars


# ----- skillmd parsing ---------------------------------------------------
def test_parse_frontmatter_and_body():
    parsed = parse_skill_md("---\nname: X\ntags: [a, b]\n---\n# Title\n\nBody.")
    assert parsed.frontmatter == {"name": "X", "tags": ["a", "b"]}
    assert parsed.first_heading() == "Title"
    assert "Body." in parsed.body


def test_parse_no_frontmatter_is_all_body():
    parsed = parse_skill_md("# Just a heading\n\nNo frontmatter here.")
    assert parsed.frontmatter == {}
    assert parsed.first_heading() == "Just a heading"


def test_parse_rejects_non_mapping_frontmatter():
    with pytest.raises(ValueError):
        parse_skill_md("---\n- not\n- a\n- map\n---\nbody")


# ----- asset classification ---------------------------------------------
def test_classify_file_categories():
    assert classify_file("run.py") == "scripts"
    assert classify_file("query.sql") == "scripts"
    assert classify_file("notes.md") == "knowledge"
    assert classify_file("config.json") == "assets"
    assert classify_file("noext") == "assets"


def test_classify_assets_groups_sidecars():
    result = classify_assets(["a.py", "b.md", "c.json", "d.sh"])
    assert result.scripts == ["a.py", "d.sh"]
    assert result.knowledge == ["b.md"]
    assert result.assets == ["c.json"]
    assert result.has_scripts is True


# ----- mapping -----------------------------------------------------------
def test_mapper_produces_schema_valid_manifest():
    src = _source(discover(FIXTURES), "text-summarize")
    manifest, report = build_manifest(src)
    validate_manifest(manifest)  # raises if invalid
    assert report.schema_valid is True
    assert manifest["identity"]["id"] == "text/summarize"
    assert manifest["lifecycle"]["stage"] == "draft"


def test_mapper_scripts_drive_determinism_and_skilltype():
    src = _source(discover(FIXTURES), "text-summarize")
    manifest, report = build_manifest(src)
    assert manifest["scoring"]["determinism"] == "high"
    assert manifest["identity"]["skillType"] == "deterministic-tool"
    assert report.assets["scripts"] == ["summarize.py"]


def test_mapper_flags_missing_iope_and_never_invents_it():
    src = _source(discover(FIXTURES), "prose-helper")
    manifest, report = build_manifest(src)
    # IOPE absent from SKILL.md -> empty arrays, and flagged for a human.
    assert manifest["capability"]["inputs"] == []
    assert manifest["capability"]["outputs"] == []
    assert any("IOPE" in m for m in report.missing)


def test_mapper_derives_id_and_defaults_for_sparse_skill():
    src = _source(discover(FIXTURES), "prose-helper")
    manifest, report = build_manifest(src)
    assert manifest["identity"]["id"] == "skills/prose-helper"
    assert manifest["identity"]["version"] == "0.1.0"
    assert manifest["identity"]["skillType"] == "anthropic-agent-skill"
    assert manifest["scoring"]["determinism"] == "low"
    assert "identity.id" in report.inferred
    assert "identity.owner" in report.missing


def test_mapper_records_provenance_hashes():
    src = _source(discover(FIXTURES), "text-summarize")
    _manifest, report = build_manifest(src)
    files = report.provenance["files"]
    assert "SKILL.md" in files
    assert "summarize.py" in files
    assert all(len(h) == 64 for h in files.values())  # sha-256 hex digests


# ----- watcher -----------------------------------------------------------
def test_watcher_reports_changes_then_is_idempotent():
    watcher = IntakeWatcher()
    first = watcher.scan(FIXTURES)
    assert len(first) == 2          # both folders new
    assert watcher.scan(FIXTURES) == []  # unchanged tree -> no re-emit


def test_watcher_detects_modified_file(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: Demo\n---\n# Demo\n")
    (skill_dir / "run.py").write_text("print('v1')\n")

    watcher = IntakeWatcher()
    assert len(watcher.scan(str(tmp_path))) == 1   # initial discovery
    assert watcher.scan(str(tmp_path)) == []       # no change

    (skill_dir / "run.py").write_text("print('v2')\n")  # mutate a sidecar
    changed = watcher.scan(str(tmp_path))
    assert len(changed) == 1
    assert changed[0].skill_dir.endswith("demo")


# ----- end-to-end: intake -> six gates -----------------------------------
def test_intake_draft_graduates_through_gates():
    src = _source(discover(FIXTURES), "text-summarize")
    manifest, report = build_manifest(src)
    assert report.schema_valid

    reg = Registry()
    sid = manifest["identity"]["id"]
    reg.register(manifest)
    reg.certify(sid, approver="coe.reviewer")
    reg.publish(sid)
    assert reg.get(sid)["lifecycle"]["stage"] == Stage.PUBLISHED.value

    # And the published draft is meaningful to the Ontology Builder Agent.
    result = OntologyBuilderAgent().sync_meaning(reg.all())
    provides = {(c.subject, c.predicate, c.obj) for c in result.proposals}
    assert (sid, "PROVIDES", "text.summarize") in provides
