"""Watcher automatique d'import de dossiers (cahier des charges §8).

Le notaire depose un dossier COMPLET sous data/inbox_dossiers/<dossier_id>/ contenant :
- dossier_master.json
- documents
- un marqueur `.ready` cree EN DERNIER

Deroulement (strictement sequentiel, un seul process a la fois) :
1. verrou `.processing`
2. verification d'integrite et de stabilite des fichiers (tailles stables)
3. verification de dossier_master.json
4. verification de l'unicite du dossier_id (absent de data/dossiers)
5. deplacement du dossier techniquement valide vers data/dossiers
6. validation deterministe de CE SEUL dossier (jamais Ollama)
7. indexation de CE SEUL dossier dans case_documents (Ollama pour les embeddings uniquement)
8. generation du rapport output/imports/<dossier_id>.json et journal JSONL
9. en cas d'echec technique -> deplacement vers data/rejected_dossiers + marqueur .failed

Les alertes metier (warnings/invalid) ne bloquent jamais l'import technique.
Les modeles et les lois ne sont jamais reindexes ; la collection n'est jamais reinitialisee.
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings
from app.services import journal
from app.services.indexing_service import IndexingService
from app.services.locks import qdrant_locked
from app.validation.validator import validate_and_write

MARKERS = (".ready", ".processing", ".failed", ".done")
ALLOWED_SUFFIXES = (".docx", ".doc", ".pdf", ".txt", ".json")
STABILITY_WAIT_SECONDS = 1.5
STABILITY_CHECKS = 2


def _is_marker(name: str) -> bool:
    return name in MARKERS or name.startswith(".ready") or name.startswith(".processed")


def _fingerprint(files: list[Path]) -> list[tuple[str, int, float]]:
    return [(f.name, f.stat().st_size, f.stat().st_mtime) for f in files]


def _stable(files: list[Path]) -> bool:
    first = _fingerprint(files)
    time.sleep(STABILITY_WAIT_SECONDS)
    second = _fingerprint(files)
    return first == second


def _validate_technical(dossier_dir: Path) -> tuple[bool, str]:
    master = dossier_dir / "dossier_master.json"
    if not master.exists():
        return False, "dossier_master.json absent"
    try:
        data = json.loads(master.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"dossier_master.json invalide : {exc}"
    if not data.get("dossier_id"):
        return False, "dossier_master.json sans champ dossier_id"
    if data["dossier_id"] != dossier_dir.name:
        return False, f"incoherence dossier_id ({data['dossier_id']} != {dossier_dir.name})"
    if not any(p.suffix.lower() in (".docx", ".doc", ".pdf", ".txt") for p in dossier_dir.iterdir() if p.is_file()):
        return False, "aucun document exploitable (docx/doc/pdf/txt) dans le dossier"
    return True, "techniquement valide"


def _write_report(dossier_id: str, payload: dict, settings: Settings) -> Path:
    path = settings.imports_dir / f"{dossier_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _reject(dossier_dir: Path, settings: Settings, reason: str) -> dict:
    """Deplace un dossier techniquement invalide vers data/rejected_dossiers (jamais de suppression)."""
    dossier_id = dossier_dir.name
    if dossier_dir.exists():
        settings.rejected_dir.mkdir(parents=True, exist_ok=True)
        rejected = settings.rejected_dir / f"{dossier_id}_{int(time.time())}"
        try:
            shutil.move(str(dossier_dir), str(rejected))
        except shutil.Error:
            rejected = dossier_dir
        (rejected / ".failed").write_text(reason, encoding="utf-8")
    journal.log_event(
        "import_dossier", corpus="dossiers", dossier_id=dossier_id,
        resultat="failed", justification=reason, settings=settings,
    )
    return {"dossier_id": dossier_id, "status": "failed", "reason": reason}


def _process_one(dossier_dir: Path, settings: Settings) -> dict:
    dossier_id = dossier_dir.name
    ready = dossier_dir / ".ready"
    processing = dossier_dir / ".processing"
    failed = dossier_dir / ".failed"
    done = dossier_dir / ".done"

    # 1. verrou .processing (atomique)
    if processing.exists() or done.exists():
        return {"dossier_id": dossier_id, "status": "skipped", "reason": "marqueur .processing/.done present (deja traite ou en cours)"}
    processing.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")

    try:
        files = [p for p in dossier_dir.iterdir() if p.is_file() and not _is_marker(p.name)]
        if not files:
            return {"dossier_id": dossier_id, "status": "skipped", "reason": "aucun fichier a importer"}

        # 2. stabilite + 3. master
        if not _stable(files):
            return {"dossier_id": dossier_id, "status": "failed", "reason": "fichiers instables (copie en cours)"}
        ok, msg = _validate_technical(dossier_dir)
        if not ok:
            return _reject(dossier_dir, settings, msg)

        # 4. unicite
        target = settings.dossiers_dir / dossier_id
        if target.exists():
            return _reject(dossier_dir, settings, "dossier_id deja present dans data/dossiers (duplique)")

        # 5. deplacement vers data/dossiers
        settings.dossiers_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dossier_dir), str(target))
        for marker in MARKERS:
            m = target / marker
            if m.exists():
                m.unlink()

        # 6. validation deterministe (jamais Ollama)
        report = validate_and_write(target)
        validation = report.model_dump()

        # 7. indexation du seul dossier (embeddings Ollama ; sans Ollama, JSONL seul)
        index_result = None
        try:
            service = IndexingService(settings=settings, embed=True)
            index_result = service.index_corpus("dossiers", only_dossier_id=dossier_id)
        except Exception as exc:  # noqa: BLE001 - ne bloque pas le rapport
            index_result = {"error": str(exc)}

        # 8. rapport + journal
        payload = {
            "dossier_id": dossier_id,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "status": "imported",
            "validation_status": report.status,
            "validation": validation,
            "indexation": index_result,
        }
        _write_report(dossier_id, payload, settings)
        (target / ".done").write_text(json.dumps({"imported_at": payload["imported_at"]}, ensure_ascii=False), encoding="utf-8")
        journal.log_event(
            "import_dossier", corpus="dossiers", dossier_id=dossier_id,
            fichiers=[f.name for f in files], resultat="ok",
            extra={"validation_status": report.status, "report": str(settings.imports_dir / f"{dossier_id}.json")},
            settings=settings,
        )
        return payload
    except Exception as exc:  # noqa: BLE001
        reason = f"erreur technique inattendue : {exc}"
        return _reject(dossier_dir, settings, reason)


@qdrant_locked
def process_inbox_once(settings: Optional[Settings] = None) -> list[dict]:
    """Traite une seule fois chaque dossier depoté sous inbox_dossiers (mode --once ou tour de watcher)."""
    settings = settings or get_settings()
    inbox = settings.inbox_dir
    results: list[dict] = []
    if not inbox.exists():
        return results
    for child in sorted(inbox.iterdir()):
        if not child.is_dir():
            continue
        results.append(_process_one(child, settings))
    return results
