"""Sauvegarde et restauration locales (cahier des charges §12).

Sauvegarde (zip) de :
- data/ (documents sources, dossier_master, rapports de validation générés) ;
- output/qdrant_local/ (index vectoriel) ;
- output/audit/ (manifests + dernier audit + decisions) ;
- output/imports/ (rapports d'import) ;
- journal (output/journal.jsonl) ;
- configuration utile (.env, environment.yml, requirements.txt).

La restauration exige une confirmation explicite et n'ecrase jamais les modeles originaux
par une operation qui les modifierait : elle restaure dans un sous-dossier output/restore/<date>
et signale les conflits au lieu d'ecraser.
"""
from __future__ import annotations

import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings
from app.services import journal


def _add_dir(zf: zipfile.ZipFile, root: Path, arc_prefix: str, max_bytes: int | None = None) -> int:
    count = 0
    if not root.exists():
        return count
    for path in sorted(root.rglob("*")):
        if path.is_file():
            if path.name.startswith("~$") or path.name.startswith("."):
                continue
            if max_bytes and path.stat().st_size > max_bytes:
                continue
            zf.write(str(path), arcname=f"{arc_prefix}/{path.relative_to(root)}")
            count += 1
    return count


def create_backup(settings: Optional[Settings] = None, include_qdrant: bool = True) -> dict:
    settings = settings or get_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup_path = settings.backups_dir / f"backup_{stamp}.zip"
    settings.backups_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(str(backup_path), "w", zipfile.ZIP_DEFLATED) as zf:
        n_data = _add_dir(zf, settings.data_path, "data")
        n_qdrant = 0
        if include_qdrant:
            qdir = settings.output_path / "qdrant_local"
            if qdir.exists():
                n_qdrant = _add_dir(zf, qdir, "qdrant_local")
        n_audit = _add_dir(zf, settings.audit_dir, "audit")
        n_imports = _add_dir(zf, settings.imports_dir, "imports")
        n_journal = 0
        if settings.journal_path.exists():
            zf.write(str(settings.journal_path), arcname="journal.jsonl")
            n_journal = 1
        for cfg in (".env", "environment.yml", "requirements.txt"):
            p = Path(cfg)
            if p.exists():
                zf.write(str(p), arcname=cfg)

    size = backup_path.stat().st_size
    journal.log_event(
        "sauvegarde", resultat="ok",
        extra={"archive": str(backup_path), "taille_octets": size,
               "compteurs": {"data": n_data, "qdrant": n_qdrant, "audit": n_audit, "imports": n_imports, "journal": n_journal}},
        settings=settings,
    )
    return {"archive": str(backup_path), "taille_octets": size, "created_at": stamp,
            "compteurs": {"data": n_data, "qdrant": n_qdrant, "audit": n_audit, "imports": n_imports, "journal": n_journal}}


def last_backup(settings: Optional[Settings] = None) -> Optional[dict]:
    settings = settings or get_settings()
    if not settings.backups_dir.exists():
        return None
    backups = sorted(settings.backups_dir.glob("backup_*.zip"))
    if not backups:
        return None
    latest = backups[-1]
    return {"archive": str(latest), "taille_octets": latest.stat().st_size}


def restore_backup(archive: Path, settings: Optional[Settings] = None) -> dict:
    """Restauration dans output/restore/<date>/ avec detection de conflits — aucune ecrasement
    silencieux des originaux. Doit etre appelee uniquement apres confirmation explicite."""
    settings = settings or get_settings()
    if not archive.exists() or archive.suffix.lower() != ".zip":
        raise ValueError("Archive de sauvegarde invalide.")
    dest = settings.output_path / "restore" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    dest.mkdir(parents=True, exist_ok=True)
    conflicts: list[str] = []
    with zipfile.ZipFile(str(archive)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            target = dest / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            # conflit : un fichier identique existe deja cote data/ ?
            original = settings.data_path / Path(member.filename).name
            if member.filename.startswith("data/") and original.exists():
                conflicts.append(member.filename)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    journal.log_event("restauration", resultat="ok", justification=f"restaure dans {dest}", extra={"conflits": conflicts}, settings=settings)
    return {"destination": str(dest), "n_fichiers": sum(1 for _ in dest.rglob("*") if _.is_file()), "conflits": conflicts}
