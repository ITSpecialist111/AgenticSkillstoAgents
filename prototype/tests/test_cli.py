"""Tests for the new persistent CLI subcommands."""

from __future__ import annotations

import glob
import json
import os

from chassis.cli import main


def _write_draft(tmp_path, manifest, name):
    manifest = json.loads(json.dumps(manifest))
    manifest["lifecycle"] = {"stage": "draft"}
    path = os.path.join(tmp_path, f"{name}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    return path


def test_register_certify_publish_persist(tmp_path, invoice_extract, capsys):
    db = f"sqlite:///{os.path.join(tmp_path, 'reg.db')}"
    path = _write_draft(tmp_path, invoice_extract, "ie")
    sid = invoice_extract["identity"]["id"]

    assert main(["register", path, "--db", db]) == 0
    assert main(["certify", sid, "--approver", "coe.reviewer", "--db", db]) == 0
    assert main(["publish", sid, "--db", db]) == 0

    capsys.readouterr()
    # A fresh process-equivalent invocation still sees the published skill.
    assert main(["list", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "published" in out and sid in out


def test_certify_unknown_skill_returns_1(tmp_path):
    db = f"sqlite:///{os.path.join(tmp_path, 'reg.db')}"
    assert main(["certify", "no/such", "--approver", "x", "--db", db]) == 1


def test_gate_command_passes_examples(capsys):
    examples = sorted(
        glob.glob(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "examples",
                "*.manifest.json",
            )
        )
    )
    assert main(["gate", *examples]) == 0
    assert "passed the gate checks" in capsys.readouterr().out


def test_metrics_command_outputs_json(tmp_path, invoice_extract, capsys):
    db = f"sqlite:///{os.path.join(tmp_path, 'reg.db')}"
    path = _write_draft(tmp_path, invoice_extract, "ie")
    main(["register", path, "--db", db])
    capsys.readouterr()
    assert main(["metrics", "--db", db]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["registry"]["skills_total"] == 1
