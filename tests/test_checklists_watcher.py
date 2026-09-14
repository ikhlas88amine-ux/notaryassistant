"""Tests des checklists des pieces (cahier des charges §7) et du watcher d'import (§8).

Tout est deterministe et local (aucun Ollama). Le watcher deplace le dossier, valide
(uniquement par code), indexe le seul dossier (sans Ollama : JSONL seul) et journalise.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.config import Settings
from app.services import checklists, watcher


def _tmp_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path / "data"),
        output_dir=str(tmp_path / "output"),
        qdrant_mode="server",
        qdrant_url="http://127.0.0.1:1",
        ollama_base_url="http://127.0.0.1:1",
    )


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------
def test_checklist_absente_pour_type_inconnu(tmp_path):
    st = _tmp_settings(tmp_path)
    assert checklists.load_checklist("TYPE_INCONNU", None, st) is None


def test_checklist_applicable_sur_vrai_corpus():
    result = checklists.evaluate_dossier("21-2026-549-VENTE-SMIRI")
    assert result["evaluable"] is True
    assert result["checklist"] == "vente_tripartite_bancaire.json"
    ids = {i["id"] for i in result["items"]}
    assert "ACTE_VENTE" in ids and "ENGAGEMENT_HYPOTHECAIRE" in ids
    acte = next(i for i in result["items"] if i["id"] == "ACTE_VENTE")
    assert acte["statut"] == "present_confirmed"  # nom + contenu confirment
    assert acte["fichier_candidat"] == "01_acte_de_vente.docx"


def test_checklist_sqalli_caution_mentionnee():
    """Le cautionnement est mentionne dans l'engagement : present_to_verify, pas invente."""
    result = checklists.evaluate_dossier("10-2024-542-HYPOTHEQUE-SQALLI")
    assert result["evaluable"] is True
    caution = next(i for i in result["items"] if i["id"] == "CAUTIONNEMENT")
    assert caution["statut"] == "present_to_verify"
    assert "01_engagement_hypothecaire.docx" in caution["raison"]


def test_checklist_item_manquant_smiri():
    result = checklists.evaluate_dossier("21-2026-549-VENTE-SMIRI")
    eng = next(i for i in result["items"] if i["id"] == "ENGAGEMENT_HYPOTHECAIRE")
    assert eng["statut"] in ("missing", "present_to_verify")  # pas de document dedie -> a verifier/manquant


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------
def _make_dossier(inbox: Path, dossier_id: str, master: dict, docx_source: Path) -> Path:
    d = inbox / dossier_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "dossier_master.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(str(docx_source), str(d / "01_acte_de_vente.docx"))
    return d


def test_watcher_import_valide(tmp_path):
    settings = _tmp_settings(tmp_path)
    docx = Path("data/dossiers/19-2024-613-VENTE-ELFASSI/01_acte_de_vente.docx")
    master = {"dossier_id": "N-2026-001-VENTE-TEST", "type_dossier": "VENTE", "variante": "simple", "annee": 2026}
    d = _make_dossier(settings.inbox_dir, master["dossier_id"], master, docx)
    (d / ".ready").write_text("ok", encoding="utf-8")

    results = watcher.process_inbox_once(settings)
    assert results and results[0]["status"] == "imported"
    target = settings.dossiers_dir / master["dossier_id"]
    assert target.exists()
    assert (target / ".done").exists()
    report = json.loads((settings.imports_dir / f"{master['dossier_id']}.json").read_text(encoding="utf-8"))
    assert report["status"] == "imported"
    assert report["validation_status"] in ("valid", "warnings", "invalid")


def test_watcher_json_invalide_vers_rejected(tmp_path):
    settings = _tmp_settings(tmp_path)
    d = settings.inbox_dir / "BAD-JSON"
    d.mkdir(parents=True, exist_ok=True)
    (d / "dossier_master.json").write_text("{pas du json", encoding="utf-8")
    (d / "01_doc.docx").write_bytes(b"faux contenu")
    (d / ".ready").write_text("ok", encoding="utf-8")

    results = watcher.process_inbox_once(settings)
    assert results and results[0]["status"] == "failed"
    rejected = [p for p in settings.rejected_dir.glob("BAD-JSON*") if p.is_dir()]
    assert rejected, "le dossier techniquement invalide doit etre deplace vers rejected_dossiers"


def test_watcher_dossier_duplique_refuse(tmp_path):
    settings = _tmp_settings(tmp_path)
    existing = settings.dossiers_dir / "19-2024-613-VENTE-ELFASSI"
    shutil.copytree("data/dossiers/19-2024-613-VENTE-ELFASSI", str(existing))
    docx = existing / "01_acte_de_vente.docx"

    inbox_d = settings.inbox_dir / "19-2024-613-VENTE-ELFASSI"
    inbox_d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(docx), str(inbox_d / "01_acte_de_vente.docx"))
    master = json.loads((existing / "dossier_master.json").read_text(encoding="utf-8"))
    (inbox_d / "dossier_master.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    (inbox_d / ".ready").write_text("ok", encoding="utf-8")

    results = watcher.process_inbox_once(settings)
    assert results and results[0]["status"] == "failed"
    assert "duplique" in results[0]["reason"]


def test_watcher_warning_metier_ne_bloque_pas(tmp_path):
    """Un warning metier (ex: societe identifiee sans RC) ne bloque pas l'import technique."""
    settings = _tmp_settings(tmp_path)
    docx = Path("data/dossiers/19-2024-613-VENTE-ELFASSI/01_acte_de_vente.docx")
    master = {
        "dossier_id": "W-2026-002-VENTE-WARN", "type_dossier": "VENTE", "variante": "simple", "annee": 2026,
        "donnees": {"vendeur": {"nom_fr": "SARL EXEMPLE", "gerant": "Karim ALAOUI"}, "acquereur": {"nom_fr": "Sara BENJELLOUN", "cin": "K123456"}},
    }
    d = _make_dossier(settings.inbox_dir, master["dossier_id"], master, docx)
    (d / ".ready").write_text("ok", encoding="utf-8")

    results = watcher.process_inbox_once(settings)
    assert results and results[0]["status"] == "imported"
    report = json.loads((settings.imports_dir / f"{master['dossier_id']}.json").read_text(encoding="utf-8"))
    assert report["validation_status"] == "warnings"


def test_watcher_traitement_unique(tmp_path):
    settings = _tmp_settings(tmp_path)
    docx = Path("data/dossiers/19-2024-613-VENTE-ELFASSI/01_acte_de_vente.docx")
    master = {"dossier_id": "U-2026-003-VENTE-UNIQ", "type_dossier": "VENTE", "variante": "simple", "annee": 2026}
    d = _make_dossier(settings.inbox_dir, master["dossier_id"], master, docx)
    (d / ".ready").write_text("ok", encoding="utf-8")

    watcher.process_inbox_once(settings)
    results2 = watcher.process_inbox_once(settings)
    # le dossier a ete deplace vers data/dossiers : plus rien dans l'inbox (traitement unique)
    assert results2 == [] or all(r["status"] == "skipped" for r in results2)


def test_watcher_mode_once_ne_boucle_pas(tmp_path):
    settings = _tmp_settings(tmp_path)
    results = watcher.process_inbox_once(settings)
    assert isinstance(results, list)
