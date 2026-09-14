from __future__ import annotations

import re

from app.core.schemas import SourceCitation


_QUOTED_RE = re.compile(r"[«\"]([^«»\"]+)[»\"]")
_AFFIRMATIVE_NOTARY_ACCOUNTING_RE = re.compile(r"(?i)\b(?:a\s+transit[ée]|a\s+été\s+payé\s+par\s+la\s+comptabilit[ée]|transit[ée]?\s+par\s+la\s+comptabilit[ée]\s+du\s+notaire)\b")
_NEGATION_MARKER_RE = re.compile(r"(?i)(hors\s+comptabilit[ée]|hors\s+contr[oô]le\s+du\s+notaire|خارج\s+محاسبته|خارج\s+مراقبة\s+الموثق)")
_BULLET_VALUE_RE = re.compile(r"^\s*-\s+(.+?)\.?\s*$", re.MULTILINE)


def _texts(citations: list[SourceCitation]) -> list[str]:
    return [(c.text or c.excerpt or "") for c in citations if (c.text or c.excerpt or "").strip()]


def validate_quotes(answer: str, citations: list[SourceCitation]) -> bool:
    texts = _texts(citations)
    for quoted in _QUOTED_RE.findall(answer or ""):
        if quoted and not any(quoted in text for text in texts):
            return False
    return True


def validate_negation_fidelity(answer: str, citations: list[SourceCitation]) -> bool:
    corpus = "\n".join(_texts(citations))
    if _NEGATION_MARKER_RE.search(corpus) and _AFFIRMATIVE_NOTARY_ACCOUNTING_RE.search(answer or ""):
        lowered = (answer or "").lower()
        if "non." not in lowered and "hors comptabil" not in lowered:
            return False
    return True


def _norm_for_match(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("dhs", "dh")
    text = re.sub(r"[\s,\.]+", "", text)
    return text


def validate_bullet_values(answer: str, citations: list[SourceCitation]) -> bool:
    texts = _texts(citations)
    normalized_texts = [_norm_for_match(t) for t in texts]
    source_mode = False
    for line in (answer or "").splitlines():
        if line.strip().lower().startswith("source"):
            source_mode = True
            continue
        if not line.strip():
            source_mode = False
            continue
        m = _BULLET_VALUE_RE.match(line)
        if not m or source_mode:
            continue
        cleaned = m.group(1).strip().strip(".")
        if not cleaned:
            continue
        if cleaned.lower().endswith((".docx", ".doc", ".pdf", ".json")):
            continue
        if any(ch.isdigit() for ch in cleaned):
            target = _norm_for_match(cleaned)
            if not any(target and target in text for text in normalized_texts):
                return False
        elif any('\u0600' <= ch <= '\u06FF' for ch in cleaned):
            if not any(cleaned in text for text in texts):
                return False
    return True


def validate_answer_fidelity(answer: str, citations: list[SourceCitation], answer_type: str) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    ok = True
    if not validate_quotes(answer, citations):
        ok = False
        warnings.append("Une citation entre guillemets ne correspond pas exactement à un chunk cité.")
    if not validate_negation_fidelity(answer, citations):
        ok = False
        warnings.append("La réponse contredit une négation explicite présente dans les sources citées.")
    if not validate_bullet_values(answer, citations):
        ok = False
        warnings.append("Une valeur affichée n’apparaît pas textuellement dans les sources citées.")
    if answer_type == "insufficient_context" and re.search(r"(?i)\b(?:vendeur|acquéreur|acquereur|banque bénéficiaire|crédit garanti|titre foncier)\b\s*:\s*\n\s*-", answer or ""):
        ok = False
        warnings.append("Une abstention ne doit pas contenir d’affirmation factuelle certaine.")
    return ok, warnings
