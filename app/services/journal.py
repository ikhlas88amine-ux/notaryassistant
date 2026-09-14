"""Journal local append-only (cahier des charges §10).

Chaque evenement est ajoute a la fin de output/journal.jsonl avec :
- horodatage UTC ;
- action ;
- corpus et dossier si applicables ;
- utilisateur local 'notaire' ;
- fichiers / hash concernes ;
- resultat ;
- justification si necessaire.

Le journal n'est jamais reecrit ni tronque : append-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings

USER_LOCAL = "notaire"


def log_event(
    action: str,
    *,
    corpus: Optional[str] = None,
    dossier_id: Optional[str] = None,
    fichiers: Optional[list[str]] = None,
    hashs: Optional[list[str]] = None,
    resultat: str = "ok",
    justification: Optional[str] = None,
    settings: Optional[Settings] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Ajoute un evenement au journal JSONL et le retourne."""
    settings = settings or get_settings()
    event = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "corpus": corpus,
        "dossier_id": dossier_id,
        "utilisateur": USER_LOCAL,
        "fichiers": fichiers or [],
        "hashs": hashs or [],
        "resultat": resultat,
        "justification": justification,
    }
    if extra:
        event["extra"] = extra
    path: Path = settings.journal_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False))
        f.write("\n")
    return event


def list_events(limit: int = 200, settings: Optional[Settings] = None) -> list[dict]:
    settings = settings or get_settings()
    path: Path = settings.journal_path
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events[-limit:][::-1]
