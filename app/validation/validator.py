"""Orchestration déterministe de la validation métier des dossiers.

Ce module délègue la logique métier à app.services.dossier_validation et écrit les rapports
exclusivement sous output/validation_reports/ afin de préserver l'intégrité du répertoire
`data/` (lecture seule pour les dossiers, chunks et index persistants).
"""
from __future__ import annotations

from pathlib import Path

from app.core.schemas import ValidationReport
from app.services.dossier_validation import validate_and_write_dossier, validate_dossier_path


def validate_dossier(dossier_path: Path) -> ValidationReport:
    return validate_dossier_path(dossier_path)


def validate_and_write(dossier_path: Path) -> ValidationReport:
    return validate_and_write_dossier(dossier_path)


def validate_all_dossiers(dossiers_dir: Path) -> dict[str, ValidationReport]:
    results: dict[str, ValidationReport] = {}
    for dossier_path in sorted(dossiers_dir.iterdir()):
        if dossier_path.is_dir():
            results[dossier_path.name] = validate_and_write(dossier_path)
    return results
