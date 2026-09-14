from __future__ import annotations

from typing import Any, Optional

TECHNICAL_DIFFICULTY_MESSAGE = (
    "Une difficulté technique empêche momentanément cette action.\n"
    "Aucune modification n’a été apportée aux documents.\n"
    "Réessayez ultérieurement ou contactez le support."
)

NOTARY_WARNING = (
    "Les contrôles sont automatisés à partir des données et documents disponibles. "
    "Ils ne remplacent pas la vérification juridique, documentaire et fiscale du notaire."
)

TYPE_LABELS = {
    "AMBIGU": "Vente immobilière",
    "VENTE": "Vente immobilière",
    "HYPOTHEQUE": "Hypothèque",
    "MAINLEVEE": "Mainlevée",
    "DONATION": "Donation",
    "SUCCESSION": "Succession",
    "PROCURATION": "Procuration",
    "VEFA": "VEFA",
    "VENTE_FONDS_COMMERCE": "Vente de fonds de commerce",
    "VENTE-FONDS-COMMERCE": "Vente de fonds de commerce",
    "CREATION_SOCIETE": "Création de société",
    "SARL": "Création de société",
    "GERANCE_LIBRE": "Gérance libre",
    "DEMANDE_ADMINISTRATIVE": "Demande administrative",
    "DEMANDES_ADMINISTRATIVES": "Demande administrative",
    "VENTE-AUTO": "Vente immobilière",
}

VARIANT_LABELS = {
    "simple": "Standard",
    "paiement_differe": "Paiement différé",
    "hors_comptabilite": "Paiement direct entre les parties",
    "mixte_comptabilite": "Paiement mixte",
    "tripartite_bancaire": "Vente avec financement bancaire",
    "terrain_nu_engagement_construire": "Terrain avec engagement de construire",
    "vefa": "VEFA",
    "fonds_de_commerce": "Vente de fonds de commerce",
    "engagement_1er_rang": "Engagement d’inscription hypothécaire",
    "engagement_avec_caution": "Engagement avec caution hypothécaire",
    "mainlevee": "Mainlevée",
    "standard": "Standard",
    "prix_contradictoire_fr_ar": "Prix à clarifier",
    "double_tf_double_prix": "Prix à clarifier",
}

PUBLIC_STATES = {
    "invalid": "Attention requise",
    "warnings": "Vérification recommandée",
    "valid": "Conforme selon les contrôles automatiques",
}

LEVEL_LABELS = {
    "blocking": "Attention requise",
    "warning": "Vérification recommandée",
    "info": "Information",
    "attention_requise": "Attention requise",
    "verification_recommandee": "Vérification recommandée",
    "information": "Information",
}


def public_type_label(type_dossier: Optional[str]) -> str:
    key = (type_dossier or "").strip().upper()
    return TYPE_LABELS.get(key, (type_dossier or "Dossier").replace("_", " ").strip() or "Dossier")


def public_variant_label(type_dossier: Optional[str], variante: Optional[str]) -> str:
    if (type_dossier or "").strip().upper() == "AMBIGU":
        return "Prix à clarifier"
    key = (variante or "").strip().lower()
    if not key:
        return "Non précisée"
    return VARIANT_LABELS.get(key, (variante or "").replace("_", " ").strip().capitalize())


def public_state_label(validation_status: Optional[str]) -> str:
    return PUBLIC_STATES.get((validation_status or "").strip().lower(), "Vérification recommandée")


def level_label(level: Optional[str]) -> str:
    return LEVEL_LABELS.get((level or "").strip().lower(), "Information")


def public_reference(master: dict[str, Any]) -> str:
    famille = master.get("client_famille")
    dossier_id = master.get("dossier_id") or "Dossier"
    return f"{dossier_id} — {famille}" if famille else str(dossier_id)


def ambigu_pricing_message(master: dict[str, Any]) -> str:
    donnees = master.get("donnees") if isinstance(master.get("donnees"), dict) else {}
    fr = donnees.get("prix_dhs_version_fr", "1 650 000")
    ar = donnees.get("prix_dhs_version_ar", "340 000")
    return (
        "Deux prix incompatibles sont indiqués dans les documents du dossier.\n\n"
        f"Version française : {format_amount(fr)} DHS.\n"
        f"Version arabe : {format_amount(ar)} DHS.\n\n"
        "Action :\n"
        "Clarifier le prix réel avec les parties avant la rédaction définitive."
    )


def format_amount(value: Any) -> str:
    if value is None or value == "":
        return "Non indiqué"
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"{int(value):,}".replace(",", " ")
        return f"{value:,}".replace(",", " ")
    return str(value)


def clean_value(value: Any) -> str:
    if value is None or value == "":
        return "Non indiqué"
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    return str(value)


def dossier_public_card(master: dict[str, Any], validation_status: Optional[str]) -> dict[str, str]:
    return {
        "type": public_type_label(master.get("type_dossier")),
        "variante": public_variant_label(master.get("type_dossier"), master.get("variante")),
        "etat": public_state_label(validation_status),
        "reference": clean_value(master.get("client_famille")),
        "annee": clean_value(master.get("annee")),
    }
