from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.config import Settings, get_settings
from app.services.db import (
    get_notification_state,
    list_document_events,
    list_notification_states,
    load_document_baseline,
    notification_key,
    save_document_baseline,
    set_notification_state,
    upsert_document_event,
)
from app.services.document_checklist import evaluate_document_checklist, resolve_checklist
from app.services.public_labels import ambigu_pricing_message, level_label, public_reference, public_state_label

SUPPORTED_DOC_SUFFIXES = {".pdf", ".doc", ".docx", ".txt"}
BADGE_LEVELS = {"attention_requise", "verification_recommandee"}
STATE_LABELS = {"new": "nouvelle", "read": "lue", "treated": "traitée"}
LEVEL_PRIORITY = {"attention_requise": 0, "verification_recommandee": 1, "information": 2}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _dossiers(settings: Settings, dossier_id: Optional[str] = None) -> list[Path]:
    if dossier_id:
        path = settings.dossiers_dir / dossier_id
        return [path] if path.exists() and path.is_dir() else []
    return [p for p in sorted(settings.dossiers_dir.iterdir()) if p.is_dir()]


def _validation_report(settings: Settings, dossier_id: str) -> Optional[dict]:
    path = settings.validation_reports_dir / f"{dossier_id}.json"
    return _load_json(path) if path.exists() else None


def _master(settings: Settings, dossier_id: str) -> dict[str, Any]:
    path = settings.dossiers_dir / dossier_id / "dossier_master.json"
    return _load_json(path) or {"dossier_id": dossier_id}


