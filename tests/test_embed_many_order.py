"""Correctif embed_many / embed : les deux methodes empruntent EXACTEMENT le meme chemin
(POST /api/embed, jamais /api/embeddings ni le champ legacy `prompt`), et l'ordre de la
reponse du serveur est conserve strictement, sans reordonner. Tests avec une API Ollama
mockee (aucun serveur reel requis).
"""
from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.retrieval.ollama_client import OllamaClient


def _make_vector(text: str) -> list[float]:
    """Vecteur deterministe et reconnaissable, unique par texte."""
    return [float(ord(ch)) for ch in text[:8]] or [0.0]


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur simulee", request=None, response=self)

    def json(self):
        return self._payload


def _install_positional_mock(monkeypatch, calls=None):
    """Simule un serveur Ollama moderne (/api/embed) qui respecte le contrat positionnel :
    un vecteur par texte de `input`, dans le meme ordre."""

    def fake_post(self, url, json=None, **kwargs):  # noqa: ANN001
        assert url.endswith("/api/embed"), "seul /api/embed doit etre appele, jamais /api/embeddings"
        assert "input" in json and "prompt" not in json, "le champ legacy 'prompt' est interdit"
        inputs = json["input"]
        if calls is not None:
            calls.append(list(inputs))
        return _FakeResponse({"embeddings": [_make_vector(t) for t in inputs]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)


def test_embed_many_preserves_order_across_multiple_batches(monkeypatch):
    """L'ordre du texte d'entree doit toujours correspondre a l'ordre du vecteur de sortie,
    y compris lorsque le decoupage en plusieurs lots (batch_size < len(texts)) est utilise."""
    _install_positional_mock(monkeypatch)
    settings = Settings(ollama_base_url="http://127.0.0.1:1")
    client = OllamaClient(settings=settings)

    texts = ["alpha texte", "beta texte", "gamma texte", "delta texte", "epsilon texte"]
    vecs = client.embed_many(texts, batch_size=2, progress=False)

    assert len(vecs) == len(texts)
    for text, vec in zip(texts, vecs):
        assert vec == _make_vector(text), "le vecteur doit correspondre a SON texte, pas a sa position"


def test_embed_many_two_batches_respects_ABCD_order(monkeypatch):
    """Cas explicitement demande : deux lots ["A", "B"] puis ["C", "D"] -> le resultat final
    respecte l'ordre A, B, C, D."""
    calls = []
    _install_positional_mock(monkeypatch, calls)
    settings = Settings(ollama_base_url="http://127.0.0.1:1")
    client = OllamaClient(settings=settings)

    texts = ["A", "B", "C", "D"]
    vecs = client.embed_many(texts, batch_size=2, progress=False)

    assert calls == [["A", "B"], ["C", "D"]]
    assert vecs == [_make_vector(t) for t in texts]


def test_embed_many_raises_clear_error_on_vector_count_mismatch(monkeypatch):
    """Une reponse avec un nombre de vecteurs incorrect doit declencher une exception explicite,
    jamais une correspondance silencieuse mal alignee."""

    def fake_post(self, url, json=None, **kwargs):  # noqa: ANN001
        inputs = json["input"]
        # Le serveur ne renvoie qu'UN SEUL vecteur alors que 2 textes ont ete envoyes.
        return _FakeResponse({"embeddings": [_make_vector(inputs[0])]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    settings = Settings(ollama_base_url="http://127.0.0.1:1")
    client = OllamaClient(settings=settings)

    with pytest.raises(Exception, match=r"(?i)vecteur|embed"):
        client.embed_many(["A", "B"], batch_size=2, max_retries=0, progress=False)


def test_embed_many_raises_when_embeddings_field_missing(monkeypatch):
    def fake_post(self, url, json=None, **kwargs):  # noqa: ANN001
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    settings = Settings(ollama_base_url="http://127.0.0.1:1")
    client = OllamaClient(settings=settings)

    with pytest.raises(Exception, match=r"(?i)vecteur|embed"):
        client.embed_many(["texte"], batch_size=1, max_retries=0, progress=False)


def test_embed_matches_embed_many_single_same_endpoint(monkeypatch):
    """embed() et embed_many([text])[0] doivent produire le meme resultat via le meme
    endpoint /api/embed (jamais /api/embeddings)."""
    calls = []
    _install_positional_mock(monkeypatch, calls)
    settings = Settings(ollama_base_url="http://127.0.0.1:1")
    client = OllamaClient(settings=settings)

    single = client.embed("texte unique de test")
    many = client.embed_many(["texte unique de test"], batch_size=1, progress=False)

    assert single == many[0] == _make_vector("texte unique de test")
    assert all(c == ["texte unique de test"] for c in calls)
