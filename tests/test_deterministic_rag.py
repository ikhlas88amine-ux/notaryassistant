"""Tests de non-regression du RAG deterministe (cahier des charges §13 - RAG).

Ces tests ne demandent ni Ollama ni reseau : ils verifient la couche deterministe
(reponses constructibles depuis dossier_master.json + rapport de validation, routage exclusif
du corpus, abstention stricte). Le moteur de generation local y est simule indisponible.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.schemas import ChatRequest, SearchRequest
from app.retrieval.qdrant_store import UnsafeSearchError
from app.retrieval.relevance import INTENT_FINANCING, INTENT_MODELS, INTENT_PARTIES, INTENT_PRICE, INTENT_RISKS, detect_intent
from app.services.rag_service import RagService


class _FakeOllamaUnavailable:
    def is_available(self) -> bool:
        return False


def _service() -> RagService:
    svc = RagService()
    svc.ollama = _FakeOllamaUnavailable()
    return svc


# --- 1. Dossier SMIRI : parties ---
def test_parties_smiri_deterministe():
    svc = _service()
    answer = svc._deterministic_answer(INTENT_PARTIES, "21-2026-549-VENTE-SMIRI", [])
    assert "SARL DAR AL BAHJA PROMOTION" in answer          # vendeur
    assert "Othmane FILALI" in answer                        # representant du vendeur
    assert "Sofia SMIRI" in answer and "Yassir SMIRI" in answer  # acquereurs
    assert "AL BARID BANK" in answer                          # banque
    assert answer.count("AL BARID BANK") == 1                 # jamais deux fois (pas classee vendeur)


# --- 2. Prix SMIRI ---
def test_prix_smiri_deterministe():
    svc = _service()
    answer = svc._deterministic_answer(INTENT_PRICE, "21-2026-549-VENTE-SMIRI", [])
    assert "980 000 DHS" in answer
    assert "HUIT CENT VINGT" not in answer


# --- 3. Financement SMIRI ---
def test_financement_smiri_deterministe():
    svc = _service()
    answer = svc._deterministic_answer(INTENT_FINANCING, "21-2026-549-VENTE-SMIRI", [])
    assert "500 000 DHS" in answer     # Sofia
    assert "300 000 DHS" in answer     # Yassir
    assert "800 000 DHS" in answer     # total calcule
    assert "HUIT CENT VINGT" not in answer
    assert "Apport personnel" not in answer and "apport personnel" not in answer


# --- 4. Hypotheque SQALLI : credit garanti et rang, jamais le rang comme montant ---
def test_financement_sqalli_rang_et_credit():
    svc = _service()
    answer = svc._deterministic_answer(INTENT_FINANCING, "10-2024-542-HYPOTHEQUE-SQALLI", [])
    assert "420 000 DHS" in answer      # credit garanti
    assert "3e rang" in answer          # rang
    assert "Le montant de l'hypothèque est de 3e rang" not in answer.lower().replace("é", "e").replace("è", "e")


# --- 5. Dossier AMBIGU : contradiction de prix sur les seules valeurs sources ---
def test_risques_ambigu_sans_date_inventee():
    svc = _service()
    answer = svc._deterministic_answer(INTENT_RISKS, "1-2024-843-AMBIGU", [])
    assert "price_multiple_declared" in answer
    assert "1650000" in answer and "340000" in answer
    assert "2024-06-21" not in answer


# --- 6. Modeles : abstention standard sans resultat ---
def test_abstention_modeles_sans_resultat():
    svc = _service()
    svc.search = lambda query, scope, dossier_id, top_k=5: {"templates_internal": []}
    reponse = svc.chat("REQUISITION.BANQUE.PT", scope="template", dossier_id=None)
    assert "Aucun modèle correspondant n'a été identifié" in reponse.answer
    assert "REQUISITION.BANQUE.PT" not in reponse.answer
    assert reponse.answer_type == "insufficient_context"


# --- 7. Documents manquants : abstention stricte sans checklist applicable ---
def test_abstention_documents_manquants_ambigu():
    """Le dossier AMBIGU n'a aucune checklist (type 'AMBIGU' sans checklist fournie)."""
    svc = _service()
    svc.search = lambda query, scope, dossier_id, top_k=5: {"case_documents": []}
    reponse = svc.chat("Quels documents manquent encore dans ce dossier ?", scope="dossier", dossier_id="1-2024-843-AMBIGU")
    assert "Les documents manquants ne peuvent pas être déterminés" in reponse.answer
    assert reponse.answer_type == "insufficient_context"


# --- 8. Choix exclusif du corpus : 'mixed' interdit ---
def test_scope_mixed_refuse():
    with pytest.raises(ValidationError):
        SearchRequest(query="x", scope="mixed")
    with pytest.raises(ValidationError):
        ChatRequest(query="x", scope="mixed")


def test_scope_dossier_sans_dossier_id_refuse():
    svc = _service()
    with pytest.raises(UnsafeSearchError):
        svc.search("hypotheque", scope="dossier", dossier_id=None)


# --- 9. Isolation : l'intention est bien detectee ---
def test_detect_intent():
    assert detect_intent("Qui est le vendeur ?", "dossier") == INTENT_PARTIES
    assert detect_intent("Quel est le prix de vente ?", "dossier") == INTENT_PRICE
    assert detect_intent("Comment est financé l'achat ?", "dossier") == INTENT_FINANCING
    assert detect_intent("Y a-t-il des risques ?", "dossier") == INTENT_RISKS
    assert detect_intent("Quel modèle utiliser ?", "template") == INTENT_MODELS
    assert detect_intent("question juridique", "law") == "legal"
