"""API FastAPI de l'application RAG notariale locale. Aucun endpoint ne modifie jamais un
document original ; aucune reponse ne peut constituer un acte authentique, une signature ou
un cachet notarial.

Correctifs ajoutes :
- selection EXCLUSIVE du corpus (dossier | template | law) ; la valeur "mixed" est refusee ;
- endpoint securise de consultation des modeles internes (data/modeles, lecture seule) ;
- checklist des pieces par dossier (deterministe) ;
- explication d'alerte au notaire (le RAG n'a jamais le pouvoir de changer un verdict) ;
- audit d'integrite lecture seule + decisions de suivi locales ;
- watcher d'import mono-dossier (mode --once) ;
- sauvegarde / restauration locales ;
- journal local (lecture).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.schemas import AlertExplainRequest, ChatRequest, ChatResponse, SearchRequest, ValidationReport
from app.retrieval.qdrant_store import UnsafeSearchError
from app.services import audit_integrity, backup, checklists, document_checklist, journal, notifications, watcher
from app.services.dossier_validation import get_validation_report_path
from app.services.db import list_reviewed, mark_reviewed
from app.services.indexing_service import CORPORA, IndexingService
from app.services.public_labels import dossier_public_card
from app.services.rag_service import RagService
from app.services.secure_files import ModelPathError, resolve_model_path
from app.validation.validator import validate_and_write, validate_dossier

app = FastAPI(
    title="Assistant documentaire notarial local (RAG)",
    description=(
        "Assistant strictement documentaire pour une etude notariale. Toute reponse doit etre "
        "validee par le notaire ; l'application ne genere jamais d'acte authentique final."
    ),
    version="0.2.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    settings = get_settings()
    from app.ingestion.extractors import soffice_available
    from app.retrieval.ollama_client import OllamaClient
    ollama_ok = OllamaClient(settings).is_available()
    return {
        "status": "ok",
        "ollama_available": ollama_ok,
        "libreoffice_available": soffice_available(),
        "qdrant_mode": settings.qdrant_mode,
        "data_dir": str(settings.data_path),
    }


@app.post("/index/all")
def index_all():
    service = IndexingService()
    manifest = service.index_all()
    return manifest


@app.post("/index/{source}")
def index_source(source: str):
    if source not in CORPORA:
        raise HTTPException(status_code=400, detail=f"Corpus inconnu: {source}. Valeurs attendues: {CORPORA}")
    service = IndexingService()
    return service.index_corpus(source)


def _dossiers_dir() -> Path:
    return get_settings().dossiers_dir


@app.get("/dossiers")
def list_dossiers():
    dossiers_dir = _dossiers_dir()
    if not dossiers_dir.exists():
        return {"dossiers": []}
    items = []
    for path in sorted(dossiers_dir.iterdir()):
        if not path.is_dir():
            continue
        master_path = path / "dossier_master.json"
        entry = {"dossier_id": path.name}
        if master_path.exists():
            master = json.loads(master_path.read_text(encoding="utf-8"))
            report_path = get_validation_report_path(path.name)
            validation_status = None
            if report_path.exists():
                try:
                    validation_status = json.loads(report_path.read_text(encoding="utf-8")).get("status")
                except Exception:  # noqa: BLE001
                    validation_status = None
            if validation_status is None:
                try:
                    validation_status = validate_dossier(path).status
                except Exception:  # noqa: BLE001
                    validation_status = None
            public_card = dossier_public_card(master, validation_status)
            entry.update({
                "type_dossier": master.get("type_dossier"),
                "variante": master.get("variante"),
                "client_famille": master.get("client_famille"),
                "annee": master.get("annee"),
                "validation_status": validation_status,
                "public_type": public_card["type"],
                "public_variant": public_card["variante"],
                "public_state": public_card["etat"],
                "public_reference": public_card["reference"],
            })
        items.append(entry)
    return {"dossiers": items}


def _get_dossier_path(dossier_id: str) -> Path:
    path = _dossiers_dir() / dossier_id
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail=f"Dossier introuvable: {dossier_id}")
    return path


@app.get("/dossiers/{dossier_id}")
def get_dossier(dossier_id: str):
    path = _get_dossier_path(dossier_id)
    master_path = path / "dossier_master.json"
    if not master_path.exists():
        raise HTTPException(status_code=404, detail="dossier_master.json absent pour ce dossier.")
    return json.loads(master_path.read_text(encoding="utf-8"))


@app.get("/dossiers/{dossier_id}/documents")
def get_dossier_documents(dossier_id: str):
    path = _get_dossier_path(dossier_id)
    files = [
        p.name for p in sorted(path.iterdir())
        if p.is_file() and p.suffix.lower() in (".docx", ".doc", ".pdf")
    ]
    return {"dossier_id": dossier_id, "documents": files}


@app.get("/dossiers/{dossier_id}/validation")
def get_dossier_validation(dossier_id: str):
    path = _get_dossier_path(dossier_id)
    report_path = get_validation_report_path(dossier_id)
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Aucun rapport de validation genere pour ce dossier. Utilisez POST /dossiers/{id}/validate.")
    return json.loads(report_path.read_text(encoding="utf-8"))


@app.post("/dossiers/{dossier_id}/validate", response_model=ValidationReport)
def validate_dossier_endpoint(dossier_id: str):
    path = _get_dossier_path(dossier_id)
    return validate_and_write(path)


@app.get("/dossiers/{dossier_id}/checklist")
def get_dossier_checklist(dossier_id: str):
    """Checklist structuree des pieces (deterministe, cahier des charges §7)."""
    _get_dossier_path(dossier_id)
    return checklists.evaluate_dossier(dossier_id)


@app.get("/dossiers/{dossier_id}/document-checklist")
def get_dossier_document_checklist(dossier_id: str):
    """Checklist documentaire metier complete (par type/variante), deterministe, sans LLM.

    Distincte de /dossiers/{id}/checklist (checklist historique) : cette checklist couvre
    l'ensemble des types de dossiers de l'etude (vente, hypotheque, mainlevee, donation,
    succession, procuration, VEFA, fonds de commerce, creation de societe, gerance libre,
    demandes administratives) via une configuration versionnee et adaptable par l'etude
    (app/config/document_checklists.yaml). Ne conclut jamais qu'un dossier est complet,
    regulier ou pret a signer.
    """
    _get_dossier_path(dossier_id)
    return document_checklist.evaluate_document_checklist(dossier_id)


@app.post("/dossiers/{dossier_id}/explain-alert", response_model=ChatResponse)
def explain_alert(dossier_id: str, payload: AlertExplainRequest):
    """Explique UNE alerte au notaire sans changer le verdict (cahier des charges §6)."""
    _get_dossier_path(dossier_id)
    service = RagService()
    return service.explain_alert(
        dossier_id=dossier_id,
        rule_id=payload.rule_id,
        severity=payload.severity,
        message=payload.message,
        evidence=payload.evidence,
        recommended_action=payload.recommended_action,
    )


@app.post("/search")
def search(request: SearchRequest):
    service = RagService()
    try:
        grouped = service.search(request.query, request.scope, request.dossier_id, top_k=request.top_k)
    except UnsafeSearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"query": request.query, "scope": request.scope, "results": {k: [c.model_dump() for c in v] for k, v in grouped.items()}}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    service = RagService()
    try:
        return service.chat(request.query, request.scope, request.dossier_id, top_k=request.top_k)
    except UnsafeSearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/models")
def models():
    settings = get_settings()
    return {
        "chat_model": settings.ollama_chat_model,
        "embedding_model": settings.ollama_embed_model,
        "ollama_base_url": settings.ollama_base_url,
    }


@app.get("/laws/search")
def search_laws(query: str, top_k: int = 5):
    service = RagService()
    grouped = service.search(query, scope="law", dossier_id=None, top_k=top_k)
    return {"query": query, "results": [c.model_dump() for c in grouped.get("legal_public", [])]}


# ---------------------------------------------------------------------------
# Consultation securisee des modeles internes (cahier des charges §5)
# ---------------------------------------------------------------------------
@app.get("/modeles/open")
def open_modele(relative_path: str = Query(..., description="relative_path indexe du modele (jamais un chemin genere par Ollama)")):
    """Sert UNIQUEMENT des fichiers sous data/modeles, en lecture seule."""
    try:
        candidate = resolve_model_path(relative_path)
    except ModelPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    journal.log_event("consultation_modele", corpus="modeles", fichiers=[relative_path], resultat="ok")
    return FileResponse(str(candidate), filename=candidate.name, media_type="application/octet-stream")


# ---------------------------------------------------------------------------
# Alertes
# ---------------------------------------------------------------------------
@app.get("/alerts")
def list_alerts(dossier_id: Optional[str] = None):
    dossiers_dir = _dossiers_dir()
    reviewed = {(r["dossier_id"], r["rule_id"]) for r in list_reviewed(dossier_id)}
    alerts = []
    targets = [dossiers_dir / dossier_id] if dossier_id else list(dossiers_dir.iterdir())
    for path in sorted(targets):
        if not path.is_dir():
            continue
        report_path = get_validation_report_path(path.name)
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for issue in report.get("issues", []):
            alerts.append({
                "dossier_id": report["dossier_id"],
                **issue,
                "reviewed": (report["dossier_id"], issue["rule_id"]) in reviewed,
            })
    return {"alerts": alerts}


@app.post("/alerts/review")
def review_alert(dossier_id: str, rule_id: str, message: str, note: str = ""):
    key = mark_reviewed(dossier_id, rule_id, message, note)
    journal.log_event("alerte_traitee", dossier_id=dossier_id, resultat="ok", justification=note, extra={"rule_id": rule_id}, )
    return {"issue_key": key, "status": "reviewed"}


@app.get("/notifications")
def get_notifications(dossier_id: Optional[str] = None):
    return notifications.list_notifications(dossier_id=dossier_id)


@app.post("/notifications/read")
def mark_notification_read(notification_key: str, dossier_id: str, note: str = ""):
    return notifications.mark_notification_read(notification_key, dossier_id, note=note)


@app.post("/notifications/treated")
def mark_notification_treated(notification_key: str, dossier_id: str, note: str = ""):
    return notifications.mark_notification_treated(notification_key, dossier_id, note=note)


# ---------------------------------------------------------------------------
# Audit d'integrite (cahier des charges §9) — lecture seule
# ---------------------------------------------------------------------------
@app.post("/audit/run")
def run_audit():
    return audit_integrity.run_audit()


@app.get("/audit/last")
def last_audit():
    report = audit_integrity.load_last_audit()
    if report is None:
        raise HTTPException(status_code=404, detail="Aucun audit execute pour l'instant.")
    return report


@app.get("/audit/decisions")
def audit_decisions():
    return {"decisions": audit_integrity.list_decisions()}


@app.post("/audit/decisions")
def audit_record_decision(anomaly_key: str, action: str, justification: str):
    if action not in ("authorized", "resolved", "ignored"):
        raise HTTPException(status_code=400, detail="Action invalide (authorized|resolved|ignored).")
    decision = audit_integrity.record_decision(anomaly_key, action, justification)
    return decision


# ---------------------------------------------------------------------------
# Watcher d'import (cahier des charges §8)
# ---------------------------------------------------------------------------
@app.post("/watcher/run-once")
def watcher_run_once():
    return {"results": watcher.process_inbox_once()}


# ---------------------------------------------------------------------------
# Sauvegarde / restauration (cahier des charges §12)
# ---------------------------------------------------------------------------
@app.post("/backup/create")
def backup_create():
    return backup.create_backup()


@app.get("/backup/last")
def backup_last():
    info = backup.last_backup()
    if info is None:
        raise HTTPException(status_code=404, detail="Aucune sauvegarde trouvee.")
    return info


# ---------------------------------------------------------------------------
# Journal local (cahier des charges §10)
# ---------------------------------------------------------------------------
@app.get("/journal")
def get_journal(limit: int = 200):
    return {"events": journal.list_events(limit=limit)}
