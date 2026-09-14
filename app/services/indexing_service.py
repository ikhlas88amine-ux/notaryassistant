"""Service d'indexation : chunking des 3 corpus, embeddings Ollama, upsert Qdrant, ecriture
des fichiers de sortie (output/chunks_*.jsonl, index_manifest.json, extraction_errors.jsonl),
manifests d'integrite (output/audit/manifests/*_latest.json) et journal local.

Supporte l'indexation complete ou incrementale (par hash de fichier / reprise), par corpus
individuel et par dossier unique (watcher). Le verrou global de Qdrant evite toute
concurrence entre indexation, watcher et audit (mode embedded).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.chunking.dossiers_chunker import chunk_dossiers_corpus
from app.chunking.lois_chunker import chunk_lois_corpus
from app.chunking.modeles_chunker import chunk_modeles_corpus
from app.core.config import Settings, get_settings
from app.core.schemas import Chunk
from app.retrieval.ollama_client import OllamaClient
from app.retrieval.qdrant_store import get_qdrant_store
from app.services import journal
from app.services.locks import qdrant_locked
from app.services.manifests import write_corpus_manifest

CORPORA = ("lois", "modeles", "dossiers")


def _write_jsonl(path: Path, chunks: list[Chunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.model_dump(), ensure_ascii=False))
            f.write("\n")


def _load_previous_manifest(manifest_path: Path) -> dict:
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


class IndexingService:
    def __init__(self, settings: Optional[Settings] = None, embed: bool = True):
        self.settings = settings or get_settings()
        self.embed = embed
        self.ollama = OllamaClient(self.settings) if embed else None
        self.store = get_qdrant_store() if embed else None

    @qdrant_locked
    def index_corpus(self, corpus: str, only_dossier_id: Optional[str] = None, resume: bool = False) -> dict:
        if corpus not in CORPORA:
            raise ValueError(f"Corpus inconnu: {corpus}")

        if corpus == "lois":
            chunks, errors = chunk_lois_corpus(self.settings.lois_dir)
        elif corpus == "modeles":
            chunks, errors = chunk_modeles_corpus(self.settings.modeles_dir)
        else:
            chunks, errors = chunk_dossiers_corpus(self.settings.dossiers_dir, only_dossier_id=only_dossier_id)

        output_path = self.settings.output_path / f"chunks_{corpus}.jsonl"

        # --- Resume (--resume) : conserve les chunks existants dont le fichier source n'a pas
        # change, et les chunks absents de la nouvelle generation (fichier retire). ---
        n_reused = 0
        if resume and output_path.exists():
            old_by_id: dict[str, Chunk] = {}
            for line in output_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    old = Chunk.model_validate(json.loads(line))
                    old_by_id[old.chunk_id] = old
                except Exception:  # noqa: BLE001
                    continue
            new_by_id: dict[str, Chunk] = {}
            for c in chunks:
                new_by_id[c.chunk_id] = c
            # un chunk ancien est "reutilise" s'il est identique a la nouvelle generation, ou
            # conserve tel quel si son fichier source n'est plus produit (fichier supprime)
            n_reused = sum(
                1 for cid, old_c in old_by_id.items()
                if cid not in new_by_id
                or (old_c.file_sha256 == new_by_id[cid].file_sha256 and old_c.text == new_by_id[cid].text)
            )
            merged = {**old_by_id, **new_by_id}
            chunks = [merged[k] for k in sorted(merged)]

        _write_jsonl(output_path, chunks)

        n_indexed = 0
        if self.embed and chunks and self.ollama is not None and self.ollama.is_available():
            vectors = self.ollama.embed_many([c.text for c in chunks])
            n_indexed = self.store.upsert_chunks(chunks, vectors)

        # Manifeste d'integrite a la fin de chaque indexation reussie.
        try:
            write_corpus_manifest(corpus, output_path, self.settings)
        except Exception as exc:  # noqa: BLE001 - le manifeste ne bloque jamais l'indexation
            errors.append(f"manifeste non ecrit pour {corpus}: {exc}")

        distinct_documents = {(c.dossier_id, c.fichier) if c.dossier_id else c.fichier for c in chunks}
        result = {
            "corpus": corpus,
            "n_documents_seen": len(distinct_documents),
            "n_chunks": len(chunks),
            "n_chunks_embedded_and_indexed": n_indexed,
            "n_extraction_errors": len(errors),
            "errors": errors,
            "output_file": str(output_path),
        }
        if resume:
            result["n_chunks_reused_resume"] = n_reused

        journal.log_event(
            "indexation", corpus=corpus,
            dossier_id=only_dossier_id,
            resultat="ok" if not errors else "warnings",
            extra={"n_chunks": len(chunks), "n_indexed": n_indexed, "n_errors": len(errors), "resume": resume},
            settings=self.settings,
        )
        return result

    @qdrant_locked
    def index_all(self) -> dict:
        results = {}
        all_errors = []
        for corpus in CORPORA:
            result = self.index_corpus(corpus)
            results[corpus] = result
            for err in result["errors"]:
                all_errors.append({"corpus": corpus, "error": err})

        errors_path = self.settings.output_path / "extraction_errors.jsonl"
        errors_path.parent.mkdir(parents=True, exist_ok=True)
        with errors_path.open("w", encoding="utf-8") as f:
            for err in all_errors:
                f.write(json.dumps({**err, "logged_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
                f.write("\n")

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ollama_embeddings_used": bool(self.embed),
            "ollama_available": self.ollama.is_available() if self.ollama else False,
            "corpora": {
                corpus: {
                    "n_documents_seen": r["n_documents_seen"],
                    "n_chunks": r["n_chunks"],
                    "n_chunks_embedded_and_indexed": r["n_chunks_embedded_and_indexed"],
                    "n_extraction_errors": r["n_extraction_errors"],
                    "output_file": r["output_file"],
                }
                for corpus, r in results.items()
            },
            "qdrant_collection_sizes": self.store.collection_sizes() if self.store else {},
            "total_extraction_errors": len(all_errors),
        }
        manifest_path = self.settings.output_path / "index_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        journal.log_event("reindexation", corpus="tous", resultat="ok", extra={"corpora": list(results.keys())}, settings=self.settings)
        return manifest
