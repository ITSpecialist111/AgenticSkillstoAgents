"""Deterministic extractive summarizer (sidecar script for the text.summarize skill)."""

from __future__ import annotations

import re
from collections import Counter


def summarize(document: str, max_sentences: int = 3) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", document) if s.strip()]
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    freq = Counter(re.findall(r"[a-z]+", document.lower()))
    scored = sorted(
        enumerate(sentences),
        key=lambda pair: sum(freq[w] for w in re.findall(r"[a-z]+", pair[1].lower())),
        reverse=True,
    )
    top = sorted(scored[:max_sentences], key=lambda pair: pair[0])
    return " ".join(sentence for _, sentence in top)
