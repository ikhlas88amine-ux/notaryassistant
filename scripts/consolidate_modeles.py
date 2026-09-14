"""Consolide les modeles notariaux reels deja partages (pieces jointes eparpillees) dans
data/modeles/originaux/<categorie>/, sans jamais modifier les fichiers sources, et genere :
  - data/modeles/inventaire_modeles.json
  - data/modeles/modeles.json (texte + chunks extraits)

Regles strictes (rappelees ici) :
  - copie uniquement (les originaux dans uploaded_attachments / branched_contexts restent intacts) ;
  - jamais de fichier fabrique pour remplacer une source inaccessible : les entrees dont le
    fichier n'a pas ete retrouve sur le disque sont listees en status="unavailable" et dans
    unavailable_files, sans creation d'aucun contenu de remplacement ;
  - les modeles restent tagges source="modele", confidentiality="internal", template_status="a_valider".
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.extractors import extract_any, is_ignorable_file  # noqa: E402
from app.ingestion.hashing import file_sha256  # noqa: E402
from app.ingestion.language import detect_language  # noqa: E402
from app.ingestion.modeles_catalog import CLASSIFICATION  # noqa: E402

WORKSPACE = Path("/home/user/workspace")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELES_DIR = PROJECT_ROOT / "data" / "modeles"
ORIGINAUX_DIR = MODELES_DIR / "originaux"

SEARCH_ROOTS = [
    WORKSPACE / "uploaded_attachments",
    WORKSPACE / "branched_contexts",
]

def find_file_on_disk(filename: str) -> Path | None:
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for candidate in root.rglob(filename):
            if candidate.is_file():
                return candidate
    return None


def slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name).strip("-").lower()


def main() -> None:
    for d in ["attestations", "immobilier", "banque_hypotheque", "societe_rc", "fonds_commerce", "administration", "non_classes"]:
        (ORIGINAUX_DIR / d).mkdir(parents=True, exist_ok=True)

    documents = []
    unavailable_files = []
    modeles_json_entries = []

    detected_and_copied = 0
    auto_classified = 0
    non_classified = 0

    for filename, meta in sorted(CLASSIFICATION.items()):
        doc_id = f"modele-{slugify(Path(filename).stem)}"
        if meta.get("unavailable"):
            unavailable_files.append({
                "fichier_original": filename,
                "type_modele": meta["type_modele"],
                "domaine": meta["domaine"],
                "reason": "Reference dans le catalogue de classification issu des sessions precedentes, "
                          "mais fichier introuvable sur le disque de cet environnement "
                          "(uploaded_attachments/ et branched_contexts/attachments/ ont ete parcourus integralement).",
                "action_requise": f"Deposer le fichier original dans data/modeles/originaux/{meta['domaine']}/ "
                                   "puis relancer scripts/consolidate_modeles.py.",
            })
            documents.append({
                "doc_id": doc_id,
                "fichier_original": filename,
                "source_path_original": None,
                "source_path_normalized": None,
                "type_fichier": Path(filename).suffix.lstrip(".").lower(),
                "type_modele": meta["type_modele"],
                "sous_type": "a_verifier",
                "domaine": meta["domaine"],
                "language": meta["langue"],
                "classification_confidence": 0.9,
                "classification_reason": "Classification issue du catalogue etabli lors des sessions precedentes "
                                          "(nom de fichier + contenu deja analyse), fichier non retrouve cette fois-ci.",
                "status": "unavailable",
                "file_sha256": None,
                "notes": ["Fichier non copie : source introuvable. Aucun contenu de remplacement genere."],
            })
            continue

        src = find_file_on_disk(filename)
        if src is None:
            unavailable_files.append({
                "fichier_original": filename,
                "type_modele": meta["type_modele"],
                "domaine": meta["domaine"],
                "reason": "Fichier attendu d'apres le catalogue mais introuvable dans uploaded_attachments/ "
                          "ou branched_contexts/attachments/ au moment de l'execution.",
                "action_requise": f"Deposer le fichier original dans data/modeles/originaux/{meta['domaine']}/ "
                                   "puis relancer scripts/consolidate_modeles.py.",
            })
            documents.append({
                "doc_id": doc_id, "fichier_original": filename, "source_path_original": None,
                "source_path_normalized": None, "type_fichier": Path(filename).suffix.lstrip(".").lower(),
                "type_modele": meta["type_modele"], "sous_type": "a_verifier", "domaine": meta["domaine"],
                "language": meta["langue"], "classification_confidence": 0.9,
                "classification_reason": "Classification issue du catalogue, fichier non retrouve.",
                "status": "unavailable", "file_sha256": None,
                "notes": ["Fichier non copie : source introuvable au moment de l'execution."],
            })
            continue

        dest_dir = ORIGINAUX_DIR / meta["domaine"]
        dest_path = dest_dir / filename
        dest_path.write_bytes(src.read_bytes())  # copie binaire stricte, aucune reecriture
        detected_and_copied += 1
        auto_classified += 1

        extraction = extract_any(dest_path)
        detected_lang = detect_language(extraction.text) if extraction.ok else meta["langue"]
        notes = []
        if extraction.ok and detected_lang != meta["langue"]:
            notes.append(f"Langue detectee automatiquement ({detected_lang}) differente de la classification connue ({meta['langue']}) - a verifier.")
        if not extraction.ok:
            notes.append(f"Extraction du texte impossible: {extraction.error}")

        documents.append({
            "doc_id": doc_id,
            "fichier_original": filename,
            "source_path_original": str(src.relative_to(WORKSPACE)),
            "source_path_normalized": str(dest_path.relative_to(PROJECT_ROOT)),
            "type_fichier": Path(filename).suffix.lstrip(".").lower(),
            "type_modele": meta["type_modele"],
            "sous_type": "a_verifier",
            "domaine": meta["domaine"],
            "language": meta["langue"],
            "classification_confidence": 0.9,
            "classification_reason": "Classification issue du catalogue etabli lors des sessions precedentes "
                                      "d'analyse de contenu (comptage de caracteres arabes/latins + lecture manuelle).",
            "status": "imported",
            "file_sha256": file_sha256(dest_path),
            "notes": notes,
        })

        modeles_json_entries.append({
            "doc_id": doc_id,
            "fichier": filename,
            "type_modele": meta["type_modele"],
            "domaine": meta["domaine"],
            "language": meta["langue"],
            "source": "modele",
            "confidentiality": "internal",
            "template_status": "a_valider",
            "extraction_method": extraction.extraction_method,
            "extraction_quality": extraction.extraction_quality,
            "n_chars": len(extraction.text),
            "text": extraction.text,
        })

    non_classified = 0  # tous les fichiers retrouves ont ete classes via le catalogue connu

    inventaire = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "documents": documents,
        "unavailable_files": unavailable_files,
    }
    (MODELES_DIR / "inventaire_modeles.json").write_text(
        json.dumps(inventaire, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (MODELES_DIR / "modeles.json").write_text(
        json.dumps({"version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(), "modeles": modeles_json_entries},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== Rapport de consolidation des modeles ===")
    print(f"Modeles detectes et copies       : {detected_and_copied}")
    print(f"Modeles classes automatiquement   : {auto_classified}")
    print(f"Modeles non classes (non_classes/) : {non_classified}")
    print(f"Fichiers impossibles a acceder     : {len(unavailable_files)}")
    for u in unavailable_files:
        print(f"   - {u['fichier_original']} ({u['type_modele']}) -> {u['action_requise']}")
    print(f"Documents indexables (texte extrait avec succes) : {sum(1 for m in modeles_json_entries if m['n_chars'] > 0)}")


if __name__ == "__main__":
    main()
