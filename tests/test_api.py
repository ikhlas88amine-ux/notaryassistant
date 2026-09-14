"""Tests de l'API FastAPI, executes contre les vraies donnees du projet (aucun mock de reponse)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.retrieval.ollama_client import OllamaClient

client = TestClient(app)


def _ollama_available() -> bool:
    try:
        return OllamaClient().is_available()
    except Exception:  # noqa: BLE001
        return False


requires_ollama = pytest.mark.skipif(not _ollama_available(), reason="Ollama local non disponible sur cette machine.")


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "ollama_available" in body


def test_list_dossiers_returns_real_dossiers():
    resp = client.get("/dossiers")
    assert resp.status_code == 200
    dossiers = resp.json()["dossiers"]
    assert len(dossiers) == 22
    ids = {d["dossier_id"] for d in dossiers}
    assert "9-2024-191-HYPOTHEQUE-AMRANI" in ids


def test_get_dossier_detail(sample_dossier_id):
    resp = client.get(f"/dossiers/{sample_dossier_id}")
    assert resp.status_code == 200


def test_get_dossier_not_found_returns_404():
    resp = client.get("/dossiers/DOSSIER-INEXISTANT-XYZ")
    assert resp.status_code == 404


def test_get_dossier_documents(sample_dossier_id):
    resp = client.get(f"/dossiers/{sample_dossier_id}/documents")
    assert resp.status_code == 200
    assert len(resp.json()["documents"]) >= 1


def test_validate_dossier_endpoint(sample_dossier_id):
    resp = client.post(f"/dossiers/{sample_dossier_id}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dossier_id"] == sample_dossier_id
    assert body["status"] in ("valid", "warnings", "invalid")


def test_search_dossier_scope_without_dossier_id_is_rejected():
    resp = client.post("/search", json={"query": "hypotheque", "scope": "dossier"})
    assert resp.status_code == 400


@requires_ollama
def test_search_dossier_scope_with_dossier_id_returns_isolated_results(sample_dossier_id):
    resp = client.post(
        "/search",
        json={"query": "hypotheque credit banque", "scope": "dossier", "dossier_id": sample_dossier_id, "top_k": 5},
    )
    assert resp.status_code == 200
    results = resp.json()["results"].get("case_documents", [])
    assert all(r["dossier_id"] == sample_dossier_id for r in results)


@requires_ollama
def test_chat_endpoint_returns_valid_response_shape(sample_dossier_id):
    resp = client.post(
        "/chat",
        json={"query": "Qui est l'emprunteur ?", "scope": "dossier", "dossier_id": sample_dossier_id, "top_k": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer_type"] in ("documentary_answer", "legal_answer", "draft", "insufficient_context")
    assert "sources" in body


def test_models_endpoint_exposes_local_models_only():
    resp = client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "ollama_base_url" in body
    assert "localhost" in body["ollama_base_url"] or "127.0.0.1" in body["ollama_base_url"]
