"""Chunking du corpus 'modeles' (modeles notariaux internes). Decoupage par titres, sous-titres,
clauses, paragraphes ou tableaux detectes. Ne modifie jamais les fichiers DOC/DOCX/PDF source.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.chunking.common import estimate_tokens, group_into_sections, pack_paragraphs, split_into_paragraphs
from app.chunking.section_detection import is_template_title
from app.core.schemas import Chunk
from app.ingestion.extractors import extract_any, is_ignorable_file
from app.ingestion.hashing import file_sha256
from app.ingestion.language import detect_language
from app.ingestion.modeles_catalog import classify_by_filename

SUPPORTED_SUFFIXES = (".docx", ".doc", ".pdf")


def _slugify_heading(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u0600-\u06FF]+", "_", text.strip()).strip("_").lower()
    return slug[:60] if slug else "section"


def _classify_modele_paragraph(paragraph: str):
    if is_template_title(paragraph):
        return (_slugify_heading(paragraph), "detected", 0.85)
    return None


def iter_modeles_files(modeles_dir: Path):
    if not modeles_dir.exists():
        return
    for path in sorted(modeles_dir.rglob("*")):
        if not path.is_file() or is_ignorable_file(path):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        yield path


def chunk_modele_file(path: Path, modeles_dir_root: Path) -> tuple[list[Chunk], list[str]]:
    errors: list[str] = []
    result = extract_any(path)
    if not result.ok:
        return [], [f"{path}: {result.error}"]

    meta = classify_by_filename(path.name)
    language = detect_language(result.text) if result.text else meta.get("langue", "unknown")
    sha = file_sha256(path)
    # Chemin toujours normalise en POSIX (portable Windows/Linux), pour rester
    # coherent avec le scan disque effectue par l'audit d'integrite.
    relative_path = (
        path.relative_to(modeles_dir_root.parent).as_posix()
        if modeles_dir_root.parent in path.parents
        else path.as_posix()
    )
    doc_id = f"modele-{path.stem}"

    paragraphs = split_into_paragraphs(result.text)
    if not paragraphs:
        return [], [f"{path}: aucun texte exploitable extrait"]

    groups = group_into_sections(paragraphs, _classify_modele_paragraph)

    chunks: list[Chunk] = []
    blocks_all: list[tuple[dict, str]] = []
    for group in groups:
        blocks = pack_paragraphs(group["paragraphs"])
        for block in blocks:
            blocks_all.append((group, block))

    total = len(blocks_all)
    for idx, (group, block) in enumerate(blocks_all):
        chunk = Chunk(
            chunk_id=f"{doc_id}:{idx}",
            source="modele",
            confidentiality="internal",
            doc_id=doc_id,
            fichier=path.name,
            relative_path=relative_path,
            type_modele=meta.get("type_modele"),
            sous_type=meta.get("sous_type", "a_verifier"),
            language=language if language in ("fr", "ar", "fr_ar", "unknown") else "unknown",
            section=group["label"],
            section_source=group["source"],
            section_confidence=group["confidence"],
            chunk_index=idx,
            chunk_count_in_doc=total,
            text=block,
            page_start=None,
            page_end=result.page_count,
            file_sha256=sha,
            extraction_method=result.extraction_method,
            extraction_quality=result.extraction_quality,
            contains_personal_data=False,
            quality_flags=list(result.quality_flags),
            requires_human_review=result.extraction_quality in ("a_verifier", "failed"),
        ).finalize()
        chunks.append(chunk)

    return chunks, errors


def chunk_modeles_corpus(modeles_dir: Path) -> tuple[list[Chunk], list[str]]:
    all_chunks: list[Chunk] = []
    all_errors: list[str] = []
    for path in iter_modeles_files(modeles_dir):
        chunks, errors = chunk_modele_file(path, modeles_dir)
        all_chunks.extend(chunks)
        all_errors.extend(errors)
    return all_chunks, all_errors
