"""Chunking du corpus 'dossiers' (dossiers clients fictifs). Decoupage d'abord par section
documentaire (identification des parties, designation du bien, prix/paiement, financement/
hypotheque, formalites/signatures, pieces jointes, clauses diverses), puis par taille cible.
Ne modifie jamais dossier_master.json ni les documents DOCX/DOC/PDF source.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.chunking.common import group_into_sections, pack_paragraphs, split_into_paragraphs
from app.chunking.section_detection import detect_dossier_section, is_heading_like
from app.core.schemas import Chunk
from app.ingestion.extractors import extract_any, is_ignorable_file
from app.ingestion.hashing import file_sha256
from app.ingestion.language import detect_language

SUPPORTED_SUFFIXES = (".docx", ".doc", ".pdf")
_NUMERIC_PREFIX_RE = re.compile(r"^\d+[_\-]?")


def _type_document_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return _NUMERIC_PREFIX_RE.sub("", stem)


def _classify_dossier_paragraph(paragraph: str):
    if not is_heading_like(paragraph):
        return None
    label, confidence = detect_dossier_section(paragraph)
    if label:
        return (label, "detected", confidence)
    return ("clauses_diverses", "inferred", 0.4)


def iter_dossier_document_files(dossier_path: Path):
    for path in sorted(dossier_path.iterdir()):
        if not path.is_file() or is_ignorable_file(path):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        yield path


def iter_dossiers(dossiers_dir: Path):
    if not dossiers_dir.exists():
        return
    for path in sorted(dossiers_dir.iterdir()):
        if path.is_dir():
            yield path


def chunk_dossier_document(path: Path, dossier_id: str, dossiers_dir_root: Path) -> tuple[list[Chunk], list[str]]:
    result = extract_any(path)
    if not result.ok:
        return [], [f"{path}: {result.error}"]

    language = detect_language(result.text) if result.text else "unknown"
    sha = file_sha256(path)
    # Chemin toujours normalise en POSIX (portable Windows/Linux), pour rester
    # coherent avec le scan disque effectue par l'audit d'integrite.
    relative_path = (
        path.relative_to(dossiers_dir_root.parent).as_posix()
        if dossiers_dir_root.parent in path.parents
        else path.as_posix()
    )
    type_document = _type_document_from_filename(path.name)
    doc_id = f"{dossier_id}:{path.stem}"

    paragraphs = split_into_paragraphs(result.text)
    if not paragraphs:
        return [], [f"{path}: aucun texte exploitable extrait"]

    groups = group_into_sections(paragraphs, _classify_dossier_paragraph)

    blocks_all: list[tuple[dict, str]] = []
    for group in groups:
        for block in pack_paragraphs(group["paragraphs"]):
            blocks_all.append((group, block))

    total = len(blocks_all)
    chunks: list[Chunk] = []
    for idx, (group, block) in enumerate(blocks_all):
        chunk = Chunk(
            chunk_id=f"{doc_id}:{idx}",
            source="client",
            confidentiality="dossier",
            dossier_id=dossier_id,
            doc_id=doc_id,
            fichier=path.name,
            relative_path=relative_path,
            type_document=type_document,
            language=language if language in ("fr", "ar", "fr_ar", "unknown") else "unknown",
            section=group["label"],
            section_source=group["source"],
            section_confidence=group["confidence"],
            chunk_index=idx,
            chunk_count_in_doc=total,
            text=block,
            page_end=result.page_count,
            file_sha256=sha,
            extraction_method=result.extraction_method,
            extraction_quality=result.extraction_quality,
            contains_personal_data=True,
            quality_flags=list(result.quality_flags),
            requires_human_review=result.extraction_quality in ("a_verifier", "failed"),
        ).finalize()
        chunks.append(chunk)

    return chunks, []


def chunk_dossiers_corpus(dossiers_dir: Path, only_dossier_id: str | None = None) -> tuple[list[Chunk], list[str]]:
    all_chunks: list[Chunk] = []
    all_errors: list[str] = []
    for dossier_path in iter_dossiers(dossiers_dir):
        dossier_id = dossier_path.name
        if only_dossier_id and dossier_id != only_dossier_id:
            continue
        for doc_path in iter_dossier_document_files(dossier_path):
            chunks, errors = chunk_dossier_document(doc_path, dossier_id, dossiers_dir)
            all_chunks.extend(chunks)
            all_errors.extend(errors)
    return all_chunks, all_errors
