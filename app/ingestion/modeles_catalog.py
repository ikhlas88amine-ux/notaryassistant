"""Catalogue de classification des modeles reels de l'etude (partage entre le script de
consolidation et le pipeline de chunking/indexation), etabli lors des sessions precedentes
d'analyse manuelle du contenu de chaque modele.
"""
from __future__ import annotations

CLASSIFICATION: dict[str, dict] = {
    "vente-fonds-de-commerce.doc": {"type_modele": "cession_fonds_de_commerce", "domaine": "fonds_commerce", "langue": "fr"},
    "vefa.doc": {"type_modele": "vente_immeuble_etat_futur_achevement", "domaine": "immobilier", "langue": "ar"},
    "vente-TRIPARTI-AL-BARID.doc": {"type_modele": "vente_avec_hypotheque_bancaire_tripartite", "domaine": "immobilier", "langue": "fr"},
    "nmwdj-by-shrk.doc": {"type_modele": "vente_immobiliere_avec_credit_vendeur_double_hypotheque", "domaine": "immobilier", "langue": "ar"},
    "thmn-lby.docx": {"type_modele": "clause_prix_bilingue_incoherente", "domaine": "immobilier", "langue": "fr_ar"},
    "thmn-lby-1.docx": {"type_modele": "clause_prix_paiement_differe", "domaine": "immobilier", "langue": "ar"},
    "qsm-mn-lthmn-mrwr-bmHsbh-w-qsm-dwn-lmrwr.docx": {"type_modele": "clause_prix_mixte_comptabilite", "domaine": "immobilier", "langue": "ar"},
    "thmn-dwn-mrwr-bmHsbth.docx": {"type_modele": "clause_prix_hors_comptabilite_totale", "domaine": "immobilier", "langue": "ar"},
    "Engagement-ATTIJARIWAFABANK.doc": {"type_modele": "engagement_hypothecaire_1er_rang", "domaine": "banque_hypotheque", "langue": "fr"},
    "Engagement-AL-BARID-BANK-caution.doc": {"type_modele": "engagement_hypothecaire_avec_caution", "domaine": "banque_hypotheque", "langue": "fr"},
    "MAINLEVEE-BMCE.doc": {"type_modele": "mainlevee_hypotheque_bancaire", "domaine": "banque_hypotheque", "langue": "fr"},
    "REQUISITION.mainlevee.docx": {"type_modele": "requisition_radiation_hypotheque", "domaine": "banque_hypotheque", "langue": "fr"},
    "dn.docx": {"type_modele": "autorisation_prelevement_sur_prix", "domaine": "banque_hypotheque", "langue": "ar"},
    "ltzm.docx": {"type_modele": "engagement_conditionnel_apres_mainlevee", "domaine": "banque_hypotheque", "langue": "ar"},
    "rsl-twDyHy-Copie.docx": {"type_modele": "lettre_rectificative_recu", "domaine": "administration", "langue": "ar"},
    "shhd.docx": {"type_modele": "attestation_liberation_local_commercial", "domaine": "attestations", "langue": "ar"},
    "tsyyr-Hr.docx": {"type_modele": "acte_gerance_libre_fonds_de_commerce", "domaine": "fonds_commerce", "langue": "ar"},
    "Tlb-lnshr-fy-ljryd-lrsmy.docx": {"type_modele": "demande_publication_bulletin_officiel", "domaine": "administration", "langue": "ar"},
    "Tlb-f-mn-lzydt-lDryby.docx": {"type_modele": "demande_exoneration_majorations_fiscales", "domaine": "administration", "langue": "ar"},
    "Tlb-rkhS-mn-lbldy.docx": {"type_modele": "demande_licence_exploitation_communale", "domaine": "administration", "langue": "ar"},
    "REQUISITION-creation-de-la-societe.docx": {"type_modele": "requisition_ouverture_dossier_societe", "domaine": "societe_rc", "langue": "fr"},
    "REQUISITION.MODEL-J.docx": {"type_modele": "requisition_modele_j", "domaine": "societe_rc", "langue": "fr"},
    "Sdq-w-kl-shq.docx": {"type_modele": "donation_sadaka_irrevocable", "domaine": "immobilier", "langue": "ar"},
    "Demande-d-attestation.docx": {"type_modele": "demande_attestation_paiement_impots_taxes", "domaine": "attestations", "langue": "fr", "unavailable": True},
}


def classify_by_filename(filename: str) -> dict:
    """Retourne les metadonnees de classification connues pour un fichier, ou un profil par defaut
    ('non_classes' / 'a_verifier') si le fichier n'est pas dans le catalogue (nouveau modele deposé
    manuellement par l'utilisateur sans classification prealable)."""
    return CLASSIFICATION.get(filename, {
        "type_modele": "a_verifier",
        "domaine": "non_classes",
        "langue": "unknown",
    })
