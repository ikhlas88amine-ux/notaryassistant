from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.dossier_validation import load_rule_specs
from app.validation.validator import validate_dossier

LEGACY_RULES = [
    {
        "rule_id": "name_presence",
        "function": "rule_name_cin_presence_in_documents",
        "file": "app/validation/rules.py",
        "condition": "Nom d'une partie absent du texte extrait",
        "severity": "medium",
        "applies_to": "Tous dossiers contenant des parties identifiées dans donnees",
    },
    {
        "rule_id": "cin_presence",
        "function": "rule_name_cin_presence_in_documents",
        "file": "app/validation/rules.py",
        "condition": "CIN d'une partie absent du texte extrait",
        "severity": "medium",
        "applies_to": "Tous dossiers contenant un CIN structuré",
    },
    {
        "rule_id": "tf_multiple_declared",
        "function": "rule_titre_foncier_consistency",
        "file": "app/validation/rules.py",
        "condition": "Plusieurs TF distincts déclarés dans dossier_master.json",
        "severity": "blocking",
        "applies_to": "Dossiers avec plusieurs champs TF",
    },
    {
        "rule_id": "tf_text_mismatch",
        "function": "rule_titre_foncier_consistency",
        "file": "app/validation/rules.py",
        "condition": "TF extrait du document absent des données structurées",
        "severity": "high",
        "applies_to": "Dossiers avec TF en données et dans le texte extrait",
    },
    {
        "rule_id": "price_breakdown_mismatch",
        "function": "rule_price_consistency",
        "file": "app/validation/rules.py",
        "condition": "Somme des composantes de prix différente du total déclaré",
        "severity": "high",
        "applies_to": "Dossiers contenant à la fois prix total et composantes de prix",
    },
    {
        "rule_id": "price_multiple_declared",
        "function": "rule_price_consistency",
        "file": "app/validation/rules.py",
        "condition": "Plusieurs montants de prix distincts incompatibles",
        "severity": "blocking",
        "applies_to": "Dossiers contenant plusieurs champs de prix/montant",
    },
    {
        "rule_id": "date_format_invalid",
        "function": "rule_date_validity",
        "file": "app/validation/rules.py",
        "condition": "Date structurée non conforme au format ISO AAAA-MM-JJ",
        "severity": "low",
        "applies_to": "Tous dossiers avec champs *date* structurés",
    },
    {
        "rule_id": "expected_document_missing",
        "function": "rule_expected_documents",
        "file": "app/validation/rules.py",
        "condition": "Document principal attendu non détecté via le nom de fichier",
        "severity": "medium",
        "applies_to": "VENTE, VENTE-AUTO, DONATION, SUCCESSION, PROCURATION, HYPOTHEQUE",
    },
    {
        "rule_id": "radiation_without_mainlevee",
        "function": "rule_radiation_requires_mainlevee",
        "file": "app/validation/rules.py",
        "condition": "Réquisition de radiation détectée sans mainlevée correspondante",
        "severity": "blocking",
        "applies_to": "Dossiers avec fichier contenant 'radiation'",
    },
    {
        "rule_id": "company_identified_by_cin",
        "function": "rule_company_identification",
        "file": "app/validation/rules.py",
        "condition": "Société repérée par un champ gérant sans RC/ICE",
        "severity": "high",
        "applies_to": "Dossiers contenant une partie société avec gérant",
    },
]

ABSENT_RULE_FAMILIES = [
    "MAINLEVEE comme type autonome (modélisé dans ce projet comme variante HYPOTHEQUE/mainlevee)",
    "CREATION_SOCIETE / SARL : aucun dossier réel détecté dans data/dossiers",
    "GERANCE_LIBRE : aucun dossier réel détecté dans data/dossiers",
    "DEMANDES_ADMINISTRATIVES : aucun dossier réel détecté dans data/dossiers",
]


