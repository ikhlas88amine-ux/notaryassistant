"""Checklists structurees des pieces requises par type + variante de dossier (cahier des charges 7).

La determination des pieces manquantes est DECLENCHEE uniquement par la checklist applicable :
- combiner nom de fichier + type de document + contenu extrait ;
- statuts : present_confirmed | present_to_verify | missing | not_applicable | not_evaluable ;
- sans checklist applicable, aucune conclusion automatique n'est tiree.

Ne modifie jamais les documents sources ni le dossier.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings
from app.ingestion.extractors import extract_any, is_ignorable_file

STATUS_PRESENT_CONFIRMED = "present_confirmed"
STATUS_PRESENT_TO_VERIFY = "present_to_verify"
STATUS_MISSING = "missing"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_NOT_EVALUABLE = "not_evaluable"
ALLOWED_STATUSES = (STATUS_PRESENT_CONFIRMED, STATUS_PRESENT_TO_VERIFY, STATUS_MISSING, STATUS_NOT_APPLICABLE, STATUS_NOT_EVALUABLE)

SUPPORTED_SUFFIXES = (".docx", ".doc", ".pdf", ".txt")


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def checklist_filename(type_dossier: str, variante: Optional[str]) -> Optional[str]:
    """Nom de fichier checklist candidat : <type>_<variante>.json puis <type>_standard.json."""
    t = _normalize(type_dossier)
    v = _normalize(variante) if variante else ""
    cands = []
    if t and v:
        cands.append(f"{t}_{v}.json")
    if t:
        cands.append(f"{t}_standard.json")
    return cands[0] if cands else None


def load_checklist(type_dossier: str, variante: Optional[str], settings: Optional[Settings] = None) -> Optional[dict]:
    settings = settings or get_settings()
    dir_path: Path = settings.checklists_dir
    if not dir_path.exists():
        return None
    candidates = []
    t = _normalize(type_dossier)
    v = _normalize(variante) if variante else ""
    if t and v:
        candidates.append(f"{t}_{v}.json")
    if t:
        candidates.append(f"{t}_standard.json")
    for name in candidates:
        path = dir_path / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    return data
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _candidate_files(dossier_path: Path) -> list[Path]:
    return sorted(
        p for p in dossier_path.iterdir()
        if p.is_file() and not is_ignorable_file(p) and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _filename_matches(name: str, keywords: list[str]) -> bool:
    n = _normalize(name)
    return any(_normalize(kw) in n for kw in keywords)


def evaluate_dossier(dossier_id: str, settings: Optional[Settings] = None) -> dict:
    """Evalue les pieces du dossier contre la checklist applicable (deterministe)."""
    settings = settings or get_settings()
    dossier_path: Path = settings.dossiers_dir / dossier_id
    if not dossier_path.exists():
        return {"dossier_id": dossier_id, "checklist": None, "items": [], "evaluable": False,
                "message": "Dossier introuvable."}

    master_path = dossier_path / "dossier_master.json"
    if not master_path.exists():
        return {"dossier_id": dossier_id, "checklist": None, "items": [], "evaluable": False,
                "message": "dossier_master.json absent : aucune checklist applicable."}

    master = json.loads(master_path.read_text(encoding="utf-8"))
    type_dossier = master.get("type_dossier", "")
    variante = master.get("variante")
    checklist = load_checklist(type_dossier, variante, settings)

    if checklist is None:
        return {
            "dossier_id": dossier_id,
            "checklist": None,
            "items": [],
            "evaluable": False,
            "type_dossier": type_dossier,
            "variante": variante,
            "message": "Aucune checklist structuree des pieces requises n'est disponible ; les pieces manquantes ne peuvent pas etre determinees automatiquement.",
        }

    files = _candidate_files(dossier_path)
    # Extraction unique du contenu de chaque document (best effort) : la preuve d'une piece
    # combine nom de fichier + type + contenu extrait, jamais le seul nom de fichier.
    contents: dict[str, str] = {}
    for f in files:
        try:
            r = extract_any(f)
            if r.ok:
                contents[f.name] = r.text or ""
        except Exception:  # noqa: BLE001
            contents[f.name] = ""
    items_out = []
    for item in checklist.get("items", []):
        item_id = item.get("id", "")
        label = item.get("label", item_id)
        required = bool(item.get("required", True))
        severity = item.get("severity", "high")
        accepted_types = item.get("accepted_document_types", [])
        accepted_kw = item.get("accepted_filename_keywords", [])
        content_proof = item.get("content_proof_keywords", [])

        candidates = [f for f in files if _filename_matches(f.name, accepted_kw or [item_id])]
        reason = ""
        status = STATUS_MISSING

        if not required and not candidates:
            status = STATUS_NOT_APPLICABLE
            reason = "Piece facultative, aucun document candidat requis."
        elif candidates:
            best = candidates[0]
            fragment = contents.get(best.name, "")
            if fragment and content_proof:
                hits = [kw for kw in content_proof if _normalize(kw) in _normalize(fragment)]
                if hits:
                    status = STATUS_PRESENT_CONFIRMED
                    reason = f"Le document '{best.name}' est present et son contenu confirme l'element ({', '.join(hits[:3])})."
                else:
                    status = STATUS_PRESENT_TO_VERIFY
                    reason = f"Le document '{best.name}' correspond au nom attendu, mais le contenu extrait ne confirme pas explicitement l'element : verification humaine requise."
            elif fragment:
                status = STATUS_PRESENT_CONFIRMED
                reason = f"Le document '{best.name}' est present et exploitable (contenu extrait non vide)."
            else:
                status = STATUS_PRESENT_TO_VERIFY
                reason = f"Le document '{best.name}' est present mais non exploitable a ce stade (extraction vide ou format non convertible) : verification humaine requise."
        else:
            if content_proof:
                # pas de document dedie, mais l'element peut etre MENTIONNE dans un autre document
                mention = None
                for fname, txt in contents.items():
                    hits = [kw for kw in content_proof if _normalize(kw) in _normalize(txt)]
                    if hits:
                        mention = (fname, hits)
                        break
                if mention:
                    status = STATUS_PRESENT_TO_VERIFY
                    reason = (f"Element '{label}' mentionne dans le contenu de '{mention[0]}' sans document dedie "
                              f"({', '.join(str(h) for h in mention[1][:3])}) : verification humaine requise.")
                else:
                    reason = f"Aucun document candidat trouve pour l'element '{label}'."
            else:
                reason = f"Aucun document candidat trouve pour l'element '{label}'."

        items_out.append({
            "id": item_id,
            "label": label,
            "required": required,
            "severity": severity,
            "accepted_document_types": accepted_types,
            "accepted_filename_keywords": accepted_kw,
            "statut": status,
            "fichier_candidat": best.name if candidates else None,
            "raison": reason,
            "action_recommandee": item.get("recommended_action", "Verifier manuellement la piece aupres du notaire.") if status in (STATUS_MISSING, STATUS_PRESENT_TO_VERIFY) else "Aucune action requise.",
        })

    n_missing = sum(1 for i in items_out if i["statut"] == STATUS_MISSING)
    n_verify = sum(1 for i in items_out if i["statut"] == STATUS_PRESENT_TO_VERIFY)
    n_confirmed = sum(1 for i in items_out if i["statut"] == STATUS_PRESENT_CONFIRMED)
    return {
        "dossier_id": dossier_id,
        "checklist": checklist.get("checklist_id") or checklist.get("id") or checklist_filename(type_dossier, variante),
        "items": items_out,
        "evaluable": True,
        "type_dossier": type_dossier,
        "variante": variante,
        "message": "",
        "compteurs": {"present_confirmed": n_confirmed, "present_to_verify": n_verify, "missing": n_missing},
    }
