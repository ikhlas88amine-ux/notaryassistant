"""Filtre de pertinence des chunks par intention de la question.

Déterministe, sans LLM : on détecte l'intention de la question, puis on reclassse / filtre les
citations récupérées selon leurs métadonnées (chunk_role, section, entités, source, texte).

Règles de sortie :
- on garde des extraits dédupliqués ;
- documents manquants -> seuls les rapports de validation / checklists structurées sont admis,
  sinon abstention ;
- risques -> anomalies explicites uniquement ;
- modèles -> source=='modele' uniquement ;
- droit -> source=='loi' uniquement.
"""
from __future__ import annotations

import re
from typing import Optional

INTENT_PARTIES = "parties"
INTENT_PRICE = "price"
INTENT_FINANCING = "financing"
INTENT_MISSING_DOCUMENTS = "missing_documents"
INTENT_RISKS = "risks"
INTENT_MODELS = "models"
INTENT_LEGAL = "legal"
INTENT_RESUME = "resume"
INTENT_OTHER = "other"
INTENT_LAND_TITLE = "land_title"
INTENT_AREA = "area"
INTENT_BORROWER = "borrower"
INTENT_DONATION = "donation"
INTENT_SUCCESSION = "succession"
INTENT_PROCURATION = "procuration"
INTENT_ACCOUNTING = "accounting"

_INTENT_KEYWORDS: dict[str, list[str]] = {
    INTENT_MISSING_DOCUMENTS: [
        "manque", "manquants", "manquante", "missing", "absent", "absents", "pièces manquantes",
        "pieces manquantes", "documents manquants", "à fournir", "a fournir", "non reçu",
        "non recu", "non reçue", "en attente", "manquent", "quels documents",
    ],
    INTENT_RISKS: [
        "risque", "incohérence", "incoherence", "contradiction", "anomalie", "divergence",
        "problème", "probleme", "écart", "ecart", "alerte", "danger", "conflit", "incompatible",
        "version française", "version francaise", "version arabe",
    ],
    INTENT_ACCOUNTING: [
        "comptabilité", "comptabilite", "hors comptabilité", "hors comptabilite", "consignation",
        "transité", "transite", "notaire", "prix transité", "prix transite", "خارج محاسبته",
        "مراقبة أداء هذا المبلغ",
    ],
    INTENT_LAND_TITLE: [
        "titre foncier", "tf", "immatriculation", "propriété", "propriete", "bien",
        "régime foncier", "regime foncier", "الرسم العقاري",
    ],
    INTENT_AREA: [
        "superficie", "surface", "m²", "m2", "metres carres", "mètres carrés", "hectare",
        "ares", "مساحة",
    ],
    INTENT_BORROWER: [
        "emprunteur", "emprunteurs", "débiteur", "debiteur", "débiteurs", "debiteurs",
        "crédit", "credit", "prêt", "pret", "loan", "المقترض",
    ],
    INTENT_DONATION: [
        "donateur", "donataire", "premier comparant", "second comparant", "donation",
        "valeur déclarée", "valeur declaree", "droits d'enregistrement", "droits d enregistrement",
        "متصدق", "المتصدق", "ابن المتصدق", "صدقة",
    ],
    INTENT_SUCCESSION: [
        "défunt", "defunt", "décès", "deces", "héritier", "heritier", "héritiers", "heritiers",
        "part successorale", "succession", "faraid", "تركة", "ورثة",
    ],
    INTENT_PROCURATION: [
        "mandant", "mandataire", "pouvoir", "objet", "durée", "duree", "procuration",
        "وكيل", "موكل",
    ],
    INTENT_FINANCING: [
        "financement", "finance", "financé", "financee", "financée", "crédit", "credit",
        "crédits", "credits", "prêt", "pret", "prêts", "prets", "hypothèque", "hypotheque",
        "hypothèques", "hypotheques", "taux", "garantie", "caution", "emprunt",
        "remboursement", "rang", "banque", "fogalef", "قرض", "رهن", "تمويل", "بنك",
    ],
    INTENT_PRICE: [
        "prix", "montant", "dhs", "dh ", "dirham", "payé comptant", "paye comptant",
        "coût de", "cout de", "combien", "الثمن", "درهم", "مبلغ", "valeur",
    ],
    INTENT_PARTIES: [
        "vendeur", "venderesse", "acquéreur", "acquereur", "acquéreurs", "acquereurs", "acheteur",
        "co-acquéreur", "coacquereur", "représentant", "representant", "gérant", "gerant",
        "mandataire", "parties", "intervenant", "prêteur", "preteur", "banque", "qui sont",
        "identité", "identite", "donateur", "donataire", "défunt", "defunt", "héritier",
        "heritier", "mandant", "premier comparant", "second comparant", "ont comparu",
        "إسم", "البائع", "المشتري",
    ],
    INTENT_MODELS: [
        "modèle", "modele", "modèles", "modeles", "clause type", "formulaire", "réquisition",
        "requisition", "mainlevée", "mainlevee", "modèle interne", "modele interne", "acte type",
    ],
    INTENT_LEGAL: [
        "article", "loi", "code civil", "disposition", "juridique", "validité", "validite",
        "opposabilité", "opposabilite", "publicité foncière", "publicite fonciere", "saisie",
        "rétention", "retention", "formalités", "formalites", "droit", "régime", "regime",
        "obligation légale", "obligation legale", "nullité", "nullite",
    ],
    INTENT_RESUME: [
        "résumé", "resume", "synthèse", "synthese", "récapitulatif", "recapitulatif",
        "état du dossier", "etat du dossier", "avancement", "vue d'ensemble", "vue densemble",
    ],
}

