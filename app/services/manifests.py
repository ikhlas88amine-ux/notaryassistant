"""Manifests d'integrite produits a la fin de chaque indexation reussie (cahier des charges §9).

output/audit/manifests/
├── dossiers_latest.json
├── modeles_latest.json
├── lois_latest.json
└── history/

Chaque manifeste contient : corpus, collection, date, modele d'embedding, dimension, fichiers
relatifs, SHA-256, taille, date de modification, chunk_ids, chunks indexables, compteurs
fichiers/chunks/vecteurs, version du schema.

Un manifeste est une constatation : il ne modifie jamais les sources, chunks ou vecteurs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings
from app.core.schemas import Chunk
from app.ingestion.hashing import file_sha256

MANIFEST_SCHEMA_VERSION = 1

COLLECTION_BY_CORPUS = {
    "dossiers": "case_documents",
    "modeles": "templates_internal",
    "lois": "legal_public",
}


def _load_chunks_jsonl(path: Path) -> list[Chunk]:
    if not path.exists():
        return []
    out: list[Chunk] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(Chunk.model_validate(json.loads(line)))
        except Exception:  # noqa: BLE001 - un chunk illisible ne bloque pas le manifeste
            continue
    return out


def build_corpus_manifest(corpus: str, chunks_jsonl: Path, settings: Optional[Settings] = None) -> dict:
    """Construit le manifeste d'un corpus a partir du JSONL de chunks produit par l'indexation."""
    settings = settings or get_settings()
    chunks = _load_chunks_jsonl(chunks_jsonl)

    files: dict[str, dict] = {}
    for chunk in chunks:
        rel = chunk.relative_path
        if not rel:
            continue
        info = files.setdefault(rel, {"fichier": chunk.fichier, "sha256": chunk.file_sha256, "chunks": 0})
        info["chunks"] += 1

    # Remontee des tailles et dates de modification des fichiers sources reels (si accessibles).
    for rel in files:
        candidate = settings.data_path / rel
        if candidate.exists() and candidate.is_file():
            files[rel]["taille_octets"] = candidate.stat().st_size
            files[rel]["mtime"] = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc).isoformat()
            try:
                files[rel]["sha256_calcul"] = file_sha256(candidate)
            except OSError:
                pass

    chunk_ids = [c.chunk_id for c in chunks]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "corpus": corpus,
        "collection": COLLECTION_BY_CORPUS.get(corpus),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "modele_embedding": settings.ollama_embed_model,
        "dimension_embedding": 768,  # nomic-embed-text (768) ; a ajuster si le modele change
        "mode_qdrant": settings.qdrant_mode,
        "fichiers": files,
        "chunk_ids": chunk_ids,
        "compteurs": {
            "n_fichiers": len(files),
            "n_chunks": len(chunks),
            "n_chunks_indexables": sum(1 for c in chunks if c.indexable and not c.retrieval_excluded),
            "n_vecteurs_qdrant": None,  # rempli par l'audit quand Qdrant est accessible
        },
    }


def write_corpus_manifest(corpus: str, chunks_jsonl: Path, settings: Optional[Settings] = None) -> Path:
    """Ecrit <corpus>_latest.json + une copie horodatee dans history/. Retourne le chemin latest."""
    settings = settings or get_settings()
    manifest = build_corpus_manifest(corpus, chunks_jsonl, settings)
    manifest_dir = settings.manifests_dir
    latest_path = manifest_dir / f"{corpus}_latest.json"
    latest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    history_dir = manifest_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    history_path = history_dir / f"{corpus}_{stamp}.json"
    history_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest_path


def load_latest_manifest(corpus: str, settings: Optional[Settings] = None) -> Optional[dict]:
    settings = settings or get_settings()
    path = settings.manifests_dir / f"{corpus}_latest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
