"""Tests de la présentation métier des résultats (Modèles internes et Recherche juridique).

Aucun score de similarité, extrait technique, JSON, chunk ni nom de fichier brut ne doit
apparaître côté notaire. Les références juridiques ne sont affichées que si les métadonnées
existent ; aucun nom de loi, numéro d'article ou interprétation n'est jamais inventé.
"""
from __future__ import annotations

from app.services.presentation import (
    AVERTISSEMENT_MODELE,
    REFERENCE_A_VERIFIER,
    carte_juridique,
    carte_modele,
    juridique_titre,
    modele_source_name,
    partition_juridique_results,
    partition_modele_results,
)

_CHUNK_MODELE = {
    "chunk_id": "modele-thmn-lby-1:0",
    "source": "modele",
    "fichier": "thmn-lby-1.docx",
    "type_modele": "clause_prix_paiement_differe",
    "section": "prix_paiement",
    "text": "Une partie du prix est payée immédiatement et le solde est différé jusqu'à l'accomplissement des formalités d'enregistrement et d'inscription foncière.",
    "score": 3.7,
}

_DICT_LOI = {
    "chunk_id": "loi-32-09__art1__p1__c0",
    "source": "loi",
    "law_name": "Loi n° 32-09 relative à l'organisation de la profession de notaire",
    "article_num": "1",
    "text": "Le notariat est une profession libérale qui s'exerce conformément aux conditions et attributions prévues par la présente loi.",
    "score": 2.9,
}

_DICT_LOI_SANS_METADONNEES = {
    "chunk_id": "loi-x:0",
    "source": "loi",
    "text": "Extrait juridique sans référence complète.",
    "score": 2.0,
}


def test_modele_titre_sans_underscore_ni_nom_brut():
    carte = carte_modele(_CHUNK_MODELE)
    assert "_" not in carte["titre"]
    assert "docx" not in carte["titre"]
    assert "thmn" not in carte["titre"]
    assert carte["titre"] == "Clause de paiement différé du prix"


def test_modele_source_lisible():
    assert modele_source_name(_CHUNK_MODELE) == "Clause de paiement différé du prix"
    source_raw = modele_source_name({"fichier": "engagement-ATTIJARIWAFABANK.doc"})
    assert "_" not in source_raw and ".doc" not in source_raw


def test_modele_avertissement_metier_visible():
    carte = carte_modele(_CHUNK_MODELE)
    assert carte["avertissement"] == AVERTISSEMENT_MODELE
    assert "référence" in AVERTISSEMENT_MODELE.lower()


def test_modele_elements_uniquement_presents_dans_lextrait():
    carte = carte_modele({**_CHUNK_MODELE, "text": "Le prix est payé comptant entre les parties."})
    assert "consignation d'une partie du prix" not in carte["elements"]
    assert carte["elements"]


def test_modele_aucun_score_ni_detail_technique_visible():
    carte = carte_modele(_CHUNK_MODELE)
    sortie = " ".join(str(v) for v in carte.values()).lower()
    for interdit in ("score", "3.7", "chunk", "qdrant", "json"):
        assert interdit not in sortie


def test_modele_resultats_secondaires_replies():
    chunks = [_CHUNK_MODELE] * 5
    principaux, secondaires = partition_modele_results(chunks)
    assert len(principaux) == 3
    assert len(secondaires) == 2


def test_juridique_titre_et_article_seulement_si_disponibles():
    carte = carte_juridique(_DICT_LOI)
    assert carte["titre"] == _DICT_LOI["law_name"]
    assert carte["article"] == "Article 1"
    assert carte["extrait"]
    assert carte["reponse"]
    assert carte["a_verifier"].startswith("Le texte officiel")


def test_juridique_reference_a_verifier_si_metadonnees_absentes():
    carte = carte_juridique(_DICT_LOI_SANS_METADONNEES)
    assert carte["titre"] == REFERENCE_A_VERIFIER
    assert carte["article"] == ""


def test_juridique_aucune_reference_inventee():
    assert juridique_titre({}) == REFERENCE_A_VERIFIER
    carte = carte_juridique({"text": "extrait", "article_num": "999"})
    assert carte["article"] == "Article 999"
    assert carte["titre"] == REFERENCE_A_VERIFIER


def test_juridique_bloc_autres_articles():
    dicts = [
        {**_DICT_LOI, "article_num": "1"},
        {**_DICT_LOI, "article_num": "2"},
        {**_DICT_LOI, "article_num": "3"},
    ]
    principal, autres = partition_juridique_results(dicts)
    assert principal["article"] == "Article 1"
    assert [a["article"] for a in autres] == ["Article 2", "Article 3"]


def test_juridique_aucun_score_ni_nom_technique_visible():
    carte = carte_juridique(_DICT_LOI)
    sortie = " ".join(str(v) for v in carte.values()).lower()
    for interdit in ("score", "2.9", "chunk_id", "json"):
        assert interdit not in sortie
