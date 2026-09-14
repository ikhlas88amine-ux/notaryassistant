"""Présentation métier des résultats Modèles internes et Recherche juridique.

Fonctions pures et déterministes : elles reçoivent des dicts de résultats déjà validés
et ne produisent que des libellés métier lisibles. Aucun score, extrait technique,
nom de fichier brut, chemine locale, hash, index ni nom de modèle local n'est exposé
au notaire par ces fonctions.
"""
from __future__ import annotations

import re
from typing import Optional

PRINCIPAUX_LIMIT = 3

AVERTISSEMENT_MODELE = (
    "Ce modèle est fourni à titre de référence.\n"
    "Les informations variables doivent être adaptées et validées par le notaire."
)

A_VERIFIER_JURIDIQUE = (
    "Le texte officiel applicable et ses éventuelles mises à jour doivent être vérifiés par le notaire."
)

REFERENCE_A_VERIFIER = "Référence juridique à vérifier dans la source officielle."

# Libellés métier des types de modèles internes de l'étude (classification existante).
MODELE_TITRES_METIER = {
    "cession_fonds_de_commerce": "Cession de fonds de commerce",
    "vente_immeuble_etat_futur_achevement": "Vente en l'état futur d'achèvement",
    "vente_avec_hypotheque_bancaire_tripartite": "Vente avec financement bancaire tripartite",
    "vente_immobiliere_avec_credit_vendeur_double_hypotheque": "Vente avec crédit vendeur et double hypothèque",
    "clause_prix_bilingue_incoherente": "Clause de prix bilingue à clarifier",
    "clause_prix_paiement_differe": "Clause de paiement différé du prix",
    "clause_prix_mixte_comptabilite": "Clause de paiement mixte du prix",
    "clause_prix_hors_comptabilite_totale": "Clause de paiement hors comptabilité du notaire",
    "engagement_hypothecaire_1er_rang": "Engagement hypothécaire de premier rang",
    "engagement_hypothecaire_avec_caution": "Engagement hypothécaire avec caution",
    "mainlevee_hypotheque_bancaire": "Mainlevée d'hypothèque bancaire",
    "requisition_radiation_hypotheque": "Réquisition de radiation d'hypothèque",
    "autorisation_prelevement_sur_prix": "Autorisation de prélèvement sur le prix",
    "engagement_conditionnel_apres_mainlevee": "Engagement conditionnel après mainlevée",
    "lettre_rectificative_recu": "Lettre rectificative de reçu",
    "attestation_liberation_local_commercial": "Attestation de libération de local commercial",
    "acte_gerance_libre_fonds_de_commerce": "Acte de gérance libre de fonds de commerce",
    "demande_publication_bulletin_officiel": "Demande de publication au Bulletin officiel",
    "demande_exoneration_majorations_fiscales": "Demande d'exonération de majorations fiscales",
    "demande_licence_exploitation_communale": "Demande de licence d'exploitation communale",
    "requisition_ouverture_dossier_societe": "Réquisition d'ouverture de dossier de société",
    "requisition_modele_j": "Réquisition au registre de commerce",
    "donation_sadaka_irrevocable": "Donation irrévocable (sadaka)",
    "demande_attestation_paiement_impots_taxes": "Demande d'attestation de paiement",
}

# Marqueurs sémantiques -> éléments explicitement présents dans l'extrait.
_MARQUEURS_ELEMENTS = [
    (r"consign", "consignation d'une partie du prix"),
    (r"déblocage|deblocage", "déblocage au profit du vendeur"),
    (r"enregistrement", "formalités d'enregistrement"),
    (r"inscription foncière|inscription fonciere|immatriculation", "inscription foncière"),
    (r"paiement différé|solde différé|solde differe", "paiement immédiat et solde différé"),
    (r"hors comptabilité|hors comptabilite", "paiement hors comptabilité du notaire"),
    (r"comptabilité du notaire|comptabilite du notaire", "passage par la comptabilité du notaire"),
    (r"hypothèque|hypotheque", "constitution d'hypothèque"),
    (r"caution", "caution hypothécaire"),
    (r"premier rang|1[èe]r rang", "engagement de premier rang"),
    (r"radiation", "radiation de l'inscription"),
    (r"mainlevée|mainlevee", "mainlevée"),
    (r"financement|prêt|pret|crédit|credit", "financement bancaire"),
    (r"donation|صدقة", "donation"),
    (r"succession|héritier|heritier|décès|deces", "succession"),
    (r"procuration|mandat", "procuration"),
    (r"gérance|gerance", "gérance libre"),
    (r"fonds de commerce", "fonds de commerce"),
    (r"société|societe|sarl", "création de société"),
    (r"vente", "vente immobilière"),
]


def _humanize(snake: str) -> str:
    return re.sub(r"([a-zà-ÿ])([A-ZÀ-Ý])", r"\1 \2", (snake or "").replace("_", " ").strip()).capitalize()


