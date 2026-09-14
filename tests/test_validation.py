"""Tests déterministes de la validation métier des dossiers réels du projet."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.validation.validator import validate_and_write, validate_dossier
from app.services.dossier_validation import get_validation_report_path


def _issues_by_rule(report):
    return {issue.rule_id: issue for issue in report.issues}


def test_ambigu_dossiers_are_detected_as_invalid(dossiers_dir, ambigu_dossier_ids):
    for dossier_id in ambigu_dossier_ids:
        report = validate_dossier(dossiers_dir / dossier_id)
        assert report.status == "invalid", f"{dossier_id} devrait rester invalide."
        assert any(issue.severity == "blocking" for issue in report.issues)


def test_clean_reference_dossiers_are_never_invalid(dossiers_dir, clean_dossier_ids):
    for dossier_id in clean_dossier_ids:
        report = validate_dossier(dossiers_dir / dossier_id)
        assert report.status in ("valid", "warnings"), f"{dossier_id} ne devrait pas être invalide."


def test_validation_report_summary_matches_issue_counts(dossiers_dir, sample_dossier_id):
    report = validate_dossier(dossiers_dir / sample_dossier_id)
    counted = {"blocking": 0, "warning": 0, "info": 0}
    for issue in report.issues:
        counted[issue.severity] += 1
    assert report.summary == counted


def test_validate_and_write_writes_only_under_output_and_not_data(dossiers_dir, sample_dossier_id):
    dossier_path = dossiers_dir / sample_dossier_id
    before = {p.name: p.stat().st_mtime_ns for p in dossier_path.iterdir() if p.is_file()}
    report = validate_and_write(dossier_path)
    out_path = get_validation_report_path(sample_dossier_id)
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["dossier_id"] == report.dossier_id
    after = {p.name: p.stat().st_mtime_ns for p in dossier_path.iterdir() if p.is_file()}
    assert before == after, "Aucun fichier sous data/dossiers ne doit être modifié par la validation."


def test_full_corpus_validation_keeps_only_ambigu_cases_invalid(dossiers_dir):
    statuses = {"valid": 0, "warnings": 0, "invalid": 0}
    invalid_ids = []
    for path in sorted(dossiers_dir.iterdir()):
        if not path.is_dir():
            continue
        report = validate_dossier(path)
        statuses[report.status] += 1
        if report.status == "invalid":
            invalid_ids.append(path.name)
    assert invalid_ids == ["1-2024-843-AMBIGU", "15-2024-824-AMBIGU"]
    assert statuses["invalid"] == 2


def test_case_1_2024_843_ambigu_reports_conflicting_prices_without_auto_selection(dossiers_dir):
    report = validate_dossier(dossiers_dir / "1-2024-843-AMBIGU")
    issues = _issues_by_rule(report)
    assert report.status == "invalid"
    assert "price_multiple_declared" in issues
    issue = issues["price_multiple_declared"]
    assert issue.severity == "blocking"
    assert "aucun prix" in issue.message.lower()


def test_case_5_2026_876_vente_tazi_keeps_payment_breakdown_consistent_and_checklist_non_blocking(dossiers_dir):
    report = validate_dossier(dossiers_dir / "5-2026-876-VENTE-TAZI")
    issues = _issues_by_rule(report)
    assert report.status == "valid"
    assert "sale_payment_breakdown_incoherent" not in issues
    assert "price_multiple_declared" not in issues
    assert "checklist_incomplete" in issues
    assert issues["checklist_incomplete"].severity == "info"


def test_case_10_2024_542_hypotheque_sqalli_detects_commitment_not_final_registration_and_surety(dossiers_dir):
    report = validate_dossier(dossiers_dir / "10-2024-542-HYPOTHEQUE-SQALLI")
    issues = _issues_by_rule(report)
    assert report.status == "valid"
    assert "mortgage_registration_not_proven" in issues
    assert issues["mortgage_registration_not_proven"].severity == "info"
    assert "mortgage_surety_detected" in issues
    assert issues["mortgage_surety_detected"].severity == "info"
    assert "mortgage_rank_amount_confusion" not in issues


def test_case_11_2024_595_donation_keeps_checklist_distinct_from_legal_validity(dossiers_dir):
    report = validate_dossier(dossiers_dir / "11-2024-595-DONATION-AMRANI")
    issues = _issues_by_rule(report)
    assert "checklist_incomplete" in issues
    assert issues["checklist_incomplete"].severity == "info"
    assert "invalide" not in issues["checklist_incomplete"].message.lower()


def test_case_7_2025_605_succession_does_not_overclaim_all_heirs_and_does_not_force_fraction_sum(dossiers_dir):
    report = validate_dossier(dossiers_dir / "7-2025-605-SUCCESSION-ELYACOUBI")
    issues = _issues_by_rule(report)
    assert report.status == "valid"
    assert "succession_shares_incoherent" not in issues
    assert not any("tous les héritiers" in issue.message.lower() for issue in report.issues)


def test_case_4_2025_539_procuration_does_not_infer_unauthorized_mortgage_power(dossiers_dir):
    report = validate_dossier(dossiers_dir / "4-2025-539-PROCURATION-ALAOUI")
    assert report.status == "valid"
    assert not any("hypoth" in issue.message.lower() for issue in report.issues)


def test_validation_ui_page_hides_rule_ids_and_json_from_notary():
    page = Path(__file__).resolve().parent.parent / "app" / "ui" / "pages" / "2_Detail_dossier.py"
    content = page.read_text(encoding="utf-8")
    assert "st.json(master)" not in content
    assert "issue.get('rule_id')" not in content
    assert "Attention requise : une incohérence doit être résolue avant la rédaction définitive." in content
    assert "Vérification recommandée : les documents disponibles ne permettent pas de confirmer ce point automatiquement." in content
    assert "Information : ce point reste à contrôler dans les pièces ou auprès des parties." in content
