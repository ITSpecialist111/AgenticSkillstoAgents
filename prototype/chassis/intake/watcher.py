"""Watcher - a dependency-light, content-hash polling loop.

This is the "monitoring" layer: it re-runs discovery on a schedule and reports
which skill folders have *changed* since the last scan (by hashing ``SKILL.md``
plus every sidecar). Polling keeps the prototype zero-extra-dependency and in the
spirit of the rest of the chassis; a filesystem-events backend (watchdog, inotify)
can replace :meth:`IntakeWatcher.watch` later behind the same interface.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Callable, Dict, List, Optional

from .discovery import SkillSource, discover


def hash_source(source: SkillSource) -> str:
    """Return a stable content hash of a skill folder (``SKILL.md`` + sidecars).

    The hash covers each file's relative path *and* its bytes, so renames, edits,
    additions, and deletions all change the digest.
    """
    digest = hashlib.sha256()
    for path in [source.skill_md, *source.sidecars]:
        rel = os.path.relpath(path, source.skill_dir).replace(os.sep, "/")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            with open(path, "rb") as handle:
                for chunk in iter(lambda h=handle: h.read(65536), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


class IntakeWatcher:
    """Tracks content hashes per skill folder and reports changes on each scan."""

    def __init__(self) -> None:
        self._hashes: Dict[str, str] = {}

    def scan(self, root: str) -> List[SkillSource]:
        """Return skill folders that are new or changed since the last scan.

        Idempotent: scanning an unchanged tree twice yields ``[]`` the second
        time. Disappeared folders are forgotten so they re-fire if re-added.
        """
        changed: List[SkillSource] = []
        seen: Dict[str, str] = {}
        for source in discover(root):
            current = hash_source(source)
            seen[source.skill_dir] = current
            if self._hashes.get(source.skill_dir) != current:
                changed.append(source)
        self._hashes = seen
        return changed

    def watch(
        self,
        root: str,
        on_change: Callable[[SkillSource], None],
        *,
        interval: float = 1.0,
        iterations: Optional[int] = None,
    ) -> int:
        """Poll ``root`` every ``interval`` seconds, calling ``on_change`` per change.

        Runs forever when ``iterations`` is ``None``; otherwise runs exactly that
        many scan cycles (used by tests). Returns the total number of change
        callbacks fired.
        """
        fired = 0
        count = 0
        while iterations is None or count < iterations:
            for source in self.scan(root):
                on_change(source)
                fired += 1
            count += 1
            if iterations is not None and count >= iterations:
                break
            time.sleep(interval)
        return fired
