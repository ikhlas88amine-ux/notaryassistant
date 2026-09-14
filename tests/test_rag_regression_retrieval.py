from __future__ import annotations

from app.retrieval.relevance import (
    INTENT_ACCOUNTING,
    INTENT_DONATION,
    INTENT_LAND_TITLE,
    INTENT_PROCURATION,
    INTENT_SUCCESSION,
    detect_intent,
)
from app.services.rag_service import RagService


class _FakeOllamaUnavailable:
    def is_available(self) -> bool:
        return False


def _service() -> RagService:
    svc = RagService()
    svc.ollama = _FakeOllamaUnavailable()
    return svc


def test_detect_intent_extended_cases():
    assert detect_intent("Quel est le titre foncier du bien ?", "dossier") == INTENT_LAND_TITLE
    assert detect_intent("Qui est le donateur ?", "dossier") == INTENT_DONATION
    assert detect_intent("Qui est le défunt ?", "dossier") == INTENT_SUCCESSION
    assert detect_intent("Quelle est la durée de la procuration ?", "dossier") == INTENT_PROCURATION
    assert detect_intent("Le prix a-t-il transité par la comptabilité du notaire ?", "dossier") == INTENT_ACCOUNTING


def test_dossier_model_question_stays_inside_dossier_corpus():
    svc = _service()
    response = svc.chat(
        "Le dossier 4-2025-539-PROCURATION-ALAOUI s'appuie-t-il sur un modèle réel de l'étude ?",
        scope="dossier",
        dossier_id="4-2025-539-PROCURATION-ALAOUI",
        top_k=5,
    )
    assert response.answer_type in {"documentary_answer", "insufficient_context"}
    assert all(src.dossier_id == "4-2025-539-PROCURATION-ALAOUI" for src in response.sources if src.dossier_id)
    assert all(src.source == "client" for src in response.sources)
