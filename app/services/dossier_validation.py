from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from app.core.config import Settings, get_settings
from app.core.schemas import ValidationIssue, ValidationReport
from app.ingestion.extractors import extract_any, is_ignorable_file
from app.services.document_checklist import evaluate_document_checklist

SUPPORTED_SUFFIXES = (".docx", ".doc", ".pdf", ".txt")
TF_RE = re.compile(r"\b\d{2,3}(?:[.,]\d{3})\s*/\s*\d{2}\b")
DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DATE_TEXT_FR_RE = re.compile(r"\b(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(\d{4})\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"([0-9][0-9 .,'’]{1,20})\s*(?:DHS|DH|dirhams|dirham|درهم)", re.IGNORECASE)
BANK_RE = re.compile(r"\b([A-Z][A-Z0-9 '&.-]{2,}BANK)\b")
RANK_RE = re.compile(r"(?:hypoth[eè]que\s+de\s+|rang\s*)(\d+)\s*(?:er|e|ème|eme)?\s*rang", re.IGNORECASE)
MORTGAGE_REF_RE = re.compile(r"(?:inscription|référence|reference)\s*(?:définitive|definitive|hypothécaire|hypothecaire)?\s*[n°ºo:]?\s*([A-Z0-9./_-]{4,})", re.IGNORECASE)
FRACTION_ONLY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")

FR_MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}

RuleHandler = Callable[["ValidationContext"], list[ValidationIssue]]


@dataclass
class RuleSpec:
    rule_id: str
    applies_to: list[tuple[str, set[str] | None]]
    severity: str
    title: str
    condition: str
    message: str
    recommended_action: str
    requires_notary_review: bool


@dataclass
class ValidationContext:
    settings: Settings
    dossier_path: Path
    dossier_id: str
    master: dict[str, Any]
    donnees: dict[str, Any]
    type_dossier: str
    variante: str
    doc_paths: list[Path]
    filenames: list[str]
    texts_by_file: dict[str, str]
    combined_text: str
    checklist_report: dict[str, Any] | None


_RULE_CACHE: dict[str, tuple[float, dict[str, RuleSpec]]] = {}


def get_validation_report_path(dossier_id: str, settings: Optional[Settings] = None) -> Path:
    settings = settings or get_settings()
    out_dir = settings.validation_reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{dossier_id}.json"


def _normalize(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_accents).strip().lower()


def _slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalize(text)).strip("_")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)
    return str(value)


