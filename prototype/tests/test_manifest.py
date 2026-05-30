"""Smoke tests for Part A: manifest loading + schema validation."""

from __future__ import annotations

import glob
import os

import pytest

from chassis.manifest import (
    ManifestError,
    iope_signature,
    load_manifest,
    validate_manifest,
)

EXAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "examples",
)


def test_all_bundled_examples_validate():
    paths = glob.glob(os.path.join(EXAMPLES_DIR, "*.manifest.json"))
    assert paths, "expected bundled example manifests"
    for path in paths:
        manifest = load_manifest(path)  # raises if invalid
        assert manifest["kind"] == "Skill"


def test_validation_rejects_missing_required_block(invoice_extract):
    del invoice_extract["scoring"]
    with pytest.raises(ManifestError):
        validate_manifest(invoice_extract)


def test_validation_rejects_bad_enum(invoice_extract):
    invoice_extract["scoring"]["risk"] = "catastrophic"
    with pytest.raises(ManifestError):
        validate_manifest(invoice_extract)


def test_validation_rejects_unknown_property(invoice_extract):
    invoice_extract["surprise"] = True
    with pytest.raises(ManifestError):
        validate_manifest(invoice_extract)


def test_iope_signature_matches_on_shared_io(invoice_extract):
    sig = iope_signature(invoice_extract)
    assert sig == (("InvoiceDocument",), ("InvoiceFields",))