_INTENT_PRIORITY = [
    INTENT_MISSING_DOCUMENTS,
    INTENT_RISKS,
    INTENT_ACCOUNTING,
    INTENT_LAND_TITLE,
    INTENT_AREA,
    INTENT_BORROWER,
    INTENT_DONATION,
    INTENT_SUCCESSION,
    INTENT_PROCURATION,
    INTENT_FINANCING,
    INTENT_PRICE,
    INTENT_PARTIES,
    INTENT_MODELS,
    INTENT_LEGAL,
    INTENT_RESUME,
]


def _normalize(text: str) -> str:
    text = re.sub(r"[^\w\s\u0600-\u06FF/%²]", " ", (text or "").lower())
    text = text.replace("m²", "m2")
    return re.sub(r"\s+", " ", text).strip()


def detect_intent(query: str, scope: Optional[str] = None) -> str:
    """Détecte l'intention à partir de mots-clés (fr/ar)."""
    if scope == "law":
        return INTENT_LEGAL
    if scope == "template":
        return INTENT_MODELS

    q = _normalize(query)
    best, best_count = INTENT_OTHER, 0
    for intent in _INTENT_PRIORITY:
        keywords = _INTENT_KEYWORDS[intent]
        count = sum(1 for kw in keywords if _normalize(kw) in q)
        if count > best_count:
            best, best_count = intent, count
    return best


