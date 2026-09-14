"""Augmentation d'un chunk : classification (rôle/section), extraction d'entités, flags qualité.

Correctifs 1-7 : la notice technique sort dans un chunk dédié non indexable, la classification
suit l'ordre de priorité obligatoire, les fragments dégénérés sont exclus, les entités sont
validées (CIN, prêts, rangs, montants, dates, banques, personnes structurées, arabe).
"""
from __future__ import annotations

from app.chunking.quality import (
    classify_full,
    extract_entities,
    is_degenerate_chunk,
)


def _apply_indexability(chunk) -> None:
    """Un chunk de notice technique n'est jamais indexable ; les fragments dégénérés non plus."""
    if chunk.chunk_role == "technical_notice" or chunk.indexable is False:
        chunk.indexable = False
        chunk.retrieval_excluded = True
        if chunk.indexable is False and "technical_notice" not in chunk.quality_flags:
            pass  # le drapeau est posé par le chunker / classify_full
        return
    degenerate, flag = is_degenerate_chunk(chunk.text)
    if degenerate:
        chunk.indexable = False
        chunk.retrieval_excluded = True
        qf = [f for f in chunk.quality_flags if f != "table_artifact_or_fragment"]
        qf.append("table_artifact_or_fragment" if "|" in chunk.text else flag)
        chunk.quality_flags = list(dict.fromkeys(qf))


def augment(chunk):
    """Met à jour rôle, section, entités, flags et indexabilité. Rétrocompatible : ne touche
    jamais aux champs law_id/chunk_id/text (lois) ni aux métadonnées d'origine."""
    role, conf, section, secondary = classify_full(chunk.text)

    if chunk.source in ("client", "modele"):
        chunk.chunk_role = role
        chunk.secondary_chunk_roles = list(dict.fromkeys(secondary))
        chunk.chunk_roles = [role] + chunk.secondary_chunk_roles

        # La section du chunker (détection par en-tête) prime si elle est 'detected' avec
        # une confiance non nulle et n'est pas 'clauses_diverses' ; sinon on applique la
        # classification par contenu (ordre de priorité du Correctif 2).
        heading_ok = (
            chunk.section_source == "detected"
            and chunk.section not in (None, "", "clauses_diverses")
            and chunk.section_confidence >= 0.5
        )
        if not heading_ok:
            chunk.section = section
            chunk.section_source = "detected" if conf >= 0.9 else "inferred"
            chunk.section_confidence = max(chunk.section_confidence, conf)

        if role == "technical_notice":
            chunk.quality_flags = list(dict.fromkeys([*chunk.quality_flags, "technical_notice"]))

        _apply_indexability(chunk)

        entities, entity_conf, flags, review = extract_entities(chunk.text)
        chunk.entities = entities
        chunk.entity_extraction_confidence = entity_conf
        chunk.quality_flags = list(dict.fromkeys([*chunk.quality_flags, *flags]))
        if review:
            chunk.requires_human_review = True

    return chunk
