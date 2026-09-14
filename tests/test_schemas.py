"""Vérifie que les schémas Pydantic respectent le contrat de validation utilisé par l'application."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.schemas import Chunk, ChatResponse, SourceCitation, ValidationIssue, ValidationReport


def _base_chunk_kwargs(**overrides):
    kwargs = dict(
        chunk_id="c1",
        source="client",
        confidentiality="dossier",
        dossier_id="9-2024-191-HYPOTHEQUE-AMRANI",
        fichier="01_engagement_hypothecaire.docx",
        relative_path="9-2024-191-HYPOTHEQUE-AMRANI/01_engagement_hypothecaire.docx",
        text="Texte de test.",
        file_sha256="abc123",
        extraction_method="docx",
    )
    kwargs.update(overrides)
    return kwargs


def test_chunk_finalize_computes_derived_fields():
    chunk = Chunk(**_base_chunk_kwargs(text="Un texte de douze caracteres.")).finalize()
    assert chunk.n_chars == len(chunk.text)
    assert chunk.n_tokens_estimate == max(1, chunk.n_chars // 4)


def test_chunk_rejects_invalid_source_literal():
    with pytest.raises(ValidationError):
        Chunk(**_base_chunk_kwargs(source="invalide"))


def test_validation_issue_uses_business_structure_for_evidence():
    issue = ValidationIssue(
        rule_id="r1",
        severity="warning",
        title="Titre",
        message="test",
        evidence={"fields": {"prix": 100}, "documents": ["01_acte.docx"], "source_refs": ["01_acte.docx"]},
    )
    assert isinstance(issue.evidence, dict)
    assert issue.evidence["fields"]["prix"] == 100
    assert issue.evidence["documents"] == ["01_acte.docx"]


def test_validation_report_status_literal_enforced():
    with pytest.raises(ValidationError):
        ValidationReport(dossier_id="x", status="pas_un_statut_valide", summary={})


def test_chat_response_answer_type_literal_enforced():
    with pytest.raises(ValidationError):
        ChatResponse(answer="test", answer_type="type_invalide", sources=[], retrieval={})

    valid = ChatResponse(answer="test", answer_type="insufficient_context", sources=[], retrieval={})
    assert valid.answer_type == "insufficient_context"


def test_source_citation_requires_fichier_and_chunk_id():
    with pytest.raises(ValidationError):
        SourceCitation(source="client")
