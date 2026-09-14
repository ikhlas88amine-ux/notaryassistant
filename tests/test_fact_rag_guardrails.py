from __future__ import annotations

from app.services.rag_service import RagService


class _FakeOllamaUnavailable:
    def is_available(self) -> bool:
        return False


def _service() -> RagService:
    svc = RagService()
    svc.ollama = _FakeOllamaUnavailable()
    return svc


def test_sqalli_title_credit_rank_combined_answer():
    svc = _service()
    response = svc.chat(
        "Quel est le titre foncier concerné, le montant du crédit garanti et le rang de l’hypothèque ?",
        scope="dossier",
        dossier_id="10-2024-542-HYPOTHEQUE-SQALLI",
    )
    assert response.answer_type == "documentary_answer"
    assert "148.201/08" in response.answer
    assert "420 000 DHS" in response.answer
    assert "3e rang" in response.answer
    assert "villa" not in response.answer.lower()


def test_sqalli_constituant_bank_delay_prudent_answer():
    svc = _service()
    response = svc.chat(
        "Qui est le constituant de l’hypothèque, quelle banque en bénéficie, et quel est le délai prévu pour l’inscription ?",
        scope="dossier",
        dossier_id="10-2024-542-HYPOTHEQUE-SQALLI",
    )
    assert "AL BARID BANK" in response.answer
    assert "30 jours à compter du déblocage des fonds" in response.answer
    assert "Réda SQALLI" in response.answer
    assert "unique constituant" not in response.answer.lower()


def test_alaoui_parties_preserve_arabic_names():
    svc = _service()
    response = svc.chat(
        "Identifie le vendeur et l’acquéreur, en conservant leur nom arabe tel qu’il apparaît dans l’acte.",
        scope="dossier",
        dossier_id="17-2025-967-VENTE-ALAOUI",
    )
    assert "لطيفة العلوي" in response.answer
    assert "ابراهيم النجاري" in response.answer
    assert "Mouhamadou Diallo" not in response.answer
    assert "Banque Al Ahli" not in response.answer
    assert "Lamia ALAOUI" not in response.answer


def test_alaoui_notary_accounting_negation_is_blocking():
    svc = _service()
    response = svc.chat(
        "Le prix a-t-il transité par la comptabilité du notaire ? Donne la formulation arabe qui justifie ta réponse.",
        scope="dossier",
        dossier_id="17-2025-967-VENTE-ALAOUI",
    )
    assert response.answer.startswith("Non.")
    assert "خارج مراقبة الموثق الممضي أسفله وخارج محاسبته" in response.answer
    assert "a transité par la comptabilité du notaire" not in response.answer.lower()


def test_alaoui_death_question_is_insufficient_context():
    svc = _service()
    response = svc.chat(
        "Qui est le défunt dans ce dossier ? Si aucun décès n’est mentionné, dis-le sans inférer un rôle.",
        scope="dossier",
        dossier_id="17-2025-967-VENTE-ALAOUI",
    )
    assert response.answer_type == "insufficient_context"
    assert "Aucun décès ni défunt" in response.answer


def test_alaoui_fees_and_taxes_are_not_abstained():
    svc = _service()
    response = svc.chat(
        "Quelle partie supporte les frais de l’acte et quelle partie reste responsable des impôts et taxes dus avant la vente ?",
        scope="dossier",
        dossier_id="17-2025-967-VENTE-ALAOUI",
    )
    assert "À la charge de l’acquéreur" in response.answer
    assert "À la charge du vendeur" in response.answer