def _docs_snapshot(dossier_path: Path) -> dict[str, dict[str, int]]:
    snapshot: dict[str, dict[str, int]] = {}
    for path in sorted(dossier_path.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_DOC_SUFFIXES:
            continue
        stat = path.stat()
        snapshot[path.name] = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    return snapshot


def capture_document_baseline(dossier_id: str, settings: Optional[Settings] = None) -> dict:
    settings = settings or get_settings()
    dossier_path = settings.dossiers_dir / dossier_id
    snapshot = _docs_snapshot(dossier_path)
    save_document_baseline(dossier_id, snapshot, settings=settings)
    return snapshot


def _required_aliases(master: dict[str, Any], settings: Settings) -> set[str]:
    type_dossier = master.get("type_dossier")
    variante = master.get("variante")
    resolved = resolve_checklist(type_dossier, variante, settings=settings)
    aliases: set[str] = set()
    if not resolved:
        return aliases
    for item in resolved.get("items", []):
        for alias in item.get("file_aliases", []) or []:
            aliases.add(str(alias).lower())
    return aliases


def _important_filename(master: dict[str, Any], filename: str, settings: Settings) -> bool:
    lowered = filename.lower()
    aliases = _required_aliases(master, settings)
    return any(alias in lowered for alias in aliases)


def _indexed_files_for_dossier(settings: Settings, dossier_id: str) -> set[str]:
    indexed: set[str] = set()
    path = settings.output_path / "chunks_dossiers.jsonl"
    if not path.exists():
        return indexed
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if row.get("dossier_id") == dossier_id and row.get("fichier"):
                    indexed.add(str(row["fichier"]))
    except Exception:  # noqa: BLE001
        return set()
    return indexed


def _active_status(report: Optional[dict]) -> str:
    return public_state_label((report or {}).get("status"))


def _event(level: str, dossier_id: str, title: str, message: str, recommended_action: str, action_label: str, action_target: str, kind: str, event_at: Optional[str] = None) -> dict:
    key = notification_key(dossier_id, kind, title, message)
    return {
        "notification_key": key,
        "dossier_id": dossier_id,
        "level": level,
        "title": title,
        "message": message,
        "recommended_action": recommended_action,
        "action_label": action_label,
        "action_target": action_target,
        "event_at": event_at or _now(),
        "kind": kind,
    }


def _sync_document_events_for_dossier(dossier_id: str, settings: Settings) -> None:
    dossier_path = settings.dossiers_dir / dossier_id
    if not dossier_path.exists():
        return
    current = _docs_snapshot(dossier_path)
    baseline_payload = load_document_baseline(dossier_id, settings=settings)
    if baseline_payload is None:
        save_document_baseline(dossier_id, current, settings=settings)
        return

    baseline = baseline_payload.get("snapshot", {})
    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    modified = sorted(name for name in set(current) & set(baseline) if current[name] != baseline[name])
    total_changes = len(added) + len(removed) + len(modified)
    if total_changes == 0:
        return

    report = _validation_report(settings, dossier_id)
    master = _master(settings, dossier_id)
    active_issue = (report or {}).get("status") in {"invalid", "warnings"}

    if total_changes > 5:
        upsert_document_event(_event(
            "attention_requise",
            dossier_id,
            "Changements documentaires multiples",
            "Plusieurs documents ont été modifiés dans un délai court.\nVérifiez les documents avant de poursuivre.",
            "Consulter le dossier et relire les pièces récentes.",
            "Voir le dossier",
            f"dossier:{dossier_id}",
            "document_changes_grouped",
        ), settings=settings)
    else:
        for name in added:
            important = _important_filename(master, name, settings)
            level = "verification_recommandee" if (important or active_issue) else "information"
            upsert_document_event(_event(
                level,
                dossier_id,
                "Document ajouté",
                "Un nouveau document a été ajouté au dossier.\nVérifiez s’il doit être pris en compte dans la préparation de l’acte.",
                "Consulter le document ajouté et vérifier son incidence sur le dossier.",
                "Voir le document",
                f"document:{dossier_id}:{name}",
                "document_added",
            ), settings=settings)
        for name in modified:
            level = "attention_requise" if active_issue else "verification_recommandee"
            upsert_document_event(_event(
                level,
                dossier_id,
                "Document modifié",
                "Un document du dossier a été modifié depuis le dernier contrôle.\nVérifiez cette version avant de poursuivre.",
                "Relire la version actuelle du document avant toute suite.",
                "Voir le document",
                f"document:{dossier_id}:{name}",
                "document_modified",
            ), settings=settings)
        for name in removed:
            important = _important_filename(master, name, settings) or name in baseline
            level = "attention_requise" if important else "verification_recommandee"
            upsert_document_event(_event(
                level,
                dossier_id,
                "Document indisponible",
                "Un document précédemment détecté dans le dossier n’est plus disponible.\nVérifiez le dossier et restaurez la pièce si nécessaire.",
                "Vérifier le dossier et restaurer la pièce si nécessaire.",
                "Voir le dossier",
                f"dossier:{dossier_id}",
                "document_removed",
            ), settings=settings)

    indexed = _indexed_files_for_dossier(settings, dossier_id)
    for name in added:
        if _important_filename(master, name, settings) and indexed and name not in indexed:
            upsert_document_event(_event(
                "verification_recommandee",
                dossier_id,
                "Document important à consulter directement",
                "Un document est présent dans le dossier mais n’est pas encore disponible dans la recherche documentaire. Vous pouvez le consulter directement.",
                "Ouvrir directement le document concerné.",
                "Voir le document",
                f"document:{dossier_id}:{name}",
                "document_search_pending",
            ), settings=settings)

    save_document_baseline(dossier_id, current, settings=settings)


def _validation_notifications(dossier_id: str, settings: Settings) -> list[dict]:
    report = _validation_report(settings, dossier_id)
    if not report:
        return []
    master = _master(settings, dossier_id)
    out: list[dict] = []
    issues = report.get("issues", []) or []
    seen_titles: set[str] = set()
    for issue in issues:
        rule_id = issue.get("rule_id", "")
        if rule_id == "price_multiple_declared" or master.get("type_dossier") == "AMBIGU":
            notif = _event(
                "attention_requise",
                dossier_id,
                "Prix contradictoires",
                ambigu_pricing_message(master),
                "Clarifier le prix avec les parties avant la rédaction définitive.",
                "Voir le dossier",
                f"dossier:{dossier_id}",
                f"validation:{rule_id or 'ambiguous_price'}",
                report.get("generated_at"),
            )
        elif rule_id == "sale_deferred_payment_missing_terms":
            notif = _event(
                "verification_recommandee",
                dossier_id,
                "Paiement différé",
                "Le solde différé est identifié, mais aucun échéancier ou engagement correspondant n’est détecté.\nAction : consulter la checklist du dossier.",
                "Consulter la checklist du dossier.",
                "Voir la checklist",
                f"checklist:{dossier_id}",
                f"validation:{rule_id}",
                report.get("generated_at"),
            )
        elif rule_id == "mortgage_registration_not_proven":
            notif = _event(
                "verification_recommandee",
                dossier_id,
                "Hypothèque",
                "Un engagement d’inscription hypothécaire est présent.\nL’inscription définitive n’est pas démontrée par les sources disponibles.\nAction : vérifier la formalité auprès de la conservation foncière.",
                "Vérifier la formalité auprès de la conservation foncière.",
                "Voir le dossier",
                f"dossier:{dossier_id}",
                f"validation:{rule_id}",
                report.get("generated_at"),
            )
        elif rule_id == "checklist_incomplete":
            notif = _event(
                "verification_recommandee",
                dossier_id,
                "Checklist documentaire",
                "Certaines pièces prévues par la checklist de l’étude ne sont pas détectées dans le dossier.\nAction : consulter la checklist documentaire.",
                "Consulter la checklist documentaire.",
                "Voir la checklist",
                f"checklist:{dossier_id}",
                f"validation:{rule_id}",
                report.get("generated_at"),
            )
        elif rule_id == "mortgage_surety_detected":
            notif = _event(
                "information",
                dossier_id,
                "Cautionnement",
                "Un cautionnement hypothécaire est mentionné dans le dossier.\nAction : vérifier l’identité de la caution, le bien affecté et l’étendue de la garantie.",
                "Vérifier l’identité de la caution, le bien affecté et l’étendue de la garantie.",
                "Voir le dossier",
                f"dossier:{dossier_id}",
                f"validation:{rule_id}",
                report.get("generated_at"),
            )
        else:
            level = {
                "blocking": "attention_requise",
                "warning": "verification_recommandee",
                "info": "information",
            }.get(issue.get("severity"), "information")
            notif = _event(
                level,
                dossier_id,
                issue.get("title") or level_label(level),
                issue.get("message") or "Un point mérite une vérification.",
                issue.get("recommended_action") or "Vérifier ce point dans le dossier.",
                "Voir le dossier",
                f"dossier:{dossier_id}",
                f"validation:{rule_id or 'issue'}",
                report.get("generated_at"),
            )
        if notif["title"] in seen_titles and notif["message"] == next((x["message"] for x in out if x["title"] == notif["title"]), None):
            continue
        seen_titles.add(notif["title"])
        out.append(notif)

    checklist = evaluate_document_checklist(dossier_id, settings=settings)
    if checklist and checklist.get("evaluable") and not any(n["title"] == "Checklist documentaire" for n in out):
        synthese = checklist.get("synthese", {})
        if synthese.get("a_ajouter", 0) or synthese.get("a_verifier", 0):
            out.append(_event(
                "verification_recommandee",
                dossier_id,
                "Checklist documentaire",
                "Certaines pièces prévues par la checklist de l’étude ne sont pas détectées dans le dossier.\nAction : consulter la checklist documentaire.",
                "Consulter la checklist documentaire.",
                "Voir la checklist",
                f"checklist:{dossier_id}",
                "checklist:synthetic",
                report.get("generated_at") if report else _now(),
            ))
    return out


def list_notifications(dossier_id: Optional[str] = None, settings: Optional[Settings] = None) -> dict:
    settings = settings or get_settings()
    dossiers = _dossiers(settings, dossier_id=dossier_id)
    for dossier_path in dossiers:
        _sync_document_events_for_dossier(dossier_path.name, settings)

    items: list[dict] = []
    states = list_notification_states(dossier_id, settings=settings)

    for dossier_path in dossiers:
        did = dossier_path.name
        master = _master(settings, did)
        ref = public_reference(master)
        for notif in _validation_notifications(did, settings):
            state = states.get(notif["notification_key"], {}).get("state", get_notification_state(notif["notification_key"], settings=settings))
            items.append({
                **notif,
                "dossier_reference": ref,
                "state": state,
                "state_label": STATE_LABELS.get(state, "nouvelle"),
                "level_label": level_label(notif["level"]),
            })

    for notif in list_document_events(dossier_id, settings=settings):
        master = _master(settings, notif["dossier_id"])
        ref = public_reference(master)
        state = states.get(notif["notification_key"], {}).get("state", get_notification_state(notif["notification_key"], settings=settings))
        items.append({
            **notif,
            "dossier_reference": ref,
            "state": state,
            "state_label": STATE_LABELS.get(state, "nouvelle"),
            "level_label": level_label(notif["level"]),
        })

    unique: dict[str, dict] = {}
    for item in items:
        key = item["notification_key"]
        existing = unique.get(key)
        if existing is None or (item.get("event_at") or "") > (existing.get("event_at") or ""):
            unique[key] = item

    notifications = sorted(
        unique.values(),
        key=lambda n: (LEVEL_PRIORITY.get(n["level"], 9), -(int(datetime.fromisoformat(n["event_at"].replace("Z", "+00:00")).timestamp()) if n.get("event_at") else 0)),
    )
    badge_count = sum(1 for n in notifications if n["level"] in BADGE_LEVELS and n.get("state") == "new")
    return {"badge_count": badge_count, "notifications": notifications}


def mark_notification_read(notification_key_value: str, dossier_id: str, note: str = "", settings: Optional[Settings] = None) -> dict:
    set_notification_state(notification_key_value, dossier_id, "read", note=note, settings=settings)
    return {"notification_key": notification_key_value, "state": "read"}


def mark_notification_treated(notification_key_value: str, dossier_id: str, note: str = "", settings: Optional[Settings] = None) -> dict:
    set_notification_state(notification_key_value, dossier_id, "treated", note=note, settings=settings)
    return {"notification_key": notification_key_value, "state": "treated"}
