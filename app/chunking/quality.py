"""Classification, extraction d'entités et règles de qualité — locales, déterministes, sans LLM.

Correctifs 2, 3, 4, 5, 6, 7 du cahier des charges :
- Rôles/sections classés par ordre de priorité (Prix/Paiement > Bien > Hypothèque > Financement >
  Parties > Signatures > Pièces jointes > clauses diverses), avec priorité absolue des titres
  explicites du type "Article 2 - Prix".
- Fragments/artefacts de tableaux exclus (indexable=False, retrieval_excluded=True).
- CIN validées (jamais "le 2024", "2024-12-12", "est", "consenti").
- Numéros de prêt extraits uniquement après déclencheur explicite.
- Rangs hypothécaires normalisés (1er rang -> 1, 3er rang -> 3) — jamais de valeur vide.
- Montants normalisés (1,650,000 DHS -> 1650000 ; 1.650.000 DHS -> 1650000 ; 600.000 درهم -> 600000)
  avec drapeaux amount_format_nonstandard et amount_words_digits_mismatch.
- Dates (ISO, JJ/MM/AAAA, "12 mai 2024", "3 نونبر 2024", "30 ماي 2025").
- Banques (BMCE Bank, AL BARID BANK, Attijariwafa Bank, BMCI, Wafa Immobilier, CDG, ...).
- Personnes structurées {name_fr, name_ar, role, cin, confidence} si les signaux sont explicites.
- Règles arabes (الثمن، تعيين العقار، رهن، قرض، بنك، حضر، التوقيع، المرفقات...) : l'arabe n'est
  JAMAIS traduit ni modifié ; les règles n'ajoutent que des métadonnées.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from app.core.schemas import Entities

# ---------------------------------------------------------------------------
# 1. Notice technique (Correctif 1)
# ---------------------------------------------------------------------------

NOTICE_RE = re.compile(
    r"(document\s+fictif\s*(?:g[ée]n[ée]r[ée])?\s*(?:pour\s+test\s+rag\s*)?-?\s*aucune\s+donn[ée]e\s+r[ée]elle"
    r"|aucune\s+donn[ée]e\s+r[ée]elle\s*-?\s*ne\s+pas\s+utiliser\s+comme\s+acte\s+authentique"
    r"|ne\s+pas\s+utiliser\s+comme\s+acte\s+authentique"
    r"|document\s+fictif"
    r"|و[ثت]يقة\s+خيالية"
    r"|لا\s+تستخدم\s+ك[وثت]يقة\s+رسمية)",
    re.IGNORECASE,
)


def is_notice_line(text: str) -> bool:
    """True si le paragraphe est la notice technique « document fictif ». La notice n'est jamais
    indexable (aucune donnée réelle exploitable) mais doit être SORTIE du contenu métier."""
    return bool(NOTICE_RE.search(text))


def split_leading_notice(paragraphs: list[str], max_leading: int = 3) -> tuple[list[str], list[str]]:
    """Détache les premières lignes de notice technique (si présentes) du reste du document.

    Renvoie (notice_paragraphs, body_paragraphs). Le corps est ensuite découpé normalement et
    indexé si suffisamment utile — on ne perd jamais les entités postérieures à la notice.
    """
    notice: list[str] = []
    i = 0
    while i < len(paragraphs) and i < max_leading and is_notice_line(paragraphs[i]):
        notice.append(paragraphs[i])
        i += 1
    return notice, paragraphs[i:]


# ---------------------------------------------------------------------------
# 2. Qualité : fragments, artefacts de tableaux, chunks dégénérés (Correctif 3)
# ---------------------------------------------------------------------------

_SIG_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ\u0600-\u06FF]")
_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ\u0600-\u06FF]{2,}")


def significant_chars(text: str) -> list[str]:
    return _SIG_RE.findall(text)


def is_table_artifact_paragraph(text: str) -> bool:
    """Ligne de tableau purement structurelle ("LE |", "DROIT RECU |", "| | LE | | |")."""
    if "|" not in text:
        return False
    return len(significant_chars(text)) < 20


def has_reliable_value(text: str) -> bool:
    """True si le fragment contient une entité fiable (montant, CIN, TF, date, banque, personne)."""
    ent, *_ = extract_entities(text)
    return bool(
        ent.cin or ent.land_titles or ent.amounts_dhs or ent.dates or ent.banks or ent.persons
    )


def is_degenerate_chunk(text: str) -> tuple[bool, str]:
    """Un chunk inutile pour le RAG (moins de 20 caractères significatifs, < 4 tokens utiles,
    uniquement séparateurs/fragments de tableau, faible ratio de contenu, aucune phrase métier).

    Retourne (est_exclu, drapeau_qualité).
    """
    t = text.strip()
    if not t:
        return True, "empty_or_separators"
    sig = significant_chars(t)
    if len(sig) < 20:
        return True, "too_short_or_fragment"
    tokens = _WORD_RE.findall(t)
    if len(tokens) < 4:
        return True, "too_few_tokens"
    alpha = [c for c in sig if c.isalpha()]
    if not alpha or len(alpha) / len(sig) < 0.15:
        return True, "low_content_ratio"
    return False, ""


# ---------------------------------------------------------------------------
# 3. Classification par sections et rôles (Correctif 2) — ordre de priorité obligatoire
# ---------------------------------------------------------------------------

PRICE_KW = ["prix", "montant", "dhs", "dirham", "الثمن", "مبلغ", "درهم"]
PAYMENT_KW = ["paiement", "payée", "payé", "versement", "comptant", "acompte", "quittance", "consignation", "أداء", "دفع"]
PROPERTY_KW = [
    "désignation", "titre foncier", "superficie", "sis à", "immeuble", "terrain",
    "objet de la vente", "consistance", "تعيين العقار", "الرسم العقاري", "وصف العقار",
    "تحديد العقار", "الملك",
]
MORTGAGE_KW = ["hypothèque", "hypothec", "hypothécaire", "engagement hypothécaire", "mainlevée", "mainlevee", "radiation", "rang", "nantissement", "رهن", "رفع اليد", "التشطيب"]
FINANCING_KW = ["banque", "prêt", "crédit", "crédit bancaire", "remboursement", "financement", "bank", "بنك", "قرض", "تمويل"]
PARTIES_KW = [
    "vendeur", "acquéreur", "acheteur", "donateur", "donataire", "mandant", "mandataire",
    "débiteur", "débiteur", "créancier", "caution", "comparant", "représentant", "notaire",
    "soussign", "emprunteur", "البائع", "المشتري", "المتصدق", "الموكل", "الوكيل", "المدين",
    "الدائن", "الكفيل", "الأطراف", "حضر", "وكالة",
]
SIGNATURES_KW = ["fait à", "fait et passé", "lecture faite", "signé", "signature", "dont acte", "حرر", "أنجز", "التوقيع", "وقع"]
ATTACHMENTS_KW = ["pièces jointes", "annexe", "pièces annexées", "المرفقات", "الوثائق المرفقة", "الوثائق المدلى بها"]

# (role, keywords, section) — l'ordre définit la priorité (Correctif 2).
ORDERED_RULES = [
    ("payment", PAYMENT_KW, "prix_paiement"),
    ("price", PRICE_KW, "prix_paiement"),
    ("property", PROPERTY_KW, "designation_bien"),
    ("mortgage", MORTGAGE_KW, "financement_hypotheque"),
    ("financing", FINANCING_KW, "financement_hypotheque"),
    ("parties", PARTIES_KW, "identification_parties"),
    ("signatures", SIGNATURES_KW, "formalites_signatures"),
    ("attachments", ATTACHMENTS_KW, "pieces_jointes"),
]

_ARTICLE_TITLE_RE = re.compile(r"^(?:article|المادة)\s+[\dIVXLCivxlc]+\s*[-–—:.]*\s*(.*)$", re.IGNORECASE)


def _norm(text: str) -> str:
    lowered = text.strip().lower()
    return unicodedata.normalize("NFKD", lowered)


def _title_keywords(text: str) -> str:
    """Extrait le titre explicite ("Article 2 - Prix") pour lui donner priorité sur le reste."""
    first = text.strip().split("\n", 1)[0].strip()
    if not first:
        return ""
    if re.match(r"^(?:article|المادة)\b", first, re.IGNORECASE):
        m = _ARTICLE_TITLE_RE.match(first)
        return (m.group(1) if m else first).strip()
    return ""


def _match_rules(text: str) -> tuple[Optional[str], float, Optional[str]]:
    """Classification par score pondéré : la catégorie avec le plus de mots-clés distincts
    gagne ; à score égal, l'ordre de priorité du Correctif 2 départage.

    Exemple : un engagement hypothécaire contient hypothèque + rang + banque + crédit +
    caution + montant : mortgage (2) et financing (2) battent price (1 seul signal DHS),
    et mortgage prime sur financing par l'ordre du cahier des charges."""
    n = _norm(text)
    scores: list[tuple[int, int, str, str]] = []
    for idx, (role, keywords, section) in enumerate(ORDERED_RULES):
        cnt = sum(1 for kw in keywords if _norm(kw) in n)
        if cnt:
            scores.append((cnt, idx, role, section))
    if not scores:
        return None, 0.0, None
    scores.sort(key=lambda x: (-x[0], x[1]))
    return scores[0][2], 0.9, scores[0][3]


