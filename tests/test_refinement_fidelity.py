"""Tests des garde-fous Ollama (reformulation validée uniquement, jamais de fait inventé).

Vérifie que la synthèse assistée ne peut jamais ajouter un montant, un sigle ou un fait
absent des extraits validés, et qu'en cas d'échec (Ollama absent, réponse non fidèle,
abstention) la fonction retourne None pour laisser place au rendu déterministe.
"""
from __future__ import annotations

from app.services.refinement import SYSTEM_PROMPT_NOTARY, refine_summary


class _FakeChat:
    def __init__(self, raw: str, available: bool = True):
        self.raw = raw
        self.available = available

    def is_available(self) -> bool:
        return self.available

    def chat(self, user_message, context_blocks, json_schema=None, system_prompt=None):
        return self.raw


def test_prompt_systeme_notarial_general():
    assert "Tu es un assistant documentaire pour une étude notariale." in SYSTEM_PROMPT_NOTARY
    assert "Cette information ne peut pas être déterminée à partir des sources disponibles." in SYSTEM_PROMPT_NOTARY
    assert "Tu n'ajoutes aucun nom, rôle, montant, date, titre foncier, banque" in SYSTEM_PROMPT_NOTARY


def test_synthese_fidele_conservee():
    client = _FakeChat(
        '{"answer": "Le prix de vente est fixé à 980 000 DHS.", "answer_type": "documentary_answer"}'
    )
    resultat = refine_summary(
        "Quel est le prix ?",
        client,
        ["Le présent acte constate la vente. Le prix de vente est fixé à 980 000 DHS."],
        "Résume en une phrase.",
    )
    assert resultat == "Le prix de vente est fixé à 980 000 DHS."


def test_montant_invente_rejete():
    client = _FakeChat(
        '{"answer": "Le prix de vente est fixé à 999 999 DHS.", "answer_type": "documentary_answer"}'
    )
    resultat = refine_summary(
        "Quel est le prix ?",
        client,
        ["Le présent acte constate la vente. Le prix de vente est fixé à 980 000 DHS."],
        "Résume en une phrase.",
    )
    assert resultat is None


def test_sigle_invente_rejete():
    client = _FakeChat(
        '{"answer": "Le financement est accordé par la banque AL BARID BANK.", "answer_type": "documentary_answer"}'
    )
    resultat = refine_summary(
        "Quelle banque ?",
        client,
        ["Le financement est accordé pour 500 000 DHS."],
        "Résume en une phrase.",
    )
    assert resultat is None


def test_ollama_indisponible_retourne_none():
    client = _FakeChat('{"answer": "x", "answer_type": "documentary_answer"}', available=False)
    assert refine_summary("q", client, ["extrait"], "résume") is None


def test_abstention_retourne_none():
    client = _FakeChat('{"answer": "…", "answer_type": "insufficient_context"}')
    assert refine_summary("q", client, ["extrait"], "résume") is None


def test_reponse_non_json_retourne_none():
    client = _FakeChat("pas du json")
    assert refine_summary("q", client, ["extrait"], "résume") is None
