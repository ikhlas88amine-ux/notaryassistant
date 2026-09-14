"""Client HTTP minimal utilisé par les pages Streamlit pour parler au backend FastAPI."""
from __future__ import annotations

import os
from typing import Optional

import httpx

API_BASE_URL = os.environ.get("NOTARY_RAG_API_URL", "http://localhost:8000")


class ApiError(RuntimeError):
    pass


def _handle(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise ApiError(f"{resp.status_code}: {detail}")
    return resp.json()


def health() -> dict:
    with httpx.Client(timeout=5) as client:
        return _handle(client.get(f"{API_BASE_URL}/health"))


def list_dossiers() -> list[dict]:
    with httpx.Client(timeout=15) as client:
        return _handle(client.get(f"{API_BASE_URL}/dossiers"))["dossiers"]


def get_dossier(dossier_id: str) -> dict:
    with httpx.Client(timeout=15) as client:
        return _handle(client.get(f"{API_BASE_URL}/dossiers/{dossier_id}"))


def get_dossier_documents(dossier_id: str) -> list[str]:
    with httpx.Client(timeout=15) as client:
        return _handle(client.get(f"{API_BASE_URL}/dossiers/{dossier_id}/documents"))["documents"]


def get_dossier_validation(dossier_id: str) -> Optional[dict]:
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{API_BASE_URL}/dossiers/{dossier_id}/validation")
        if resp.status_code == 404:
            return None
        return _handle(resp)


def validate_dossier(dossier_id: str) -> dict:
    with httpx.Client(timeout=30) as client:
        return _handle(client.post(f"{API_BASE_URL}/dossiers/{dossier_id}/validate"))


def get_dossier_checklist(dossier_id: str) -> Optional[dict]:
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{API_BASE_URL}/dossiers/{dossier_id}/checklist")
        if resp.status_code != 200:
            return None
        return _handle(resp)


def get_dossier_document_checklist(dossier_id: str) -> Optional[dict]:
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{API_BASE_URL}/dossiers/{dossier_id}/document-checklist")
        if resp.status_code != 200:
            return None
        return _handle(resp)


def explain_alert(dossier_id: str, rule_id: str, severity: str, message: str,
                  evidence: Optional[dict] = None, recommended_action: str = "") -> dict:
    with httpx.Client(timeout=120) as client:
        return _handle(client.post(f"{API_BASE_URL}/dossiers/{dossier_id}/explain-alert", json={
            "rule_id": rule_id, "severity": severity, "message": message,
            "evidence": evidence or {}, "recommended_action": recommended_action,
        }))


def search(query: str, scope: str, dossier_id: Optional[str] = None, top_k: int = 5) -> dict:
    with httpx.Client(timeout=60) as client:
        return _handle(client.post(f"{API_BASE_URL}/search", json={
            "query": query, "scope": scope, "dossier_id": dossier_id, "top_k": top_k,
        }))


def chat(query: str, scope: str, dossier_id: Optional[str] = None, top_k: int = 5) -> dict:
    with httpx.Client(timeout=120) as client:
        return _handle(client.post(f"{API_BASE_URL}/chat", json={
            "query": query, "scope": scope, "dossier_id": dossier_id, "top_k": top_k,
        }))


def modele_open_url(relative_path: str) -> str:
    from urllib.parse import quote
    return f"{API_BASE_URL}/modeles/open?relative_path={quote(relative_path, safe='')}"


def models() -> dict:
    with httpx.Client(timeout=5) as client:
        return _handle(client.get(f"{API_BASE_URL}/models"))


def search_laws(query: str, top_k: int = 5) -> list[dict]:
    with httpx.Client(timeout=60) as client:
        return _handle(client.get(f"{API_BASE_URL}/laws/search", params={"query": query, "top_k": top_k}))["results"]


def list_alerts(dossier_id: Optional[str] = None) -> list[dict]:
    params = {"dossier_id": dossier_id} if dossier_id else {}
    with httpx.Client(timeout=15) as client:
        return _handle(client.get(f"{API_BASE_URL}/alerts", params=params))["alerts"]


def review_alert(dossier_id: str, rule_id: str, message: str, note: str = "") -> dict:
    with httpx.Client(timeout=15) as client:
        return _handle(client.post(f"{API_BASE_URL}/alerts/review", params={
            "dossier_id": dossier_id, "rule_id": rule_id, "message": message, "note": note,
        }))


def list_notifications(dossier_id: Optional[str] = None) -> dict:
    params = {"dossier_id": dossier_id} if dossier_id else {}
    with httpx.Client(timeout=20) as client:
        return _handle(client.get(f"{API_BASE_URL}/notifications", params=params))


def mark_notification_read(notification_key: str, dossier_id: str, note: str = "") -> dict:
    with httpx.Client(timeout=15) as client:
        return _handle(client.post(f"{API_BASE_URL}/notifications/read", params={
            "notification_key": notification_key,
            "dossier_id": dossier_id,
            "note": note,
        }))


def mark_notification_treated(notification_key: str, dossier_id: str, note: str = "") -> dict:
    with httpx.Client(timeout=15) as client:
        return _handle(client.post(f"{API_BASE_URL}/notifications/treated", params={
            "notification_key": notification_key,
            "dossier_id": dossier_id,
            "note": note,
        }))


def index_all() -> dict:
    with httpx.Client(timeout=600) as client:
        return _handle(client.post(f"{API_BASE_URL}/index/all"))


def index_source(source: str) -> dict:
    with httpx.Client(timeout=600) as client:
        return _handle(client.post(f"{API_BASE_URL}/index/{source}"))


def run_audit() -> dict:
    with httpx.Client(timeout=300) as client:
        return _handle(client.post(f"{API_BASE_URL}/audit/run"))


def last_audit() -> Optional[dict]:
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{API_BASE_URL}/audit/last")
        if resp.status_code == 404:
            return None
        return _handle(resp)


def audit_decisions() -> list[dict]:
    with httpx.Client(timeout=15) as client:
        return _handle(client.get(f"{API_BASE_URL}/audit/decisions"))["decisions"]


def audit_record_decision(anomaly_key: str, action: str, justification: str) -> dict:
    with httpx.Client(timeout=15) as client:
        return _handle(client.post(f"{API_BASE_URL}/audit/decisions", params={
            "anomaly_key": anomaly_key, "action": action, "justification": justification,
        }))


def watcher_run_once() -> dict:
    with httpx.Client(timeout=300) as client:
        return _handle(client.post(f"{API_BASE_URL}/watcher/run-once"))


def backup_create() -> dict:
    with httpx.Client(timeout=300) as client:
        return _handle(client.post(f"{API_BASE_URL}/backup/create"))


def backup_last() -> Optional[dict]:
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{API_BASE_URL}/backup/last")
        if resp.status_code == 404:
            return None
        return _handle(resp)


def journal(limit: int = 200) -> list[dict]:
    with httpx.Client(timeout=15) as client:
        return _handle(client.get(f"{API_BASE_URL}/journal", params={"limit": limit}))["events"]