def _list_document_files(dossier_path: Path) -> list[Path]:
    if not dossier_path.exists():
        return []
    return sorted(
        p for p in dossier_path.iterdir()
        if p.is_file() and not is_ignorable_file(p) and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _extract_texts(doc_paths: list[Path]) -> tuple[dict[str, str], list[str]]:
    texts: dict[str, str] = {}
    errors: list[str] = []
    for path in doc_paths:
        try:
            result = extract_any(path)
            if result.ok:
                texts[path.name] = result.text or ""
            else:
                texts[path.name] = ""
                errors.append(f"{path.name}: {result.error}")
        except Exception as exc:  # noqa: BLE001
            texts[path.name] = ""
            errors.append(f"{path.name}: {exc}")
    return texts, errors


def _safe_load_master(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _flatten_pairs(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, sub in value.items():
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_flatten_pairs(sub, new_prefix))
    elif isinstance(value, list):
        for idx, sub in enumerate(value):
            new_prefix = f"{prefix}[{idx}]"
            out.extend(_flatten_pairs(sub, new_prefix))
    else:
        out.append((prefix, value))
    return out


def _get_by_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _amount_to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _stringify(value).strip()
    if not text:
        return None
    digits = re.sub(r"[^0-9,.-]", "", text.replace(" ", ""))
    if not digits:
        return None
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", digits):
        digits = re.sub(r"[.,]", "", digits)
    else:
        digits = digits.replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return None


def _fmt_amount(value: Any) -> str:
    number = _amount_to_number(value)
    if number is None:
        return _stringify(value)
    if float(number).is_integer():
        return f"{int(number):,}".replace(",", " ")
    return f"{number}".replace(",", " ")


def _extract_amounts_from_text(text: str) -> list[float]:
    values: list[float] = []
    for match in AMOUNT_RE.finditer(text or ""):
        number = _amount_to_number(match.group(1))
        if number is not None:
            values.append(number)
    return values


def _extract_tfs(text: str) -> list[str]:
    return [m.group(0).replace(" ", "") for m in TF_RE.finditer(text or "")]


def _extract_iso_dates(text: str) -> list[date]:
    out: list[date] = []
    for raw in DATE_ISO_RE.findall(text or ""):
        try:
            out.append(date.fromisoformat(raw))
        except ValueError:
            continue
    for day, month, year in DATE_TEXT_FR_RE.findall(text or ""):
        try:
            out.append(date(int(year), FR_MONTHS[_normalize(month)], int(day)))
        except Exception:  # noqa: BLE001
            continue
    return out


def _extract_banks(text: str) -> list[str]:
    text_u = text or ""
    found = []
    for explicit in ("AL BARID BANK", "ATTIJARIWAFA BANK", "BMCE Bank", "BMCE BANK", "Banque Populaire", "Banque Populaire El Jadida"):
        if explicit.lower() in text_u.lower():
            found.append(explicit)
    for match in BANK_RE.finditer(text_u):
        found.append(re.sub(r"\s+", " ", match.group(1)).strip())
    uniq: list[str] = []
    for item in found:
        norm = _normalize(item)
        if norm not in {_normalize(x) for x in uniq}:
            uniq.append(item)
    return uniq


def _extract_ranks(text: str) -> list[int]:
    ranks: list[int] = []
    for match in RANK_RE.finditer(text or ""):
        try:
            ranks.append(int(match.group(1)))
        except ValueError:
            continue
    return ranks


def _has_keywords(text: str, *keywords: str) -> bool:
    hay = _normalize(text)
    return any(_normalize(k) in hay for k in keywords)


def _collect_party_names(party: Any) -> list[str]:
    out: list[str] = []
    if isinstance(party, dict):
        for key in ("nom_fr", "nom_ar", "gerant", "cin", "cin_gerant", "lien", "role"):
            if party.get(key):
                out.append(str(party.get(key)))
    return out


def _issue(spec: RuleSpec, message: Optional[str] = None, *, fields: Optional[dict[str, Any]] = None,
           documents: Optional[list[str]] = None, source_refs: Optional[list[str]] = None,
           severity: Optional[str] = None) -> ValidationIssue:
    return ValidationIssue(
        rule_id=spec.rule_id,
        severity=severity or spec.severity,
        title=spec.title,
        message=message or spec.message,
        evidence={
            "fields": fields or {},
            "documents": documents or [],
            "source_refs": source_refs or [],
        },
        recommended_action=spec.recommended_action,
        requires_notary_review=spec.requires_notary_review,
    )


def load_rule_specs(settings: Optional[Settings] = None) -> dict[str, RuleSpec]:
    settings = settings or get_settings()
    path = settings.validation_rules_path
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    cached = _RULE_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = raw.get("rules", []) if isinstance(raw, dict) else []
    specs: dict[str, RuleSpec] = {}
    for entry in rules:
        if not isinstance(entry, dict):
            continue
        rule_id = str(entry.get("id", "")).strip()
        if not rule_id:
            continue
        applies_raw = entry.get("applies_to") or []
        applies_to: list[tuple[str, set[str] | None]] = []
        if isinstance(applies_raw, dict):
            applies_raw = [applies_raw]
        for ap in applies_raw:
            if not isinstance(ap, dict):
                continue
            type_dossier = str(ap.get("type_dossier", "")).strip().upper()
            if not type_dossier:
                continue
            variants = ap.get("variants")
            applies_to.append((type_dossier, None if not variants else {_slug(v) for v in variants}))
        specs[rule_id] = RuleSpec(
            rule_id=rule_id,
            applies_to=applies_to,
            severity=str(entry.get("severity", "warning")),
            title=str(entry.get("title", "")).strip(),
            condition=str(entry.get("condition", "")).strip(),
            message=str(entry.get("message", "")).strip(),
            recommended_action=str(entry.get("recommended_action", "")).strip(),
            requires_notary_review=bool(entry.get("requires_notary_review", True)),
        )
    _RULE_CACHE[str(path)] = (mtime, specs)
    return specs


def _applies(spec: RuleSpec, ctx: ValidationContext) -> bool:
    if not spec.applies_to:
        return True
    for type_dossier, variants in spec.applies_to:
        if type_dossier != ctx.type_dossier:
            continue
        if variants is None or ctx.variante in variants:
            return True
    return False


def _required_paths_for_context(ctx: ValidationContext) -> list[str]:
    mapping: dict[tuple[str, str], list[str]] = {
        ("VENTE", "simple"): ["vendeur.nom_fr", "acquereur.nom_fr", "bien.tf", "prix_dhs"],
        ("VENTE", "paiement_differe"): ["vendeur.nom_fr", "acquereur.nom_fr", "bien.tf", "prix_dhs", "montant_immediat_dhs", "montant_differe_dhs"],
        ("VENTE", "hors_comptabilite"): ["vendeur.nom_fr", "acquereur.nom_fr", "bien.tf", "prix_dhs", "modalite_paiement"],
        ("VENTE", "mixte_comptabilite"): ["vendeur.nom_fr", "acquereur.nom_fr", "bien.tf", "prix_dhs", "montant_hors_comptabilite_dhs", "montant_via_comptabilite_dhs"],
        ("VENTE", "tripartite_bancaire"): ["vendeur.nom_fr", "acquereur_1.nom_fr", "acquereur_2.nom_fr", "banque", "bien.tf", "prix_dhs"],
        ("VENTE", "terrain_nu_engagement_construire"): ["vendeur.nom_fr", "acquereur.nom_fr", "bien.tf", "prix_dhs", "engagement_construire_delai_ans"],
        ("VENTE", "vefa"): ["vendeur.nom_fr", "acquereur.nom_fr", "bien.tf_origine", "prix_total_dhs", "delai_achevement_mois"],
        ("VENTE", "fonds_de_commerce"): ["cedant.nom_fr", "cessionnaire.nom_fr", "fonds.nature", "prix_dhs"],
        ("HYPOTHEQUE", "engagement_1er_rang"): ["emprunteur.nom_fr", "banque", "bien.tf", "montant_credit_dhs", "rang_hypotheque"],
        ("HYPOTHEQUE", "engagement_avec_caution"): ["emprunteur.nom_fr", "banque", "bien.tf", "montant_credit_dhs", "rang_hypotheque"],
        ("HYPOTHEQUE", "mainlevee"): ["debiteur.nom_fr", "banque", "bien.tf", "date_mainlevee"],
        ("DONATION", "standard"): ["donateur.nom_fr", "donataire.nom_fr", "bien.tf", "valeur_venale_dhs"],
        ("SUCCESSION", "standard"): ["defunt.nom_fr", "heritiers", "date_acte_notoriete"],
        ("PROCURATION", "standard"): ["mandant.nom_fr", "mandataire.nom_fr", "objet"],
        ("VENTE-AUTO", "standard"): ["vendeur.nom_fr", "acquereur.nom_fr", "vehicule.immatriculation", "prix_dhs"],
    }
    return mapping.get((ctx.type_dossier, ctx.variante), [])


def _parse_share_fraction(value: Any) -> Optional[Fraction]:
    if not isinstance(value, str):
        return None
    m = FRACTION_ONLY_RE.match(value)
    if not m:
        return None
    numerator = int(m.group(1))
    denominator = int(m.group(2))
    if denominator == 0:
        return None
    return Fraction(numerator, denominator)


def _collect_source_refs(ctx: ValidationContext, terms: list[str]) -> list[str]:
    refs: list[str] = []
    for filename, text in ctx.texts_by_file.items():
        hay = _normalize(text)
        if any(_normalize(term) in hay for term in terms if term):
            refs.append(filename)
    return refs or ctx.filenames[:1]


def rule_dossier_identity_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    missing = {}
    if not ctx.master.get("dossier_id"):
        missing["dossier_id"] = None
    if not ctx.type_dossier:
        missing["type_dossier"] = None
    if not ctx.master.get("annee"):
        missing["annee"] = None
    if ctx.master.get("dossier_id") and ctx.master.get("dossier_id") != ctx.dossier_id:
        missing["dossier_id_incoherent"] = {
            "attendu": ctx.dossier_id,
            "lu": ctx.master.get("dossier_id"),
        }
    if not missing:
        return []
    return [_issue(spec, fields=missing, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_document_source_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.doc_paths:
        return []
    return [_issue(spec, documents=[], source_refs=["Aucun document source détecté dans le dossier"]) ]


def rule_required_field_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    missing_paths = []
    for path in _required_paths_for_context(ctx):
        value = _get_by_path(ctx.donnees, path)
        if value in (None, "", [], {}):
            missing_paths.append(path)
    if not missing_paths:
        return []
    return [_issue(
        spec,
        message=f"Certains champs attendus pour ce type de dossier ne sont pas renseignés : {', '.join(missing_paths)}.",
        fields={"missing_fields": missing_paths},
        documents=["dossier_master.json"],
        source_refs=["dossier_master.json"],
    )]


def rule_amount_invalid(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    problematic: dict[str, Any] = {}
    for path, value in _flatten_pairs(ctx.donnees):
        slug = _slug(path)
        if any(token in slug for token in ("taux", "superficie", "m2", "prix_lettres", "role")):
            continue
        expects_amount = slug.endswith("_dhs") or slug.endswith("_dh") or slug in {"prix_dhs", "prix_total_dhs", "valeur_venale_dhs", "valeur_succession_dhs", "montant_credit_dhs"}
        if not expects_amount:
            continue
        number = _amount_to_number(value)
        if number is None or number <= 0:
            problematic[path] = value
    if not problematic:
        return []
    return [_issue(
        spec,
        message="Au moins un montant attendu comme strictement positif est absent, nul, négatif ou non numérique.",
        fields=problematic,
        documents=["dossier_master.json"],
        source_refs=["dossier_master.json"],
    )]


def rule_date_order_incoherent(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    data_pairs = {k: v for k, v in _flatten_pairs(ctx.donnees) if isinstance(v, str) and DATE_ISO_RE.fullmatch(v)}
    parsed = {}
    for key, value in data_pairs.items():
        try:
            parsed[key] = date.fromisoformat(value)
        except ValueError:
            continue
    if "reference_propriete.acte_precedent_date" in parsed and "reference_propriete.date_enregistrement" in parsed:
        if parsed["reference_propriete.date_enregistrement"] < parsed["reference_propriete.acte_precedent_date"]:
            issues.append(_issue(
                spec,
                message="L'ordre chronologique des dates de référence de propriété est incohérent.",
                fields={
                    "reference_propriete.acte_precedent_date": data_pairs["reference_propriete.acte_precedent_date"],
                    "reference_propriete.date_enregistrement": data_pairs["reference_propriete.date_enregistrement"],
                },
                documents=["dossier_master.json"],
                source_refs=["dossier_master.json"],
            ))
    return issues


def rule_multiple_conflicting_values(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    conflicts: dict[str, list[Any]] = {}
    tf_values = [v for k, v in _flatten_pairs(ctx.donnees) if isinstance(v, str) and (_slug(k).startswith("tf") or _slug(k).endswith("_tf") or _slug(k).endswith("tf") or TF_RE.search(v))]
    tf_norm = sorted({str(v).replace(" ", "") for v in tf_values if str(v).strip()})
    if len(tf_norm) > 1:
        conflicts["titre_foncier"] = tf_norm

    price_values = {}
    for path, value in _flatten_pairs(ctx.donnees):
        slug = _slug(path)
        if not isinstance(value, (int, float)):
            continue
        if any(token in slug for token in ("prix", "montant")) and not any(token in slug for token in ("credit", "solde", "verse_tiers", "taux", "m2")):
            price_values[path] = value
    normalized_prices = sorted({_fmt_amount(v) for v in price_values.values()})
    if len(set(price_values.values())) > 1 and any(k in _slug(path) for path in price_values for k in ("version", "section")):
        conflicts["montants_critiques"] = price_values

    party_conflicts = {}
    for label in ("vendeur", "acquereur", "banque", "donateur", "donataire", "mandant", "mandataire", "defunt"):
        vals = [v for k, v in _flatten_pairs(ctx.donnees) if _slug(k).endswith(label) and isinstance(v, str)]
        vals = sorted({v for v in vals if v})
        if len(vals) > 1:
            party_conflicts[label] = vals
    conflicts.update(party_conflicts)

    if not conflicts:
        return []
    return [_issue(
        spec,
        message="Plusieurs valeurs distinctes existent pour un même champ critique du dossier.",
        fields=conflicts,
        documents=["dossier_master.json"],
        source_refs=["dossier_master.json"],
        severity="blocking",
    )]


def rule_source_fact_conflict(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    text = ctx.combined_text
    if not text:
        return issues

    data_tf = ctx.donnees.get("bien", {}).get("tf") if isinstance(ctx.donnees.get("bien"), dict) else None
    text_tfs = sorted(set(_extract_tfs(text)))
    if data_tf and text_tfs and str(data_tf).replace(" ", "") not in {tf.replace(" ", "") for tf in text_tfs}:
        issues.append(_issue(
            spec,
            message="Le titre foncier déclaré dans les données structurées n'est pas confirmé par le document extrait du même dossier.",
            fields={"dossier_master": data_tf, "documents_extraits": text_tfs},
            documents=ctx.filenames,
            source_refs=_collect_source_refs(ctx, [str(data_tf)] + text_tfs),
            severity="blocking",
        ))

    prix = ctx.donnees.get("prix_dhs") or ctx.donnees.get("prix_total_dhs") or ctx.donnees.get("valeur_venale_dhs")
    amounts = [a for a in _extract_amounts_from_text(text) if a > 0]
    if prix is not None and amounts:
        target = _amount_to_number(prix)
        if target is not None and not any(abs(a - target) < 0.5 for a in amounts):
            issues.append(_issue(
                spec,
                message="Le montant principal déclaré dans dossier_master.json n'est pas retrouvé tel quel dans les documents disponibles.",
                fields={"dossier_master": _fmt_amount(prix), "documents_extraits": [_fmt_amount(a) for a in sorted(set(amounts))[:8]]},
                documents=ctx.filenames,
                source_refs=ctx.filenames[:2],
                severity="blocking",
            ))
    return issues


def rule_checklist_incomplete(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    report = ctx.checklist_report or {}
    if not report.get("evaluable"):
        return []
    synthese = report.get("synthese", {}) or {}
    missing = synthese.get("a_ajouter", 0)
    verify = synthese.get("a_verifier", 0)
    if not missing and not verify:
        return []
    return [_issue(
        spec,
        message=(
            f"La checklist documentaire signale {missing} pièce(s) à ajouter et {verify} point(s) à vérifier. "
            "Cette information ne vaut pas invalidité juridique automatique."
        ),
        fields={"checklist_synthese": synthese},
        documents=[report.get("checklist_label", "checklist_documentaire")],
        source_refs=[report.get("checklist_label", "checklist_documentaire")],
        severity="info",
    )]


def rule_sale_parties_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    vendeur = ctx.donnees.get("vendeur") or ctx.donnees.get("cedant")
    acquereur = ctx.donnees.get("acquereur") or ctx.donnees.get("cessionnaire") or ctx.donnees.get("acquereur_1")
    if vendeur and acquereur:
        return []
    return [_issue(spec, fields={"vendeur": vendeur, "acquereur": acquereur}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_sale_tf_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    bien = ctx.donnees.get("bien") if isinstance(ctx.donnees.get("bien"), dict) else {}
    if bien.get("tf") or bien.get("tf_origine"):
        return []
    if _has_keywords(_stringify(bien), "immat", "titre foncier", "tf") or _has_keywords(ctx.combined_text, "titre foncier", "الرسم العقاري"):
        return [_issue(spec, fields={"bien": bien}, documents=["dossier_master.json"], source_refs=ctx.filenames[:1] or ["dossier_master.json"]) ]
    return []


def rule_sale_price_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if any(k in ctx.donnees for k in ("prix_dhs", "prix_total_dhs")):
        return []
    return [_issue(spec, fields={"champs_prix": [k for k, _ in _flatten_pairs(ctx.donnees) if "prix" in _slug(k)]}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_price_multiple_declared(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    values: dict[str, float] = {}
    components: dict[str, float] = {}
    total_candidates: dict[str, float] = {}
    component_tokens = ("immediat", "differe", "corporel", "incorporel", "hors_comptabilite", "via_comptabilite")
    excluded_tokens = ("credit", "solde", "verse_tiers", "taux", "m2")
    for path, value in _flatten_pairs(ctx.donnees):
        slug = _slug(path)
        if not isinstance(value, (int, float)):
            continue
        if not any(token in slug for token in ("prix", "montant")) or any(token in slug for token in excluded_tokens):
            continue
        values[path] = float(value)
        if any(token in slug for token in component_tokens):
            components[path] = float(value)
        else:
            total_candidates[path] = float(value)
    if components and total_candidates:
        component_sum = sum(components.values())
        if any(abs(component_sum - total_value) < 0.5 for total_value in total_candidates.values()):
            residual = {k: v for k, v in total_candidates.items() if abs(v - component_sum) >= 0.5}
            if not residual:
                return []
            values = {**residual, **components}
            total_candidates = residual
    if ctx.type_dossier == "VENTE" and ctx.variante == "fonds_de_commerce":
        total = ctx.donnees.get("prix_dhs")
        corporel = ctx.donnees.get("prix_corporel_dhs")
        incorporel = ctx.donnees.get("prix_incorporel_dhs")
        if total is not None and corporel is not None and incorporel is not None and abs((corporel + incorporel) - total) < 0.5:
            return []
    unique = sorted(set(total_candidates.values() if total_candidates else values.values()))
    if len(unique) <= 1:
        return []
    return [_issue(
        spec,
        message="Plusieurs prix déclarés distincts et incompatibles apparaissent dans le dossier ; aucun prix ne peut être retenu automatiquement.",
        fields={k: _fmt_amount(v) for k, v in values.items()},
        documents=ctx.filenames,
        source_refs=ctx.filenames[:2] or ["dossier_master.json"],
        severity="blocking",
    )]


def rule_sale_payment_breakdown_incoherent(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    total = ctx.donnees.get("prix_dhs") or ctx.donnees.get("prix_total_dhs")
    immediat = ctx.donnees.get("montant_immediat_dhs")
    differe = ctx.donnees.get("montant_differe_dhs")
    if None in (total, immediat, differe):
        return []
    total_n = _amount_to_number(total)
    immediat_n = _amount_to_number(immediat)
    differe_n = _amount_to_number(differe)
    if None in (total_n, immediat_n, differe_n):
        return []
    if abs((immediat_n + differe_n) - total_n) < 0.5:
        return []
    return [_issue(
        spec,
        fields={"prix_total_dhs": _fmt_amount(total), "montant_immediat_dhs": _fmt_amount(immediat), "montant_differe_dhs": _fmt_amount(differe)},
        documents=["dossier_master.json"],
        source_refs=["dossier_master.json"],
        severity="blocking",
    )]


def rule_sale_deferred_payment_missing_terms(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    is_deferred = ctx.variante == "paiement_differe" or ctx.donnees.get("modalite_paiement") == "differe" or ctx.donnees.get("montant_differe_dhs") not in (None, 0, 0.0)
    if not is_deferred:
        return []
    delay = ctx.donnees.get("delai_differe_jours") or ctx.donnees.get("delai_differe_mois")
    amount = ctx.donnees.get("montant_differe_dhs")
    if amount not in (None, "", 0, 0.0) and delay not in (None, "", 0, 0.0):
        return []
    return [_issue(spec, fields={"montant_differe_dhs": amount, "delai": delay}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_sale_payment_route_unclear(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    text = ctx.combined_text
    if ctx.donnees.get("modalite_paiement"):
        return []
    if _has_keywords(text, "hors comptabilité", "hors comptabilite", "entre les mains du notaire", "devant le notaire", "consigné", "consigne", "ضمن محاسبته", "خارج محاسبة", "مباشرة للطرف البائع", "إيداع لدى الموثق", "credit", "prêteur", "preteur"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1])]


def rule_sale_representative_missing_power(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if not _has_keywords(ctx.combined_text + " " + _stringify(ctx.donnees), "procuration", "mandataire", "représenté par procuration", "represente par procuration"):
        return []
    if any("procuration" in _slug(name) for name in ctx.filenames):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["procuration", "mandataire"]))]


def rule_sale_tax_and_fees_clause_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if not ctx.doc_paths:
        return []
    if _has_keywords(ctx.combined_text, "taxe", "frais", "droits", "ضرائب", "رسوم"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="info")]


def rule_mortgage_beneficiary_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("banque"):
        return []
    return [_issue(spec, fields={"banque": None}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_mortgage_tf_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    tf = (ctx.donnees.get("bien") or {}).get("tf") if isinstance(ctx.donnees.get("bien"), dict) else None
    if tf:
        return []
    return [_issue(spec, fields={"bien": ctx.donnees.get("bien")}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_mortgage_credit_amount_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("montant_credit_dhs") is not None:
        return []
    return [_issue(spec, fields={"montant_credit_dhs": ctx.donnees.get("montant_credit_dhs")}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_mortgage_rank_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("rang_hypotheque") is not None:
        return []
    if _extract_ranks(ctx.combined_text):
        return []
    return [_issue(spec, documents=["dossier_master.json"], source_refs=ctx.filenames[:1] or ["dossier_master.json"]) ]


def rule_mortgage_rank_amount_confusion(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    doc_ranks = _extract_ranks(ctx.combined_text)
    data_rank = ctx.donnees.get("rang_hypotheque")
    if data_rank is not None and doc_ranks and int(data_rank) not in set(doc_ranks):
        return [_issue(
            spec,
            message="Le rang hypothécaire déclaré ne correspond pas au rang extrait du document ; la distinction rang / montant doit être vérifiée.",
            fields={"rang_hypotheque": data_rank, "rangs_extraits": doc_ranks},
            documents=ctx.filenames,
            source_refs=_collect_source_refs(ctx, ["rang", "hypothèque", "hypotheque"]),
            severity="blocking",
        )]
    return []


def rule_mortgage_registration_not_proven(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.variante == "mainlevee":
        return []
    refs = MORTGAGE_REF_RE.findall(ctx.combined_text)
    if refs:
        return []
    if _has_keywords(ctx.combined_text, "m'engage à inscrire", "engagement hypothécaire", "engagement hypothecaire", "ألتزم", "التزام"):
        return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["engage", "inscrire", "engagement"]) , severity="info")]
    return []


def rule_mortgage_surety_detected(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("caution") or _has_keywords(ctx.combined_text, "cautionnement hypothécaire", "cautionnement hypothecaire", "garantie solidaire"):
        return [_issue(
            spec,
            fields={"caution": ctx.donnees.get("caution")},
            documents=ctx.filenames,
            source_refs=_collect_source_refs(ctx, ["cautionnement", "garantie solidaire", "caution"]),
            severity="info",
        )]
    return []


def rule_mortgage_deadline_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.variante == "mainlevee":
        return []
    if ctx.donnees.get("delai_inscription_jours") is not None:
        return []
    if _has_keywords(ctx.combined_text, "30 jours", "délai", "delai"):
        return []
    if _has_keywords(ctx.combined_text, "engagement", "m'engage à inscrire", "inscrire au profit"):
        return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["engagement", "délai", "delai"]), severity="info")]
    return []


def rule_release_bank_discharge_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text, "mainlevée", "mainlevee", "décharge", "decharge", "رفع اليد"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1])]


def rule_release_requisition_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if any("requisition" in _slug(name) for name in ctx.filenames) or _has_keywords(ctx.combined_text, "réquisition", "requisition", "radiation", "تشطيب"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1])]


def rule_release_reference_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    tf = (ctx.donnees.get("bien") or {}).get("tf") if isinstance(ctx.donnees.get("bien"), dict) else None
    if tf or _extract_tfs(ctx.combined_text):
        return []
    return [_issue(spec, fields={"bien": ctx.donnees.get("bien")}, documents=ctx.filenames, source_refs=ctx.filenames[:1])]


def rule_release_bank_conflict(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    banks = set()
    if ctx.donnees.get("banque"):
        banks.add(_normalize(ctx.donnees.get("banque")))
    banks.update({_normalize(b) for b in _extract_banks(ctx.combined_text)})
    if len({b for b in banks if b}) <= 1:
        return []
    return [_issue(spec, fields={"banques": sorted(banks)}, documents=ctx.filenames, source_refs=ctx.filenames[:2], severity="blocking")]


def rule_donation_parties_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("donateur") and ctx.donnees.get("donataire"):
        return []
    return [_issue(spec, fields={"donateur": ctx.donnees.get("donateur"), "donataire": ctx.donnees.get("donataire")}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_donation_tf_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if isinstance(ctx.donnees.get("bien"), dict) and ctx.donnees["bien"].get("tf"):
        return []
    return [_issue(spec, fields={"bien": ctx.donnees.get("bien")}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_donation_declared_value_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("valeur_venale_dhs") is not None:
        return []
    return [_issue(spec, fields={"valeur_venale_dhs": None}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_donation_qualification_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text + " " + _stringify(ctx.master), "donation", "صدقة", "متصدق"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="info")]


def rule_donation_family_link_unproven(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    donataire = ctx.donnees.get("donataire") if isinstance(ctx.donnees.get("donataire"), dict) else {}
    lien = donataire.get("lien") if isinstance(donataire, dict) else None
    if not lien and not _has_keywords(ctx.combined_text, "fils", "fille", "époux", "epoux", "épouse", "epouse", "ابن"):
        return []
    justificatifs = [name for name in ctx.filenames if any(token in _slug(name) for token in ("livret", "etat_civil", "naissance", "famille"))]
    if justificatifs:
        return []
    return [_issue(spec, fields={"lien_invoque": lien or "mention textuelle"}, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, [str(lien or "fils")]))]


def rule_donation_tax_rate_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    mentions_taux = _has_keywords(_stringify(ctx.donnees) + " " + ctx.combined_text, "%", "taux", "واجبات التسجيل")
    if not mentions_taux:
        return []
    if ctx.donnees.get("taux_enregistrement") or re.search(r"\d+[,.]?\d*\s*%", ctx.combined_text):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["taux", "%"]), severity="info")]


def rule_succession_death_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    death_date = (ctx.donnees.get("defunt") or {}).get("date_deces") if isinstance(ctx.donnees.get("defunt"), dict) else None
    if death_date or _has_keywords(ctx.combined_text, "décès", "deces", "وفاة"):
        return []
    return [_issue(spec, fields={"defunt": ctx.donnees.get("defunt")}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_succession_deceased_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("defunt"):
        return []
    return [_issue(spec, fields={"defunt": None}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_succession_heirs_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    heirs = ctx.donnees.get("heritiers")
    if isinstance(heirs, list) and heirs:
        return []
    return [_issue(spec, fields={"heritiers": heirs}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_succession_shares_incoherent(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    heirs = ctx.donnees.get("heritiers")
    if not isinstance(heirs, list) or not heirs:
        return []
    parsed: list[Fraction] = []
    raw_parts: list[str] = []
    for heir in heirs:
        if not isinstance(heir, dict):
            return []
        raw = heir.get("part")
        raw_parts.append(_stringify(raw))
        frac = _parse_share_fraction(raw)
        if frac is None:
            return []
        parsed.append(frac)
    total = sum(parsed, start=Fraction(0, 1))
    if total == Fraction(1, 1):
        return []
    return [_issue(
        spec,
        fields={"parts": raw_parts, "somme": f"{total.numerator}/{total.denominator}"},
        documents=["dossier_master.json"],
        source_refs=["dossier_master.json"],
        severity="blocking",
    )]


def rule_succession_property_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("bien"):
        return []
    return [_issue(spec, fields={"bien": None}, documents=["dossier_master.json"], source_refs=["dossier_master.json"], severity="info")]


def rule_succession_representative_missing_power(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    heirs = ctx.donnees.get("heritiers")
    if not isinstance(heirs, list):
        return []
    represented = any(isinstance(h, dict) and (h.get("represente_par") or h.get("mandataire")) for h in heirs)
    if not represented:
        return []
    if any("procuration" in _slug(name) for name in ctx.filenames):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["represente", "mandataire", "procuration"]))]


def rule_power_principal_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("mandant"):
        return []
    return [_issue(spec, fields={"mandant": None}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_power_agent_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("mandataire"):
        return []
    return [_issue(spec, fields={"mandataire": None}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_power_scope_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("objet") or _has_keywords(ctx.combined_text, "pouvoir", "vendre", "gérer", "gérer et administrer", "وكيل"):
        return []
    return [_issue(spec, fields={"objet": ctx.donnees.get("objet")}, documents=["dossier_master.json"], source_refs=ctx.filenames[:1] or ["dossier_master.json"]) ]


def rule_power_duration_unclear(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    duree = _stringify(ctx.donnees.get("duree"))
    text = duree + " " + ctx.combined_text
    has_duration = _has_keywords(text, "an", "ans", "mois", "durée", "duree")
    has_revocation = _has_keywords(text, "révocable", "revocable", "révocation", "revocation")
    if has_duration and has_revocation:
        return []
    return [_issue(spec, fields={"duree": ctx.donnees.get("duree")}, documents=ctx.filenames[:1] or ["dossier_master.json"], source_refs=_collect_source_refs(ctx, ["durée", "duree", "révocable", "revocable"]), severity="info")]


def rule_power_foreign_formality_unverified(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    text = _stringify(ctx.donnees) + " " + ctx.combined_text
    if not _has_keywords(text, "étranger", "etranger", "consulat", "apostille", "légalisation", "legalisation"):
        return []
    if any(any(token in _slug(name) for token in ("apostille", "legalisation", "traduction", "consulaire")) for name in ctx.filenames):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["apostille", "legalisation", "etranger"]))]


def rule_vefa_program_or_tf_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    bien = ctx.donnees.get("bien") if isinstance(ctx.donnees.get("bien"), dict) else {}
    if bien.get("tf_origine") or bien.get("tf"):
        return []
    return [_issue(spec, fields={"bien": bien}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_vefa_plan_or_description_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    bien = ctx.donnees.get("bien") if isinstance(ctx.donnees.get("bien"), dict) else {}
    if bien.get("nature") or bien.get("superficie_terrain_m2") or bien.get("superficie_couverte_m2"):
        return []
    if _has_keywords(ctx.combined_text, "plan", "superficie", "villa", "copropriété", "copropriete"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1])]


def rule_vefa_payment_schedule_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text, "5%", "10%", "20%", "échéancier", "echeancier", "moyen de paiement", "كيفية أداء الثمن"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1])]


def rule_vefa_guarantee_unproven(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("garantie") or _has_keywords(ctx.combined_text, "garantie", "garantie bancaire", "ضمانة", "بنكية"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="info")]


def rule_vefa_delivery_terms_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("delai_achevement_mois") or _has_keywords(ctx.combined_text, "livraison", "réception", "reception", "24 mois", "أجل إنجاز"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="info")]


def rule_vefa_completion_documents_not_applicable(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text + " " + _stringify(ctx.donnees), "réception", "reception", "date_livraison", "livraison_effectuee"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="info")]


def rule_business_sale_parties_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("cedant") and ctx.donnees.get("cessionnaire"):
        return []
    return [_issue(spec, fields={"cedant": ctx.donnees.get("cedant"), "cessionnaire": ctx.donnees.get("cessionnaire")}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_business_sale_rc_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    cedant = ctx.donnees.get("cedant") if isinstance(ctx.donnees.get("cedant"), dict) else {}
    cessionnaire = ctx.donnees.get("cessionnaire") if isinstance(ctx.donnees.get("cessionnaire"), dict) else {}
    if cedant.get("rc") and cessionnaire.get("rc"):
        return []
    return [_issue(spec, fields={"cedant.rc": cedant.get("rc"), "cessionnaire.rc": cessionnaire.get("rc")}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_business_sale_lease_or_occupation_unclear(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text, "bail", "droit au bail", "occupation"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="warning")]


def rule_business_sale_encumbrances_unverified(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text, "certificat de non-opposition", "non-opposition", "créanciers", "creanciers"):
        return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["non-opposition", "créanciers", "creanciers"]), severity="info")]
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="warning")]


def rule_business_sale_inventory_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text, "inventaire", "liste des éléments", "liste des elements"):
        return []
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1])]


def rule_business_sale_price_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if ctx.donnees.get("prix_dhs") is not None:
        return []
    return [_issue(spec, fields={"prix_dhs": None}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


def rule_business_sale_publicity_unverified(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    if _has_keywords(ctx.combined_text, "publication", "bulletin officiel", "journal d'annonces légales", "journal d annonces legales"):
        return [_issue(spec, documents=ctx.filenames, source_refs=_collect_source_refs(ctx, ["publication", "bulletin officiel", "annonces légales"]), severity="info")]
    return [_issue(spec, documents=ctx.filenames, source_refs=ctx.filenames[:1], severity="warning")]


def rule_auto_sale_vehicle_identification_missing(ctx: ValidationContext, spec: RuleSpec) -> list[ValidationIssue]:
    vehicle = ctx.donnees.get("vehicule") if isinstance(ctx.donnees.get("vehicule"), dict) else {}
    missing = [k for k in ("marque", "modele", "immatriculation", "numero_chassis") if not vehicle.get(k)]
    if not missing:
        return []
    return [_issue(spec, fields={"missing_vehicle_fields": missing}, documents=["dossier_master.json"], source_refs=["dossier_master.json"]) ]


RULE_HANDLERS: dict[str, RuleHandler] = {
    "dossier_identity_missing": lambda ctx: rule_dossier_identity_missing(ctx, load_rule_specs(ctx.settings)["dossier_identity_missing"]),
    "document_source_missing": lambda ctx: rule_document_source_missing(ctx, load_rule_specs(ctx.settings)["document_source_missing"]),
    "required_field_missing": lambda ctx: rule_required_field_missing(ctx, load_rule_specs(ctx.settings)["required_field_missing"]),
    "amount_invalid": lambda ctx: rule_amount_invalid(ctx, load_rule_specs(ctx.settings)["amount_invalid"]),
    "date_order_incoherent": lambda ctx: rule_date_order_incoherent(ctx, load_rule_specs(ctx.settings)["date_order_incoherent"]),
    "multiple_conflicting_values": lambda ctx: rule_multiple_conflicting_values(ctx, load_rule_specs(ctx.settings)["multiple_conflicting_values"]),
    "source_fact_conflict": lambda ctx: rule_source_fact_conflict(ctx, load_rule_specs(ctx.settings)["source_fact_conflict"]),
    "checklist_incomplete": lambda ctx: rule_checklist_incomplete(ctx, load_rule_specs(ctx.settings)["checklist_incomplete"]),
    "sale_parties_missing": lambda ctx: rule_sale_parties_missing(ctx, load_rule_specs(ctx.settings)["sale_parties_missing"]),
    "sale_tf_missing": lambda ctx: rule_sale_tf_missing(ctx, load_rule_specs(ctx.settings)["sale_tf_missing"]),
    "sale_price_missing": lambda ctx: rule_sale_price_missing(ctx, load_rule_specs(ctx.settings)["sale_price_missing"]),
    "price_multiple_declared": lambda ctx: rule_price_multiple_declared(ctx, load_rule_specs(ctx.settings)["price_multiple_declared"]),
    "sale_payment_breakdown_incoherent": lambda ctx: rule_sale_payment_breakdown_incoherent(ctx, load_rule_specs(ctx.settings)["sale_payment_breakdown_incoherent"]),
    "sale_deferred_payment_missing_terms": lambda ctx: rule_sale_deferred_payment_missing_terms(ctx, load_rule_specs(ctx.settings)["sale_deferred_payment_missing_terms"]),
    "sale_payment_route_unclear": lambda ctx: rule_sale_payment_route_unclear(ctx, load_rule_specs(ctx.settings)["sale_payment_route_unclear"]),
    "sale_representative_missing_power": lambda ctx: rule_sale_representative_missing_power(ctx, load_rule_specs(ctx.settings)["sale_representative_missing_power"]),
    "sale_tax_and_fees_clause_missing": lambda ctx: rule_sale_tax_and_fees_clause_missing(ctx, load_rule_specs(ctx.settings)["sale_tax_and_fees_clause_missing"]),
    "mortgage_beneficiary_missing": lambda ctx: rule_mortgage_beneficiary_missing(ctx, load_rule_specs(ctx.settings)["mortgage_beneficiary_missing"]),
    "mortgage_tf_missing": lambda ctx: rule_mortgage_tf_missing(ctx, load_rule_specs(ctx.settings)["mortgage_tf_missing"]),
    "mortgage_credit_amount_missing": lambda ctx: rule_mortgage_credit_amount_missing(ctx, load_rule_specs(ctx.settings)["mortgage_credit_amount_missing"]),
    "mortgage_rank_missing": lambda ctx: rule_mortgage_rank_missing(ctx, load_rule_specs(ctx.settings)["mortgage_rank_missing"]),
    "mortgage_rank_amount_confusion": lambda ctx: rule_mortgage_rank_amount_confusion(ctx, load_rule_specs(ctx.settings)["mortgage_rank_amount_confusion"]),
    "mortgage_registration_not_proven": lambda ctx: rule_mortgage_registration_not_proven(ctx, load_rule_specs(ctx.settings)["mortgage_registration_not_proven"]),
    "mortgage_surety_detected": lambda ctx: rule_mortgage_surety_detected(ctx, load_rule_specs(ctx.settings)["mortgage_surety_detected"]),
    "mortgage_deadline_missing": lambda ctx: rule_mortgage_deadline_missing(ctx, load_rule_specs(ctx.settings)["mortgage_deadline_missing"]),
    "release_bank_discharge_missing": lambda ctx: rule_release_bank_discharge_missing(ctx, load_rule_specs(ctx.settings)["release_bank_discharge_missing"]),
    "release_requisition_missing": lambda ctx: rule_release_requisition_missing(ctx, load_rule_specs(ctx.settings)["release_requisition_missing"]),
    "release_reference_missing": lambda ctx: rule_release_reference_missing(ctx, load_rule_specs(ctx.settings)["release_reference_missing"]),
    "release_bank_conflict": lambda ctx: rule_release_bank_conflict(ctx, load_rule_specs(ctx.settings)["release_bank_conflict"]),
    "donation_parties_missing": lambda ctx: rule_donation_parties_missing(ctx, load_rule_specs(ctx.settings)["donation_parties_missing"]),
    "donation_tf_missing": lambda ctx: rule_donation_tf_missing(ctx, load_rule_specs(ctx.settings)["donation_tf_missing"]),
    "donation_declared_value_missing": lambda ctx: rule_donation_declared_value_missing(ctx, load_rule_specs(ctx.settings)["donation_declared_value_missing"]),
    "donation_qualification_missing": lambda ctx: rule_donation_qualification_missing(ctx, load_rule_specs(ctx.settings)["donation_qualification_missing"]),
    "donation_family_link_unproven": lambda ctx: rule_donation_family_link_unproven(ctx, load_rule_specs(ctx.settings)["donation_family_link_unproven"]),
    "donation_tax_rate_missing": lambda ctx: rule_donation_tax_rate_missing(ctx, load_rule_specs(ctx.settings)["donation_tax_rate_missing"]),
    "succession_death_missing": lambda ctx: rule_succession_death_missing(ctx, load_rule_specs(ctx.settings)["succession_death_missing"]),
    "succession_deceased_missing": lambda ctx: rule_succession_deceased_missing(ctx, load_rule_specs(ctx.settings)["succession_deceased_missing"]),
    "succession_heirs_missing": lambda ctx: rule_succession_heirs_missing(ctx, load_rule_specs(ctx.settings)["succession_heirs_missing"]),
    "succession_shares_incoherent": lambda ctx: rule_succession_shares_incoherent(ctx, load_rule_specs(ctx.settings)["succession_shares_incoherent"]),
    "succession_property_missing": lambda ctx: rule_succession_property_missing(ctx, load_rule_specs(ctx.settings)["succession_property_missing"]),
    "succession_representative_missing_power": lambda ctx: rule_succession_representative_missing_power(ctx, load_rule_specs(ctx.settings)["succession_representative_missing_power"]),
    "power_principal_missing": lambda ctx: rule_power_principal_missing(ctx, load_rule_specs(ctx.settings)["power_principal_missing"]),
    "power_agent_missing": lambda ctx: rule_power_agent_missing(ctx, load_rule_specs(ctx.settings)["power_agent_missing"]),
    "power_scope_missing": lambda ctx: rule_power_scope_missing(ctx, load_rule_specs(ctx.settings)["power_scope_missing"]),
    "power_duration_unclear": lambda ctx: rule_power_duration_unclear(ctx, load_rule_specs(ctx.settings)["power_duration_unclear"]),
    "power_foreign_formality_unverified": lambda ctx: rule_power_foreign_formality_unverified(ctx, load_rule_specs(ctx.settings)["power_foreign_formality_unverified"]),
    "vefa_program_or_tf_missing": lambda ctx: rule_vefa_program_or_tf_missing(ctx, load_rule_specs(ctx.settings)["vefa_program_or_tf_missing"]),
    "vefa_plan_or_description_missing": lambda ctx: rule_vefa_plan_or_description_missing(ctx, load_rule_specs(ctx.settings)["vefa_plan_or_description_missing"]),
    "vefa_payment_schedule_missing": lambda ctx: rule_vefa_payment_schedule_missing(ctx, load_rule_specs(ctx.settings)["vefa_payment_schedule_missing"]),
    "vefa_guarantee_unproven": lambda ctx: rule_vefa_guarantee_unproven(ctx, load_rule_specs(ctx.settings)["vefa_guarantee_unproven"]),
    "vefa_delivery_terms_missing": lambda ctx: rule_vefa_delivery_terms_missing(ctx, load_rule_specs(ctx.settings)["vefa_delivery_terms_missing"]),
    "vefa_completion_documents_not_applicable": lambda ctx: rule_vefa_completion_documents_not_applicable(ctx, load_rule_specs(ctx.settings)["vefa_completion_documents_not_applicable"]),
    "business_sale_parties_missing": lambda ctx: rule_business_sale_parties_missing(ctx, load_rule_specs(ctx.settings)["business_sale_parties_missing"]),
    "business_sale_rc_missing": lambda ctx: rule_business_sale_rc_missing(ctx, load_rule_specs(ctx.settings)["business_sale_rc_missing"]),
    "business_sale_lease_or_occupation_unclear": lambda ctx: rule_business_sale_lease_or_occupation_unclear(ctx, load_rule_specs(ctx.settings)["business_sale_lease_or_occupation_unclear"]),
    "business_sale_encumbrances_unverified": lambda ctx: rule_business_sale_encumbrances_unverified(ctx, load_rule_specs(ctx.settings)["business_sale_encumbrances_unverified"]),
    "business_sale_inventory_missing": lambda ctx: rule_business_sale_inventory_missing(ctx, load_rule_specs(ctx.settings)["business_sale_inventory_missing"]),
    "business_sale_price_missing": lambda ctx: rule_business_sale_price_missing(ctx, load_rule_specs(ctx.settings)["business_sale_price_missing"]),
    "business_sale_publicity_unverified": lambda ctx: rule_business_sale_publicity_unverified(ctx, load_rule_specs(ctx.settings)["business_sale_publicity_unverified"]),
    "auto_sale_vehicle_identification_missing": lambda ctx: rule_auto_sale_vehicle_identification_missing(ctx, load_rule_specs(ctx.settings)["auto_sale_vehicle_identification_missing"]),
}


def build_context(dossier_path: Path, settings: Optional[Settings] = None) -> tuple[ValidationContext, list[str]]:
    settings = settings or get_settings()
    dossier_id = dossier_path.name
    master_path = dossier_path / "dossier_master.json"
    master = _safe_load_master(master_path) if master_path.exists() else {}
    donnees = master.get("donnees") if isinstance(master.get("donnees"), dict) else {}
    doc_paths = _list_document_files(dossier_path)
    texts_by_file, extraction_errors = _extract_texts(doc_paths)
    combined_text = "\n\n".join(texts_by_file.values())
    checklist_report = evaluate_document_checklist(dossier_id, settings=settings)
    return ValidationContext(
        settings=settings,
        dossier_path=dossier_path,
        dossier_id=dossier_id,
        master=master,
        donnees=donnees,
        type_dossier=str(master.get("type_dossier", "") or "").strip().upper(),
        variante=_slug(master.get("variante") or ""),
        doc_paths=doc_paths,
        filenames=[p.name for p in doc_paths],
        texts_by_file=texts_by_file,
        combined_text=combined_text,
        checklist_report=checklist_report,
    ), extraction_errors


def validate_dossier_path(dossier_path: Path, settings: Optional[Settings] = None) -> ValidationReport:
    settings = settings or get_settings()
    dossier_id = dossier_path.name
    if not (dossier_path / "dossier_master.json").exists():
        return ValidationReport(
            dossier_id=dossier_id,
            status="invalid",
            summary={"blocking": 1, "warning": 0, "info": 0},
            issues=[ValidationIssue(
                rule_id="missing_dossier_master",
                severity="blocking",
                title="Dossier maître absent",
                message="Le fichier dossier_master.json est absent ; la cohérence automatique ne peut pas être contrôlée.",
                evidence={"fields": {}, "documents": [], "source_refs": []},
                recommended_action="Restaurer le fichier dossier_master.json avant toute vérification complémentaire.",
                requires_notary_review=True,
            )],
        )

    ctx, extraction_errors = build_context(dossier_path, settings=settings)
    specs = load_rule_specs(settings)
    issues: list[ValidationIssue] = []
    for rule_id, handler in RULE_HANDLERS.items():
        spec = specs.get(rule_id)
        if not spec or not _applies(spec, ctx):
            continue
        issues.extend(handler(ctx))

    if extraction_errors:
        spec = RuleSpec(
            rule_id="document_extraction_warning",
            applies_to=[],
            severity="warning",
            title="Extraction documentaire incomplète",
            condition="Au moins un document n'a pas pu être lu intégralement.",
            message="Au moins un document n'a pas pu être extrait automatiquement ; une lecture humaine reste nécessaire.",
            recommended_action="Contrôler manuellement le ou les documents signalés.",
            requires_notary_review=True,
        )
        issues.append(_issue(spec, fields={"erreurs_extraction": extraction_errors}, documents=ctx.filenames, source_refs=extraction_errors))

    issues.sort(key=lambda i: {"blocking": 0, "warning": 1, "info": 2}.get(i.severity, 9))
    summary = {"blocking": 0, "warning": 0, "info": 0}
    for issue in issues:
        summary[issue.severity] = summary.get(issue.severity, 0) + 1
    if summary["blocking"] > 0:
        status = "invalid"
    elif summary["warning"] > 0:
        status = "warnings"
    else:
        status = "valid"
    return ValidationReport(dossier_id=dossier_id, status=status, summary=summary, issues=issues)


def write_validation_report(report: ValidationReport, settings: Optional[Settings] = None) -> Path:
    settings = settings or get_settings()
    out_path = get_validation_report_path(report.dossier_id, settings=settings)
    payload = report.model_dump()
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def validate_and_write_dossier(dossier_path: Path, settings: Optional[Settings] = None) -> ValidationReport:
    report = validate_dossier_path(dossier_path, settings=settings)
    write_validation_report(report, settings=settings)
    return report
