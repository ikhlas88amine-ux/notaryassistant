"""Synthèse courte assistée, uniquement après validation de fidélité.

Ollama peut reformuler une courte présentation des extraits DÉJÀ validés. Toute réponse
qui ajoute un fait (montant, numéro, sigle, date, nom…) absent des extraits est rejetée
et l'appelant affiche alors le rendu déterministe. Aucune nouvelle clause, obligation,
montant, interprétation ou conseil juridique n'est jamais rédigé ici.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from app.core.schemas import SourceCitation
from app.services.response_fidelity import validate_answer_fidelity

SYSTEM_PROMPT_NOTARY = (
    "Tu es un assistant documentaire pour une étude notariale.\n\n"
    "Tu réponds uniquement à partir des faits et extraits validés fournis.\n"
    "Tu n'ajoutes aucun nom, rôle, montant, date, titre foncier, banque, qualité juridique "
    "ou document absent des sources.\n"
    "Tu ne transformes jamais un exemple de modèle en donnée de dossier.\n"
    "Tu respectes strictement les négations explicites.\n"
    "Tu ne donnes pas de conseil juridique définitif.\n"
    "Tu réponds en français clair et concis.\n"
    "Tu n'affiches aucun détail technique.\n\n"
    "Si les informations validées sont insuffisantes, réponds exactement :\n"
    "« Cette information ne peut pas être déterminée à partir des sources disponibles. »"
)

REFINE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "answer_type": {"type": "string", "enum": ["documentary_answer", "insufficient_context"]},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "answer_type"],
}

_NUMBRE_RE = re.compile(r"\d{2,}(?:[ .,]\d{3})*(?:[.,]\d+)?")
_SIGLE_RE = re.compile(r"\b[A-ZÀ-Ý]{2,}(?:[A-ZÀ-Ý0-9-]{1,})\b")


def _normaliser(texte: str) -> str:
    return re.sub(r"[\s,.]", "", (texte or "")).lower()


def _faits_sensibles_nouveaux(reponse: str, textes_sources: list[str]) -> list[str]:
    """Montants, numéros et sigles présents dans la réponse mais absents des extraits."""
    norm_sources = " ".join(_normaliser(t) for t in textes_sources)
    texte_sources = " ".join(textes_sources)
    nouveaux: list[str] = []
    for m in _NUMBRE_RE.findall(reponse or ""):
        if _normaliser(m) and _normaliser(m) not in norm_sources and m not in nouveaux:
            nouveaux.append(m)
    for m in _SIGLE_RE.findall(reponse or ""):
        if m not in texte_sources and m not in nouveaux:
            nouveaux.append(m)
    return nouveaux


def _citations_minimales(textes: list[str]) -> list[SourceCitation]:
    return [
        SourceCitation(source="loi", fichier="extrait_valide", chunk_id=f"valide:{i}", text=t)
        for i, t in enumerate(textes)
        if (t or "").strip()
    ]


def refine_summary(
    question: str,
    client,
    textes: list[str],
    consigne: str,
    system_prompt: str = SYSTEM_PROMPT_NOTARY,
) -> Optional[str]:
    """Tente une courte synthèse Ollama validée.

    Retourne None si : Ollama indisponible, aucun extrait, réponse non exploitable,
    abstention demandée, fait sensible ajouté, ou échec du contrôle de fidélité standard.
    L'appelant affiche alors le rendu déterministe (jamais la réponse Ollama brute).
    """
    textes = [t for t in (textes or []) if (t or "").strip()]
    if not textes or not getattr(client, "is_available", lambda: False)():
        return None
    try:
        raw = client.chat(
            f"{consigne}\n\nQuestion : {question}",
            textes,
            json_schema=REFINE_JSON_SCHEMA,
            system_prompt=system_prompt,
        )
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001 — toute anomalie conduit au rendu déterministe
        return None
    answer = (parsed.get("answer") or "").strip()
    answer_type = parsed.get("answer_type", "documentary_answer")
    if not answer or answer_type == "insufficient_context":
        return None
    if _faits_sensibles_nouveaux(answer, textes):
        return None
    citations = _citations_minimales(textes)
    ok, _ = validate_answer_fidelity(answer, citations, answer_type)
    return answer if ok else None
