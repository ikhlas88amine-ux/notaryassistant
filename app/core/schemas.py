"""Schemas Pydantic partagés par toute l'application (chunking, retrieval, API)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

Source = Literal["loi", "modele", "client"]
Confidentiality = Literal["public", "internal", "dossier"]
Language = Literal["fr", "ar", "fr_ar", "unknown"]
SectionSource = Literal["detected", "inferred", "none"]
ExtractionMethod = Literal["docx", "doc_libreoffice", "pdf_text", "pdf_ocr", "json_existing"]
ExtractionQuality = Literal["verified", "normal", "a_verifier", "failed"]

# Périmètres de recherche autorisés : UN SEUL corpus à la fois.
SearchScope = Literal["dossier", "template", "law"]


class Entities(BaseModel):
    """Entités extraites de manière déterministe depuis le texte d'un chunk (aucun LLM)."""

    cin: list[str] = Field(default_factory=list)
    land_titles: list[str] = Field(default_factory=list)
    areas_m2: list[float] = Field(default_factory=list)
    amounts_dhs: list[float] = Field(default_factory=list)
    amounts_in_words_fr: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    banks: list[str] = Field(default_factory=list)
    loan_numbers: list[str] = Field(default_factory=list)
    mortgage_ranks: list[str] = Field(default_factory=list)
    persons: list[dict] = Field(default_factory=list)


class Chunk(BaseModel):
    """Unité atomique indexée dans Qdrant."""

    chunk_id: str
    parent_chunk_id: Optional[str] = None
    source: Source
    confidentiality: Confidentiality

    law_id: Optional[str] = None
    law_name: Optional[str] = None
    article_num: Optional[str] = None

    dossier_id: Optional[str] = None
    doc_id: Optional[str] = None
    fichier: str = ""
    relative_path: str = ""

    type_document: Optional[str] = None
    type_modele: Optional[str] = None
    sous_type: Optional[str] = None

    language: Language = "unknown"
    section: Optional[str] = None
    section_source: SectionSource = "none"
    section_confidence: float = 0.0

    chunk_index: int = 0
    chunk_count_in_doc: int = 1
    text: str

    page_start: Optional[int] = None
    page_end: Optional[int] = None

    n_chars: int = 0
    n_tokens_estimate: int = 0

    file_sha256: str = ""
    extraction_method: ExtractionMethod = "docx"
    extraction_quality: ExtractionQuality = "normal"

    contains_personal_data: bool = False
    quality_flags: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    indexable: bool = True
    retrieval_excluded: bool = False
    chunk_role: str = ""
    secondary_chunk_roles: list[str] = Field(default_factory=list)
    chunk_roles: list[str] = Field(default_factory=list)
    entities: Entities = Field(default_factory=Entities)
    entity_extraction_confidence: float = 0.0

    indexed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def finalize(self) -> "Chunk":
        self.n_chars = len(self.text)
        self.n_tokens_estimate = max(1, self.n_chars // 4) if self.text else 0
        return self


class LegalChunk(BaseModel):
    """Vue des chunks du corpus juridique exporté."""

    chunk_id: str
    law_id: Optional[str] = None
    law_name: Optional[str] = None
    law_short: Optional[str] = None
    article_num: Optional[str] = None
    page_start: Optional[Union[str, int]] = None
    page_end: Optional[Union[str, int]] = None
    text: str = ""
    section: Optional[str] = None
    titre: Optional[str] = None
    chapitre: Optional[str] = None
    livre: Optional[str] = None
    partie: Optional[str] = None
    language: Optional[str] = None
    type_document: Optional[str] = None
    chunk_index: int = 0
    chunk_count_in_article: int = 1
    n_chars: int = 0
    n_tokens: int = 0


class ExtractionError(BaseModel):
    corpus: Literal["lois", "modeles", "dossiers"]
    relative_path: str
    error: str
    logged_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ValidationIssue(BaseModel):
    rule_id: str
    severity: Literal["blocking", "warning", "info"]
    title: str = ""
    message: str
    evidence: dict[str, Any] = Field(default_factory=lambda: {"fields": {}, "documents": [], "source_refs": []})
    recommended_action: str = ""
    requires_notary_review: bool = True


class ValidationReport(BaseModel):
    dossier_id: str
    status: Literal["valid", "warnings", "invalid"]
    summary: dict[str, int]
    issues: list[ValidationIssue] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SearchRequest(BaseModel):
    query: str
    scope: Optional[SearchScope] = None
    dossier_id: Optional[str] = None
    language: Optional[Language] = None
    top_k: int = 5


class SourceCitation(BaseModel):
    source: Source
    dossier_id: Optional[str] = None
    fichier: str
    section: Optional[str] = None
    chunk_id: str
    article_num: Optional[str] = None
    page_start: Optional[int] = None
    score: float = 0.0
    excerpt: str = ""
    relative_path: Optional[str] = None
    doc_id: Optional[str] = None
    file_sha256: Optional[str] = None
    chunk_role: Optional[str] = None
    text: str = ""
    secondary_chunk_roles: list[str] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    chunk_index: Optional[int] = None
    chunk_count_in_doc: Optional[int] = None


class ChatRequest(BaseModel):
    query: str
    scope: Optional[SearchScope] = None
    dossier_id: Optional[str] = None
    top_k: int = 5


class AlertExplainRequest(BaseModel):
    rule_id: str
    severity: str = "warning"
    message: str = ""
    evidence: dict[str, Any] = Field(default_factory=lambda: {"fields": {}, "documents": [], "source_refs": []})
    recommended_action: str = ""


class ChatResponse(BaseModel):
    answer: str
    answer_type: Literal["documentary_answer", "legal_answer", "draft", "insufficient_context"]
    warnings: list[str] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    retrieval: dict