def value_of(item, key, default=None):
    """Accès uniforme à un attribut dict/Pydantic."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _text_haystack(c) -> str:
    parts = [
        value_of(c, "text") or "",
        value_of(c, "excerpt") or "",
        value_of(c, "section") or "",
        value_of(c, "chunk_role") or "",
        *(value_of(c, "secondary_chunk_roles") or []),
        value_of(c, "fichier") or "",
    ]
    return _normalize(" ".join(str(p) for p in parts if p))


def _entities_haystack(c) -> str:
    entities = value_of(c, "entities") or {}
    if hasattr(entities, "model_dump"):
        entities = entities.model_dump()
    if not isinstance(entities, dict):
        return ""
    vals: list[str] = []
    for value in entities.values():
        if isinstance(value, list):
            for item in value:
                vals.append(str(item))
        elif value not in (None, ""):
            vals.append(str(value))
    return _normalize(" ".join(vals))


def _entity_list(c, key: str) -> list:
    entities = value_of(c, "entities") or {}
    if hasattr(entities, "model_dump"):
        entities = entities.model_dump()
    if isinstance(entities, dict):
        value = entities.get(key) or []
        return value if isinstance(value, list) else []
    return []


def _combined_rank_score(c, intent_score: float) -> float:
    base = float(value_of(c, "score", 0.0) or 0.0)
    return intent_score * 100.0 + base


def _score_for_intent(c, intent: str) -> float:
    text = _text_haystack(c)
    entities = _entities_haystack(c)
    role = _normalize(value_of(c, "chunk_role") or "")
    section = _normalize(value_of(c, "section") or "")
    file_name = _normalize(value_of(c, "fichier") or "")
    score = 0.0

    if intent == INTENT_PARTIES:
        if role == "parties":
            score += 3.0
        if section == "identification_parties":
            score += 2.0
        for kw in (
            "vendeur", "acquereur", "acheteur", "ont comparu", "donateur", "donataire",
            "defunt", "heritier", "mandant", "mandataire", "premier comparant", "second comparant",
        ):
            if kw in text or kw in entities:
                score += 2.0
                break
        if _entity_list(c, "persons"):
            score += 1.0

    elif intent == INTENT_PRICE:
        if role in ("price", "payment"):
            score += 3.0
        if section in ("prix_paiement", "financement_hypotheque"):
            score += 2.0
        if _entity_list(c, "amounts_dhs"):
            score += 2.0
        for kw in ("prix", "montant", "valeur", "dhs", "dirham", "درهم"):
            if kw in text:
                score += 1.5
                break

    elif intent == INTENT_FINANCING:
        if role in ("financing", "mortgage"):
            score += 3.0
        if section == "financement_hypotheque":
            score += 2.0
        if _entity_list(c, "banks"):
            score += 1.5
        if _entity_list(c, "mortgage_ranks"):
            score += 1.5
        for kw in ("hypotheque", "rang", "banque", "credit", "pret", "garantie", "attijariwafa"):
            if kw in text or kw in entities:
                score += 2.0
                break

    elif intent == INTENT_MISSING_DOCUMENTS:
        if (section and "piece" in section) or "checklist" in section or "validation" in section:
            score += 3.0
        for kw in ("manquant", "a fournir", "non recu", "en attente", "checklist"):
            if kw in text:
                score += 2.0
                break

    elif intent == INTENT_RISKS:
        for kw in (
            "anomalie", "incoherence", "ne correspond pas", "ecart", "contradiction",
            "version francaise", "version arabe", "volontaire",
        ):
            if kw in text:
                score += 2.0
                break
        if "anomalie" in section or "risque" in section or "validation" in section:
            score += 1.5

    elif intent == INTENT_MODELS:
        if value_of(c, "source") == "modele":
            score += 3.0
        for kw in ("modele", "modèle", "structure legale standard", "aucun modele reel", "aucun modèle réel", "acte type"):
            if kw in text:
                score += 2.5
                break
        if role or section:
            score += 1.0

    elif intent == INTENT_LEGAL:
        if value_of(c, "source") == "loi":
            score += 3.0
        if value_of(c, "article_num"):
            score += 1.0

    elif intent == INTENT_RESUME:
        score += 1.0
        if _entity_list(c, "persons") or _entity_list(c, "amounts_dhs") or _entity_list(c, "land_titles"):
            score += 1.0

    elif intent == INTENT_LAND_TITLE:
        if _entity_list(c, "land_titles"):
            score += 5.0
        if "titre foncier" in text or "tf" in text or "الرسم العقاري" in text or "immatriculation" in text:
            score += 3.0

    elif intent == INTENT_AREA:
        if _entity_list(c, "areas_m2"):
            score += 5.0
        if any(kw in text for kw in ("superficie", "surface", "m2", "hectare", "مساحة")):
            score += 3.0

    elif intent == INTENT_BORROWER:
        if role in ("financing", "mortgage", "parties"):
            score += 1.5
        if section == "financement_hypotheque":
            score += 1.5
        if _entity_list(c, "persons"):
            score += 1.0
        for kw in ("emprunteur", "debiteur", "credit", "pret", "consenti", "mademoiselle", "madame", "monsieur"):
            if kw in text:
                score += 2.0
                break

    elif intent == INTENT_DONATION:
        if "donation" in file_name:
            score += 2.0
        for kw in (
            "donateur", "donataire", "premier comparant", "second comparant", "ابن المتصدق",
            "المتصدق", "صدقة", "valeur declaree", "droits d enregistrement",
        ):
            if kw in text or kw in entities:
                score += 3.0
                break
        if _entity_list(c, "land_titles") or _entity_list(c, "amounts_dhs") or _entity_list(c, "persons"):
            score += 1.0

    elif intent == INTENT_SUCCESSION:
        if "success" in file_name:
            score += 2.0
        for kw in ("defunt", "deces", "heritier", "part successorale", "succession", "faraid"):
            if kw in text or kw in entities:
                score += 3.0
                break
        if _entity_list(c, "land_titles") or _entity_list(c, "persons") or _entity_list(c, "dates"):
            score += 1.0

    elif intent == INTENT_PROCURATION:
        if "procuration" in file_name:
            score += 2.0
        for kw in ("mandant", "mandataire", "pouvoir", "procuration", "duree", "constitue"):
            if kw in text:
                score += 3.0
                break
        if _entity_list(c, "persons") or _entity_list(c, "land_titles"):
            score += 1.0

    elif intent == INTENT_ACCOUNTING:
        for kw in (
            "hors comptabilite", "comptabilite", "consignation", "transite", "notaire",
            "خارج محاسبته", "مراقبة أداء هذا المبلغ",
        ):
            if kw in text:
                score += 3.0
                break
        if _entity_list(c, "amounts_dhs"):
            score += 1.0

    return score


def filter_chunks(citations: list, intent: str, top_n: int = 3) -> list:
    """Reclasse et filtre les citations selon l'intention."""
    if not citations:
        return []

    if intent == INTENT_MISSING_DOCUMENTS:
        admissible = [c for c in citations if _score_for_intent(c, intent) >= 3.0]
        return admissible[:top_n]

    if intent == INTENT_MODELS:
        admissible = [c for c in citations if _score_for_intent(c, intent) > 0.0]
        seen = set()
        uniq = []
        for c in admissible:
            key = value_of(c, "fichier") if value_of(c, "source") == "modele" else value_of(c, "chunk_id")
            key = key or value_of(c, "chunk_id") or value_of(c, "fichier")
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)
        return uniq[:top_n]

    if intent == INTENT_LEGAL:
        admissible = [c for c in citations if value_of(c, "source") == "loi" and _score_for_intent(c, intent) > 0.0]
        return admissible[:top_n]

    scored = sorted(citations, key=lambda c: _combined_rank_score(c, _score_for_intent(c, intent)), reverse=True)
    keep = [c for c in scored if _score_for_intent(c, intent) > 0.0]
    if not keep:
        return []

    seen = set()
    uniq = []
    for c in keep:
        key = value_of(c, "chunk_id") or value_of(c, "fichier")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq[:top_n]