def _secondary_roles(text: str, primary: str) -> list[str]:
    n = _norm(text)
    out: list[str] = []
    for role, keywords, _section in ORDERED_RULES:
        if role == primary:
            continue
        if any(_norm(kw) in n for kw in keywords):
            out.append(role)
    return out


def classify_full(text: str) -> tuple[str, float, str, list[str]]:
    """(chunk_role, confidence, section, secondary_chunk_roles) — Correctif 2 + 6.

    Priorité :
    1. notice technique (non indexable) ;
    2. titre explicite "Article N - ..." ;
    3. règles par ordre de priorité (Prix/Paiement avant tout, clauses en dernier recours).
    """
    if is_notice_line(text):
        return "technical_notice", 0.98, "notice_technique", []

    title = _title_keywords(text)
    role_b, conf_b, section_b = _match_rules(text)

    if title:
        role_t, conf_t, _sec_t = _match_rules(title)
        if role_t:
            # Un titre explicite l'emporte toujours sur les mots génériques du corps.
            return role_t, max(conf_t, 0.95), _sec_t or "clauses_diverses", _secondary_roles(text, role_t)

    if role_b and role_b != "clause":
        return role_b, conf_b, section_b or "clauses_diverses", _secondary_roles(text, role_b)

    return "clause", 0.5, "clauses_diverses", []


