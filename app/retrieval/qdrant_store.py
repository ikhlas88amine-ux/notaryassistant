"""Wrapper Qdrant local (mode embarque par defaut, sans Docker) avec 3 collections strictement
separees : legal_public, templates_internal, case_documents.

Regles de securite (feature 5 du cahier des charges) appliquees ici, pas seulement documentees :
- Une question juridique n'interroge QUE legal_public.
- Une demande de modele n'interroge QUE templates_internal.
- Une question de dossier interroge case_documents AVEC un filtre dossier_id obligatoire.
- Une recherche globale non filtree sur les documents clients est INTERDITE (leve une exception).
"""
from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import Settings, get_settings
from app.core.schemas import Chunk

COLLECTION_LEGAL = "legal_public"
COLLECTION_TEMPLATES = "templates_internal"
COLLECTION_CASES = "case_documents"

ALL_COLLECTIONS = (COLLECTION_LEGAL, COLLECTION_TEMPLATES, COLLECTION_CASES)


class UnsafeSearchError(Exception):
    """Leve quand une recherche tenterait d'acceder aux documents clients sans filtre dossier_id."""


def _uuid_for(chunk_id: str) -> str:
    """Identifiant Qdrant deterministe et stable pour un chunk_id donne (reindexation idempotente)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


class QdrantStore:
    def __init__(self, settings: Optional[Settings] = None, embedding_dim: int = 768):
        self.settings = settings or get_settings()
        self.embedding_dim = embedding_dim
        if self.settings.qdrant_mode == "embedded":
            self.client = QdrantClient(path=self.settings.qdrant_local_path)
        else:
            self.client = QdrantClient(url=self.settings.qdrant_url)

    def ensure_collections(self) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        for name in ALL_COLLECTIONS:
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=qmodels.VectorParams(size=self.embedding_dim, distance=qmodels.Distance.COSINE),
                )

    def collection_for_source(self, source: str) -> str:
        return {
            "loi": COLLECTION_LEGAL,
            "modele": COLLECTION_TEMPLATES,
            "client": COLLECTION_CASES,
        }[source]

    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        self.ensure_collections()
        by_collection: dict[str, list[qmodels.PointStruct]] = {c: [] for c in ALL_COLLECTIONS}
        for chunk, vector in zip(chunks, vectors):
            if chunk.retrieval_excluded or not chunk.indexable:
                continue  # correctif 3 : les notices techniques et fragments degeneres ne partent jamais dans Qdrant
            collection = self.collection_for_source(chunk.source)
            point_id = _uuid_for(chunk.chunk_id)
            payload = chunk.model_dump()
            by_collection[collection].append(qmodels.PointStruct(id=point_id, vector=vector, payload=payload))

        total = 0
        for collection, points in by_collection.items():
            if points:
                self.client.upsert(collection_name=collection, points=points)
                total += len(points)
        return total

    def search_legal(self, query_vector: list[float], top_k: int = 5) -> list[qmodels.ScoredPoint]:
        self.ensure_collections()
        return self.client.query_points(collection_name=COLLECTION_LEGAL, query=query_vector, limit=top_k).points

    def search_templates(self, query_vector: list[float], top_k: int = 5) -> list[qmodels.ScoredPoint]:
        self.ensure_collections()
        return self.client.query_points(collection_name=COLLECTION_TEMPLATES, query=query_vector, limit=top_k).points

    def delete_dossier_points(self, dossier_id: str) -> int:
        """Supprime tous les points Qdrant d'un dossier (utilise par le watcher lors d'une
        reindexation mono-dossier : seuls les chunks de ce dossier sont touches)."""
        if not dossier_id:
            raise UnsafeSearchError("Suppression refuse : dossier_id obligatoire.")
        self.ensure_collections()
        result = self.client.delete(
            collection_name=COLLECTION_CASES,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="dossier_id", match=qmodels.MatchValue(value=dossier_id))]
                )
            ),
        )
        return 1 if getattr(result, "status", None) else 0

    def search_case_documents(self, query_vector: list[float], dossier_id: str, top_k: int = 5) -> list[qmodels.ScoredPoint]:
        """Recherche dans les documents clients. `dossier_id` est OBLIGATOIRE (pas de defaut) :
        cette signature empeche par construction une recherche non filtree entre dossiers."""
        if not dossier_id:
            raise UnsafeSearchError(
                "Recherche dans case_documents refusee : un dossier_id est obligatoire pour ne "
                "jamais melanger les documents de deux dossiers clients differents."
            )
        self.ensure_collections()
        query_filter = qmodels.Filter(
            must=[qmodels.FieldCondition(key="dossier_id", match=qmodels.MatchValue(value=dossier_id))]
        )
        return self.client.query_points(
            collection_name=COLLECTION_CASES, query=query_vector, query_filter=query_filter, limit=top_k
        ).points

    def collection_sizes(self) -> dict[str, int]:
        self.ensure_collections()
        return {c: self.client.count(collection_name=c).count for c in ALL_COLLECTIONS}

    def close(self) -> None:
        self.client.close()


@lru_cache
def get_qdrant_store() -> QdrantStore:
    """Instance UNIQUE et partagee du client Qdrant embarque pour tout le process.

    Le mode embarque (fichier local, sans serveur) verrouille son dossier de stockage : un
    deuxieme QdrantClient ouvert sur le meme chemin dans le meme process echoue immediatement
    ('Storage folder ... already accessed'). Toute la couche services (indexation, RAG, API)
    doit donc reutiliser cette instance plutot que d'instancier QdrantStore() directement, sous
    peine de verrouillage apres quelques appels. Utiliser qdrant_mode='server' + un vrai serveur
    Qdrant si un jour plusieurs process independants doivent acceder au meme index en parallele.
    """
    return QdrantStore()
