"""Correctif 1 (BLOQUANT) : app/retrieval/relevance.py doit fonctionner avec de vrais
objets Pydantic SourceCitation, pas seulement avec des dicts.

Reproduit l'AttributeError historique : 'SourceCitation' object has no attribute 'get'.
"""
from __future__ import annotations

from app.core.schemas import SourceCitation
from app.retrieval.relevance import (
    INTENT_LEGAL,
    INTENT_MODELS,
    INTENT_PARTIES,
    filter_chunks,
    value_of,
)


def _citation(**overrides) -> SourceCitation:
    base = dict(
        source="client",
        dossier_id="D1",
        fichier="doc.docx",
        section="identification_parties",
        chunk_id="D1:doc:0",
        excerpt="Le vendeur et l'acquéreur ont comparu.",
        chunk_role="parties",
    )
    base.update(overrides)
    return SourceCitation(**base)


def test_value_of_supports_pydantic_object_and_dict():
    cit = _citation()
    assert value_of(cit, "fichier") == "doc.docx"
    assert value_of(cit, "section") == "identification_parties"
    assert value_of(cit, "inexistant", "défaut") == "défaut"

    as_dict = {"fichier": "doc.docx", "section": "identification_parties"}
    assert value_of(as_dict, "fichier") == "doc.docx"
    assert value_of(as_dict, "inexistant", "défaut") == "défaut"


def test_filter_chunks_accepts_real_source_citation_objects_parties():
    """Ne doit pas lever AttributeError et doit retourner la citation pertinente."""
    citations = [
        _citation(chunk_id="D1:doc:0", chunk_role="parties", section="identification_parties"),
        _citation(chunk_id="D1:doc:1", chunk_role="price", section="prix_paiement", excerpt="780000 DHS"),
    ]
    filtered = filter_chunks(citations, INTENT_PARTIES, top_n=3)
    assert filtered, "au moins une citation pertinente attendue"
    assert all(isinstance(c, SourceCitation) for c in filtered)
    assert filtered[0].chunk_id == "D1:doc:0"


def test_filter_chunks_models_dedupe_by_fichier_with_source_citation():
    citations = [
        _citation(chunk_id="M:1", source="modele", fichier="modele_a.docx", section="clause"),
        _citation(chunk_id="M:2", source="modele", fichier="modele_a.docx", section="clause"),
        _citation(chunk_id="M:3", source="modele", fichier="modele_b.docx", section="clause"),
    ]
    filtered = filter_chunks(citations, INTENT_MODELS, top_n=5)
    fichiers = [c.fichier for c in filtered]
    assert fichiers == sorted(set(fichiers), key=fichiers.index)
    assert len(fichiers) == len(set(fichiers))


def test_filter_chunks_legal_only_keeps_loi_source_with_source_citation():
    citations = [
        _citation(chunk_id="L:1", source="loi", section="article", article_num="212", excerpt="article 212 du code"),
        _citation(chunk_id="C:1", source="client", section="autre"),
    ]
    filtered = filter_chunks(citations, INTENT_LEGAL, top_n=5)
    assert len(filtered) == 1
    assert filtered[0].source == "loi"
