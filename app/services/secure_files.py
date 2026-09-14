"""Resolution securisee de chemins vers les fichiers sous data/modeles (cahier des charges §5).

Rules:
- le chemin est toujours resolu a partir de `relative_path` indexe (jamais genere par Ollama) ;
- refus de `..` et des chemins absolus ;
- le chemin resolu doit rester sous la racine data/modeles ;
- le fichier doit exister ;
- extensions autorisees : .doc, .docx, .pdf, .txt ;
- la consultation est en lecture seule.

Ordre de controle obligatoire (avant toute resolution disque) :
1. chaine vide ;
2. chemin absolu ;
3. presence de `..` ;
4. extension autorisee ;
5. resolution ;
6. controle sous data/modeles ;
7. existence du fichier.

La detection de chemin absolu / parcours parent se fait sur la CHAINE BRUTE, jamais via le
seul `pathlib.Path(...).is_absolute()` de la plateforme d'execution : sur Windows,
`PureWindowsPath("/etc/passwd").is_absolute()` vaut False (il manque une lettre de lecteur),
ce qui laisserait passer un chemin absolu de type POSIX. On detecte donc explicitement les
formes POSIX (`/...`), UNC (`\\\\serveur\\partage`) et lettre de lecteur Windows (`C:\\...`)
sur la chaine d'origine, quelle que soit la plateforme d'execution.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from app.core.config import Settings, get_settings

ALLOWED_SUFFIXES = (".doc", ".docx", ".pdf", ".txt")

_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")


class ModelPathError(ValueError):
    pass


def _is_absolute_path(raw: str) -> bool:
    """Detecte un chemin absolu quelle que soit sa convention d'origine (POSIX, UNC,
    lettre de lecteur Windows), independamment de la plateforme d'execution."""
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/"):
        # couvre a la fois '/etc/passwd' et '\\serveur\partage\fichier.docx' (UNC)
        return True
    if _WINDOWS_DRIVE_RE.match(raw):
        return True
    return Path(raw).is_absolute()


def _contains_parent_traversal(raw: str) -> bool:
    normalized = raw.replace("\\", "/")
    return ".." in normalized.split("/")


def resolve_model_path(relative_path: str, settings: Optional[Settings] = None) -> Path:
    """Retourne le chemin reel d'un fichier sous data/modeles, ou leve ModelPathError."""
    settings = settings or get_settings()
    if not relative_path or not relative_path.strip():
        raise ModelPathError("Chemin vide.")
    if _is_absolute_path(relative_path):
        raise ModelPathError("Chemin absolu refuse.")
    if _contains_parent_traversal(relative_path):
        raise ModelPathError("Parcours parent (..) interdit.")
    p = Path(relative_path)
    # l'extension est controlee AVANT l'existence (refus net des chemins de mauvais type)
    if p.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ModelPathError(f"Extension non autorisee : {p.suffix}")
    # les relative_path indexes commencent par 'modeles/...' : on resout depuis data/ et
    # on contraint le resultat sous la racine data/modeles
    base = Path(settings.data_dir).resolve()
    root = settings.modeles_dir.resolve()
    candidate = (base / p).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ModelPathError(f"Chemin hors de data/modeles : {relative_path}") from None
    if not candidate.exists() or not candidate.is_file():
        raise ModelPathError(f"Fichier introuvable sous data/modeles : {relative_path}")
    return candidate
