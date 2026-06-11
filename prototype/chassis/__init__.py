"""Reference prototype of the AgenticSkillstoAgents graduation chassis.

This package is a small, dependency-light reference implementation of the
construct described in the repository docs:

* Part A — the canonical Skill **Manifest** (validated against
  ``schemas/skill-manifest.schema.json``). See :mod:`chassis.manifest`.
* Part B — the six-gate **pipeline** state machine
  (Register -> Certify -> Publish -> Meaning-sync -> Compose -> Retire).
  See :mod:`chassis.registry`.
* Part C — the replaceable **Ontology Builder Agent** with the contract
  ``sync_meaning(manifests, ontology) -> proposals/confidence/flags/reviewQueue``.
  See :mod:`chassis.ontology`.

The implementation is intentionally heuristic and in-memory: it exists to make
the specification executable and testable, not to be a production registry.
"""

from .manifest import (
    Manifest,
    ManifestError,
    iope_signature,
    load_manifest,
    validate_manifest,
)
from .ontology import Ontology, OntologyBuilderAgent, SyncResult
from .registry import GateError, Registry, Stage
from .store import InMemoryStore, SkillStore, SqliteStore, open_store

# The package major version tracks the manifest ``apiVersion`` (skills.dev/v1):
# any breaking change to the canonical manifest bumps both in lock-step.
__version__ = "1.0.0"
API_VERSION = "skills.dev/v1"

__all__ = [
    "__version__",
    "API_VERSION",
    "Manifest",
    "ManifestError",
    "iope_signature",
    "load_manifest",
    "validate_manifest",
    "Ontology",
    "OntologyBuilderAgent",
    "SyncResult",
    "GateError",
    "Registry",
    "Stage",
    "SkillStore",
    "InMemoryStore",
    "SqliteStore",
    "open_store",
]
