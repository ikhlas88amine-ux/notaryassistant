"""Historique de session des recherches (Modèles internes et Recherche juridique).

Règles garanties :
- l'historique est conservé UNIQUEMENT dans l'état de session/UI (jamais écrit dans les
  documents, les dossiers, Qdrant, les chunks, les corpus ou les index) ;
- au maximum 20 entrées par onglet, strictement séparées entre Modèles et Juridique ;
- aucune requête ni texte intégral de source n'est persistée hors de la session ;
- aucun score ni détail technique n'est exposé dans les libellés.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

HISTORY_LIMIT = 20


def now_label(now: Optional[datetime] = None) -> str:
    """Libellé d'horodatage lisible, ex. « Aujourd'hui, 15:30 »."""
    dt = now or datetime.now()
    return dt.strftime("Aujourd'hui, %H:%M")


def add_entry(
    entries: list[dict],
    question: str,
    nb_resultats: int,
    horodatage: Optional[str] = None,
    limit: int = HISTORY_LIMIT,
) -> list[dict]:
    """Ajoute une entrée en tête (dédupliquée par question) et borne la liste à `limit` entrées."""
    question = (question or "").strip()
    entry = {
        "question": question,
        "horodatage": horodatage or now_label(),
        "nb_resultats": max(0, int(nb_resultats or 0)),
    }
    out = [entry] + [e for e in (entries or []) if (e or {}).get("question") != question]
    return out[:limit]


def clear_entries(entries: list[dict]) -> list[dict]:
    """Efface l'historique d'un onglet (aucun effet hors session)."""
    return []


def relance_question(entry: dict) -> str:
    """Question à relancer depuis une entrée d'historique."""
    return (entry or {}).get("question", "")


def resultat_label(nb: int) -> str:
    """Libellé métier du nombre de résultats (aucune information technique)."""
    if nb <= 0:
        return "Aucun résultat exploitable"
    if nb == 1:
        return "1 résultat pertinent"
    return f"{nb} résultats pertinents"
