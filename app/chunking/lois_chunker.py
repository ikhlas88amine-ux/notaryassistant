"""Chunking du corpus 'lois' (textes juridiques publics).

Deux formats sources sont acceptes :
1. `lois_chunks.json` (export historique) : une LISTE de chunks deja decoupes (chunk_id, text,
   article_num, page_start...) — ils sont preserves tels quels (jamais de contenu invente).
2. Fichier JSON au format `schema_loi.example.json` : dict avec champ `articles` — chaque article
   est l'unite parente ; un article trop long est decoupe en sous-chunks avec chevauchement sans
   jamais separer une liste numerotee de son intitule.

Ne modifie jamais le contenu des fichiers JSON source.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.chunking.common import pack_paragraphs, split_into_paragraphs
from app.core.schemas import Chunk
from app.ingestion.hashing import file_sha256

EXCLUDED_SUFFIXES = (".example.json",)


def iter_lois_files(lois_dir: Path):
    if not lois_dir.exists():
        return
    for path in sorted(lois_dir.rglob("*.json")):
        if any(str(path).endswith(suf) for suf in EXCLUDED_SUFFIXES):
            continue
        yield path


def _page_to_int(value) -> Path:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chunks_from_export_list(data: list, path: Path, lois_dir: Path, sha: str) -> list[Chunk]:
    """Convertit une liste de chunks exportes (lois_chunks.json) sans en modifier le contenu."""
    chunks: list[Chunk] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict) or not item.get("text"):
            continue
        chunk_id = item.get("chunk_id") or f"loi:{path.stem}:export{idx}"
        chunk = Chunk(
            chunk_id=chunk_id,
            source="loi",
            confidentiality="public",
            law_id=item.get("law_id") or path.stem,
            law_name=item.get("law_name"),
            article_num=item.get("article_num"),
            fichier=path.name,
            relative_path=(
                path.relative_to(lois_dir.parent.parent).as_posix()
                if lois_dir.parent.parent in path.parents
                else f"lois/{path.name}"
            ),
            type_document=item.get("type_document") or "article_de_loi",
            language=(item.get("language") or "fr") if (item.get("language") or "fr") in ("fr", "ar", "fr_ar", "unknown") else "unknown",
            section=item.get("titre") or item.get("section"),
            section_source="detected" if (item.get("titre") or item.get("section")) else "none",
            section_confidence=1.0 if (item.get("titre") or item.get("section")) else 0.0,
            chunk_index=int(item.get("chunk_index") or 0),
            chunk_count_in_doc=int(item.get("chunk_count_in_article") or 1),
            text=item["text"],
            page_start=_page_to_int(item.get("page_start")),
            page_end=_page_to_int(item.get("page_end")),
            file_sha256=sha,
            extraction_method="json_existing",
            extraction_quality="verified",
            contains_personal_data=False,
            requires_human_review=False,
        ).finalize()
        chunks.append(chunk)
    return chunks


def _chunks_from_articles_format(data: dict, path: Path, lois_dir: Path, sha: str) -> tuple[list[Chunk], list[str]]:
    errors: list[str] = []
    law_id = data.get("law_id") or path.stem
    law_name = data.get("law_name")
    language = data.get("language", "fr")
    articles = data.get("articles", [])
    if not isinstance(articles, list):
        return [], [f"{path}: champ 'articles' absent ou invalide"]

    # Chemin toujours normalise en POSIX (portable Windows/Linux), pour rester
    # coherent avec le scan disque effectue par l'audit d'integrite.
    relative_path = (
        path.relative_to(lois_dir.parent.parent).as_posix()
        if lois_dir.parent.parent in path.parents
        else f"lois/{path.name}"
    )

    chunks: list[Chunk] = []
    for article in articles:
        article_num = str(article.get("article_num", "")) or None
        text = (article.get("text") or "").strip()
        if not text:
            errors.append(f"{path}: article {article_num} sans texte, ignore")
            continue

        parent_chunk_id = f"loi:{law_id}:art{article_num}"
        paragraphs = split_into_paragraphs(text)
        blocks = pack_paragraphs(paragraphs)

        for idx, block in enumerate(blocks):
            chunk_id = parent_chunk_id if len(blocks) == 1 else f"{parent_chunk_id}:{idx}"
            chunk = Chunk(
                chunk_id=chunk_id,
                parent_chunk_id=None if len(blocks) == 1 else parent_chunk_id,
                source="loi",
                confidentiality="public",
                law_id=law_id,
                law_name=law_name,
                article_num=article_num,
                fichier=path.name,
                relative_path=relative_path,
                type_document="article_de_loi",
                language=language if language in ("fr", "ar", "fr_ar", "unknown") else "unknown",
                section=article.get("titre"),
                section_source="detected" if article.get("titre") else "none",
                section_confidence=1.0 if article.get("titre") else 0.0,
                chunk_index=idx,
                chunk_count_in_doc=len(blocks),
                text=block,
                page_start=article.get("page"),
                page_end=article.get("page"),
                file_sha256=sha,
                extraction_method="json_existing",
                extraction_quality="verified",
                contains_personal_data=False,
                requires_human_review=False,
            ).finalize()
            chunks.append(chunk)
    return chunks, errors


def chunk_law_file(path: Path, lois_dir: Path) -> tuple[list[Chunk], list[str]]:
    """Retourne (chunks, erreurs) pour un fichier de loi JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [], [f"{path}: JSON invalide ({exc})"]

    sha = file_sha256(path)
    if isinstance(data, list):
        return _chunks_from_export_list(data, path, lois_dir, sha), []
    if isinstance(data, dict) and "articles" in data:
        return _chunks_from_articles_format(data, path, lois_dir, sha)
    return [], [f"{path}: format JSON non reconnu (liste de chunks ou objet 'articles' attendu)"]


def chunk_lois_corpus(lois_dir: Path) -> tuple[list[Chunk], list[str]]:
    all_chunks: list[Chunk] = []
    all_errors: list[str] = []
    for path in iter_lois_files(lois_dir):
        chunks, errors = chunk_law_file(path, lois_dir)
        all_chunks.extend(chunks)
        all_errors.extend(errors)
    return all_chunks, all_errors