def classify_text(text: str) -> tuple[str, float, str]:
    """API rétrocompatible (3 valeurs) utilisée par les anciens tests."""
    role, conf, section, _ = classify_full(text)
    return role, conf, section


# ---------------------------------------------------------------------------
# 4. Entités : CIN, prêts, rangs, montants, dates, banques (Correctif 4)
# ---------------------------------------------------------------------------

CIN_STOPWORDS = {
    "le", "la", "les", "du", "de", "des", "un", "une", "et", "ou", "au", "aux", "est",
    "consenti", "accordé", "dans", "sur", "pour", "par", "ce", "se", "sa", "son", "the",
    "sur", "avec", "sous", "che", "maitre", "maître",
}
CIN_RE = re.compile(r"(?<![0-9A-Za-z])([A-Za-z]{1,2}[0-9]{4,7})(?![0-9A-Za-z])")


def _valid_cin(token: str) -> bool:
    """CIN plausible : >= 1 lettre, >= 3 chiffres, aucun espace, pas une date,
    pas un mot courant, pas un fragment de phrase."""
    m = re.fullmatch(r"([A-Za-z]{1,2})([0-9]{4,7})", token)
    if not m:
        return False
    letters = m.group(1).lower()
    digits = m.group(2)
    if len(digits) < 3:
        return False
    if letters in CIN_STOPWORDS:
        return False
    # pas une année isolée du type "le2024" (déjà couvert par stopword) ni un fragment court
    if re.fullmatch(r"20\d\d", digits) and len(token) <= 6:
        return False
    return True


