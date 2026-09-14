"""Tests de la checklist documentaire metier complete (par type/variante de dossier).

Deterministe, sans Ollama. Utilise en priorite le corpus reel (data/dossiers) et, pour les
types sans dossier reel dans le corpus (creation de societe, gerance libre, demandes
administratives), un dossier synthetique minimal cree dans tmp_path.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import document_checklist as dc


def _tmp_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=str(tmp_path / "data"), output_dir=str(tmp_path / "output"))


def _make_dossier(base: Path, dossier_id: str, master: dict, files: dict[str, bytes] | None = None) -> Path:
    d = base / dossier_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "dossier_master.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    for name, content in (files or {}).items():
        (d / name).write_bytes(content)
    return d


# ---------------------------------------------------------------------------
# 1. Vente standard avec acte seul
# ---------------------------------------------------------------------------
def test_vente_standard_acte_seul():
    r = dc.evaluate_document_checklist("19-2024-613-VENTE-ELFASSI")
    assert r["evaluable"] is True
    acte = next(i for i in r["items"] if i["id"] == "ACTE_VENTE")
    assert acte["statut"] == dc.STATUT_PRESENTE
    autres = [i for i in r["items"] if i["id"] != "ACTE_VENTE" and i["id"] not in ("PROCURATION", "DOCUMENTS_COPROPRIETE")]
    assert all(i["statut"] in (dc.STATUT_A_AJOUTER, dc.STATUT_A_VERIFIER, dc.STATUT_NON_APPLICABLE) for i in autres)
    # aucune piece n'est jamais declaree juridiquement validee : le rappel figure partout
    assert all(i["rappel"] == dc.RAPPEL_JURIDIQUE for i in r["items"])


# ---------------------------------------------------------------------------
# 2. Vente a paiement differe 5-2026-876-VENTE-TAZI
# ---------------------------------------------------------------------------
def test_vente_paiement_differe_tazi():
    r = dc.evaluate_document_checklist("5-2026-876-VENTE-TAZI")
    assert r["evaluable"] is True
    by_id = {i["id"]: i for i in r["items"]}

    assert by_id["ACTE_VENTE"]["statut"] == dc.STATUT_PRESENTE
    assert by_id["ACTE_VENTE"]["fichiers_detectes"] == ["01_acte_de_vente.docx"]
    assert by_id["CIN_VENDEUR"]["statut"] == dc.STATUT_A_AJOUTER
    assert by_id["CIN_ACQUEREUR"]["statut"] == dc.STATUT_A_AJOUTER
    assert by_id["CERTIFICAT_PROPRIETE"]["statut"] == dc.STATUT_A_AJOUTER
    assert by_id["JUSTIFICATIF_PAIEMENT_IMMEDIAT"]["statut"] == dc.STATUT_A_AJOUTER
    assert by_id["ECHEANCIER_SOLDE"]["statut"] == dc.STATUT_A_AJOUTER
    # procuration : non applicable, aucune representation dans les donnees du dossier
    assert by_id["PROCURATION"]["statut"] == dc.STATUT_NON_APPLICABLE
    # garantie du solde : jamais affirmee requise -> a verifier
    assert by_id["GARANTIE_SOLDE"]["statut"] == dc.STATUT_A_VERIFIER

    # controle arithmetique documente comme verification manuelle, jamais comme validation juridique
    master = json.loads((Path("data/dossiers/5-2026-876-VENTE-TAZI/dossier_master.json")).read_text(encoding="utf-8"))
    donnees = master["donnees"]
    assert donnees["montant_immediat_dhs"] + donnees["montant_differe_dhs"] == donnees["prix_dhs"]
    assert any("montant" in c for c in r["manual_checks"])


# ---------------------------------------------------------------------------
# 3. Hypotheque
# ---------------------------------------------------------------------------
def test_hypotheque_engagement_detecte():
    r = dc.evaluate_document_checklist("10-2024-542-HYPOTHEQUE-SQALLI")
    assert r["evaluable"] is True
    eng = next(i for i in r["items"] if i["id"] == "ENGAGEMENT_HYPOTHECAIRE")
    assert eng["statut"] == dc.STATUT_PRESENTE
    # banque, montant, rang et TF restent des champs a verifier par le notaire (jamais valides automatiquement)
    checks = " ".join(r["manual_checks"]).lower()
    assert "banque" in checks or "montant" in checks or "rang" in checks or "tf" in checks


# ---------------------------------------------------------------------------
# 4. Mainlevee
# ---------------------------------------------------------------------------
def test_mainlevee_requete_et_decharge_distinguees():
    r = dc.evaluate_document_checklist("12-2024-306-HYPOTHEQUE-TEMSAMANI")
    assert r["evaluable"] is True
    assert r["checklist_label"] == "Mainlevee d'hypotheque"
    decharge = next(i for i in r["items"] if i["id"] == "MAINLEVEE_DECHARGE")
    requisition = next(i for i in r["items"] if i["id"] == "REQUISITION_RADIATION")
    assert decharge["fichiers_detectes"] == ["01_mainlevee_hypotheque.docx"]
    assert requisition["fichiers_detectes"] == ["02_requisition_radiation.docx"]
    assert decharge["statut"] == dc.STATUT_PRESENTE
    assert requisition["statut"] == dc.STATUT_PRESENTE
    # une simple mention de mainlevee dans un autre fichier ne doit pas faire matcher la decharge
    assert "04_engagement_conditionnel.docx" not in decharge["fichiers_detectes"]


def test_mainlevee_via_alias_variante_hypotheque():
    """HYPOTHEQUE + variante 'mainlevee' redirige entierement vers la checklist MAINLEVEE."""
    checklist = dc.resolve_checklist("HYPOTHEQUE", "mainlevee")
    assert checklist is not None
    assert checklist["type_key"] == "MAINLEVEE"


# ---------------------------------------------------------------------------
# 5. Donation
# ---------------------------------------------------------------------------
def test_donation_acte_detecte_et_verifications_toujours_requises():
    r = dc.evaluate_document_checklist("11-2024-595-DONATION-AMRANI")
    assert r["evaluable"] is True
    acte = next(i for i in r["items"] if i["id"] == "ACTE_DONATION")
    assert acte["statut"] == dc.STATUT_PRESENTE
    checks = " ".join(r["manual_checks"]).lower()
    for mot in ("identite", "tf", "lien familial", "regime fiscal"):
        assert mot in checks


def test_donation_representation_donataire_detectee():
    """Le donataire represente (represente_par dans les donnees) rend la procuration applicable."""
    r = dc.evaluate_document_checklist("14-2025-124-DONATION-AMRANI")
    proc = next(i for i in r["items"] if i["id"] == "PROCURATION")
    assert proc["statut"] in (dc.STATUT_A_AJOUTER, dc.STATUT_PRESENTE, dc.STATUT_A_VERIFIER)
    assert proc["statut"] != dc.STATUT_NON_APPLICABLE


# ---------------------------------------------------------------------------
# 6. Succession
# ---------------------------------------------------------------------------
def test_succession_deces_et_notoriete_distincts_jamais_valides_automatiquement():
    r = dc.evaluate_document_checklist("7-2025-605-SUCCESSION-ELYACOUBI")
    assert r["evaluable"] is True
    notoriete = next(i for i in r["items"] if i["id"] == "ACTE_NOTORIETE")
    deces = next(i for i in r["items"] if i["id"] == "ACTE_DECES")
    assert notoriete["statut"] == dc.STATUT_PRESENTE
    assert deces["statut"] == dc.STATUT_A_AJOUTER  # aucun fichier d'acte de deces dans ce corpus
    checks = " ".join(r["manual_checks"]).lower()
    assert "qualite" in checks or "heritiers" in checks
    assert "jamais" in checks  # le nombre/la qualite des heritiers ne sont jamais valides automatiquement


# ---------------------------------------------------------------------------
# 7. Procuration
# ---------------------------------------------------------------------------
def test_procuration_mandant_mandataire_distincts():
    r = dc.evaluate_document_checklist("13-2025-709-PROCURATION-CHRAIBI")
    assert r["evaluable"] is True
    by_id = {i["id"]: i for i in r["items"]}
    assert by_id["CIN_MANDANT"]["id"] != by_id["CIN_MANDATAIRE"]["id"]
    assert by_id["PROJET_PROCURATION"]["statut"] == dc.STATUT_PRESENTE


def test_procuration_origine_etrangere_declenche_verification_seulement_si_indiquee():
    # Sans mention d'origine etrangere dans les donnees -> condition non etablie -> a verifier,
    # jamais "non applicable" invente ni "presente" invente.
    r = dc.evaluate_document_checklist("13-2025-709-PROCURATION-CHRAIBI")
    legalisation = next(i for i in r["items"] if i["id"] == "LEGALISATION_ETRANGERE")
    assert legalisation["statut"] == dc.STATUT_A_VERIFIER


# ---------------------------------------------------------------------------
# 8. VEFA
# ---------------------------------------------------------------------------
def test_vefa_echeancier_garanties_separes_et_livraison_non_applicable():
    r = dc.evaluate_document_checklist("16-2023-882-VENTE-SQALLI")
    assert r["evaluable"] is True
    assert r["checklist_label"].startswith("Vente en l'etat futur")
    by_id = {i["id"]: i for i in r["items"]}
    assert "ECHEANCIER_PAIEMENT" in by_id and "GARANTIE_ACHEVEMENT" in by_id
    assert by_id["ECHEANCIER_PAIEMENT"]["id"] != by_id["GARANTIE_ACHEVEMENT"]["id"]
    # aucune mention de reception/livraison dans les donnees -> non applicable avant achevement
    assert by_id["ATTESTATION_LIVRAISON"]["statut"] == dc.STATUT_NON_APPLICABLE


def test_vefa_via_alias_variante_vente():
    checklist = dc.resolve_checklist("VENTE", "vefa")
    assert checklist is not None
    assert checklist["type_key"] == "VEFA"


# ---------------------------------------------------------------------------
# 9. Fonds de commerce
# ---------------------------------------------------------------------------
def test_fonds_commerce_rc_bail_inscriptions_inventaire_distingues():
    r = dc.evaluate_document_checklist("8-2025-687-VENTE-GHALI")
    assert r["evaluable"] is True
    assert r["checklist_label"] == "Vente de fonds de commerce"
    ids = {i["id"] for i in r["items"]}
    assert {"REGISTRE_COMMERCE", "BAIL_COMMERCIAL", "ETAT_INSCRIPTIONS", "INVENTAIRE_ELEMENTS"} <= ids


def test_fonds_commerce_via_alias_variante_vente():
    checklist = dc.resolve_checklist("VENTE", "fonds_de_commerce")
    assert checklist is not None
    assert checklist["type_key"] == "VENTE_FONDS_COMMERCE"


# ---------------------------------------------------------------------------
# 10. Creation de societe (dossier synthetique : aucun dossier reel de ce type dans le corpus)
# ---------------------------------------------------------------------------
def test_creation_societe_statuts_modele_j_annonce_rc_cin_distincts(tmp_path):
    settings = _tmp_settings(tmp_path)
    master = {"dossier_id": "T-SOC-1", "type_dossier": "SARL", "variante": "standard"}
    _make_dossier(settings.dossiers_dir, "T-SOC-1", master, files={
        "01_statuts.docx": b"STATUTS",
        "02_modele_j.docx": b"MODELE J",
    })
    r = dc.evaluate_document_checklist("T-SOC-1", settings)
    assert r["evaluable"] is True
    assert r["checklist_label"].startswith("Creation de societe")
    by_id = {i["id"]: i for i in r["items"]}
    assert by_id["STATUTS"]["statut"] == dc.STATUT_PRESENTE
    assert by_id["MODELE_J"]["statut"] == dc.STATUT_PRESENTE
    assert by_id["ANNONCE_LEGALE"]["statut"] == dc.STATUT_A_AJOUTER
    assert by_id["REGISTRE_COMMERCE"]["statut"] == dc.STATUT_A_AJOUTER
    assert by_id["CIN_ASSOCIES"]["statut"] == dc.STATUT_A_AJOUTER
    # aucun fichier de modele interne (data/modeles) n'est jamais confondu avec une piece du dossier client :
    # seuls les fichiers du repertoire du dossier selectionne sont explores.
    assert all(
        f not in ("01_statuts.docx", "02_modele_j.docx")
        for i in r["items"] if i["id"] not in ("STATUTS", "MODELE_J")
        for f in i["fichiers_detectes"]
    )


def test_sarl_est_un_alias_de_creation_societe():
    checklist = dc.resolve_checklist("SARL", None)
    assert checklist is not None
    assert checklist["type_key"] == "CREATION_SOCIETE"


# ---------------------------------------------------------------------------
# 11. Gerance libre (dossier synthetique)
# ---------------------------------------------------------------------------
def test_gerance_libre_contrat_rc_bail_annonce_parties_distingues(tmp_path):
    settings = _tmp_settings(tmp_path)
    master = {"dossier_id": "T-GL-1", "type_dossier": "GERANCE_LIBRE", "variante": "standard"}
    _make_dossier(settings.dossiers_dir, "T-GL-1", master, files={"01_gerance_libre.docx": b"CONTRAT"})
    r = dc.evaluate_document_checklist("T-GL-1", settings)
    assert r["evaluable"] is True
    ids = {i["id"] for i in r["items"]}
    assert {"CONTRAT_GERANCE", "REGISTRE_COMMERCE", "BAIL_LOCAUX", "ANNONCE_LEGALE", "IDENTITE_PARTIES"} <= ids
    by_id = {i["id"]: i for i in r["items"]}
    assert by_id["CONTRAT_GERANCE"]["statut"] == dc.STATUT_PRESENTE


# ---------------------------------------------------------------------------
# 12. Demandes administratives (dossier synthetique)
# ---------------------------------------------------------------------------
def test_administration_sous_type_a_sa_propre_liste_et_annexes_jamais_presumees(tmp_path):
    settings = _tmp_settings(tmp_path)
    master = {"dossier_id": "T-ADM-1", "type_dossier": "DEMANDES_ADMINISTRATIVES", "variante": "demande_mainlevee_radiation"}
    _make_dossier(settings.dossiers_dir, "T-ADM-1", master, files={"01_demande.docx": b"DEMANDE"})
    r = dc.evaluate_document_checklist("T-ADM-1", settings)
    assert r["evaluable"] is True
    by_id = {i["id"]: i for i in r["items"]}
    # une annexe simplement citee dans le texte n'est jamais declaree "presente" sans fichier reel
    assert by_id["ANNEXES_CITEES"]["statut"] != dc.STATUT_PRESENTE
    assert by_id["ANNEXES_CITEES"]["fichiers_detectes"] == []


# ---------------------------------------------------------------------------
# 13. Securite : lecture seule, pas de fuite de chemin, pas de fuite entre dossiers
# ---------------------------------------------------------------------------
def test_securite_aucune_ecriture_dans_les_sources(tmp_path):
    settings = _tmp_settings(tmp_path)
    master = {"dossier_id": "5-2026-876-VENTE-TAZI", "type_dossier": "VENTE", "variante": "paiement_differe"}
    src = Path("data/dossiers/5-2026-876-VENTE-TAZI")
    dest = _make_dossier(settings.dossiers_dir, "5-2026-876-VENTE-TAZI", master)
    shutil.copy2(str(src / "01_acte_de_vente.docx"), str(dest / "01_acte_de_vente.docx"))
    before = sorted(p.name for p in dest.iterdir())
    before_hash = {p.name: p.stat().st_mtime for p in dest.iterdir()}

    dc.evaluate_document_checklist("5-2026-876-VENTE-TAZI", settings)

    after = sorted(p.name for p in dest.iterdir())
    after_hash = {p.name: p.stat().st_mtime for p in dest.iterdir()}
    assert before == after  # aucun fichier cree/supprime dans le dossier
    assert before_hash == after_hash  # aucun fichier source modifie


def test_securite_aucune_fuite_de_chemin_complet():
    r = dc.evaluate_document_checklist("5-2026-876-VENTE-TAZI")
    for item_ in r["items"]:
        for f in item_["fichiers_detectes"]:
            assert "/" not in f and "\\" not in f  # nom de fichier seul, jamais un chemin


def test_securite_pas_de_fuite_entre_dossiers():
    """Un fichier d'un autre dossier ne doit jamais apparaitre dans les resultats de celui-ci."""
    r = dc.evaluate_document_checklist("5-2026-876-VENTE-TAZI")
    all_files = {f for i in r["items"] for f in i["fichiers_detectes"]}
    assert all_files <= {"01_acte_de_vente.docx"}


def test_type_inconnu_checklist_non_configuree():
    r = dc.evaluate_document_checklist("1-2024-843-AMBIGU")
    assert r["evaluable"] is False
    assert r["statut_global"] == dc.STATUT_NON_CONFIGUREE
    assert r["items"] == []
