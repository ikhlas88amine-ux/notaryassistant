"""Fixtures partagees : chemins reels vers les corpus (jamais de contenu fabrique)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def dossiers_dir(settings):
    return settings.dossiers_dir


@pytest.fixture(scope="session")
def modeles_dir(settings):
    return settings.modeles_dir


@pytest.fixture(scope="session")
def lois_dir(settings):
    return settings.lois_dir


@pytest.fixture(scope="session")
def sample_dossier_id() -> str:
    return "9-2024-191-HYPOTHEQUE-AMRANI"


@pytest.fixture(scope="session")
def clean_dossier_ids() -> list[str]:
    """Dossiers reputes coherents (hors AMBIGU) pour tester la validation positive."""
    return [
        "9-2024-191-HYPOTHEQUE-AMRANI",
        "10-2024-542-HYPOTHEQUE-SQALLI",
        "17-2025-967-VENTE-ALAOUI",
    ]


@pytest.fixture(scope="session")
def ambigu_dossier_ids() -> list[str]:
    """Les deux dossiers intentionnellement incoherents (anomalies volontaires)."""
    return ["1-2024-843-AMBIGU", "15-2024-824-AMBIGU"]
