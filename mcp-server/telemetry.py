"""Stage E telemetry — append-only event sink for MCP tool calls.

One row per tool invocation: ``{ts, tool, args_hash, latency_ms, ok,
error_class, extras}``. Three backends, selected by ``TELEMETRY_BACKEND``:

    null    -> drop every event (default for tests / stdio)
    stdout  -> single-line JSON prefixed with ``TELEMETRY:`` (Container Apps
               surfaces this in Log Analytics automatically — zero deps)
    jsonl   -> append to ``TELEMETRY_LOG_PATH`` (local-first; query with DuckDB)

Args are never logged in the clear — only a 16-char sha256 prefix. Per-tool
extras (e.g. ``totalPaths`` for ``query_ontology``) are explicit at the
caller, never harvested from args.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional, Protocol


class Telemetry(Protocol):
    def record(self, event: Dict[str, Any]) -> None: ...


class NullTelemetry:
    def record(self, event: Dict[str, Any]) -> None:  # noqa: D401 — protocol
        return


class StdoutTelemetry:
    """Emit a single line of JSON to stdout per event.

    Prefixed with ``TELEMETRY:`` so log scrapers (Container Apps → Log
    Analytics, ``kubectl logs | grep``, etc.) can pull telemetry out of
    the same stream the server uses for normal logs.
    """

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout

    def record(self, event: Dict[str, Any]) -> None:
        try:
            line = json.dumps(event, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            line = json.dumps({"ts": event.get("ts"), "tool": event.get("tool"),
                               "error_class": "TelemetrySerializationError"})
        self._stream.write(f"TELEMETRY: {line}\n")
        self._stream.flush()


class JsonlTelemetry:
    """Append one JSON object per line to ``path``.

    No locking — append is atomic on POSIX for small writes; on Windows we
    accept that two concurrent writers may interleave. Telemetry is
    advisory; this is fine.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def record(self, event: Dict[str, Any]) -> None:
        try:
            line = json.dumps(event, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            return
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def make_telemetry() -> Telemetry:
    backend = os.environ.get("TELEMETRY_BACKEND", "null").lower()
    if backend == "stdout":
        return StdoutTelemetry()
    if backend == "jsonl":
        path = os.environ.get("TELEMETRY_LOG_PATH")
        if not path:
            raise RuntimeError(
                "TELEMETRY_BACKEND=jsonl requires TELEMETRY_LOG_PATH"
            )
        return JsonlTelemetry(path)
    if backend == "null":
        return NullTelemetry()
    raise RuntimeError(f"unknown TELEMETRY_BACKEND: {backend!r}")


def hash_args(args: Dict[str, Any]) -> str:
    """Stable 16-char sha256 prefix of the args dict.

    Sorted keys so identical calls collapse to the same hash regardless of
    keyword order. Non-serialisable values are stringified.
    """
    blob = json.dumps(args, sort_keys=True, default=repr).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


@contextlib.contextmanager
def record_call(
    tel: Telemetry,
    *,
    tool: str,
    args: Dict[str, Any],
    extras_factory: Optional[Any] = None,
) -> Iterator[Dict[str, Any]]:
    """Context manager: time the wrapped block, record an event on exit.

    ``extras_factory`` is an optional callable taking the result object
    (set on the yielded dict as ``result``) and returning a dict of extra
    fields to merge into the event. Caller sets ``yielded["result"] = ...``
    so the factory can read it.
    """
    start = time.perf_counter()
    state: Dict[str, Any] = {"result": None}
    err_class: Optional[str] = None
    try:
        yield state
    except Exception as exc:
        err_class = type(exc).__name__
        raise
    finally:
        event: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "args_hash": hash_args(args),
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 1),
            "ok": err_class is None,
            "error_class": err_class,
        }
        if extras_factory is not None and err_class is None:
            try:
                extras = extras_factory(state.get("result"))
                if isinstance(extras, dict):
                    event.update(extras)
            except Exception:
                pass
        tel.record(event)