# Numéros de prêt : uniquement après déclencheurs explicites (Correctif 4)
_LOAN_TRIGGERS = [
    r"pr[êe]t\s+num[ée]ro\s*",
    r"pr[êe]t\s*(?:n[°ºo]\s*)?[:#\-]?\s*",
    r"n[°ºo]\s*de\s*pr[êe]t\s*[:#\-]?\s*",
    r"num[ée]ro\s*de\s*pr[êe]t\s*[:#\-]?\s*",
    r"num[ée]ro\s*de\s*cr[ée]dit\s*[:#\-]?\s*",
    r"r[ée]f[ée]rence\s*(?:de\s*)?pr[êe]t\s*[:#\-]?\s*",
    r"r[ée]f[ée]rence\s*(?:de\s*)?cr[ée]dit\s*[:#\-]?\s*",
    r"loan\s+number\s*[:#\-]?\s*",
]
LOAN_RE = re.compile(
    r"(?i)(?:" + "|".join(_LOAN_TRIGGERS) + r")([A-Z0-9][A-Z0-9/_.\-]{2,})"
)
_LOAN_STOPWORDS = {"est", "consenti", "accordé", "de", "du", "le", "la", "sur", "pour", "a", "à", "au"}


# Rangs hypothécaires : 1er rang -> 1, 3er rang -> 3, premier rang -> 1 (Correctif 4)
_RANK_WORDS = {
    "premier": 1, "première": 1, "premiere": 1,
    "deuxième": 2, "deuxieme": 2, "second": 2,
    "troisième": 3, "troisieme": 3,
}
_RANK_TOKENS = {
    "1er": 1, "1ere": 1, "1ère": 1, "1re": 1, "1st": 1,
    "2e": 2, "2ème": 2, "2eme": 2, "2nd": 2, "2d": 2,
    "3e": 3, "3er": 3, "3eme": 3, "3ème": 3,
}
_AR_RANKS = {"الأولى": 1, "الاولى": 1, "الثانية": 2, "الثانية": 2, "الثالثة": 3, "الثالثة": 3}
_RANK_TOKEN_RE = re.compile(r"(?i)\b(1er|1[èe]re|1re|1st|2e|2[èe]me|2eme|2nd|2d|3er|3e|3[èe]me|3eme)\s+rang\b")
_RANK_WORD_RE = re.compile(r"(?i)\b(premier|premi[èe]re|deuxi[èe]me|second|troisi[èe]me)\s+rang\b")
_RANK_NUM_RE = re.compile(r"(?i)\brang\s*(?:n[°ºo]\s*|de\s*)?([123])\b")
_RANK_AR_RE = re.compile(r"(?:الرتبة|رتبة)\s*(?:الأولى|الاولى|الثانية|الثالثة)")


def _extract_mortgage_ranks(text: str) -> list[str]:
    ranks: list[str] = []
    for m in _RANK_TOKEN_RE.finditer(text):
        ranks.append(str(_RANK_TOKENS[m.group(1).lower()]))
    for m in _RANK_WORD_RE.finditer(text):
        w = m.group(1).lower()
        ranks.append(str(_RANK_WORDS.get(w, 0)))
    for m in _RANK_NUM_RE.finditer(text):
        ranks.append(m.group(1))
    for m in _RANK_AR_RE.finditer(text):
        word = re.findall(r"(الأولى|الاولى|الثانية|الثالثة)", m.group(0))
        if word:
            ranks.append(str(_AR_RANKS[word[-1]]))
    # dédoublonnage, ordre conservé, jamais de valeur vide
    out: list[str] = []
    for r in ranks:
        if r and r not in out:
            out.append(r)
    return out


# Montants (Correctif 4) — unités : DHS, DH, dirham(s), درهم
AMOUNT_RE = re.compile(
    r"(?<![0-9])([0-9]{1,3}(?:[.,\s][0-9]{3})+)\s*(DHS|DH|dirhams?|درهم)\b", re.IGNORECASE
)


