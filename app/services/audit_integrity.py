"""Audit de securite et d'integrite RAG (cahier des charges §9).

Surveille les modifications et incoherences entre :
1. fichiers sources (data/dossiers, data/modeles, data/lois) ;
2. chunks JSONL (output/chunks_*.jsonl) ;
3. collections Qdrant ;
4. manifests d'integrite (output/audit/manifests).

L'audit ne modifie JAMAIS les sources, chunks ou vecteurs : il produit uniquement un rapport et
des alertes. Le notaire peut marquer un evenement comme autorise/resolu/ignore avec justification
(journal append-only des decisions). Une difference de hash signifie « modification detectee »,
pas automatiquement « attaque ».
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings
from app.ingestion.hashing import file_sha256
from app.retrieval.qdrant_store import get_qdrant_store
from app.services import journal
from app.services.locks import qdrant_locked
from app.services.manifests import load_latest_manifest

# Codes d'anomalie
SOURCE_ADDED = "SOURCE_ADDED"
SOURCE_REMOVED = "SOURCE_REMOVED"
SOURCE_MODIFIED = "SOURCE_MODIFIED"
SOURCE_RENAMED_POSSIBLE = "SOURCE_RENAMED_POSSIBLE"
CHUNK_ADDED = "CHUNK_ADDED"
CHUNK_REMOVED = "CHUNK_REMOVED"
CHUNK_HASH_MISMATCH = "CHUNK_HASH_MISMATCH"
CHUNK_ORPHANED = "CHUNK_ORPHANED"
QDRANT_VECTOR_COUNT_MISMATCH = "QDRANT_VECTOR_COUNT_MISMATCH"
QDRANT_UNKNOWN_POINT = "QDRANT_UNKNOWN_POINT"
QDRANT_MISSING_POINT = "QDRANT_MISSING_POINT"
EMBEDDING_DIMENSION_MISMATCH = "EMBEDDING_DIMENSION_MISMATCH"
MANIFEST_MISSING = "MANIFEST_MISSING"

SEVERITY_BY_CODE = {
    SOURCE_MODIFIED: "high",
    SOURCE_REMOVED: "high",
    CHUNK_HASH_MISMATCH: "high",
    CHUNK_ORPHANED: "medium",
    QDRANT_VECTOR_COUNT_MISMATCH: "high",
    QDRANT_UNKNOWN_POINT: "medium",
    QDRANT_MISSING_POINT: "medium",
    EMBEDDING_DIMENSION_MISMATCH: "high",
    SOURCE_ADDED: "low",
    SOURCE_RENAMED_POSSIBLE: "medium",
    CHUNK_ADDED: "low",
    CHUNK_REMOVED: "medium",
    MANIFEST_MISSING: "info",
}

JSONL_BY_CORPUS = {"dossiers": "chunks_dossiers.jsonl", "modeles": "chunks_modeles.jsonl", "lois": "chunks_lois.jsonl"}


def _load_chunks_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _decisions_path(settings: Settings) -> Path:
    return settings.audit_dir / "decisions.jsonl"


def list_decisions(settings: Optional[Settings] = None) -> list[dict]:
    settings = settings or get_settings()
    path = _decisions_path(settings)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def is_decided(anomaly_key: str, settings: Optional[Settings] = None) -> bool:
    return any(d.get("anomaly_key") == anomaly_key for d in list_decisions(settings))


def record_decision(anomaly_key: str, action: str, justification: str, settings: Optional[Settings] = None) -> dict:
    """Action locale de suivi (autorise/resolu/ignore) — jamais de correction automatique."""
    settings = settings or get_settings()
    decision = {
        "anomaly_key": anomaly_key,
        "action": action,
        "justification": justification,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "utilisateur": journal.USER_LOCAL,
    }
    path = _decisions_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False))
        f.write("\n")
    journal.log_event("audit_decision", resultat=action, justification=justification, extra={"anomaly_key": anomaly_key}, settings=settings)
    return decision


def _scan_sources(corpus: str, settings: Settings) -> dict[str, dict]:
    """Visite les fichiers sources reels du corpus : relative_path -> {sha256, taille, mtime}."""
    base = {"dossiers": settings.dossiers_dir, "modeles": settings.modeles_dir, "lois": settings.lois_dir}[corpus]
    out: dict[str, dict] = {}
    if not base.exists():
        return out
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if corpus == "lois" and path.suffix.lower() not in (".json",):
            continue
        if corpus != "lois" and path.suffix.lower() not in (".docx", ".doc", ".pdf"):
            continue
        if path.name.startswith("~$") or path.name.startswith("."):
            continue
        try:
            # Toujours normalise en POSIX : le manifeste (construit a partir de
            # Chunk.relative_path) et le scan disque doivent utiliser le meme format
            # de chemin, y compris sous Windows ou Path.relative_to() renvoie des
            # antislashes. Ne jamais comparer un chemin absolu avec un chemin relatif.
            rel = path.relative_to(settings.data_path).as_posix()
            out[rel] = {
                "sha256": file_sha256(path),
                "taille": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        except (OSError, ValueError):
            continue
    return out


def _check_corpus(corpus: str, settings: Settings, include_qdrant: bool) -> tuple[list[dict], dict]:
    manifest = load_latest_manifest(corpus, settings)
    anomalies: list[dict] = []
    stats = {"files": 0, "chunks": 0, "points": 0}

    if manifest is None:
        anomalies.append({
            "corpus": corpus, "code": MANIFEST_MISSING, "severity": SEVERITY_BY_CODE[MANIFEST_MISSING],
            "message": f"Aucun manifeste d'integrite present pour {corpus} (output/audit/manifests/{corpus}_latest.json).",
            "ancien_hash": None, "nouveau_hash": None,
        })
        return anomalies, stats

    stats["chunks"] = manifest.get("compteurs", {}).get("n_chunks", 0)

    # source files actuels
    current = _scan_sources(corpus, settings)
    # fichiers connus du manifeste (relative_path -> info)
    known = manifest.get("fichiers", {})
    stats["files"] = len(current)

    for rel, info in current.items():
        if rel not in known:
            anomalies.append({
                "corpus": corpus, "code": SOURCE_ADDED, "severity": SEVERITY_BY_CODE[SOURCE_ADDED],
                "message": f"Fichier source ajoute depuis le dernier manifeste : {rel}",
                "fichier": rel, "ancien_hash": None, "nouveau_hash": info["sha256"],
            })
            continue
        prev = known[rel]
        if prev.get("sha256") != info["sha256"]:
            anomalies.append({
                "corpus": corpus, "code": SOURCE_MODIFIED, "severity": SEVERITY_BY_CODE[SOURCE_MODIFIED],
                "message": f"Fichier source modifie (hash change) : {rel}",
                "fichier": rel, "ancien_hash": prev.get("sha256"), "nouveau_hash": info["sha256"],
            })
        if prev.get("sha256") == info["sha256"] and prev.get("chunks", 0) == 0 and stats["chunks"] > 0:
            # fichier present dans le manifeste sans chunks : banal (ex: inventaire_modeles.json)
            pass

    for rel in known:
        if rel not in current:
            anomalies.append({
                "corpus": corpus, "code": SOURCE_REMOVED, "severity": SEVERITY_BY_CODE[SOURCE_REMOVED],
                "message": f"Fichier source absent du disque mais present dans le manifeste : {rel}",
                "fichier": rel, "ancien_hash": known[rel].get("sha256"), "nouveau_hash": None,
            })

    # chunks JSONL vs manifeste
    jsonl = settings.output_path / JSONL_BY_CORPUS[corpus]
    chunk_rows = _load_chunks_jsonl(jsonl)
    manifest_ids = set(manifest.get("chunk_ids", []))
    jsonl_ids = {c.get("chunk_id") for c in chunk_rows}
    removed = manifest_ids - jsonl_ids
    added = jsonl_ids - manifest_ids
    for cid in sorted(removed):
        anomalies.append({
            "corpus": corpus, "code": CHUNK_REMOVED, "severity": SEVERITY_BY_CODE[CHUNK_REMOVED],
            "message": f"Chunk present dans le manifeste mais absent du JSONL : {cid}",
            "fichier": cid,
        })
    for cid in sorted(added):
        anomalies.append({
            "corpus": corpus, "code": CHUNK_ADDED, "severity": SEVERITY_BY_CODE[CHUNK_ADDED],
            "message": f"Chunk present dans le JSONL mais absent du manifeste : {cid}",
            "fichier": cid,
        })

    # hash des chunks versus fichier source (leur relative_path)
    sha_by_rel: dict[str, str] = {rel: info.get("sha256") for rel, info in current.items()}
    for c in chunk_rows:
        rel = c.get("relative_path")
        if rel and rel in sha_by_rel and c.get("file_sha256") and c["file_sha256"] != sha_by_rel[rel]:
            key = f"{corpus}:{c.get('chunk_id')}"
            if not is_decided(key, settings):
                anomalies.append({
                    "corpus": corpus, "code": CHUNK_HASH_MISMATCH, "severity": SEVERITY_BY_CODE[CHUNK_HASH_MISMATCH],
                    "message": f"Hash du chunk {c.get('chunk_id')} different du fichier source {rel}",
                    "fichier": rel, "ancien_hash": sha_by_rel[rel], "nouveau_hash": c.get("file_sha256"),
                    "anomaly_key": key,
                })

    # Qdrant
    if include_qdrant:
        try:
            store = get_qdrant_store()
            collection = {
                "dossiers": "case_documents", "modeles": "templates_internal", "lois": "legal_public",
            }[corpus]
            counts = store.collection_sizes()
            n_points = counts.get(collection, 0)
            stats["points"] = n_points
            n_indexables = manifest.get("compteurs", {}).get("n_chunks_indexables")
            if n_indexables is not None and n_points != n_indexables:
                anomalies.append({
                    "corpus": corpus, "code": QDRANT_VECTOR_COUNT_MISMATCH,
                    "severity": SEVERITY_BY_CODE[QDRANT_VECTOR_COUNT_MISMATCH],
                    "message": f"Qdrant {collection} contient {n_points} vecteurs, le manifeste en declare {n_indexables}.",
                })
        except Exception as exc:  # noqa: BLE001 - Qdrant indisponible : anomalie d'observation, pas un crash
            anomalies.append({
                "corpus": corpus, "code": QDRANT_VECTOR_COUNT_MISMATCH,
                "severity": SEVERITY_BY_CODE[QDRANT_VECTOR_COUNT_MISMATCH],
                "message": f"Impossible de lire Qdrant pour {corpus} : {exc}",
            })

    return anomalies, stats


@qdrant_locked
def run_audit(settings: Optional[Settings] = None, include_qdrant: bool = True) -> dict:
    """Audit complet en lecture seule. Retourne le rapport ; ne corrige rien."""
    settings = settings or get_settings()
    corpora = ("dossiers", "modeles", "lois")
    all_anomalies: list[dict] = []
    per_corpus: dict[str, dict] = {}
    totals = {"files": 0, "chunks": 0, "points": 0}

    for corpus in corpora:
        anomalies, stats = _check_corpus(corpus, settings, include_qdrant)
        per_corpus[corpus] = {"anomalies": anomalies, **stats}
        for k in totals:
            totals[k] += stats[k]
        all_anomalies.extend(anomalies)

    # orphelins : chunks dont le fichier source n'existe plus
    for corpus in corpora:
        jsonl = settings.output_path / JSONL_BY_CORPUS[corpus]
        rows = _load_chunks_jsonl(jsonl)
        for c in rows:
            rel = c.get("relative_path")
            if not rel:
                continue
            src = settings.data_path / rel
            if not src.exists():
                key = f"{corpus}:{c.get('chunk_id')}"
                if not is_decided(key, settings):
                    all_anomalies.append({
                        "corpus": corpus, "code": CHUNK_ORPHANED,
                        "severity": SEVERITY_BY_CODE[CHUNK_ORPHANED],
                        "message": f"Chunk {c.get('chunk_id')} orphelin : fichier source {rel} absent du disque.",
                        "fichier": rel, "anomaly_key": key,
                    })

    counts_by_severity = {"blocking": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for a in all_anomalies:
        sev = a.get("severity", "info")
        counts_by_severity[sev] = counts_by_severity.get(sev, 0) + 1

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "modele": "lecture seule (aucune correction automatique)",
        "totals": totals,
        "counts_by_severity": counts_by_severity,
        "corpora": per_corpus,
        "anomalies": all_anomalies,
    }
    last_path = settings.audit_dir / "last_audit.json"
    last_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    journal.log_event("audit_integrity", resultat="ok", extra={"n_anomalies": len(all_anomalies), "counts": counts_by_severity}, settings=settings)
    return report


def load_last_audit(settings: Optional[Settings] = None) -> Optional[dict]:
    settings = settings or get_settings()
    path = settings.audit_dir / "last_audit.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
