"""Recherche VOLONTAIRE de situations documentaires similaires (multi-dossiers autorisés).

Ce module est strictement isolé de l'Assistant documentaire d'un dossier :
- activation EXPLICITE par le notaire (`enabled=True`) ; il n'est JAMAIS utilisé comme
  fallback automatique d'une question posée dans un dossier sélectionné ;
- le RAG de dossier conserve son filtre `dossier_id` obligatoire (aucun code de ce module
  n'est appelé par app/services/rag_service.py) ;
- les collections, chunks, index et embeddings ne sont ni lus ni modifiés : seules les
  métadonnées de dossier (dossier_master) sont utilisées ;
- résultats anonymisés par défaut : type, année, variante et point commun uniquement.
  Jamais de nom complet, CIN, adresse, titre foncier, montant, texte intégral, document
  source ni score de similarité ;
- les modèles internes et les textes juridiques ne sont jamais interrogés ici.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from app.services.public_labels import public_type_label, public_variant_label

TYPE_OPTIONS = [
    "Tous les dossiers autorisés",
    "Vente immobilière",
    "Hypothèque",
    "Donation",
    "Succession",
    "Procuration",
    "VEFA",
    "Vente de fonds de commerce",
    "Création de société",
    "Gérance libre",
]

AVERTISSEMENT_SIMILARES = (
    "Les résultats sont fournis à titre de comparaison documentaire. "
    "Ils ne constituent pas un précédent juridique ni un modèle prêt à réutiliser."
)

_POINTS_COMMUNS = [
    ("paiement_differe", "Un paiement immédiat et un solde différé sont indiqués."),
    ("mixte_comptabilite", "Une partie du prix passe par la comptabilité du notaire et une autre est versée directement."),
    ("hors_comptabilite", "Le paiement est indiqué hors comptabilité du notaire."),
    ("financement_bancaire", "Un financement bancaire est mentionné."),
    ("caution", "Une caution hypothécaire est mentionnée."),
    ("hypotheque", "Une hypothèque est constituée."),
    ("donation_parent_enfant", "Une donation entre parent et enfant est indiquée."),
    ("donation", "Une donation est mentionnée."),
    ("succession", "Une succession est en cause."),
    ("procuration", "Une procuration est mentionnée."),
    ("vefa", "Une vente en l'état futur d'achèvement est en cause."),
    ("fonds_de_commerce", "Un fonds de commerce est en cause."),
    ("societe", "Une création de société est en cause."),
    ("gerance_libre", "Une gérance libre est en cause."),
    ("vente", "Une vente immobilière est en cause."),
]


def _traits(master: dict) -> dict:
    donnees = master.get("donnees") if isinstance(master.get("donnees"), dict) else {}
    variante = (master.get("variante") or "").lower()
    type_dossier = str(master.get("type_dossier") or "").upper()
    return {
        "paiement_differe": bool(donnees.get("solde_differe_dhs")) or "paiement_differe" in variante,
        "hors_comptabilite": "hors_comptabilite" in variante,
        "mixte_comptabilite": "mixte_comptabilite" in variante
        or (donnees.get("paiement_immediat_dhs") is not None and donnees.get("solde_differe_dhs") is not None),
        "financement_bancaire": bool(donnees.get("banque")) or "tripartite" in variante
        or bool(donnees.get("montant_credit_dhs")) or bool(donnees.get("credit_garanti_dhs")),
        "hypotheque": bool(donnees.get("rang_hypotheque")) or bool(donnees.get("rang"))
        or "HYPOTHEQUE" in type_dossier,
        "caution": "caution" in variante,
        "donation": "DONATION" in type_dossier,
        "donation_parent_enfant": "DONATION" in type_dossier
        and bool(donnees.get("donateur")) and bool(donnees.get("donataire")),
        "succession": "SUCCESSION" in type_dossier,
        "procuration": "PROCURATION" in type_dossier,
        "vefa": "VEFA" in type_dossier or "vefa" in variante,
        "fonds_de_commerce": "fonds" in variante or "FONDS" in type_dossier,
        "societe": "SOCIETE" in type_dossier or "SARL" in type_dossier,
        "gerance_libre": "gerance" in variante,
        "vente": "VENTE" in type_dossier,
        "annee": str(master.get("annee") or ""),
    }


def point_commun(traits: dict) -> str:
    """Point commun déterministe, fondé sur les traits structurés (aucune donnée privée)."""
    for cle, libelle in _POINTS_COMMUNS:
        if traits.get(cle):
            return libelle
    return "Les dossiers partagent un même type d'opération."


def anonymized_catalog(dossiers_dir: Path, authorized_ids: Optional[list[str]] = None) -> list[dict]:
    """Catalogue anonymisé des dossiers autorisés (type, année, variante, traits)."""
    dossiers_dir = Path(dossiers_dir)
    if not dossiers_dir.exists():
        return []
    out: list[dict] = []
    for path in sorted(dossiers_dir.iterdir()):
        if not path.is_dir():
            continue
        dossier_id = path.name
        if authorized_ids is not None and dossier_id not in authorized_ids:
            continue
        master_path = path / "dossier_master.json"
        if not master_path.exists():
            continue
        try:
            master = json.loads(master_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out.append({
            "dossier_id": dossier_id,
            "type_public": public_type_label(master.get("type_dossier")),
            "variante_public": public_variant_label(master.get("type_dossier"), master.get("variante")),
            "annee": str(master.get("annee") or ""),
            "traits": _traits(master),
        })
    return out


def _requete_traits(query: str) -> dict:
    q = re.sub(r"[^\w\sà-ÿ\u0600-\u06FF]", " ", (query or "").lower())
    return {
        "paiement_differe": any(k in q for k in ("différé", "differe", "échéance", "echeance", "solde")),
        "hors_comptabilite": any(k in q for k in ("hors comptabilité", "hors comptabilite", "hors contrôle", "hors controle")),
        "mixte_comptabilite": "mixte" in q or "comptabilité du notaire" in q or "comptabilite du notaire" in q,
        "financement_bancaire": any(k in q for k in ("financement", "finance", "crédit", "credit", "prêt", "pret", "banque", "hypothèque", "hypotheque", "caution")),
        "caution": "caution" in q,
        "hypotheque": any(k in q for k in ("hypothèque", "hypotheque", "rang")),
        "donation": any(k in q for k in ("donation", "donateur", "donataire", "parent", "enfant")),
        "donation_parent_enfant": any(k in q for k in ("parent", "enfant")),
        "succession": any(k in q for k in ("succession", "héritier", "heritier", "défunt", "defunt", "décès", "deces")),
        "procuration": any(k in q for k in ("procuration", "mandat", "mandant", "mandataire")),
        "vefa": any(k in q for k in ("vefa", "état futur", "etat futur", "achèvement", "achevement")),
        "fonds_de_commerce": "fonds de commerce" in q,
        "societe": any(k in q for k in ("société", "societe", "sarl", "rc")),
        "gerance_libre": "gérance" in q or "gerance" in q,
        "vente": any(k in q for k in ("vente", "vendre")),
    }


def search_similar(
    query: str,
    catalog: list[dict],
    *,
    enabled: bool = False,
    type_filter: Optional[str] = None,
    annee_filter: Optional[str] = None,
    variante_filter: Optional[str] = None,
    max_results: int = 6,
) -> list[dict]:
    """Recherche de situations comparables. Activation EXPLICITE obligatoire :
    sans `enabled=True`, aucune recherche n'est lancée (jamais de fallback automatique)."""
    if not enabled or not (query or "").strip():
        return []
    wanted = _requete_traits(query)
    scored: list[tuple[int, dict]] = []
    for item in catalog:
        if type_filter and type_filter != "Tous les dossiers autorisés" and item["type_public"] != type_filter:
            continue
        if annee_filter and item["annee"] != str(annee_filter):
            continue
        if variante_filter and variante_filter != "Toutes" and item["variante_public"] != variante_filter:
            continue
        traits = item["traits"]
        score = sum(1 for k, v in wanted.items() if v and traits.get(k))
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    results: list[dict] = []
    for _score, item in scored[:max_results]:
        # Résultat anonymisé : aucun nom, CIN, adresse, TF, montant, texte, fichier ni score.
        results.append({
            "dossier_id": item["dossier_id"],
            "type_public": item["type_public"],
            "annee": item["annee"],
            "variante_public": item["variante_public"],
            "point_commun": point_commun(item["traits"]),
        })
    return results
