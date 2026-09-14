from __future__ import annotations

import ast
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import Settings
from app.services.notifications import capture_document_baseline, list_notifications, mark_notification_read, mark_notification_treated

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = PROJECT_ROOT / "app" / "ui" / "pages"
client = TestClient(app)

FORBIDDEN_TERMS = [
    "qdrant",
    "embedding",
    "chunk",
    "json",
    "yaml",
    "sha",
    "manifest",
    "pytest",
    "traceback",
    r"c:\\",
    ".py",
    "collection",
    "indexation",
    "dossier_master",
    "rule_id",
    "price_multiple_declared",
]


def _public_string_literals(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if "pages/" in value:
                continue
            out.append(value)
    return "\n".join(out).lower()


def _temp_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    (data_dir / "dossiers").mkdir(parents=True, exist_ok=True)
    (output_dir / "qdrant_local").mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=str(data_dir),
        output_dir=str(output_dir),
        sqlite_path=str(output_dir / "app_metadata.sqlite3"),
        qdrant_local_path=str(output_dir / "qdrant_local"),
        document_checklists_path_str=str(PROJECT_ROOT / "app" / "config" / "document_checklists.yaml"),
        validation_rules_path_str=str(PROJECT_ROOT / "app" / "config" / "validation_rules.yaml"),
    )


