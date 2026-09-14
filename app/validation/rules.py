"""Regles de validation de la coherence d'un dossier notarial fictif.

Chaque regle prend en entree le `dossier_master.json` deserialise et le texte extrait
(concatene) des documents du dossier, et retourne une liste de `ValidationIssue`.
Aucune regle ne doit jamais corriger silencieusement une incoherence : elle doit uniquement
la signaler, avec une preuve (evidence) et une action recommandee.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.core.schemas import ValidationIssue

TF_PATTERN = re.compile(r"\b\d{2,3}[.,]\d{3}\s*/\s*\d{2}\b")
AMOUNT_PATTERN = re.compile(r"\b\d{1,3}(?:[.,\s]\d{3}){1,3}\b")

# Documents minimaux attendus par type_dossier / variante (motifs recherches dans les noms de
# fichiers, en minuscules, sans le prefixe numerique).
EXPECTED_DOCUMENTS: dict[str, list[str]] = {
    "VENTE": ["acte_de_vente"],
    "VENTE-AUTO": ["contrat_vente_vehicule"],
    "DONATION": ["acte_de_donation"],
    "SUCCESSION": ["acte_notoriete_successorale"],
    "PROCURATION": ["procuration"],
    "HYPOTHEQUE": ["engagement_hypothecaire", "mainlevee_hypotheque"],  # au moins un des deux
}


def _iter_party_dicts(donnees: dict) -> list[tuple[str, dict]]:
    """Retourne les sous-dictionnaires de `donnees` qui ressemblent a des parties (personnes)."""
    parties = []
    for key, value in donnees.items():
        if isinstance(value, dict) and ("nom_fr" in value or "gerant" in value):
            parties.append((key, value))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict) and "nom_fr" in item:
                    parties.append((f"{key}[{idx}]", item))
    return parties


def rule_name_cin_presence_in_documents(donnees: dict, combined_text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for label, party in _iter_party_dicts(donnees):
        nom_fr = party.get("nom_fr")
        nom_ar = party.get("nom_ar")
        cin = party.get("cin") or party.get("cin_gerant")

        found_fr = False
        if nom_fr:
            nom_tokens = [t for t in re.split(r"\s+", nom_fr) if len(t) > 2]
            found_fr = bool(nom_tokens) and any(tok.upper() in combined_text.upper() for tok in nom_tokens)

        found_ar = False
        if nom_ar:
            # Le nom arabe est parfois suivi d'annotations entre parentheses (ex: "(epouse)");
            # on ne compare que les tokens purement arabes.
            ar_tokens = [t for t in re.split(r"\s+", nom_ar) if len(t) > 1 and re.search(r"[\u0600-\u06FF]", t)]
            found_ar = bool(ar_tokens) and any(tok in combined_text for tok in ar_tokens)

        if nom_fr and not found_fr and not found_ar:
            issues.append(ValidationIssue(
                rule_id="name_presence",
                severity="medium",
                message=f"Le nom declare pour '{label}' ({nom_fr}{' / ' + nom_ar if nom_ar else ''}) n'apparait (ni en francais ni en arabe) dans aucun document extrait du dossier.",
                documents=[],
                evidence=[nom_fr] + ([nom_ar] if nom_ar else []),
                recommended_action="Verifier que le document correspondant a bien ete genere/joint et que l'orthographe du nom est identique.",
            ))
        if cin and cin.upper() not in combined_text.upper():
            issues.append(ValidationIssue(
                rule_id="cin_presence",
                severity="medium",
                message=f"Le CIN declare pour '{label}' ({cin}) n'apparait dans aucun document extrait du dossier.",
                documents=[],
                evidence=[cin],
                recommended_action="Verifier la coherence du numero de CIN entre le dossier_master et les documents.",
            ))
    return issues


def rule_titre_foncier_consistency(donnees: dict, combined_text: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    declared_tfs: set[str] = set()
    for key, value in donnees.items():
        if key.lower().startswith("tf") or key == "tf":
            if isinstance(value, str):
                declared_tfs.add(value.strip())
        if isinstance(value, dict) and "tf" in value:
            declared_tfs.add(str(value["tf"]).strip())

    if len(declared_tfs) > 1:
        issues.append(ValidationIssue(
            rule_id="tf_multiple_declared",
            severity="blocking",
            message=f"Plusieurs numeros de titre foncier distincts sont declares pour le meme bien dans dossier_master.json : {sorted(declared_tfs)}.",
            documents=[],
            evidence=sorted(declared_tfs),
            recommended_action="Determiner le numero de titre foncier exact avec le notaire avant toute inscription ou publication.",
        ))

    extracted_tfs = set(m.group(0).replace(" ", "") for m in TF_PATTERN.finditer(combined_text))
    if declared_tfs and extracted_tfs:
        normalized_declared = {tf.replace(" ", "") for tf in declared_tfs}
        unexpected = extracted_tfs - normalized_declared
        if unexpected and not (len(declared_tfs) > 1):
            # Un TF extrait du texte qui ne correspond a aucun TF declare (et ce n'est pas deja
            # signale par la regle ci-dessus) peut indiquer une incoherence de saisie.
            issues.append(ValidationIssue(
                rule_id="tf_text_mismatch",
                severity="high",
                message=f"Numero(s) de titre foncier trouve(s) dans le texte du document mais absent(s) des donnees du dossier : {sorted(unexpected)}.",
                documents=[],
                evidence=sorted(unexpected),
                recommended_action="Verifier que le titre foncier mentionne dans l'acte correspond bien a celui du dossier.",
            ))

    return issues


def rule_price_consistency(donnees: dict) -> list[ValidationIssue]:
    """Compare les montants de prix/transaction declares dans le dossier.

    - Les champs designant un prix unitaire, un taux, un credit bancaire ou un solde de
      remboursement sont exclus (ce ne sont pas des composantes du prix de vente).
    - Les champs designant une composante connue d'une decomposition de prix (paiement
      immediat/differe, part corporelle/incorporelle, part avec/hors comptabilite) sont
      reconcilies : si leur somme correspond a un montant total restant, ils ne sont pas
      consideres comme une incoherence.
    - Seuls les montants "totaux" qui restent distincts entre eux sont signales.
    """
    issues: list[ValidationIssue] = []
    excluded_tokens = ("m2", "unitaire", "taux", "credit", "solde", "verse_tiers")
    component_tokens = ("immediat", "differe", "incorporel", "corporel", "hors_comptabilite", "via_comptabilite")

    price_fields = {
        k: v for k, v in donnees.items()
        if ("prix" in k.lower() or "montant" in k.lower())
        and isinstance(v, (int, float))
        and not any(tok in k.lower() for tok in excluded_tokens)
    }

    components = {k: v for k, v in price_fields.items() if any(tok in k.lower() for tok in component_tokens)}
    totals = {k: v for k, v in price_fields.items() if k not in components}

    if components:
        component_sum = sum(components.values())
        if not any(component_sum == total_value for total_value in totals.values()):
            issues.append(ValidationIssue(
                rule_id="price_breakdown_mismatch",
                severity="high",
                message=(
                    f"La somme des composantes de prix declarees ({components} = {component_sum}) ne "
                    f"correspond a aucun des montants totaux declares ({totals})."
                ),
                documents=[],
                evidence=[str(components), str(totals)],
                recommended_action="Verifier la decomposition du prix par rapport au prix total de l'acte.",
            ))

    distinct_totals = set(totals.values())
    if len(distinct_totals) > 1:
        issues.append(ValidationIssue(
            rule_id="price_multiple_declared",
            severity="blocking",
            message=f"Plusieurs montants de prix distincts et incompatibles sont declares dans le dossier : {totals}.",
            documents=[],
            evidence=[str(totals)],
            recommended_action="Clarifier avec les parties le prix reel de la transaction avant redaction de l'acte definitif.",
        ))
    return issues


def rule_date_validity(donnees: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    date_fields = {k: v for k, v in donnees.items() if "date" in k.lower() and isinstance(v, str)}
    parsed: dict[str, date] = {}
    for key, value in date_fields.items():
        try:
            parsed[key] = date.fromisoformat(value)
        except ValueError:
            issues.append(ValidationIssue(
                rule_id="date_format_invalid",
                severity="low",
                message=f"Le champ de date '{key}' ('{value}') n'est pas au format ISO AAAA-MM-JJ.",
                documents=[],
                evidence=[value],
                recommended_action="Normaliser le format de date dans les donnees du dossier.",
            ))
    return issues


def rule_expected_documents(type_dossier: str, filenames: list[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    expected = EXPECTED_DOCUMENTS.get(type_dossier)
    if not expected:
        return issues
    lower_filenames = [f.lower() for f in filenames]
    if not any(any(pattern in fname for fname in lower_filenames) for pattern in expected):
        issues.append(ValidationIssue(
            rule_id="expected_document_missing",
            severity="medium",
            message=f"Aucun document du dossier ne correspond aux types attendus pour '{type_dossier}' ({expected}).",
            documents=filenames,
            evidence=[],
            recommended_action="Verifier que le document principal du scenario a bien ete genere ou joint au dossier.",
        ))
    return issues


def rule_radiation_requires_mainlevee(filenames: list[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    lower = [f.lower() for f in filenames]
    has_radiation = any("radiation" in f for f in lower)
    has_mainlevee = any("mainlevee" in f for f in lower)
    if has_radiation and not has_mainlevee:
        issues.append(ValidationIssue(
            rule_id="radiation_without_mainlevee",
            severity="blocking",
            message="Une requisition de radiation d'hypotheque est presente sans mainlevee justificative correspondante dans le meme dossier.",
            documents=filenames,
            evidence=[],
            recommended_action="Ne jamais deposer de requisition de radiation sans la mainlevee (bancaire ou etatique) justifiant l'extinction de l'hypotheque.",
        ))
    return issues


def rule_company_identification(donnees: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for label, party in _iter_party_dicts(donnees):
        if "gerant" in party and not party.get("rc") and not party.get("ice"):
            issues.append(ValidationIssue(
                rule_id="company_identified_by_cin",
                severity="high",
                message=(
                    f"La partie '{label}' semble etre une societe (champ 'gerant' present) mais aucun "
                    f"numero de RC ou d'ICE n'est declare pour l'identifier."
                ),
                documents=[],
                evidence=[str(party)],
                recommended_action="Identifier la societe par sa denomination, sa forme juridique, son RC/ICE et le CIN de son gerant, pas seulement par un CIN de personne physique.",
            ))
    return issues


ALL_RULES = [
    "name_cin_presence_in_documents",
    "titre_foncier_consistency",
    "price_consistency",
    "date_validity",
    "expected_documents",
    "radiation_requires_mainlevee",
    "company_identification",
]
