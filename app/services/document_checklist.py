"""Checklist documentaire metier complete, adaptee au type et a la variante du dossier.

Objectif (cf. specification metier) : donner au notaire une vue claire, en francais, sans
JSON ni details techniques (pas de chunk, vecteur, Qdrant, hash, chemin Windows, nom de
variable Python ou score technique), des pieces :
- presentes dans le dossier ;
- attendues mais non detectees ("a ajouter selon la checklist de l'etude") ;
- a verifier manuellement par le notaire ;
- non applicables (condition non remplie) ;
- ou pour lesquelles aucune checklist n'est configuree.

Contrainte juridique : la presence d'un fichier ne vaut JAMAIS validation juridique. Ce
module ne dit jamais qu'un dossier est complet, regulier, valide ou pret a signer.

Determinisme : la detection est basee uniquement sur les fichiers reellement presents dans
le dossier et, si la piece de checklist l'autorise (`auto_detection: filename_or_content`),
sur le texte deja extrait des documents. Le LLM (Ollama) n'est jamais appele ici. En cas de
doute, le statut retenu est toujours "a verifier par le notaire", jamais "presente".

Lecture seule : ce module ne modifie, ne cree ni ne supprime aucun fichier de dossier, de
modele ou de loi, et n'ecrit jamais dans les chunks/index/Qdrant.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

import yaml

from app.core.config import Settings, get_settings
from app.ingestion.extractors import extract_any, is_ignorable_file

# --------------------------------------------------------------------------- statuts UI
STATUT_PRESENTE = "presente"
STATUT_A_AJOUTER = "a_ajouter"
STATUT_A_VERIFIER = "a_verifier"
STATUT_NON_APPLICABLE = "non_applicable"
STATUT_NON_CONFIGUREE = "checklist_non_configuree"

STATUT_LABELS = {
    STATUT_PRESENTE: "Presente dans le dossier",
    STATUT_A_AJOUTER: "A ajouter selon la checklist de l'etude",
    STATUT_A_VERIFIER: "A verifier par le notaire",
    STATUT_NON_APPLICABLE: "Non applicable",
    STATUT_NON_CONFIGUREE: "Checklist non configuree",
}
STATUT_ICONES = {
    STATUT_PRESENTE: "✅",
    STATUT_A_AJOUTER: "⏳",
    STATUT_A_VERIFIER: "⚠️",
    STATUT_NON_APPLICABLE: "➖",
    STATUT_NON_CONFIGUREE: "ℹ️",
}

RAPPEL_JURIDIQUE = "La presence d'un fichier ne vaut pas validation juridique."

SUPPORTED_SUFFIXES = (".docx", ".doc", ".pdf", ".txt")


# --------------------------------------------------------------------------- utilitaires
def _normalize(text: str) -> str:
    """Normalisation deterministe : minuscule, sans accents, separateurs -> underscore."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")


def _alias_matches_filename(alias: str, filename_normalized: str) -> bool:
    """Correspondance stricte par jeton (evite qu'un alias generique comme 'cin' matche
    n'importe quel fichier contenant 'cin' : 'cin_vendeur' ne doit pas matcher 'cin_acquereur').
    """
    alias_n = _normalize(alias)
    if not alias_n:
        return False
    pattern = r"(?:^|_)" + re.escape(alias_n) + r"(?:_|$)"
    return re.search(pattern, filename_normalized) is not None