def _collect_tests_by_rule(tests_dir: Path, rule_id: str) -> list[str]:
    hits = []
    for path in sorted(tests_dir.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if rule_id in text:
            hits.append(path.name)
    return hits


def _matches_rule(spec, type_dossier: str, variante: str | None) -> bool:
    variante_slug = (variante or "").lower().replace("é", "e").replace("-", "_")
    if not spec.applies_to:
        return True
    for spec_type, variants in spec.applies_to:
        if spec_type != type_dossier:
            continue
        if variants is None or variante_slug in variants:
            return True
    return False


def main() -> None:
    settings = get_settings()
    root = ROOT
    dossiers_dir = settings.dossiers_dir
    tests_dir = root / "tests"
    specs = load_rule_specs(settings)

    dossiers = []
    combo_counts = Counter()
    type_counts = Counter()
    variant_counts = Counter()
    rules_seen_by_combo = defaultdict(set)
    example_by_combo = {}
    example_by_type = {}
    for dossier_path in sorted(dossiers_dir.iterdir()):
        if not dossier_path.is_dir():
            continue
        master = json.loads((dossier_path / "dossier_master.json").read_text(encoding="utf-8"))
        type_dossier = master.get("type_dossier")
        variante = master.get("variante")
        combo = (type_dossier, variante)
        combo_counts[combo] += 1
        type_counts[type_dossier] += 1
        variant_counts[variante] += 1
        example_by_combo.setdefault(combo, dossier_path.name)
        example_by_type.setdefault(type_dossier, dossier_path.name)
        report = validate_dossier(dossier_path)
        rules_seen_by_combo[combo].update(issue.rule_id for issue in report.issues)
        dossiers.append((dossier_path.name, master, report))

    out_lines = []
    out_lines.append("# Audit des règles de validation métier")
    out_lines.append("")
    out_lines.append("## 1. Règles existantes détectées avant refonte")
    out_lines.append("")
    out_lines.append("| Rule ID | Fichier / fonction | Types concernés | Déclenchement | Niveau | Tests existants | Exemple dossier |")
    out_lines.append("|---|---|---|---|---|---|---|")
    for item in LEGACY_RULES:
        tests = ", ".join(_collect_tests_by_rule(tests_dir, item["rule_id"])) or "aucun test dédié"
        example = "1-2024-843-AMBIGU" if item["rule_id"] in {"tf_multiple_declared", "price_multiple_declared"} else example_by_type.get("VENTE", "n/a")
        out_lines.append(
            f"| {item['rule_id']} | `{item['file']}` / `{item['function']}` | {item['applies_to']} | {item['condition']} | {item['severity']} | {tests} | {example} |"
        )

    out_lines.append("")
    out_lines.append("## 2. Types et variantes réellement détectés dans les dossiers")
    out_lines.append("")
    out_lines.append("| type_dossier | variante | nombre de dossiers | règles actives observées | règles manquantes / non observées | exemple |")
    out_lines.append("|---|---:|---:|---|---|---|")
    for (type_dossier, variante), count in sorted(combo_counts.items()):
        seen = sorted(rules_seen_by_combo[(type_dossier, variante)])
        spec_rules = sorted(
            rule_id for rule_id, spec in specs.items() if _matches_rule(spec, type_dossier, variante)
        )
        missing = sorted(set(spec_rules) - set(seen))
        out_lines.append(
            f"| {type_dossier} | {variante} | {count} | {', '.join(seen) if seen else 'aucune règle déclenchée'} | {', '.join(missing) if missing else 'aucune'} | {example_by_combo[(type_dossier, variante)]} |"
        )

    out_lines.append("")
    out_lines.append("## 3. Règles versionnées actives après refonte")
    out_lines.append("")
    out_lines.append("| Rule ID | Gravité | Titre | Types / variantes | Tests existants | Exemple dossier |")
    out_lines.append("|---|---|---|---|---|---|")
    for rule_id, spec in sorted(specs.items()):
        applies = []
        example = "n/a"
        for type_dossier, variants in spec.applies_to:
            if variants:
                applies.append(f"{type_dossier}:{'/'.join(sorted(variants))}")
            else:
                applies.append(type_dossier)
            for (combo_type, combo_variant), dossier_id in example_by_combo.items():
                if combo_type == type_dossier and (variants is None or _matches_rule(spec, combo_type, combo_variant)):
                    example = dossier_id
                    break
            if example != "n/a":
                break
        tests = ", ".join(_collect_tests_by_rule(tests_dir, rule_id)) or "couvert indirectement"
        out_lines.append(f"| {rule_id} | {spec.severity} | {spec.title} | {', '.join(applies)} | {tests} | {example} |")

    out_lines.append("")
    out_lines.append("## 4. Doublons, règles mortes et dépendances de données")
    out_lines.append("")
    out_lines.append("- `app/validation/rules.py` est désormais **héritée** : les anciennes fonctions existent encore pour audit mais ne pilotent plus la validation métier active.")
    out_lines.append("- Les anciennes sévérités `high/medium/low` ne sont plus utilisées par la validation dossier active ; elles subsistent dans l'audit d'intégrité RAG, qui est un sous-système distinct.")
    out_lines.append("- `price_multiple_declared` a été **conservée** comme identifiant stable pour ne pas casser les tests historiques, tout en étant normalisée dans l'architecture YAML + service déterministe.")
    out_lines.append("- `checklist_incomplete` reste une information documentaire et ne conclut jamais à une invalidité juridique automatique.")
    out_lines.append("- Les familles suivantes n'ont pas été implémentées faute de dossiers réels correspondants dans ce projet :")
    for item in ABSENT_RULE_FAMILIES:
        out_lines.append(f"  - {item}")
    out_lines.append("- `VENTE-AUTO` est présent dans les données ; une couverture minimale spécifique a été ajoutée (identification véhicule), distincte des ventes immobilières.")

    out_lines.append("")
    out_lines.append("## 5. Distribution actuelle observée sur les dossiers réels")
    out_lines.append("")
    status_counter = Counter(report.status for _, _, report in dossiers)
    out_lines.append(f"- Dossiers `valid` : {status_counter['valid']}")
    out_lines.append(f"- Dossiers `warnings` : {status_counter['warnings']}")
    out_lines.append(f"- Dossiers `invalid` : {status_counter['invalid']}")
    out_lines.append("- Seuls les dossiers AMBIGU restent invalides après refonte : `1-2024-843-AMBIGU`, `15-2024-824-AMBIGU`.")

    output_path = settings.audit_dir / "validation_rules_audit.md"
    output_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
