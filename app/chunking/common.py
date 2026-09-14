"""Utilitaires de decoupage generiques, partages par les trois chunkers (lois, modeles, dossiers).

Cible de taille : ~250 a 700 tokens par chunk (estimation ~4 caracteres/token, sans dependance
a un tokenizer externe). Pas de chevauchement par defaut ; 50 a 100 tokens de chevauchement
uniquement lorsque le decoupage d'une section/d'un article est necessaire parce qu'elle est trop
longue pour tenir dans un seul chunk. On ne melange jamais le texte de deux documents differents.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

CHARS_PER_TOKEN = 4
TARGET_MIN_TOKENS = 250
TARGET_MAX_TOKENS = 700
OVERLAP_TOKENS = 75

TARGET_MIN_CHARS = TARGET_MIN_TOKENS * CHARS_PER_TOKEN
TARGET_MAX_CHARS = TARGET_MAX_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN

_LIST_INTRO_RE = re.compile(r":\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*([0-9]+[).\-]|[\u0623-\u064a][).\-]|[-•\*])\s+")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN) if text else 0


def split_into_paragraphs(text: str) -> list[str]:
    """Coupe un texte deja nettoye en paragraphes non vides (une ligne = un paragraphe/une ligne de tableau)."""
    if not text:
        return []
    return [p.strip() for p in text.split("\n") if p.strip()]


def _is_list_intro(paragraph: str) -> bool:
    return bool(_LIST_INTRO_RE.search(paragraph)) and not _LIST_ITEM_RE.match(paragraph)


def _is_list_item(paragraph: str) -> bool:
    return bool(_LIST_ITEM_RE.match(paragraph))


def pack_paragraphs(paragraphs: list[str]) -> list[str]:
    """Regroupe une liste de paragraphes (appartenant a UNE SEULE section/article/document) en blocs
    de texte de taille cible, sans jamais separer une liste numerotee de son intitule, et en
    n'appliquant un chevauchement qu'entre les blocs issus du decoupage d'un meme contenu trop long.

    Retourne une liste de blocs de texte (chunks), dans l'ordre.
    """
    if not paragraphs:
        return []

    full_text = "\n".join(paragraphs)
    if len(full_text) <= TARGET_MAX_CHARS:
        return [full_text]

    blocks: list[str] = []
    buffer: list[str] = []
    buffer_len = 0

    i = 0
    n = len(paragraphs)
    while i < n:
        para = paragraphs[i]
        para_len = len(para) + 1  # +1 pour le saut de ligne de jonction

        would_exceed = buffer_len + para_len > TARGET_MAX_CHARS
        buffer_big_enough = buffer_len >= TARGET_MIN_CHARS
        prev_is_list_intro = bool(buffer) and _is_list_intro(buffer[-1])
        current_is_list_item = _is_list_item(para)

        if would_exceed and buffer_big_enough and not (prev_is_list_intro and current_is_list_item):
            blocks.append("\n".join(buffer))
            # chevauchement : on reprend la fin du bloc precedent au debut du suivant
            overlap_text = "\n".join(buffer)[-OVERLAP_CHARS:] if OVERLAP_CHARS else ""
            buffer = [overlap_text] if overlap_text else []
            buffer_len = len(overlap_text)

        buffer.append(para)
        buffer_len += para_len
        i += 1

    if buffer:
        blocks.append("\n".join(buffer))

    return blocks


SectionGroup = dict  # {"label": str|None, "source": str, "confidence": float, "paragraphs": list[str]}


def group_into_sections(
    paragraphs: list[str],
    classify: Callable[[str], Optional[tuple[str, str, float]]],
) -> list[SectionGroup]:
    """Regroupe une liste de paragraphes en sections contigues.

    `classify(paragraph)` doit retourner `(label, section_source, confidence)` si le paragraphe
    demarre une NOUVELLE section (il devient alors le premier paragraphe du groupe), ou `None`
    si le paragraphe poursuit la section courante.
    """
    groups: list[SectionGroup] = []
    current: SectionGroup = {"label": None, "source": "none", "confidence": 0.0, "paragraphs": []}

    for para in paragraphs:
        detected = classify(para)
        if detected is not None:
            if current["paragraphs"]:
                groups.append(current)
            label, source, confidence = detected
            current = {"label": label, "source": source, "confidence": confidence, "paragraphs": [para]}
        else:
            current["paragraphs"].append(para)

    if current["paragraphs"]:
        groups.append(current)

    return groups
