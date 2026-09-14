"""Métadonnées applicatives locales (SQLite).

Stocke uniquement des états d'usage de l'application (notifications, alertes lues/traitées,
état de référence documentaire), jamais une copie des documents originaux ni de contenu extrait.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_reviews (
    issue_key TEXT PRIMARY KEY,
    dossier_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    reviewed_note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notification_states (
    notification_key TEXT PRIMARY KEY,
    dossier_id TEXT NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS document_baselines (
    dossier_id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_events (
    notification_key TEXT PRIMARY KEY,
    dossier_id TEXT NOT NULL,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    action_label TEXT NOT NULL,
    action_target TEXT NOT NULL,
    event_at TEXT NOT NULL,
    kind TEXT NOT NULL
);
"""

VALID_NOTIFICATION_STATES = {"new", "read", "treated"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection(settings: Optional[Settings] = None):
    settings = settings or get_settings()
    path = Path(settings.sqlite_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def issue_key(dossier_id: str, rule_id: str, message: str) -> str:
    digest = hashlib.sha256(f"{dossier_id}:{rule_id}:{message}".encode("utf-8")).hexdigest()[:16]
    return f"{dossier_id}:{rule_id}:{digest}"


def notification_key(dossier_id: str, category: str, title: str, message: str) -> str:
    digest = hashlib.sha256(f"{dossier_id}:{category}:{title}:{message}".encode("utf-8")).hexdigest()[:16]
    return f"{dossier_id}:{category}:{digest}"


def mark_reviewed(dossier_id: str, rule_id: str, message: str, note: str = "", settings: Optional[Settings] = None) -> str:
    key = issue_key(dossier_id, rule_id, message)
    with get_connection(settings) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO alert_reviews (issue_key, dossier_id, rule_id, reviewed_at, reviewed_note) VALUES (?, ?, ?, ?, ?)",
            (key, dossier_id, rule_id, _now(), note),
        )
    return key


def is_reviewed(dossier_id: str, rule_id: str, message: str, settings: Optional[Settings] = None) -> bool:
    key = issue_key(dossier_id, rule_id, message)
    with get_connection(settings) as conn:
        row = conn.execute("SELECT 1 FROM alert_reviews WHERE issue_key = ?", (key,)).fetchone()
        return row is not None


def list_reviewed(dossier_id: Optional[str] = None, settings: Optional[Settings] = None) -> list[dict]:
    with get_connection(settings) as conn:
        if dossier_id:
            rows = conn.execute(
                "SELECT issue_key, dossier_id, rule_id, reviewed_at, reviewed_note FROM alert_reviews WHERE dossier_id = ?",
                (dossier_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT issue_key, dossier_id, rule_id, reviewed_at, reviewed_note FROM alert_reviews").fetchall()
    return [
        {"issue_key": r[0], "dossier_id": r[1], "rule_id": r[2], "reviewed_at": r[3], "reviewed_note": r[4]}
        for r in rows
    ]


def set_notification_state(notification_key_value: str, dossier_id: str, state: str, note: str = "", settings: Optional[Settings] = None) -> None:
    if state not in VALID_NOTIFICATION_STATES:
        raise ValueError(f"Etat de notification invalide: {state}")
    with get_connection(settings) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notification_states (notification_key, dossier_id, state, updated_at, note) VALUES (?, ?, ?, ?, ?)",
            (notification_key_value, dossier_id, state, _now(), note),
        )


def get_notification_state(notification_key_value: str, settings: Optional[Settings] = None) -> str:
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT state FROM notification_states WHERE notification_key = ?",
            (notification_key_value,),
        ).fetchone()
    return row[0] if row else "new"


def list_notification_states(dossier_id: Optional[str] = None, settings: Optional[Settings] = None) -> dict[str, dict]:
    with get_connection(settings) as conn:
        if dossier_id:
            rows = conn.execute(
                "SELECT notification_key, dossier_id, state, updated_at, note FROM notification_states WHERE dossier_id = ?",
                (dossier_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT notification_key, dossier_id, state, updated_at, note FROM notification_states"
            ).fetchall()
    return {
        r[0]: {"notification_key": r[0], "dossier_id": r[1], "state": r[2], "updated_at": r[3], "note": r[4]}
        for r in rows
    }


def save_document_baseline(dossier_id: str, snapshot: dict, settings: Optional[Settings] = None) -> None:
    with get_connection(settings) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_baselines (dossier_id, snapshot_json, captured_at) VALUES (?, ?, ?)",
            (dossier_id, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), _now()),
        )


def load_document_baseline(dossier_id: str, settings: Optional[Settings] = None) -> Optional[dict]:
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT snapshot_json, captured_at FROM document_baselines WHERE dossier_id = ?",
            (dossier_id,),
        ).fetchone()
    if not row:
        return None
    return {"snapshot": json.loads(row[0]), "captured_at": row[1]}


def upsert_document_event(event: dict, settings: Optional[Settings] = None) -> None:
    with get_connection(settings) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO document_events (notification_key, dossier_id, level, title, message, recommended_action, action_label, action_target, event_at, kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event["notification_key"],
                event["dossier_id"],
                event["level"],
                event["title"],
                event["message"],
                event.get("recommended_action", ""),
                event.get("action_label", "Voir le dossier"),
                event.get("action_target", f"dossier:{event['dossier_id']}"),
                event.get("event_at", _now()),
                event.get("kind", "document"),
            ),
        )


def list_document_events(dossier_id: Optional[str] = None, settings: Optional[Settings] = None) -> list[dict]:
    with get_connection(settings) as conn:
        if dossier_id:
            rows = conn.execute(
                "SELECT notification_key, dossier_id, level, title, message, recommended_action, action_label, action_target, event_at, kind FROM document_events WHERE dossier_id = ? ORDER BY event_at DESC",
                (dossier_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT notification_key, dossier_id, level, title, message, recommended_action, action_label, action_target, event_at, kind FROM document_events ORDER BY event_at DESC"
            ).fetchall()
    return [
        {
            "notification_key": r[0],
            "dossier_id": r[1],
            "level": r[2],
            "title": r[3],
            "message": r[4],
            "recommended_action": r[5],
            "action_label": r[6],
            "action_target": r[7],
            "event_at": r[8],
            "kind": r[9],
        }
        for r in rows
    ]
