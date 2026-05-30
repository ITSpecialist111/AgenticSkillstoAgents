"""Shared pytest fixtures for the chassis prototype smoke tests."""

from __future__ import annotations

import copy
import os

import pytest

from chassis.manifest import load_manifest

EXAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "examples",
)


def _example(name: str):
    return load_manifest(os.path.join(EXAMPLES_DIR, f"{name}.manifest.json"))


@pytest.fixture
def invoice_extract():
    return copy.deepcopy(_example("invoice-extract"))


@pytest.fixture
def po_match():
    return copy.deepcopy(_example("po-match"))


@pytest.fixture
def ap_intake():
    return copy.deepcopy(_example("ap-intake"))


@pytest.fixture
def as_draft():
    """Return a helper that resets a manifest's lifecycle to draft."""

    def _reset(manifest):
        manifest = copy.deepcopy(manifest)
        manifest["lifecycle"] = {"stage": "draft"}
        return manifest

    return _reset
