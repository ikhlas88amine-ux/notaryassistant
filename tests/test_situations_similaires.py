"""Tests du mode volontaire de recherche de situations similaires.

Ce mode n'a AUCUNE activation automatique : jamais utilisé comme fallback du RAG de
dossier ; le RAG de dossier conserve son dossier_id obligatoire ; les résultats sont
anonymisés (aucun nom, CIN, adresse, titre foncier, montant, texte intégral, document
source ni score) ; les corpus modeles/lois ne sont jamais interrogés.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.retrieval.qdrant_store import UnsafeSearchError
from app.services.rag_service import RagService
from app.services.similar_cases import (
    AVERTISSEMENT_SIMILARES,
    anonymized_catalog,
    search_similar,
)

_VENTE_DIFFEREE = {
    "dossier_id": "5-2026-876-VENTE-TAZI",
    "type_public": "Vente immobilière",
    "variante_public": "Paiement différé",
    "annee": "2026",
    "traits": {
        "paiement_differe": True, "hors_comptabilite": False, "mixte_comptabilite": False,
        "financement_bancaire": False, "hypotheque": False, "caution": False,
        "donation": False, "donation_parent_enfant": False, "succession": False,
        "procuration": False, "vefa": False, "fonds_de_commerce": False,
        "societe": False, "gerance_libre": False, "vente": True, "annee": "2026",
    },
}

_HYPOTHEQUE_CAUTION = {
    "dossier_id": "10-2024-542-HYPOTHEQUE-SQALLI",
    "type_public": "Hypothèque",
    "variante_public": "Engagement avec caution hypothécaire",
    "annee": "2024",
    "traits": {
        "paiement_differe": False, "hors_comptabilite": False, "mixte_comptabilite": False,
        "financement_bancaire": True, "hypotheque": True, "caution": True,
        "donation": False, "donation_parent_enfant": False, "succession": False,
        "procuration": False, "vefa": False, "fonds_de_commerce": False,
        "societe": False, "gerance_libre": False, "vente": False, "annee": "2024",
    },
}

_DONATION = {
    "dossier_id": "11-2024-595-DONATION-AMRANI",
    "type_public": "Donation",
    "variante_public": "Standard",
    "annee": "2024",
    "traits": {
        "paiement_differe": False, "hors_comptabilite": False, "mixte_comptabilite": False,
        "financement_bancaire": False, "hypotheque": False, "caution": False,
        "donation": True, "donation_parent_enfant": True, "succession": False,
        "procuration": False, "vefa": False, "fonds_de_commerce": False,
        "societe": False, "gerance_libre": False, "vente": False, "annee": "2024",
    },
}

_CATALOGUE = [_VENTE_DIFFEREE, _HYPOTHEQUE_CAUTION, _DONATION]


class _FakeOllamaUnavailable:
    def is_available(self) -> bool:
        return False


def test_activation_explicite_obligatoire():
    assert search_similar("vente avec paiement différé", _CATALOGUE, enabled=False) == []
    assert search_similar("", _CATALOGUE, enabled=True) == []


def test_recherche_vente_paiement_differe():
    resultats = search_similar("vente avec paiement différé", _CATALOGUE, enabled=True, max_results=6)
    assert any(r["dossier_id"] == "5-2026-876-VENTE-TAZI" for r in resultats)
    assert resultats[0]["point_commun"] == "Un paiement immédiat et un solde différé sont indiqués."


def test_filtre_par_type():
    resultats = search_similar("hypothèque", _CATALOGUE, enabled=True, type_filter="Hypothèque", max_results=6)
    assert [r["dossier_id"] for r in resultats] == ["10-2024-542-HYPOTHEQUE-SQALLI"]
    resultats_ventes = search_similar(
        "vente", _CATALOGUE, enabled=True, type_filter="Tous les dossiers autorisés", max_results=6
    )
    assert any(r["dossier_id"] == "5-2026-876-VENTE-TAZI" for r in resultats_ventes)


def test_filtre_par_annee():
    resultats = search_similar("donation", _CATALOGUE, enabled=True, annee_filter="2024", max_results=6)
    assert all(r["annee"] == "2024" for r in resultats)


def test_filtre_par_variante():
    resultats = search_similar(
        "caution", _CATALOGUE, enabled=True, variante_filter="Engagement avec caution hypothécaire", max_results=6
    )
    assert [r["dossier_id"] for r in resultats] == ["10-2024-542-HYPOTHEQUE-SQALLI"]


def test_resultats_anonymises_sans_donnees_privees():
    resultats = search_similar("vente différé", _CATALOGUE, enabled=True)
    assert resultats
    assert set(resultats[0].keys()) == {"dossier_id", "type_public", "annee", "variante_public", "point_commun"}
    for r in resultats:
        for champ in ("nom", "cin", "adresse", "titre foncier", "dhs", "montant", "score"):
            assert champ not in str(r).lower()


def test_catalogue_anonymise_respecte_les_autorisations(tmp_path):
    dossiers = tmp_path / "dossiers"
    (dossiers / "A-2026-001-VENTE").mkdir(parents=True)
    (dossiers / "B-2026-002-VENTE").mkdir()
    master_a = {
        "dossier_id": "A-2026-001-VENTE", "type_dossier": "VENTE",
        "variante": "paiement_differe", "annee": 2026,
        "donnees": {"vendeur": {"nom_fr": "Nom Privé"}, "solde_differe_dhs": 100000},
    }
    master_b = {
        "dossier_id": "B-2026-002-VENTE", "type_dossier": "HYPOTHEQUE",
        "variante": "simple", "annee": 2026, "donnees": {},
    }
    (dossiers / "A-2026-001-VENTE" / "dossier_master.json").write_text(
        json.dumps(master_a, ensure_ascii=False), encoding="utf-8"
    )
    (dossiers / "B-2026-002-VENTE" / "dossier_master.json").write_text(
        json.dumps(master_b, ensure_ascii=False), encoding="utf-8"
    )
    catal = anonymized_catalog(dossiers, authorized_ids=["A-2026-001-VENTE"])
    assert [c["dossier_id"] for c in catal] == ["A-2026-001-VENTE"]
    # le nom privé ne doit jamais transiter dans le catalogue anonymisé
    assert "Nom Privé" not in json.dumps(catal, ensure_ascii=False)


def test_avertissement_permanent_present():
    assert "comparaison documentaire" in AVERTISSEMENT_SIMILARES
    assert "précédent juridique" in AVERTISSEMENT_SIMILARES


def test_jamais_fallback_du_rag_de_dossier():
    """Le module de situations similaires n'est importé par aucun chemin du RAG de dossier
    et une recherche de dossier sans dossier_id reste refusée."""
    src = (Path(__file__).resolve().parent.parent / "app" / "services" / "rag_service.py").read_text(encoding="utf-8")
    assert "similar_cases" not in src
    svc = RagService()
    svc.ollama = _FakeOllamaUnavailable()
    with pytest.raises(UnsafeSearchError):
        svc.search("hypothèque", scope="dossier", dossier_id=None)


def test_aucune_fuite_entre_dossiers_dans_une_reponse_du_rag():
    svc = RagService()
    svc.ollama = _FakeOllamaUnavailable()
    reponse = svc.chat("Quel est le prix de vente ?", scope="dossier", dossier_id="5-2026-876-VENTE-TAZI", top_k=5)
    for s in reponse.sources or []:
        if s.dossier_id:
            assert s.dossier_id == "5-2026-876-VENTE-TAZI"