FORMAT_PARTIES = """FORMAT DE REPONSE ATTENDU - PARTIES :
Vendeur :
- ...
Representant du vendeur :
- ...
Acquereur(s) :
- ...
Representant(s) des acquereurs :
- ...
Banque / preteur :
- ...
Autres intervenants :
- ...
Sources :
- ..."""

FORMAT_PRICE = """FORMAT DE REPONSE ATTENDU - PRIX ET FINANCEMENT :
Prix de vente :
- ...
Banque / preteur :
- ...
Credits identifies :
- [personne] : [montant] DHS, taux [taux si explicitement present].
Total calcule a partir des credits cites :
- ... DHS.
Sources :
- ..."""

FORMAT_RESUME = """FORMAT DE REPONSE ATTENDU - RESUME DE DOSSIER :
Parties
Objet
Montant(s)
Bien concerne
Financement et garanties
Statut documentaire / etat d'avancement
Sources"""

FORMAT_RISKS = """FORMAT DE REPONSE ATTENDU - RISQUES :
Risques etablis par les sources :
- ...
Points a verifier :
- ...
Aucune autre incoherence ne peut etre etablie a partir des sources disponibles."""

FORMAT_MODELS = """FORMAT DE REPONSE ATTENDU - MODELES :
Modele identifie :
- Nom du fichier
- Type ou usage explicitement etabli
- Extrait pertinent
Consultation :
- Bouton / lien vers le modele original
Sources :
- ..."""

FORMAT_LEGAL = """FORMAT DE REPONSE ATTENDU - JURIDIQUE :
Reponse fondee sur les extraits juridiques disponibles :
- ...
Limite :
- Les extraits disponibles ne constituent pas necessairement une liste exhaustive.
Sources juridiques :
- Texte, article, page si connue."""

FORMAT_OTHER = """FORMAT DE REPONSE ATTENDU :
Reponse fondee uniquement sur les sources fournies, avec leurs references (fichier, section, page)."""


def format_guidance(intent: str) -> str:
    return {
        INTENT_PARTIES: FORMAT_PARTIES,
        INTENT_PRICE: FORMAT_PRICE,
        INTENT_FINANCING: FORMAT_PRICE,
        INTENT_BORROWER: FORMAT_PRICE,
        INTENT_RESUME: FORMAT_RESUME,
        INTENT_RISKS: FORMAT_RISKS,
        INTENT_MODELS: FORMAT_MODELS,
        INTENT_LEGAL: FORMAT_LEGAL,
        INTENT_DONATION: FORMAT_PARTIES,
        INTENT_SUCCESSION: FORMAT_PARTIES,
        INTENT_PROCURATION: FORMAT_PARTIES,
        INTENT_LAND_TITLE: FORMAT_OTHER,
        INTENT_AREA: FORMAT_OTHER,
        INTENT_ACCOUNTING: FORMAT_OTHER,
        INTENT_OTHER: FORMAT_OTHER,
    }.get(intent, FORMAT_OTHER)