def _normalize_amount(raw: str) -> tuple[Optional[float], list[str]]:
    """Normalise sans modifier le texte source :
    1,650,000 DHS -> 1650000 | 1.650.000 DHS -> 1650000 | 600.000 درهم -> 600000
    Les virgules et les espaces sont considérés comme des formats non standard au Maroc
    (le point séparateur de milliers y est la convention) ; les formats mixtes sont ambigus.
    """
    flags: list[str] = []
    s = raw.replace(" ", "")
    if not s:
        return None, flags
    if "," in s and "." in s:
        flags.append("amount_format_nonstandard")  # format mixte ambigu
        return float(s.replace(",", "").replace(".", "")), flags
    if "," in s:
        # virgule = séparateur de milliers (format non standard pour des dirhams marocains)
        flags.append("amount_format_nonstandard")
        return float(s.replace(",", "")), flags
    if "." in s:
        parts = s.split(".")
        if len(parts) > 1 and len(parts[-1]) <= 2:
            # décimale (ex: 12.5) — rare dans les actes, format non standard
            flags.append("amount_format_nonstandard")
            return float(s), flags
        return float(s.replace(".", "")), flags  # 340.000 -> 340000 (convention locale)
    return float(s), flags


# --- Comparaison montant en chiffres / montant en lettres (français, local) ---
_FR_NUM = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12,
    "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "trente": 30,
    "quarante": 40, "cinquante": 50, "soixante": 60, "soixante-dix": 70,
    "quatre-vingt": 80, "quatre-vingt-dix": 90, "cent": 100, "cents": 100,
    "mille": 1000, "million": 1_000_000, "millions": 1_000_000,
}
_AMOUNT_WORD_HINT = re.compile(
    r"(?i)\b(?:mille|millions?|cent|vingt|trente|quarante|cinquante|soixante|dix|onze|douze|"
    r"treize|quatorze|quinze|seize|un|deux|trois|quatre|cinq|six|sept|huit|neuf)\b"
)


def parse_french_number(phrase: str) -> Optional[int]:
    """Parse déterministe d'un montant en lettres françaises (ex: SEPT CENT QUATRE-VINGT MILLE = 780000)."""
    tokens = re.findall(r"[a-zà-ÿ]+(?:-[a-zà-ÿ]+)?", phrase.lower())
    if not tokens:
        return None
    valid: list[str] = []
    for tok in tokens:
        if tok in _FR_NUM:
            valid.append(tok)
        elif tok in ("dhs", "dh", "dirham", "dirhams", "et"):
            if tok == "et":
                continue
            break
        else:
            break
    if not valid:
        return None
    total, cur = 0, 0
    for tok in valid:
        v = _FR_NUM[tok]
        if v == 100:
            cur = (cur if cur else 1) * 100
        elif v in (1000, 1_000_000):
            cur = (cur if cur else 1) * v
            total += cur
            cur = 0
        else:
            cur += v
    return total + cur


def _words_amount_near(text: str, start: int, end: int) -> Optional[int]:
    window = text[end : end + 220]
    m = re.search(r"\(\s*([^()]{2,110}?)\s*\)", window)
    phrase = m.group(1) if m else None
    if phrase and re.search(r"\d", phrase):
        phrase = None
    if phrase is None:
        m2 = re.search(r"(?i)\b([a-zà-ÿ\- ]{2,80}?\b(?:dhs|dh|dirhams?))\b", window)
        if not m2:
            return None
        phrase = m2.group(1)
    if not _AMOUNT_WORD_HINT.search(phrase):
        return None
    return parse_french_number(phrase)


# Titres fonciers (Correctif 4)
TF_RE = re.compile(
    r"(?i)(?:t\.?\s*f\.?|titre\s+foncier|r[ée]f[ée]rence\s+fonci[èe]re|الرسم\s+العقاري)\s*"
    r"(?:n[°ºo]\s*)?[:#\- ]{0,3}([0-9]{2,3}[.,][0-9]{3}/[0-9]{2})"
)
_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m[²2]", re.IGNORECASE)

# Dates (Correctif 4)
_DATE_PATTERNS = [
    re.compile(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}"),                       # 2024-06-11
    re.compile(r"\d{1,2}/\d{1,2}/(?:20\d{2}|\d{2})"),                     # 12/06/2024
    re.compile(r"(?i)\b\d{1,2}\s+(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
               r"septembre|octobre|novembre|d[ée]cembre)\s+20\d{2}\b"),   # 12 mai 2024
    re.compile(r"\b\d{1,2}\s+(?:يناير|فبراير|مارس|أبريل|ماي|مايو|يونيو|يوليوز|غشت|شتنبر|"
               r"أكتوبر|نونبر|دجنبر)\s+20\d{2}\b"),                        # 3 نونبر 2024 / 30 ماي 2025
]

