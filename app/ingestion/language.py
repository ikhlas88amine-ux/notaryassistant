"""Detection simple et deterministe de la langue d'un texte : fr, ar, fr_ar ou unknown.

On evite volontairement toute dependance a un modele de langue externe : la detection
est basee sur un comptage de caracteres (bloc Unicode arabe vs alphabet latin), ce qui
est suffisant et fiable pour des documents notariaux structures, et ne necessite aucun
appel reseau ni modele local.
"""
from __future__ import annotations

import re

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")


def detect_language(text: str) -> str:
    """Retourne 'fr', 'ar', 'fr_ar' ou 'unknown' selon la proportion de caracteres arabes/latins."""
    if not text or not text.strip():
        return "unknown"

    n_ar = len(_ARABIC_RE.findall(text))
    n_lat = len(_LATIN_RE.findall(text))
    total = n_ar + n_lat

    if total == 0:
        return "unknown"

    ar_ratio = n_ar / total
    lat_ratio = n_lat / total

    # Seuils : un texte est considere bilingue si les deux scripts representent
    # chacun une part significative (>= 15%) du contenu alphabetique detecte.
    if ar_ratio >= 0.15 and lat_ratio >= 0.15:
        return "fr_ar"
    if ar_ratio > lat_ratio:
        return "ar"
    if lat_ratio > ar_ratio:
        return "fr"
    return "unknown"
