"""Recherche lexicale locale (BM25 simplifié), exacte et fusion RRF.

Correctif 9 : toute recherche dans les chunks de dossiers clients impose `dossier_id`.
Si un appel tente de chercher parmi les dossiers sans dossier_id explicite -> UnsafeSearchError.
La règle s'applique à : recherche lexicale (BM25 simplifié), recherche exacte, hybride (RRF),
reranking et récupération des chunks voisins.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable, Optional

from app.retrieval.qdrant_store import UnsafeSearchError


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[\wÀ-ÿ\u0600-\u06FF]+", s.lower()))


def load_chunks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return [x for x in out if not x.get("retrieval_excluded") and x.get("indexable", True)]


def _check_dossier_access(chunks: Iterable[dict], dossier_id: Optional[str]) -> None:
    """Lève UnsafeSearchError si la liste de chunks contient des dossiers clients et qu'aucun
    dossier_id actif n'est fourni (correctif 9 : pas de recherche globale sur les dossiers)."""
    if dossier_id:
        return
    for c in chunks:
        if c.get("source") == "client":
            raise UnsafeSearchError(
                "Recherche parmi les documents clients interdite sans dossier_id actif : "
                "passez dossier_id=<dossier> pour ne jamais melanger deux dossiers."
            )


def lexical_search(chunks: list[dict], query: str, top_k: int = 10, dossier_id: Optional[str] = None) -> list[tuple[float, dict]]:
    """BM25 simplifié (score de chevauchement). Exige dossier_id pour les chunks client."""
    _check_dossier_access(chunks, dossier_id)
    q = _tokens(query)
    scored: list[tuple[float, dict]] = []
    for c in chunks:
        if c.get("source") == "client" and c.get("dossier_id") != dossier_id:
            continue
        text = c.get("text", "")
        t = _tokens(text)
        overlap = len(q & t)
        exact = sum(1 for token in q if token in text.lower())
        # idf léger : les termes rares pèsent plus
        df = sum(1 for other in chunks if q and len(q & _tokens(other.get("text", ""))) > 0)
        idf = math.log((len(chunks) + 1) / (df + 1)) if q else 0.0
        score = ((overlap / (len(q) or 1)) * 0.7 + (exact / (len(q) or 1)) * 0.3) * (1.0 + idf)
        if score:
            scored.append((score, c))
    return sorted(scored, key=lambda x: x[0], reverse=True)[:top_k]


def exact_search(chunks: list[dict], query: str, top_k: int = 10, dossier_id: Optional[str] = None) -> list[dict]:
    """Recherche exacte (sous-chaîne dans texte + entités). Exige dossier_id si clients."""
    _check_dossier_access(chunks, dossier_id)
    q = query.lower()
    out = []
    for c in chunks:
        if c.get("source") == "client" and c.get("dossier_id") != dossier_id:
            continue
        e = c.get("entities", {}) or {}
        hay = " ".join(
            [
                c.get("text", ""),
                *sum(([str(v) for v in vals] for vals in e.values() if isinstance(vals, list)), []),
            ]
        )
        if q in hay.lower():
            out.append(c)
    return out[:top_k]


def rrf(*ranked_lists: list[tuple[float, dict] | dict], top_k: int = 10,
        dossier_id: Optional[str] = None) -> list[tuple[float, dict]]:
    """Fusion Reciprocal Rank Frequency. Vérifie l'accès dossier AVANT fusion (aucun point
    d'un autre dossier ne peut transiter par le RRF)."""
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst, 1):
            doc = item[1] if isinstance(item, tuple) else item
            if doc.get("source") == "client":
                if not dossier_id:
                    raise UnsafeSearchError("Fusion hybride refusee : dossier_id obligatoire pour les documents clients.")
                if doc.get("dossier_id") != dossier_id:
                    continue  # ce point provient d'un autre dossier : exclu à la source
            key = doc.get("chunk_id", "")
            docs[key] = doc
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    return [(scores[k], docs[k]) for k in sorted(scores, key=scores.get, reverse=True)[:top_k]]


def reciprocal_rank_fusion(*ranked_lists: list[tuple[float, dict] | dict], top_k: int = 10,
                           dossier_id: Optional[str] = None) -> list[tuple[float, dict]]:
    """Alias de `rrf` (rétrocompatibilité)."""
    return rrf(*ranked_lists, top_k=top_k, dossier_id=dossier_id)


def fetch_neighbors_local(chunks: list[dict], chunk_id: str, dossier_id: Optional[str] = None,
                          same_law: bool = False, window: int = 1) -> list[dict]:
    """Chunks voisins (local, depuis les jsonl) : 
    - dossiers : même dossier + même document (chunk_index adjacent) — dossier_id obligatoire ;
    - lois : même law_id + même article_num (tous les chunks de l'article)."""
    target = next((c for c in chunks if c.get("chunk_id") == chunk_id), None)
    if target is None:
        return []
    if target.get("source") == "client":
        if not dossier_id:
            raise UnsafeSearchError("Voisins de dossier refusés : dossier_id obligatoire.")
        if target.get("dossier_id") != dossier_id:
            raise UnsafeSearchError("Le chunk cible n'appartient pas au dossier actif.")
    if target.get("source") == "loi" and same_law:
        law_id = target.get("law_id")
        article = target.get("article_num")
        return [
            c for c in chunks
            if c.get("law_id") == law_id and c.get("article_num") == article and c.get("chunk_id") != chunk_id
        ]
    parts = chunk_id.rsplit(":", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return []
    prefix, base = parts[0], int(parts[1])
    wanted = {f"{prefix}:{base + d}" for d in range(-window, window + 1) if d != 0}
    out = []
    for c in chunks:
        if c.get("chunk_id") in wanted:
            if c.get("source") == "client" and c.get("dossier_id") != dossier_id:
                continue
            out.append(c)
    return sorted(out, key=lambda c: c.get("chunk_index", 0))