# Banques et organismes (Correctif 4)
BANKS = [
    ("BMCE Bank", r"bmce\s*bank|banque\s+bmce|bmce"),
    ("AL BARID BANK", r"al\s*barid\s*bank|barid"),
    ("Attijariwafa Bank", r"attijariwafa\s*bank|attijari\s+wafa\s*bank|attijariwafa|attijari"),
    ("BMCI", r"\bbmci\b"),
    ("Wafa Immobilier", r"wafa\s+immobilier"),
    ("CDG", r"\bcdg\b|caisse\s+de\s+d[ée]p[ôo]t\s+et\s+de\s+gestion"),
    ("CIH Bank", r"\bcih\b"),
    ("Banque Populaire", r"banque\s+populaire"),
    ("Société Générale Maroc", r"soci[ée]t[ée]\s+g[ée]n[ée]rale\s*maroc"),
    ("Crédit Agricole du Maroc", r"cr[ée]dit\s+agricole\s*maroc"),
]


def extract_dates(text: str) -> list[str]:
    out: list[str] = []
    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            out.append(m.group(0))
    dedup: list[str] = []
    for d in out:
        if d not in dedup:
            dedup.append(d)
    return dedup


def extract_banks(text: str) -> list[str]:
    found: list[str] = []
    t = " " + text + " "
    tn = t.lower()
    for canonical, pattern in BANKS:
        if re.search(pattern, tn):
            found.append(canonical)
    return found


# ---------------------------------------------------------------------------
# 5. Personnes et rôles structurés (Correctif 5)
# ---------------------------------------------------------------------------

ROLE_SYNONYMS = {
    "vendeur": "vendeur", "vend": "vendeur",
    "acquéreur": "acquéreur", "acquereur": "acquéreur", "acheteur": "acquéreur",
    "donateur": "donateur", "donataire": "donataire",
    "mandant": "mandant", "mandataire": "mandataire",
    "débiteur": "débiteur", "debiteur": "débiteur", "emprunteur": "débiteur",
    "créancier": "créancier", "crediteur": "créancier",
    "caution": "caution",
    "représentant": "représentant", "representant": "représentant", "gerant": "représentant", "gérant": "représentant",
    "notaire": "notaire", "comparant": "comparant",
    "البائع": "vendeur", "المشتري": "acquéreur", "المتصدق": "donateur",
    "المتصدق عليه": "donataire", "الموكل": "mandant", "الوكيل": "mandataire",
    "المدين": "débiteur", "الدائن": "créancier", "الكفيل": "caution",
    "النائب": "représentant", "الموثق": "notaire", "الحاضر": "comparant", "حضر": "comparant",
}
_ROLE_KEYWORD_RE = re.compile(
    r"(?i)\b(vendeur|venderesse|acquéreur|acquereur|acheteur|donateur|donataire|mandant|mandataire|"
    r"d[ée]biteur|emprunteur|cr[ée]ancier|caution|repr[ée]sentant|g[ée]rant|notaire|comparant)\b"
    r"|(البائع|المشتري|المتصدق|الموكل|الوكيل|المدين|الدائن|الكفيل|النائب|الموثق|الحاضر)",
    re.IGNORECASE,
)

# "Mohamed ELYACOUBI (محمد اليعقوبي, CIN EJ221190), ci-après « le Vendeur »"
_QUOTES = '\u00ab\u00bb\u201c\u201d\u2018\u2019"'
_PERSON_PAREN_RE = re.compile(
    r"(?P<name>[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’\- ]{1,45}?)\s*\((?P<paren>[^()]{0,60}?)\)"
    r"\s*,?\s*(?:ci-après\s*)?[" + _QUOTES + r"]?\s*(?:le|la|les|l'|d'|M\.|Mme|Mlle)?\s*"
    r"(?P<role>[A-Za-zÀ-ÿ]{3,20})[" + _QUOTES + r"]?",
    re.IGNORECASE,
)
# "Je soussigné Maître Fouad BENJELLOUN, notaire à El Jadida,"
_PERSON_COMMA_RE = re.compile(
    r"(?P<name>[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’\- ]{1,45}?)\s*,\s*(?P<role>notaire|repr[ée]sentant|caution|"
    r"vendeur|acqu[ée]reur|mandant|mandataire|d[ée]biteur|cr[ée]ancier|donateur|donataire)\b",
    re.IGNORECASE,
)
_NAME_BEFORE_CIN_RE = re.compile(r"([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’\- ]{2,45})$")
_CIN_IN_PAREN_RE = re.compile(r"CIN\s*([A-Za-z]{1,2}[0-9]{4,7})", re.IGNORECASE)