def _flatten_strings(value, out: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, (int, float, bool)):
        out.append(str(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            out.append(str(k))
            _flatten_strings(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _flatten_strings(v, out)


def _flatten_keys(value, out: list[str]) -> None:
    """Ne collecte que les CLES (pas les valeurs) d'un dict imbrique, recursivement."""
    if isinstance(value, dict):
        for k, v in value.items():
            out.append(_normalize(str(k)))
            _flatten_keys(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _flatten_keys(v, out)


# --------------------------------------------------------------------------- config
_CONFIG_CACHE: dict[str, tuple[float, dict]] = {}


def load_config(settings: Optional[Settings] = None) -> Optional[dict]:
    """Charge le fichier de configuration versionne (YAML), avec cache invalide sur mtime."""
    settings = settings or get_settings()
    path: Path = settings.document_checklists_path
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = _CONFIG_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("checklists"), dict):
        return None
    _CONFIG_CACHE[str(path)] = (mtime, data)
    return data


def _find_type_entry(config: dict, type_dossier: str) -> Optional[tuple[str, dict]]:
    t = (type_dossier or "").strip().upper()
    checklists = config.get("checklists", {})
    if t in checklists:
        return t, checklists[t]
    for key, entry in checklists.items():
        aliases = entry.get("aliases_types") or []
        if t in [a.upper() for a in aliases]:
            return key, entry
    return None


def resolve_checklist(type_dossier: str, variante: Optional[str], settings: Optional[Settings] = None,
                       _depth: int = 0) -> Optional[dict]:
    """Resout la checklist applicable pour (type_dossier, variante).

    Gere :
    - le type direct (et ses alias_types, ex. SARL -> CREATION_SOCIETE) ;
    - les variantes en mode "extend" (items de base + items supplementaires) ;
    - les variantes en mode "alias" (redirection complete vers une autre checklist,
      ex. VENTE/vefa -> VEFA, HYPOTHEQUE/mainlevee -> MAINLEVEE).

    Retourne None si aucune checklist n'est configuree pour ce type/variante (-> le notaire
    doit voir "Checklist non configuree", jamais une conclusion inventee).
    """
    if _depth > 3:  # garde-fou anti-boucle sur des alias mal configures
        return None
    config = load_config(settings)
    if config is None:
        return None
    found = _find_type_entry(config, type_dossier)
    if not found:
        return None
    type_key, entry = found

    items = list(entry.get("items", []))
    manual_checks = list(entry.get("manual_checks", []))
    variants = entry.get("variants", {}) or {}
    v = _normalize(variante) if variante else ""

    variant_entry = None
    if v:
        for vkey, vval in variants.items():
            if _normalize(vkey) == v:
                variant_entry = vval
                break

    if variant_entry:
        mode = variant_entry.get("mode", "extend")
        if mode == "alias":
            target = variant_entry.get("target")
            if target:
                return resolve_checklist(target, None, settings, _depth=_depth + 1)
        elif mode == "extend":
            items = items + list(variant_entry.get("extra_items", []))
            manual_checks = manual_checks + list(variant_entry.get("manual_checks", []))

    return {
        "type_key": type_key,
        "label": entry.get("label", type_key),
        "variante": variante,
        "items": items,
        "manual_checks": manual_checks,
    }


# --------------------------------------------------------------------------- conditions
def _get_donnees(master: dict) -> dict:
    d = master.get("donnees")
    return d if isinstance(d, dict) else {}


def _condition_representation_detectee(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    if not donnees and not all_text:
        return None
    keys: list[str] = []
    _flatten_keys(donnees, keys)
    if any(k in ("represente_par", "mandataire", "reference_procuration") for k in keys):
        return True
    if "procuration" in all_text or "represente par" in all_text or "mandataire" in all_text:
        return True
    if donnees:
        return False
    return None


def _condition_copropriete_detectee(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    strings: list[str] = []
    _flatten_strings(donnees, strings)
    joined = _normalize(" ".join(strings))
    if "copropriete" in joined or "copropriete" in _normalize(all_text) or "syndic" in _normalize(all_text):
        return True
    if donnees:
        return False
    return None


def _condition_charges_mentionnees(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    strings: list[str] = []
    _flatten_strings(donnees, strings)
    joined = _normalize(" ".join(strings))
    at = _normalize(all_text)
    if any(kw in joined or kw in at for kw in ("hypotheque", "charge", "privilege", "nantissement")):
        return True
    if donnees:
        return False
    return None


def _condition_lien_familial_invoque(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    keys: list[str] = []
    _flatten_keys(donnees, keys)
    if "lien" in keys:
        return True
    at = _normalize(all_text)
    if any(kw in at for kw in ("fils", "fille", "epoux", "epouse", "petit_fils", "petite_fille")):
        return True
    if donnees:
        return False
    return None


def _condition_heritier_represente(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    heritiers = donnees.get("heritiers") if isinstance(donnees, dict) else None
    if isinstance(heritiers, list):
        for h in heritiers:
            if isinstance(h, dict) and ("represente_par" in h or "mandataire" in h):
                return True
        return False
    if "represente" in _normalize(all_text) or "mandataire" in _normalize(all_text):
        return True
    return None


def _condition_urbanisme_necessaire(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    strings: list[str] = []
    _flatten_strings(donnees, strings)
    joined = _normalize(" ".join(strings))
    at = _normalize(all_text)
    if any(kw in joined or kw in at for kw in ("construire", "construction", "permis")):
        return True
    return None  # ne jamais conclure "non applicable" par defaut : a verifier si etabli inconnu


def _condition_achevement_constate(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    keys: list[str] = []
    _flatten_keys(donnees, keys)
    if any(k in ("date_livraison", "livraison_effectuee", "date_reception") for k in keys):
        return True
    at = _normalize(all_text)
    if "reception" in at or "livraison" in at:
        return True
    if donnees:
        return False  # dossier VEFA connu, aucune trace d'achevement -> non applicable
    return None


def _condition_siege_renseigne(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    keys: list[str] = []
    _flatten_keys(donnees, keys)
    if any(k in ("siege_social", "adresse_siege", "siege") for k in keys):
        return True
    if donnees:
        return False
    return None


def _condition_origine_etrangere(master: dict, all_text: str) -> Optional[bool]:
    donnees = _get_donnees(master)
    strings: list[str] = []
    _flatten_strings(donnees, strings)
    joined = _normalize(" ".join(strings))
    at = _normalize(all_text)
    if any(kw in joined or kw in at for kw in ("etranger", "consulat", "ambassade", "apostille")):
        return True
    return None


CONDITIONS = {
    "representation_detectee": _condition_representation_detectee,
    "copropriete_detectee": _condition_copropriete_detectee,
    "charges_mentionnees": _condition_charges_mentionnees,
    "lien_familial_invoque": _condition_lien_familial_invoque,
    "heritier_represente": _condition_heritier_represente,
    "urbanisme_necessaire": _condition_urbanisme_necessaire,
    "achevement_constate": _condition_achevement_constate,
    "siege_renseigne": _condition_siege_renseigne,
    "origine_etrangere": _condition_origine_etrangere,
}


# --------------------------------------------------------------------------- detection
def _candidate_files(dossier_path: Path) -> list[Path]:
    return sorted(
        p for p in dossier_path.iterdir()
        if p.is_file() and not is_ignorable_file(p) and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _find_candidates(item: dict, files: list[Path]) -> list[Path]:
    aliases = item.get("file_aliases") or []
    if not aliases:
        return []
    out = []
    for f in files:
        fn = _normalize(f.stem)
        if any(_alias_matches_filename(a, fn) for a in aliases):
            out.append(f)
    return out


def _evaluate_item(item: dict, master: dict, files: list[Path], contents: dict[str, str],
                    all_text: str) -> dict:
    item_id = item.get("id", "")
    label = item.get("label", item_id)
    conditional = item.get("conditional")
    auto_detection = item.get("auto_detection", "filename_only")
    manual_verification_required = bool(item.get("manual_verification_required", True))
    help_text = item.get("help_text", "")
    condition_description = item.get("condition_description", "")

    # 1) Condition d'applicabilite
    condition_result: Optional[bool] = True
    if conditional:
        fn = CONDITIONS.get(conditional)
        condition_result = fn(master, all_text) if fn else None

    if condition_result is False:
        return {
            "id": item_id, "label": label, "statut": STATUT_NON_APPLICABLE,
            "fichiers_detectes": [], "explication": condition_description or "Condition non remplie pour ce dossier.",
            "rappel": RAPPEL_JURIDIQUE, "help_text": help_text,
        }

    # 2) Detection deterministe (fichiers, puis contenu si autorise)
    candidates = _find_candidates(item, files)
    condition_incertaine = conditional is not None and condition_result is None

    if auto_detection == "manual" and not candidates:
        # Jamais "a ajouter" pour une piece a verification purement manuelle : on ne peut pas
        # affirmer qu'elle est requise ou absente de maniere deterministe.
        explication = help_text or "Piece a verifier manuellement : aucune detection automatique fiable n'est possible."
        return {
            "id": item_id, "label": label, "statut": STATUT_A_VERIFIER,
            "fichiers_detectes": [], "explication": explication,
            "rappel": RAPPEL_JURIDIQUE, "help_text": help_text,
        }

    if candidates:
        content_markers = item.get("content_markers") or []
        if auto_detection == "filename_or_content" and content_markers:
            hits = []
            for f in candidates:
                txt = _normalize(contents.get(f.name, ""))
                if any(_normalize(m) in txt for m in content_markers):
                    hits.append(f.name)
            if not hits:
                # Nom de fichier plausible mais contenu non confirmant : en cas de doute, a verifier.
                return {
                    "id": item_id, "label": label, "statut": STATUT_A_VERIFIER,
                    "fichiers_detectes": [f.name for f in candidates],
                    "explication": "Fichier correspondant au nom attendu, mais le contenu extrait ne confirme pas explicitement l'element : verification par le notaire requise.",
                    "rappel": RAPPEL_JURIDIQUE, "help_text": help_text,
                }
        statut = STATUT_A_VERIFIER if condition_incertaine else STATUT_PRESENTE
        explication = (
            "Fichier correspondant detecte dans le dossier."
            if statut == STATUT_PRESENTE
            else "Fichier correspondant detecte, mais l'applicabilite de cette piece n'a pas pu etre etablie automatiquement : a verifier par le notaire."
        )
        if manual_verification_required and statut == STATUT_PRESENTE:
            explication += " La validite, l'actualite, la signature et la conformite restent a verifier par le notaire."
        return {
            "id": item_id, "label": label, "statut": statut,
            "fichiers_detectes": [f.name for f in candidates],
            "explication": explication, "rappel": RAPPEL_JURIDIQUE, "help_text": help_text,
        }

    # 3) Aucun fichier candidat
    if condition_incertaine:
        return {
            "id": item_id, "label": label, "statut": STATUT_A_VERIFIER,
            "fichiers_detectes": [],
            "explication": (condition_description or "Applicabilite incertaine") + " Aucun document correspondant detecte : a verifier par le notaire.",
            "rappel": RAPPEL_JURIDIQUE, "help_text": help_text,
        }
    return {
        "id": item_id, "label": label, "statut": STATUT_A_AJOUTER,
        "fichiers_detectes": [],
        "explication": "Aucun document correspondant a cette piece n'a ete detecte dans le dossier.",
        "rappel": RAPPEL_JURIDIQUE, "help_text": help_text,
    }


# --------------------------------------------------------------------------- API principale
def evaluate_document_checklist(dossier_id: str, settings: Optional[Settings] = None) -> dict:
    """Evalue la checklist documentaire metier complete pour un dossier (deterministe,
    lecture seule, sans appel au LLM).
    """
    settings = settings or get_settings()
    dossier_path: Path = settings.dossiers_dir / dossier_id
    if not dossier_path.exists():
        return {
            "dossier_id": dossier_id, "evaluable": False, "statut_global": STATUT_NON_CONFIGUREE,
            "message": "Dossier introuvable.", "items": [], "synthese": {}, "rappel": RAPPEL_JURIDIQUE,
        }

    master_path = dossier_path / "dossier_master.json"
    master: dict = {}
    type_dossier = ""
    variante = None
    if master_path.exists():
        try:
            master = json.loads(master_path.read_text(encoding="utf-8"))
            type_dossier = master.get("type_dossier", "") or ""
            variante = master.get("variante")
        except (json.JSONDecodeError, OSError):
            master = {}

    checklist = resolve_checklist(type_dossier, variante, settings)
    if checklist is None:
        return {
            "dossier_id": dossier_id, "evaluable": False, "statut_global": STATUT_NON_CONFIGUREE,
            "type_dossier": type_dossier, "variante": variante,
            "message": (
                "Aucune checklist documentaire n'est configuree pour ce type de dossier"
                + (f" (\"{type_dossier}\"" + (f" / variante \"{variante}\"" if variante else "") + ")" if type_dossier else "")
                + ". Aucune piece manquante ne peut etre determinee automatiquement."
            ),
            "items": [], "synthese": {}, "rappel": RAPPEL_JURIDIQUE,
        }

    files = _candidate_files(dossier_path) if dossier_path.exists() else []
    contents: dict[str, str] = {}
    for f in files:
        try:
            r = extract_any(f)
            if r.ok:
                contents[f.name] = r.text or ""
        except Exception:  # noqa: BLE001 - une extraction defaillante ne doit jamais casser la checklist
            contents[f.name] = ""
    all_text = _normalize(" ".join(contents.values()))

    items_out = [_evaluate_item(item, master, files, contents, all_text) for item in checklist["items"]]

    synthese = {
        STATUT_PRESENTE: sum(1 for i in items_out if i["statut"] == STATUT_PRESENTE),
        STATUT_A_AJOUTER: sum(1 for i in items_out if i["statut"] == STATUT_A_AJOUTER),
        STATUT_A_VERIFIER: sum(1 for i in items_out if i["statut"] == STATUT_A_VERIFIER),
        STATUT_NON_APPLICABLE: sum(1 for i in items_out if i["statut"] == STATUT_NON_APPLICABLE),
    }
    applicables = len(items_out) - synthese[STATUT_NON_APPLICABLE]

    return {
        "dossier_id": dossier_id,
        "evaluable": True,
        "statut_global": "ok",
        "type_dossier": type_dossier,
        "variante": variante,
        "checklist_label": checklist.get("label"),
        "items": items_out,
        "synthese": synthese,
        "nb_applicables": applicables,
        "manual_checks": checklist.get("manual_checks", []),
        "message": "",
        "rappel": RAPPEL_JURIDIQUE,
    }
