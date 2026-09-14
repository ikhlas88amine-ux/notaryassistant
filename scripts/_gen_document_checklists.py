"""Script ponctuel : genere app/config/document_checklists.yaml a partir d'une structure
Python, pour garantir une syntaxe YAML valide. Ce script n'est pas execute par
l'application ; il sert uniquement a produire le fichier de configuration versionne.
Relancer ce script régénère intégralement le fichier (à n'utiliser que pour une refonte
volontaire de la configuration, jamais automatiquement par l'application).
"""
from __future__ import annotations

import yaml
from pathlib import Path

SOURCE = "checklist_configuree_etude"


def item(id_, label, *, required=True, conditional=None, condition_description="",
         file_aliases=None, content_markers=None, auto_detection="filename_only",
         manual_verification_required=True, help_text=""):
    return {
        "id": id_,
        "label": label,
        "required": required,
        "conditional": conditional,
        "condition_description": condition_description,
        "file_aliases": file_aliases or [],
        "content_markers": content_markers or [],
        "auto_detection": auto_detection,
        "manual_verification_required": manual_verification_required,
        "help_text": help_text,
        "source": SOURCE,
    }


CONFIG = {
    "version": 1,
    "source": SOURCE,
    "note": (
        "Checklists documentaires configurables par l'etude notariale. Cette configuration "
        "n'est pas une liste legale universelle : elle doit etre revue et validee par l'etude, "
        "et ne dispense jamais le notaire de sa propre verification juridique."
    ),
    "checklists": {

        # ------------------------------------------------------------------ VENTE
        "VENTE": {
            "label": "Vente immobiliere standard",
            "items": [
                item("ACTE_VENTE", "Acte de vente / projet d'acte",
                     file_aliases=["acte_de_vente", "vente", "projet_vente"],
                     auto_detection="filename_only", manual_verification_required=True,
                     help_text="Projet ou acte de vente du bien concerne."),
                item("CIN_VENDEUR", "Piece d'identite du vendeur",
                     file_aliases=["cin_vendeur", "cnie_vendeur", "id_vendeur", "passeport_vendeur"],
                     help_text="Copie de la piece d'identite du vendeur."),
                item("CIN_ACQUEREUR", "Piece d'identite de l'acquereur",
                     file_aliases=["cin_acquereur", "cnie_acquereur", "id_acquereur", "passeport_acquereur"],
                     help_text="Copie de la piece d'identite de l'acquereur."),
                item("CERTIFICAT_PROPRIETE", "Certificat de propriete / etat foncier recent",
                     file_aliases=["certificat_propriete", "etat_foncier", "certificat_foncier"],
                     help_text="Certificat de propriete ou etat foncier a jour du bien."),
                item("TITRE_FONCIER", "Titre foncier ou reference fonciere",
                     file_aliases=["titre_foncier", "tf", "copie_tf"],
                     help_text="Reference ou copie du titre foncier du bien."),
                item("SITUATION_HYPOTHECAIRE", "Situation hypothecaire / charges",
                     required=False, conditional="charges_mentionnees",
                     condition_description="Applicable si le bien ou les documents mentionnent une hypotheque, un privilege ou une charge en cours.",
                     file_aliases=["situation_hypothecaire", "etat_charges", "attestation_charges"],
                     auto_detection="filename_or_content", content_markers=["hypotheque", "charge", "privilege"],
                     help_text="Etat des inscriptions/charges grevant le bien, si le dossier en fait etat."),
                item("JUSTIFICATIF_PAIEMENT", "Justificatif du prix ou des modalites de paiement",
                     file_aliases=["virement", "justificatif_paiement", "recu_paiement", "preuve_paiement"],
                     auto_detection="filename_only",
                     help_text="Preuve du paiement du prix ou des modalites convenues."),
                item("PROCURATION", "Procuration",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable uniquement si une partie est representee (procuration/mandat detecte dans les donnees ou les documents).",
                     file_aliases=["procuration", "mandat", "power_of_attorney"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat"],
                     help_text="Procuration de la partie representee, le cas echeant."),
                item("DOCUMENTS_COPROPRIETE", "Documents de copropriete",
                     required=False, conditional="copropriete_detectee",
                     condition_description="Applicable uniquement si le bien est en copropriete (mention dans les donnees ou les documents).",
                     file_aliases=["copropriete", "syndic", "reglement_copropriete"],
                     auto_detection="filename_or_content", content_markers=["copropriete", "syndic"],
                     help_text="Reglement de copropriete, etat des charges de syndic, etc."),
                item("AUTORISATION_URBANISTIQUE", "Autorisation / documents urbanistiques",
                     required=False, conditional="urbanisme_necessaire",
                     condition_description="Applicable si la nature du bien ou l'operation implique une construction, un permis d'habiter ou une conformite a verifier.",
                     file_aliases=["permis_habiter", "autorisation_construire", "certificat_conformite"],
                     auto_detection="filename_or_content", content_markers=["permis", "autorisation de construire", "conformite"],
                     help_text="Permis d'habiter, autorisation de construire ou certificat de conformite, si necessaire."),
            ],
            "variants": {
                "paiement_differe": {
                    "label": "Vente a paiement differe",
                    "mode": "extend",
                    "extra_items": [
                        item("ECHEANCIER_SOLDE", "Echeancier ou engagement relatif au solde differe",
                             file_aliases=["echeancier", "engagement_solde", "paiement_differe", "reconnaissance_dette"],
                             help_text="Document formalisant l'echeancier ou l'engagement de paiement du solde differe."),
                        item("JUSTIFICATIF_PAIEMENT_IMMEDIAT", "Justificatif du paiement immediat",
                             file_aliases=["virement_initial", "paiement_initial", "recu_acompte"],
                             auto_detection="filename_only",
                             help_text="Preuve du versement de la part immediate du prix."),
                        item("GARANTIE_SOLDE", "Garantie eventuelle du solde",
                             required=False, conditional=None, auto_detection="manual",
                             file_aliases=["garantie_solde", "caution", "hypotheque_garantie", "nantissement"],
                             help_text=(
                                 "Garantie eventuelle du solde differe (caution, hypotheque, nantissement). "
                                 "Ne jamais affirmer automatiquement qu'une garantie est requise ou absente : "
                                 "a verifier par le notaire si aucune garantie n'apparait dans les donnees."
                             )),
                    ],
                    "manual_checks": [
                        "Verification manuelle des montants : prix total = montant immediat + solde differe (controle arithmetique, pas une validation juridique).",
                        "Verification manuelle de la date et des conditions d'exigibilite du solde differe.",
                    ],
                },
                "vefa": {"mode": "alias", "target": "VEFA"},
                "fonds_de_commerce": {"mode": "alias", "target": "VENTE_FONDS_COMMERCE"},
            },
        },

        # ------------------------------------------------------------- HYPOTHEQUE
        "HYPOTHEQUE": {
            "label": "Hypotheque",
            "items": [
                item("ENGAGEMENT_HYPOTHECAIRE", "Lettre d'engagement hypothecaire ou acte d'hypotheque",
                     file_aliases=["engagement_hypothecaire", "acte_hypotheque", "hypotheque"],
                     help_text="Acte ou lettre d'engagement constituant l'hypotheque."),
                item("CIN_EMPRUNTEUR", "Piece d'identite de l'emprunteur / constituant",
                     file_aliases=["cin_emprunteur", "cin_constituant", "id_emprunteur"]),
                item("OFFRE_CREDIT", "Offre, convention ou attestation de credit bancaire",
                     file_aliases=["offre_pret", "contrat_credit", "attestation_credit", "credit_bancaire"]),
                item("ATTESTATION_BANQUE", "Attestation ou instruction bancaire",
                     file_aliases=["attestation_banque", "instruction_banque", "lettre_banque"]),
                item("CERTIFICAT_PROPRIETE", "Certificat de propriete / titre foncier",
                     file_aliases=["certificat_propriete", "titre_foncier", "tf"]),
                item("ETAT_CHARGES", "Etat des inscriptions / charges",
                     file_aliases=["etat_charges", "situation_hypothecaire", "certificat_charges"]),
                item("REQUISITION_INSCRIPTION", "Requisition d'inscription",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["requisition_inscription", "requisition_hypotheque"],
                     help_text="Requisition d'inscription, si prevue dans le processus de l'etude."),
                item("PROCURATION", "Procuration",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable uniquement si une partie est representee.",
                     file_aliases=["procuration", "mandat", "power_of_attorney"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat"]),
            ],
            "manual_checks": [
                "Verification manuelle : montant garanti, rang, beneficiaire, TF, identite du constituant et delai de l'engagement.",
            ],
            "variants": {
                "mainlevee": {"mode": "alias", "target": "MAINLEVEE"},
            },
        },

        # -------------------------------------------------------------- MAINLEVEE
        "MAINLEVEE": {
            "label": "Mainlevee d'hypotheque",
            "items": [
                item("MAINLEVEE_DECHARGE", "Mainlevee, decharge ou accord de radiation de la banque",
                     file_aliases=["mainlevee", "decharge", "accord_radiation", "levee_hypotheque"],
                     help_text="Document de decharge/accord de radiation emanant de la banque."),
                item("REQUISITION_RADIATION", "Requisition de radiation / inscription de mainlevee",
                     file_aliases=["requisition_mainlevee", "requisition_radiation"]),
                item("REFERENCE_HYPOTHEQUE", "Reference de l'hypotheque ou attestation bancaire associee",
                     file_aliases=["reference_hypotheque", "attestation_banque", "credit_solde"]),
                item("CERTIFICAT_PROPRIETE", "Certificat de propriete / etat des charges",
                     file_aliases=["certificat_propriete", "etat_charges", "situation_hypothecaire"]),
                item("CIN_PROPRIETAIRE", "Piece d'identite du proprietaire ou du requerant",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["cin_proprietaire", "cin_requerant"],
                     help_text="Piece d'identite du proprietaire/requerant, si necessaire au dossier."),
                item("PROCURATION", "Procuration",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable uniquement si une partie est representee.",
                     file_aliases=["procuration", "mandat", "power_of_attorney"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat"]),
            ],
            "manual_checks": [
                "Verification manuelle : identite de la banque, reference de l'inscription a radier, TF concerne, decharge integrale et destination de la requete.",
                "Une simple mention de mainlevee dans un autre document n'equivaut pas a une decharge : la piece de decharge doit etre distinguee de la requisition.",
            ],
        },

        # --------------------------------------------------------------- DONATION
        "DONATION": {
            "label": "Donation",
            "items": [
                item("ACTE_DONATION", "Acte de donation",
                     file_aliases=["acte_donation", "donation", "sdq"]),
                item("CIN_DONATEUR", "Piece d'identite du donateur",
                     file_aliases=["cin_donateur", "cnie_donateur", "id_donateur"]),
                item("CIN_DONATAIRE", "Piece d'identite du donataire",
                     file_aliases=["cin_donataire", "cnie_donataire", "id_donataire"]),
                item("CERTIFICAT_PROPRIETE", "Certificat de propriete / titre foncier",
                     file_aliases=["certificat_propriete", "titre_foncier", "tf"]),
                item("LIEN_FAMILIAL", "Justificatif du lien familial",
                     required=False, conditional="lien_familial_invoque",
                     condition_description="Applicable uniquement si le lien familial est invoque pour le regime fiscal ou dans l'acte.",
                     file_aliases=["acte_naissance", "livret_famille", "certificat_lien_familial"],
                     auto_detection="filename_or_content", content_markers=["fils", "fille", "epoux", "epouse", "petit-fils", "petite-fille", "lien"]),
                item("EVALUATION_BIEN", "Evaluation / valeur declaree du bien",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["evaluation", "valeur_declaree", "expertise"]),
                item("PROCURATION", "Procuration",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable uniquement si une partie est representee.",
                     file_aliases=["procuration", "mandat", "power_of_attorney"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat", "represente"]),
                item("DOCUMENTS_COPROPRIETE", "Documents de copropriete ou autres documents immobiliers",
                     required=False, conditional="copropriete_detectee",
                     condition_description="Applicable si le bien donne est en copropriete.",
                     file_aliases=["copropriete", "syndic", "reglement_copropriete"],
                     auto_detection="filename_or_content", content_markers=["copropriete", "syndic"]),
            ],
            "manual_checks": [
                "Verification manuelle : acceptation du donataire, qualification de la donation, identite des parties, TF, valeur declaree, regime fiscal, references du lien familial si invoque.",
            ],
        },

        # ------------------------------------------------------------- SUCCESSION
        "SUCCESSION": {
            "label": "Succession",
            "items": [
                item("ACTE_DECES", "Acte de deces / certificat de deces",
                     file_aliases=["acte_deces", "certificat_deces", "deces"]),
                item("ACTE_NOTORIETE", "Acte de notoriete successorale / acte d'heredite",
                     file_aliases=["acte_notoriete_successorale", "notoriete", "heredite", "rsm_istifa"]),
                item("CIN_HERITIER", "Pieces d'identite des heritiers",
                     file_aliases=["cin_heritier", "cnie_heritier", "id_heritier"]),
                item("CIN_DEFUNT", "Piece d'identite du defunt",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["cin_defunt", "id_defunt"],
                     help_text="Si disponible et utile au dossier."),
                item("CERTIFICAT_PROPRIETE", "Certificat de propriete / TF des biens successoraux",
                     file_aliases=["certificat_propriete", "titre_foncier", "tf"]),
                item("QUALITE_HERITIERS", "Documents etablissant la qualite des heritiers",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["acte_naissance", "livret_famille", "acte_mariage", "certificat_familial"],
                     help_text="Selon le dossier (filiation, mariage, etc.)."),
                item("PROCURATION_HERITIER", "Procurations eventuelles des heritiers",
                     required=False, conditional="heritier_represente",
                     condition_description="Applicable uniquement si un heritier est represente par mandataire.",
                     file_aliases=["procuration_heritier", "mandat_heritier"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat", "represente"]),
                item("EVALUATION_BIENS", "Evaluation des biens",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["evaluation", "expertise", "valeur_bien"]),
            ],
            "manual_checks": [
                "Verification manuelle : date de deces, identite du defunt, nombre et qualite des heritiers, quotes-parts, TF, biens concernes et pouvoirs des representants. "
                "Le nombre et la qualite des heritiers ne sont jamais valides automatiquement.",
            ],
        },

        # ----------------------------------------------------------- PROCURATION
        "PROCURATION": {
            "label": "Procuration",
            "items": [
                item("PROJET_PROCURATION", "Projet ou acte de procuration",
                     file_aliases=["procuration", "mandat", "power_of_attorney"]),
                item("CIN_MANDANT", "Piece d'identite du mandant",
                     file_aliases=["cin_mandant", "cnie_mandant", "id_mandant"]),
                item("CIN_MANDATAIRE", "Piece d'identite du mandataire",
                     file_aliases=["cin_mandataire", "cnie_mandataire", "id_mandataire"]),
                item("OBJET_MANDAT", "Document relatif a l'objet du mandat",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["titre_foncier", "certificat_propriete", "projet_vente", "contrat_credit"],
                     help_text="Si le mandat porte sur un bien ou une operation precise."),
                item("LEGALISATION_ETRANGERE", "Legalisation, apostille ou traduction de la procuration",
                     required=False, conditional="origine_etrangere",
                     condition_description="Applicable uniquement si la procuration est etablie a l'etranger.",
                     file_aliases=["apostille", "legalisation", "traduction_asernentee", "procuration_consulaire"],
                     auto_detection="filename_or_content", content_markers=["apostille", "consulat", "etranger", "legalisation"]),
            ],
            "manual_checks": [
                "Verification manuelle : objet precis, identite, pouvoirs expres, bien concerne, prix/plafond eventuel, duree, revocation et substitution.",
                "Les procurations liees aux operations immobilieres doivent etre suffisamment precises sur l'objet, les parties et les pouvoirs ; la forme applicable doit etre verifiee par le notaire.",
            ],
        },

        # ----------------------------------------------------------------- VEFA
        "VEFA": {
            "label": "Vente en l'etat futur d'achevement (VEFA)",
            "items": [
                item("CONTRAT_VEFA", "Contrat de reservation, contrat preliminaire ou acte VEFA",
                     file_aliases=["reservation", "contrat_preliminaire", "vefa", "acte_vefa"]),
                item("CIN_PARTIES", "Pieces d'identite de l'acquereur et du vendeur/promoteur",
                     file_aliases=["cin_acquereur", "cin_vendeur", "cin_promoteur"]),
                item("TITRE_FONCIER_TERRAIN", "Titre foncier ou reference fonciere du terrain",
                     file_aliases=["titre_foncier", "tf", "certificat_propriete"]),
                item("PLANS_NOTICE", "Plans, notice descriptive et documents techniques",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["plans", "notice_descriptive", "cahier_charges", "descriptif_technique"]),
                item("PERMIS_CONSTRUIRE", "Permis de construire / autorisations applicables",
                     file_aliases=["permis_construire", "autorisation_construire"]),
                item("GARANTIE_ACHEVEMENT", "Garantie d'achevement ou de remboursement",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["garantie_achevement", "garantie_remboursement"],
                     help_text="Si prevue dans le contrat."),
                item("ECHEANCIER_PAIEMENT", "Echeancier de paiement",
                     file_aliases=["echeancier_paiement", "appels_fonds"]),
                item("ATTESTATION_LIVRAISON", "Attestation de livraison / reception",
                     required=False, conditional="achevement_constate",
                     condition_description="Non applicable avant l'achevement du programme ; applicable seulement si une reception/livraison est mentionnee dans les donnees ou les documents.",
                     file_aliases=["attestation_livraison", "reception", "livraison"],
                     auto_detection="filename_or_content", content_markers=["reception", "livraison", "achevement"]),
                item("PROCURATION", "Procuration",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable uniquement si une partie est representee.",
                     file_aliases=["procuration", "mandat", "power_of_attorney"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat"]),
            ],
            "manual_checks": [
                "Verification manuelle : identification du programme, TF, superficie, delai de livraison, garanties, echeancier et annexes techniques.",
                "Les contrats VEFA doivent faire l'objet d'une verification renforcee des mentions et garanties applicables.",
            ],
        },

        # ------------------------------------------------------ VENTE_FONDS_COMMERCE
        "VENTE_FONDS_COMMERCE": {
            "label": "Vente de fonds de commerce",
            "items": [
                item("ACTE_VENTE_FONDS", "Acte de vente de fonds de commerce",
                     file_aliases=["vente_fonds_commerce", "acte_vente_fonds", "fonds_commerce"]),
                item("REGISTRE_COMMERCE", "Registre de commerce et identifiants de l'entreprise",
                     file_aliases=["registre_commerce", "rc", "ice", "identifiant_fiscal"]),
                item("IDENTITE_PARTIES", "Piece d'identite vendeur / acquereur ou documents societe",
                     file_aliases=["cin_vendeur", "cin_acquereur", "statuts", "pouvoirs_societe"]),
                item("BAIL_COMMERCIAL", "Bail commercial ou titre d'occupation",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["bail_commercial", "contrat_bail", "autorisation_bailleur"],
                     help_text="Si applicable au fonds concerne."),
                item("ETAT_INSCRIPTIONS", "Etat des inscriptions, nantissements ou privileges",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["etat_inscriptions", "nantissement", "privilege"]),
                item("INVENTAIRE_ELEMENTS", "Inventaire des elements cedes",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["inventaire", "elements_cedes"],
                     help_text="Si prevu par l'acte."),
                item("JUSTIFICATIF_PAIEMENT", "Justificatif de paiement / consignation",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["virement", "consignation", "preuve_paiement"]),
                item("PROCURATION", "Procuration",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable uniquement si une partie est representee.",
                     file_aliases=["procuration", "mandat", "power_of_attorney"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat"]),
            ],
            "manual_checks": [
                "Verification manuelle : qualite des parties, RC, bail, inscriptions, elements cedes, prix, formalites de publicite et d'opposition.",
            ],
        },

        # ------------------------------------------------------------ CREATION_SOCIETE
        "CREATION_SOCIETE": {
            "label": "Creation de societe (dont SARL)",
            "aliases_types": ["SARL"],
            "items": [
                item("STATUTS", "Statuts originaux", file_aliases=["statuts", "statuts_societe"]),
                item("REQUISITION_CREATION", "Requisition de creation de societe",
                     file_aliases=["requisition_creation", "creation_societe"]),
                item("MODELE_J", "Modele J / formulaire ou document equivalent",
                     file_aliases=["modele_j", "model_j"]),
                item("ANNONCE_LEGALE", "Annonce legale / attestation de publication",
                     file_aliases=["annonce_legale", "journal_annonces_legales", "publication_legale"]),
                item("NOTIFICATION_IDENTIFIANTS", "Notification des identifiants / documents du CRI",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["notification_identifiants", "cri", "identifiants"],
                     help_text="Si applicable selon le circuit de creation (CRI)."),
                item("REGISTRE_COMMERCE", "Registre de commerce ou demande d'immatriculation",
                     file_aliases=["registre_commerce", "rc", "immatriculation"]),
                item("CIN_ASSOCIES", "Pieces d'identite des associes et du gerant",
                     file_aliases=["cin_associe", "cin_gerant", "id_associe", "id_gerant"]),
                item("JUSTIFICATIF_SIEGE", "Justificatif du siege social",
                     required=False, conditional="siege_renseigne",
                     condition_description="Applicable uniquement si le siege social est renseigne dans les donnees du dossier.",
                     file_aliases=["bail_siege", "domiciliation", "titre_siege"]),
                item("PROCURATION", "Procuration / pouvoir",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable si un signataire represente un associe.",
                     file_aliases=["procuration", "mandat", "power_of_attorney"],
                     auto_detection="filename_or_content", content_markers=["procuration", "mandat", "pouvoir"]),
            ],
            "manual_checks": [
                "Verification manuelle : denomination, objet social, capital, apports, siege, gerance, identite des associes, signatures et formalites d'immatriculation.",
            ],
        },

        # -------------------------------------------------------------- GERANCE_LIBRE
        "GERANCE_LIBRE": {
            "label": "Gerance libre",
            "items": [
                item("CONTRAT_GERANCE", "Contrat de gerance libre",
                     file_aliases=["gerance_libre", "contrat_gerance"]),
                item("REGISTRE_COMMERCE", "Registre de commerce du proprietaire et du gerant",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["registre_commerce", "rc"]),
                item("IDENTITE_PARTIES", "Pieces d'identite / pouvoirs des parties",
                     file_aliases=["cin_proprietaire", "cin_gerant", "pouvoirs_societe"]),
                item("BAIL_LOCAUX", "Bail ou justificatif de jouissance des locaux",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["bail_commercial", "contrat_bail"]),
                item("ELEMENTS_FONDS", "Elements relatifs au fonds de commerce",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["fonds_commerce", "inventaire", "inscriptions"]),
                item("ANNONCE_LEGALE", "Annonce legale / publication",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=["annonce_legale", "publication"],
                     help_text="Si prevue dans la procedure de l'etude."),
            ],
            "manual_checks": [
                "Verification manuelle : identite et qualite des parties, objet du fonds, duree, redevance, responsabilites, formalites de publicite.",
            ],
        },

        # ------------------------------------------------------- DEMANDES_ADMINISTRATIVES
        "DEMANDES_ADMINISTRATIVES": {
            "label": "Demandes administratives diverses",
            "items": [
                item("DEMANDE_SIGNEE", "Demande ou requete signee",
                     file_aliases=["requisition", "demande", "lettre", "requete"]),
                item("PIECE_JUSTIFICATIVE_OBJET", "Piece justificative correspondant a l'objet de la demande",
                     required=False, conditional=None, auto_detection="manual",
                     file_aliases=[],
                     help_text="Alias configurables par sous-type (conservateur, modele J, journal officiel, licence municipale, administration fiscale, mainlevee/radiation)."),
                item("CIN_OU_POUVOIR_SIGNATAIRE", "Piece d'identite ou pouvoir du signataire",
                     required=False, conditional="representation_detectee",
                     condition_description="Applicable si le signataire agit en representation d'un tiers.",
                     file_aliases=["cin_signataire", "procuration", "pouvoir"],
                     auto_detection="filename_or_content", content_markers=["procuration", "pouvoir"]),
                item("ANNEXES_CITEES", "Documents annexes cites dans la demande",
                     required=False, conditional=None, auto_detection="filename_or_content",
                     file_aliases=[], content_markers=["pieces jointes", "المرفقات"],
                     help_text=(
                         "Detection possible a partir d'une section 'PIECES JOINTES' ou 'المرفقات' si "
                         "l'extraction du document est disponible. Les annexes citees ne sont jamais "
                         "declarees presentes sans fichier correspondant reellement detecte."
                     )),
            ],
            "subtypes": [
                "requete_au_conservateur", "modele_j", "demande_publication_journal_officiel",
                "demande_licence_municipale", "demande_administration_fiscale", "demande_mainlevee_radiation",
            ],
            "manual_checks": [
                "Verification manuelle : destinataire, objet, references, annexes, signature et date.",
                "Chaque sous-type a sa propre liste de pieces ; les annexes citees peuvent etre proposees comme 'a verifier', mais jamais declarees presentes sans fichier.",
            ],
        },
    },
}


def main() -> None:
    out_path = Path(__file__).resolve().parent.parent / "app" / "config" / "document_checklists.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Fichier de configuration VERSIONNE des checklists documentaires metier.\n"
        "# Editable directement par l'etude (ajout/retrait de pieces, alias de fichiers, etc.).\n"
        "# Genere initialement par scripts/_gen_document_checklists.py ; ce script peut servir de\n"
        "# base pour une regeneration complete, mais n'est pas necessaire pour des ajustements ponctuels.\n"
        "#\n"
        "# Ce fichier NE constitue PAS une liste legale universelle. Les checklists doivent etre\n"
        "# revues et adaptees par l'etude notariale. La presence d'un fichier ne vaut jamais\n"
        "# validation juridique : la validite, l'actualite, les signatures, les originaux et la\n"
        "# conformite des pieces doivent toujours etre verifiees par le notaire.\n\n"
    )
    text = yaml.safe_dump(CONFIG, allow_unicode=True, sort_keys=False, width=100)
    out_path.write_text(header + text, encoding="utf-8")
    print(f"Ecrit : {out_path} ({out_path.stat().st_size} octets)")


if __name__ == "__main__":
    main()