# --------------------------------------------------------------------------- Modèles
def modele_titre_metier(chunk: dict) -> str:
    """Titre métier du modèle : jamais d'underscore, jamais de nom de fichier brut."""
    t = (chunk.get("type_modele") or "").strip()
    if t:
        return MODELE_TITRES_METIER.get(t, _humanize(t))
    return _humanize((chunk.get("fichier") or "Modèle").rsplit(".", 1)[0].replace("-", " ") or "Modèle")


def modele_source_name(chunk: dict) -> str:
    """Nom lisible de la source du modèle (extension et symboles retirés)."""
    t = (chunk.get("type_modele") or "").strip()
    if t:
        return MODELE_TITRES_METIER.get(t, _humanize(t))
    f = (chunk.get("fichier") or "").strip()
    if not f:
        return "Modèle interne de l'étude"
    stem = f.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip()
    return _humanize(stem) or "Modèle interne de l'étude"


def modele_description(chunk: dict, limit: int = 260) -> str:
    """Description factuelle courte, fondée uniquement sur l'extrait validé."""
    texte = " ".join(((chunk.get("text") or chunk.get("excerpt") or "") or "").split())
    if not texte:
        return "Extrait non disponible dans le modèle."
    return (texte[:limit] + "…") if len(texte) > limit else texte


def modele_elements(chunk: dict, max_items: int = 6) -> list[str]:
    """Éléments explicitement présents dans l'extrait (jamais d'inférence)."""
    texte = (
        ((chunk.get("text") or chunk.get("excerpt") or "") or "")
        + " "
        + (chunk.get("section") or "")
    ).lower()
    out: list[str] = []
    for motif, libelle in _MARQUEURS_ELEMENTS:
        if re.search(motif, texte) and libelle not in out:
            out.append(libelle)
        if len(out) >= max_items:
            break
    if not out:
        section = (chunk.get("section") or "").strip()
        out.append(_humanize(section) if section else "contenu du modèle disponible dans l'extrait")
    return out


def carte_modele(chunk: dict) -> dict:
    return {
        "titre": modele_titre_metier(chunk),
        "source": modele_source_name(chunk),
        "description": modele_description(chunk),
        "elements": modele_elements(chunk),
        "avertissement": AVERTISSEMENT_MODELE,
    }


def partition_modele_results(chunks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Résultats principaux (affichés par défaut) puis résultats secondaires
    (repliés sous « Autres résultats potentiels »)."""
    chunks = [c for c in (chunks or []) if c]
    return chunks[:PRINCIPAUX_LIMIT], chunks[PRINCIPAUX_LIMIT:]


# ----------------------------------------------------------------------- Juridique
def juridique_titre(chunk: dict) -> str:
    """Nom officiel du texte juridique, ou mention explicite à vérifier si indisponible."""
    nom = (chunk.get("law_name") or "").strip()
    return nom or REFERENCE_A_VERIFIER


def juridique_article_label(chunk: dict) -> str:
    """Libellé d'article UNIQUEMENT si le numéro est disponible (jamais inventé)."""
    article = (chunk.get("article_num") or "").strip()
    return f"Article {article}" if article else ""


def juridique_extrait(chunk: dict, limit: int = 1400) -> str:
    texte = " ".join(((chunk.get("text") or chunk.get("excerpt") or "") or "").split())
    if not texte:
        return "Extrait juridique non disponible."
    return (texte[:limit] + "…") if len(texte) > limit else texte


def reponse_documentaire(extrait: str, limit: int = 280) -> str:
    """Résumé court, uniquement fondé sur l'extrait (déterministe : première phrase)."""
    texte = re.sub(r"\s+", " ", (extrait or "")).strip()
    if not texte:
        return "Extrait non disponible."
    for separateur in (". ", "! ", "? "):
        idx = texte.find(separateur)
        if 0 < idx <= limit:
            texte = texte[: idx + 1]
            break
    if len(texte) > limit:
        texte = texte[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return texte


def carte_juridique(chunk: dict) -> dict:
    extrait = juridique_extrait(chunk)
    return {
        "titre": juridique_titre(chunk),
        "article": juridique_article_label(chunk),
        "extrait": extrait,
        "reponse": reponse_documentaire(extrait),
        "a_verifier": A_VERIFIER_JURIDIQUE,
    }


def partition_juridique_results(chunks: list[dict]) -> tuple[Optional[dict], list[dict]]:
    """Le plus pertinent est affiché ; les autres articles sont repliés dans un bloc
    « Autres articles potentiellement utiles » (dédupliqués par article)."""
    chunks = [c for c in (chunks or []) if c]
    if not chunks:
        return None, []
    principal = carte_juridique(chunks[0])
    autres: list[dict] = []
    vus: set[str] = set()
    for c in chunks[1:]:
        cle = (c.get("article_num") or c.get("chunk_id") or "")
        if cle in vus:
            continue
        vus.add(cle)
        autres.append(carte_juridique(c))
    return principal, autres