# Mots français vides / titres / unités monétaires qui disqualifient un nom propre capturé.
_BAD_NAME_TOKENS = {
    "le", "la", "les", "du", "de", "des", "un", "une", "et", "ou", "au", "aux", "en",
    "par", "avec", "pour", "sur", "sous", "dans", "maître", "maitre", "par-devant",
    "soussigné", "soussigne", "entre", "mains", "dhs", "dh", "dirham", "dirhams", "درهم",
    "moi", "je", "lui", "elle", "dont", "acte", "lequel", "laquelle", "son", "sa",
}
_MONEY_NAME_RE = re.compile(r"(?i)^(dhs|dh|dirhams?|درهم)([\s,\u00ab\u00bb])?$")


def _plausible_person_name(name: str) -> Optional[str]:
    """Nettoie et valide un nom propre candidat. Retourne None si le nom est en fait un
    fragment de phrase, une unité monétaire ou un titre (faux positifs Correctif 5)."""
    n = name.strip().strip('«»"“”’')
    n = re.sub(r"\s+", " ", n).strip()
    if len(n) < 3 or len(n) > 48:
        return None
    if _MONEY_NAME_RE.match(n):
        return None
    tokens = n.split()
    if len(tokens) > 4:
        return None
    if any(t.strip(".,;:«»""''").lower() in _BAD_NAME_TOKENS for t in tokens):
        return None
    if n.lower().startswith(("par-devant", "maître ", "maitre ", "me ", "m.")):
        return None
    # un nom propre doit contenir au moins un vrai mot commençant par une majuscule
    if not any(t[:1].isupper() for t in tokens):
        return None
    return n


def _split_ar_and_cin(paren: str) -> tuple[str, Optional[str]]:
    m = _CIN_IN_PAREN_RE.search(paren)
    cin = m.group(1) if m else None
    ar = re.sub(r"(?i)CIN\s*[A-Za-z]{1,2}[0-9]{4,7}[,\s]*", "", paren)
    ar = re.sub(r"[,\s]+$", "", ar).strip()
    return ar, cin


def _canonical_role(word: Optional[str]) -> Optional[str]:
    if not word:
        return None
    w = word.strip().strip('»"“”’«').strip()
    if not w:
        return None
    return ROLE_SYNONYMS.get(w.lower())


def _role_near(text: str) -> Optional[str]:
    m = _ROLE_KEYWORD_RE.search(text)
    if not m:
        return None
    word = m.group(1) or m.group(2)
    return _canonical_role(word)


def _find_name_before(before: str) -> Optional[str]:
    left = before.rsplit("(", 1)[0]
    m = _NAME_BEFORE_CIN_RE.search(left)
    return m.group(1).strip() if m else None


