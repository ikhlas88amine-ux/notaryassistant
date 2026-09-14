"""Tests de non-régression des 8 échecs représentatifs (objectif 34/34) + garde anti-réponse vide.

Exécution locale : aucun Ollama ni Qdrant requis (le moteur déterministe répond depuis les
chunks jsonl réels du corpus). Même convention que tests/test_deterministic_rag.py et
tests/test_fact_rag_guardrails.py : Ollama est simulé indisponible.
"""
from __future__ import annotations

from app.services.rag_service import RagService, _guard_documentary_answer


class _FakeOllamaUnavailable:
    def is_available(self) -> bool:
        return False


def _service() -> RagService:
    svc = RagService()
    svc.ollama = _FakeOllamaUnavailable()
    return svc


def _ask(dossier_id: str, question: str):
    svc = _service()
    return svc.chat(question, scope="dossier", dossier_id=dossier_id, top_k=5)


# --- 1. Donation : taux de droits d'enregistrement = 1,5% ---
def test_donation_taux_droits_enregistrement():
    r = _ask(
        "11-2024-595-DONATION-AMRANI",
        "Quel est le taux de droits d'enregistrement appliqué dans le dossier 11-2024-595-DONATION-AMRANI ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "1,5%" in r.answer
    assert any("acte_de_donation" in (s.fichier or "") for s in r.sources)


# --- 2. Succession : défunt = Mohamed ELYACOUBI ---
def test_succession_defunt_nom():
    r = _ask(
        "7-2025-605-SUCCESSION-ELYACOUBI",
        "Qui est le défunt dans le dossier 7-2025-605-SUCCESSION-ELYACOUBI ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "Mohamed ELYACOUBI" in r.answer
    assert any("acte_notoriete_successorale" in (s.fichier or "") for s in r.sources)


# --- 3. Succession : date du décès normalisée ISO ---
def test_succession_date_deces_iso():
    r = _ask(
        "7-2025-605-SUCCESSION-ELYACOUBI",
        "Quelle est la date du décès dans le dossier 7-2025-605-SUCCESSION-ELYACOUBI ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "2025-07-30" in r.answer
    assert any("acte_notoriete_successorale" in (s.fichier or "") for s in r.sources)


# --- 4. Donation : modèle réel -> qualification arabe présente dans le document ---
def test_donation_modele_qualification_arabe():
    r = _ask(
        "11-2024-595-DONATION-AMRANI",
        "Le dossier 11-2024-595-DONATION-AMRANI s'appuie-t-il sur un modèle réel de l'étude ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "عقد صدقة لا رجعة فيها" in r.answer
    assert any("acte_de_donation" in (s.fichier or "") for s in r.sources)


# --- 5. Succession : modèle réel -> STRUCTURE LEGALE STANDARD ---
def test_succession_modele_structure_standard():
    r = _ask(
        "7-2025-605-SUCCESSION-ELYACOUBI",
        "Le dossier 7-2025-605-SUCCESSION-ELYACOUBI s'appuie-t-il sur un modèle réel de l'étude ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "STRUCTURE LEGALE STANDARD" in r.answer
    assert any("acte_notoriete_successorale" in (s.fichier or "") for s in r.sources)


# --- 6. Dossier ambigu : comparaison des deux prix -> anomalie ---
def test_ambigu_comparaison_prix_anomalie():
    r = _ask(
        "1-2024-843-AMBIGU",
        "Le prix de vente est-il identique dans les deux versions du dossier 1-2024-843-AMBIGU ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "NE PAS UTILISER COMME ACTE AUTHENTIQUE" in r.answer
    assert "1.650.000" in r.answer and "340.000" in r.answer
    assert any("acte_de_vente" in (s.fichier or "") for s in r.sources)


# --- 7. Dossier ambigu : prix version française = 1.650.000 ---
def test_ambigu_prix_version_francaise():
    r = _ask(
        "1-2024-843-AMBIGU",
        "Quel est le prix indiqué en version française dans le dossier 1-2024-843-AMBIGU ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "1.650.000" in r.answer
    assert any("acte_de_vente" in (s.fichier or "") for s in r.sources)


# --- 8. Dossier ambigu : prix version arabe traduite = 340.000 ---
def test_ambigu_prix_version_arabe():
    r = _ask(
        "1-2024-843-AMBIGU",
        "Quel est le prix indiqué en version arabe (traduite) dans le dossier 1-2024-843-AMBIGU ?",
    )
    assert r.answer_type == "documentary_answer"
    assert "340.000" in r.answer
    assert any("acte_de_vente" in (s.fichier or "") for s in r.sources)


# --- 9. Non-régression : aucune réponse documentaire vide ou réduite à « Sources : » ---
def test_jamais_reponse_documentaire_vide_ni_source_seule():
    abstention = "Cette information ne peut pas être déterminée à partir des sources disponibles."
    assert _guard_documentary_answer("") == abstention
    assert _guard_documentary_answer(None) == abstention
    assert _guard_documentary_answer("   \n  ") == abstention
    assert _guard_documentary_answer("Sources :") == abstention
    assert _guard_documentary_answer("Source :") == abstention
    assert _guard_documentary_answer("Sources :\n- 01_acte_de_vente.docx") == abstention
    # une réponse métier normale est conservée telle quelle
    assert _guard_documentary_answer("Le défunt est Mohamed ELYACOUBI.") == "Le défunt est Mohamed ELYACOUBI."