def _write_master(settings: Settings, dossier_id: str, *, type_dossier: str = "VENTE", variante: str = "simple") -> Path:
    dossier = settings.dossiers_dir / dossier_id
    dossier.mkdir(parents=True, exist_ok=True)
    payload = {
        "dossier_id": dossier_id,
        "annee": 2026,
        "type_dossier": type_dossier,
        "variante": variante,
        "client_famille": "Famille test",
        "donnees": {
            "vendeur": {"nom_fr": "Vendeur Test"},
            "acquereur": {"nom_fr": "Acquéreur Test"},
            "bien": {"tf": "123.456/78", "superficie_m2": 80},
            "prix_dhs_version_fr": 1650000,
            "prix_dhs_version_ar": 340000,
        },
    }
    (dossier / "dossier_master.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return dossier


def _write_report(settings: Settings, dossier_id: str, status: str = "invalid", issues: list[dict] | None = None) -> None:
    settings.validation_reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "dossier_id": dossier_id,
        "status": status,
        "summary": {"blocking": 1 if status == "invalid" else 0, "warning": 1 if status == "warnings" else 0, "info": 0},
        "issues": issues or [],
        "generated_at": "2026-08-25T10:00:00+00:00",
    }
    (settings.validation_reports_dir / f"{dossier_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_notary_pages_visible_menu_matches_business_navigation():
    visible_pages = sorted(p.name for p in PAGES_DIR.glob("*.py"))
    assert visible_pages == [
        "1_Dossiers.py",
        "2_Detail_dossier.py",
        "3_Assistant_documentaire.py",
        "4_Recherche_juridique.py",
        "5_Modeles_internes.py",
        "6_Notifications.py",
        "7_Situations_similaires.py",
    ]
    support_dir = PROJECT_ROOT / "app" / "ui" / "support"
    assert (support_dir / "Administration.py").exists()
    assert (support_dir / "Audit_RAG.py").exists()


def test_notary_pages_do_not_expose_forbidden_technical_terms():
    targets = [PROJECT_ROOT / "app" / "ui" / "Accueil.py"] + sorted(PAGES_DIR.glob("*.py"))
    combined = "\n".join(_public_string_literals(path) for path in targets)
    for term in FORBIDDEN_TERMS:
        assert term.lower() not in combined, f"Terme technique visible côté notaire: {term}"
    assert "fiche complète (dossier_master.json)" not in combined
    assert "administration" not in combined
    assert "accueil" not in combined


def test_dossiers_endpoint_maps_ambigu_to_business_labels():
    resp = client.get("/dossiers")
    assert resp.status_code == 200
    dossiers = resp.json()["dossiers"]
    ambigu = next(d for d in dossiers if d["dossier_id"] == "1-2024-843-AMBIGU")
    assert ambigu["type_dossier"] == "AMBIGU"
    assert ambigu["public_type"] == "Vente immobilière"
    assert ambigu["public_variant"] == "Prix à clarifier"
    assert ambigu["public_state"] == "Attention requise"


def test_notifications_read_then_treated_keeps_active_anomaly_visible(tmp_path):
    settings = _temp_settings(tmp_path)
    dossier_id = "X-2026-001-AMBIGU"
    _write_master(settings, dossier_id, type_dossier="AMBIGU", variante="prix_contradictoire_fr_ar")
    _write_report(
        settings,
        dossier_id,
        status="invalid",
        issues=[
            {
                "rule_id": "price_multiple_declared",
                "severity": "blocking",
                "title": "Plusieurs prix déclarés incompatibles",
                "message": "Plusieurs prix incompatibles apparaissent dans le dossier.",
                "recommended_action": "Clarifier le prix.",
            }
        ],
    )

    first = list_notifications(dossier_id=dossier_id, settings=settings)
    notif = next(n for n in first["notifications"] if n["title"] == "Prix contradictoires")
    assert notif["state"] == "new"
    assert first["badge_count"] == 1

    mark_notification_read(notif["notification_key"], dossier_id, settings=settings)
    second = list_notifications(dossier_id=dossier_id, settings=settings)
    notif2 = next(n for n in second["notifications"] if n["notification_key"] == notif["notification_key"])
    assert notif2["state"] == "read"
    assert second["badge_count"] == 0

    mark_notification_treated(notif["notification_key"], dossier_id, settings=settings)
    third = list_notifications(dossier_id=dossier_id, settings=settings)
    notif3 = next(n for n in third["notifications"] if n["notification_key"] == notif["notification_key"])
    assert notif3["state"] == "treated"
    assert notif3["title"] == "Prix contradictoires"
    assert "Clarifier le prix réel avec les parties" in notif3["message"]


def test_document_change_notifications_added_modified_removed(tmp_path):
    settings = _temp_settings(tmp_path)
    dossier_id = "X-2026-002-VENTE"
    dossier = _write_master(settings, dossier_id, type_dossier="VENTE", variante="simple")
    (dossier / "acte_de_vente.pdf").write_text("v1", encoding="utf-8")
    (dossier / "titre_foncier.pdf").write_text("titre", encoding="utf-8")
    _write_report(settings, dossier_id, status="warnings", issues=[])

    capture_document_baseline(dossier_id, settings=settings)
    (dossier / "acte_de_vente.pdf").write_text("v2", encoding="utf-8")
    (dossier / "titre_foncier.pdf").unlink()
    (dossier / "virement.pdf").write_text("paiement", encoding="utf-8")

    payload = list_notifications(dossier_id=dossier_id, settings=settings)
    titles = {n["title"] for n in payload["notifications"]}
    messages = "\n".join(n["message"] for n in payload["notifications"])
    assert "Document ajouté" in titles
    assert "Document modifié" in titles
    assert "Document indisponible" in titles
    assert "Un nouveau document a été ajouté au dossier." in messages
    assert "Un document du dossier a été modifié depuis le dernier contrôle." in messages
    assert "Un document précédemment détecté dans le dossier n’est plus disponible." in messages
    assert "attaque" not in messages.lower()


def test_ten_document_changes_are_grouped_into_one_attention_notification(tmp_path):
    settings = _temp_settings(tmp_path)
    dossier_id = "X-2026-003-VENTE"
    _write_master(settings, dossier_id, type_dossier="VENTE", variante="simple")
    capture_document_baseline(dossier_id, settings=settings)
    dossier = settings.dossiers_dir / dossier_id
    for idx in range(10):
        (dossier / f"piece_{idx}.pdf").write_text(f"doc {idx}", encoding="utf-8")

    payload = list_notifications(dossier_id=dossier_id, settings=settings)
    grouped = [n for n in payload["notifications"] if n["title"] == "Changements documentaires multiples"]
    assert len(grouped) == 1
    assert grouped[0]["level"] == "attention_requise"
    assert payload["badge_count"] == 1


def test_notifications_do_not_write_in_data_chunks_qdrant_or_index(tmp_path):
    settings = _temp_settings(tmp_path)
    dossier_id = "X-2026-004-VENTE"
    dossier = _write_master(settings, dossier_id, type_dossier="VENTE", variante="simple")
    doc = dossier / "acte_de_vente.pdf"
    doc.write_text("version", encoding="utf-8")
    chunks = settings.output_path / "chunks_dossiers.jsonl"
    chunks.write_text("", encoding="utf-8")
    manifest = settings.output_path / "index_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    qmeta = Path(settings.qdrant_local_path) / "meta.json"
    qmeta.write_text("{}", encoding="utf-8")

    before = {
        doc: doc.stat().st_mtime_ns,
        chunks: chunks.stat().st_mtime_ns,
        manifest: manifest.stat().st_mtime_ns,
        qmeta: qmeta.stat().st_mtime_ns,
    }
    capture_document_baseline(dossier_id, settings=settings)
    list_notifications(dossier_id=dossier_id, settings=settings)
    after = {path: path.stat().st_mtime_ns for path in before}
    assert before == after
