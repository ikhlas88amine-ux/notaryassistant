"""Helpers de guardrails lecture seule pour la construction du contexte RAG."""
from __future__ import annotations

from app.retrieval.relevance import (
    INTENT_ACCOUNTING,
    INTENT_AREA,
    INTENT_BORROWER,
    INTENT_DONATION,
    INTENT_FINANCING,
    INTENT_LAND_TITLE,
    INTENT_PROCURATION,
    INTENT_RESUME,
    INTENT_RISKS,
    INTENT_SUCCESSION,
)

_DOC_HEAVY_INTENTS = {
    INTENT_FINANCING,
    INTENT_BORROWER,
    INTENT_DONATION,
    INTENT_SUCCESSION,
    INTENT_PROCURATION,
    INTENT_ACCOUNTING,
    INTENT_LAND_TITLE,
    INTENT_AREA,
}
_SUMMARY_INTENTS = {INTENT_RESUME, INTENT_RISKS}


def context_window_for_intent(intent: str) -> tuple[int, int]:
    if intent in _SUMMARY_INTENTS:
        return (6, 10)
    if intent in _DOC_HEAVY_INTENTS:
        return (5, 8)
    return (3, 5)


def target_context_size(intent: str, available: int) -> int:
    low, high = context_window_for_intent(intent)
    if available <= 0:
        return 0
    if available < low:
        return available
    return min(available, high)


def dedupe_citations(citations: list, max_items: int | None = None) -> list:
    seen = set()
    out = []
    for citation in citations:
        key = getattr(citation, "chunk_id", None) or getattr(citation, "doc_id", None) or getattr(citation, "fichier", None)
        if key in seen:
            continue
        seen.add(key)
        out.append(citation)
        if max_items is not None and len(out) >= max_items:
            break
    return out
