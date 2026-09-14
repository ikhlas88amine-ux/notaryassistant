"""Feature 5 : tests d'integration reels (Ollama + Qdrant embarque local) verifiant
l'isolation stricte des dossiers et l'interdiction de recherche client non filtree.

Ces tests appellent le vrai Ollama local et le vrai Qdrant embarque -- ils sont
automatiquement ignores (skip) si Ollama n'est pas disponible, mais ne sont JAMAIS
remplaces par un mock silencieux : soit ils tournent en reel, soit ils sont explicitement skip."""
from __future__ import annotations

import pytest

from app.retrieval.ollama_client import OllamaClient
from app.retrieval.qdrant_store import UnsafeSearchError, get_qdrant_store


def _ollama_available() -> bool:
    try:
        return OllamaClient().is_available()
    except Exception:  # noqa: BLE001
        return False


requires_ollama = pytest.mark.skipif(not _ollama_available(), reason="Ollama local non disponible sur cette machine.")


@requires_ollama
def test_search_case_documents_requires_dossier_id():
    store = get_qdrant_store()
    client = OllamaClient()
    vector = client.embed("hypotheque")
    with pytest.raises(UnsafeSearchError):
        store.search_case_documents(vector, dossier_id="")


@requires_ollama
def test_search_case_documents_returns_only_requested_dossier(settings):
    from app.chunking.dossiers_chunker import chunk_dossiers_corpus

    store = get_qdrant_store()
    client = OllamaClient()

    dossier_a = "9-2024-191-HYPOTHEQUE-AMRANI"
    dossier_b = "10-2024-542-HYPOTHEQUE-SQALLI"
    chunks, _ = chunk_dossiers_corpus(settings.dossiers_dir)
    relevant = [c for c in chunks if c.dossier_id in (dossier_a, dossier_b)]
    assert relevant, "Les 2 dossiers de test doivent produire des chunks."

    vectors = [client.embed(c.text) for c in relevant]
    store.upsert_chunks(relevant, vectors)

    query_vector = client.embed("hypotheque credit banque")
    results = store.search_case_documents(query_vector, dossier_id=dossier_a, top_k=10)
    assert all(p.payload["dossier_id"] == dossier_a for p in results), (
        "Une recherche filtree sur un dossier ne doit jamais renvoyer de points d'un autre dossier."
    )


@requires_ollama
def test_ollama_embed_returns_correct_dimension():
    client = OllamaClient()
    vector = client.embed("texte de test court")
    assert len(vector) == 768


@requires_ollama
def test_ollama_embed_handles_oversized_chunk_via_truncation_fallback():
    """Regression test pour le bug reel rencontre pendant l'indexation : certains chunks notariaux
    denses en chiffres depassent la fenetre de contexte du modele d'embedding (2048 tokens),
    alors meme que l'estimation caracteres/4 au chunking les jugeait dans la cible. Le client doit
    reussir par troncature progressive plutot que de faire echouer toute l'indexation."""
    client = OllamaClient()
    dense_text = (
        "Le present acte constate la constitution d'une hypotheque de premier rang au profit de "
        "la banque, portant sur le titre foncier numero 155.660/08, sise a Casablanca, en garantie "
        "d'un credit de 640,000 DHS (SIX CENT QUARANTE MILLE DIRHAMS) consenti a Madame Nadia AMRANI. "
    ) * 27
    vector = client.embed(dense_text)
    assert len(vector) == 768
