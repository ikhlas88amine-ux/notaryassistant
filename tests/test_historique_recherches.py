"""Tests de l'historique de session des recherches (Modèles internes / Recherche juridique).

Vérifie : séparation stricte entre les deux onglets, relance, effacement, limite à 20
entrées, libellés métier, et absence totale d'écriture dans les documents, Qdrant ou chunks.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.ui.history import (
    HISTORY_LIMIT,
    add_entry,
    clear_entries,
    now_label,
    relance_question,
    resultat_label,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_limite_a_20_entrees():
    entries: list[dict] = []
    for i in range(25):
        entries = add_entry(entries, f"Question numéro {i}", nb_resultats=i % 3)
    assert len(entries) == HISTORY_LIMIT == 20
    assert entries[0]["question"] == "Question numéro 24"


def test_entrees_dedupliquees_par_question():
    entries = add_entry([], "Question A", 2)
    entries = add_entry(entries, "Question B", 3)
    entries = add_entry(entries, "Question A", 5)
    assert len(entries) == 2
    assert entries[0]["question"] == "Question A"
    assert entries[0]["nb_resultats"] == 5


def test_effacer_historique():
    entries = add_entry([], "Question A", 1)
    assert clear_entries(entries) == []


def test_relancer_une_recherche():
    entries = add_entry([], "Clause de consignation du prix de vente", 1)
    assert relance_question(entries[0]) == "Clause de consignation du prix de vente"


def test_libelles_metier_du_nombre_de_resultats():
    assert resultat_label(0) == "Aucun résultat exploitable"
    assert resultat_label(1) == "1 résultat pertinent"
    assert resultat_label(4) == "4 résultats pertinents"


def test_horodatage_lisible():
    assert now_label().startswith("Aujourd'hui")


def test_historique_juridique_strictement_separe_de_modeles():
    """Les deux onglets utilisent des clés de session distinctes (aucun mélange)."""
    page_juridique = (PROJECT_ROOT / "app" / "ui" / "pages" / "4_Recherche_juridique.py").read_text(encoding="utf-8")
    page_modeles = (PROJECT_ROOT / "app" / "ui" / "pages" / "5_Modeles_internes.py").read_text(encoding="utf-8")
    assert '"historique_juridique"' in page_juridique
    assert '"historique_modeles"' in page_modeles
    assert '"historique_juridique"' not in page_modeles
    assert '"historique_modeles"' not in page_juridique


def test_historique_aucune_ecriture_dans_documents_qdrant_chunks():
    """Le module d'historique est purement en session : aucune écriture, aucun chemin."""
    source = (PROJECT_ROOT / "app" / "ui" / "history.py").read_text(encoding="utf-8")
    for motif in (r"\bopen\s*\(", r"write_text", r"write_bytes", r"Path\(", r"sqlite", r"qdrant", r"jsonl"):
        assert not re.search(motif, source), f"écriture persistante détectée dans l'historique : {motif}"