def extract_persons(text: str) -> list[dict]:
    """Personnes structurées {name_fr, name_ar, role, cin, confidence}.

    On ne crée une entité que lorsque les signaux sont explicites (nom + CIN et/ou rôle
    adjacent). Si le lien nom/rôle/CIN est ambigu, aucune entité structurée n'est créée.
    """
    persons: list[dict] = []

    for m in _PERSON_PAREN_RE.finditer(text):
        name = _plausible_person_name(m.group("name"))
        if not name:
            continue
        ar, cin = _split_ar_and_cin(m.group("paren"))
        role = _canonical_role(m.group("role"))
        if not role:
            role = _role_near(text[max(0, m.start() - 40) : m.end() + 60])
        conf = 0.9 if (cin and role) else (0.8 if (cin or role) else 0.0)
        if conf == 0.0:
            continue
        persons.append({
            "name_fr": name,
            "name_ar": ar,
            "role": role or "partie",
            "cin": cin or "",
            "confidence": conf,
        })

    for m in _PERSON_COMMA_RE.finditer(text):
        name = _plausible_person_name(m.group("name"))
        if not name:
            continue
        role = _canonical_role(m.group("role"))
        persons.append({
            "name_fr": name,
            "name_ar": "",
            "role": role or "partie",
            "cin": "",
            "confidence": 0.75,
        })

    # Ancrage par CIN : nom juste avant la parenthèse, rôle à proximité
    for m in CIN_RE.finditer(text):
        cin = m.group(1)
        if not _valid_cin(cin):
            continue
        before = text[max(0, m.start() - 140) : m.start()]
        after = text[m.end() : m.end() + 180]
        name = _find_name_before(before)
        role = _role_near(before) or _role_near(after)
        if name and role and len(name.split()) >= 2:
            persons.append({
                "name_fr": name,
                "name_ar": "",
                "role": role,
                "cin": cin,
                "confidence": 0.85,
            })

    # dédoublonnage (nom + CIN) en conservant l'ordre
    seen = set()
    out: list[dict] = []
    for p in persons:
        key = (p["name_fr"], p.get("cin") or "", p.get("role") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# 6. Point d'entrée global d'extraction d'entités
# ---------------------------------------------------------------------------

_amount_in_words_re = re.compile(
    r"(?i)\b(?:un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|"
    r"quinze|seize|vingt|trente|quarante|cinquante|soixante|cent|mille|million|millions)"
    r"[\w\s\-]{0,60}\b(?:dirhams?|dhs|dh)\b"
)


def extract_entities(text: str) -> tuple[Entities, float, list[str], bool]:
    """Retourne (Entities, confidence, quality_flags, requires_human_review)."""
    e = Entities()
    flags: list[str] = []

    def add(field: str, values: list):
        dedup: list = []
        for v in values:
            if v not in dedup:
                dedup.append(v)
        setattr(e, field, dedup)

    # CIN (Correctif 4)
    cin_vals: list[str] = []
    for m in CIN_RE.finditer(text):
        tok = m.group(1)
        if _valid_cin(tok):
            cin_vals.append(tok.upper())
    add("cin", cin_vals)

    # Titres fonciers
    add("land_titles", [m.group(1) for m in TF_RE.finditer(text)])

    # Surfaces
    add("areas_m2", [float(x.replace(",", ".")) for x in _AREA_RE.findall(text)])

    # Montants DHS / dirhams / درهم + comparaison chiffres/lettres
    amounts: list[float] = []
    for m in AMOUNT_RE.finditer(text):
        value, amt_flags = _normalize_amount(m.group(1))
        if value is None:
            continue
        if int(value) == value:
            value = float(int(value))
        amounts.append(value)
        flags.extend(amt_flags)
        words_val = _words_amount_near(text, m.start(), m.end())
        if words_val is not None and int(words_val) != int(value):
            flags.append("amount_words_digits_mismatch")
    add("amounts_dhs", amounts)

    # Montants en lettres (conservés pour comparaison/audit)
    add("amounts_in_words_fr", [m.group(0).strip() for m in _amount_in_words_re.finditer(text)])

    # Dates
    add("dates", extract_dates(text))

    # Banques
    add("banks", extract_banks(text))

    # Numéros de prêt (déclencheurs explicites uniquement)
    loan_vals: list[str] = []
    for m in LOAN_RE.finditer(text):
        candidate = m.group(1)
        if candidate.lower() in _LOAN_STOPWORDS:
            continue
        if not any(ch.isalpha() for ch in candidate) and len(candidate) < 6:
            continue
        loan_vals.append(candidate)
    add("loan_numbers", loan_vals)

    # Rangs hypothécaires (jamais de valeur vide)
    add("mortgage_ranks", _extract_mortgage_ranks(text))

    # Personnes structurées
    add("persons", extract_persons(text))

    has_entities = bool(e.cin or e.land_titles or e.amounts_dhs or e.dates or e.banks or e.persons)
    confidence = 0.9 if has_entities else 0.5
    flags = list(dict.fromkeys(flags))
    review = "amount_words_digits_mismatch" in flags
    return e, confidence, flags, review
