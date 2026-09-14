"""Detection heuristique de sections documentaires (dossiers clients) et de titres/clauses
(modeles internes), en francais et en arabe, sans dependance a un modele de langue externe.
"""
from __future__ import annotations

import re
import unicodedata

# Sections documentaires canoniques pour les dossiers clients (cahier des charges).
DOSSIER_SECTIONS = [
    "identification_parties",
    "designation_bien",
    "prix_paiement",
    "financement_hypotheque",
    "formalites_signatures",
    "pieces_jointes",
    "clauses_diverses",
]

_DOSSIER_KEYWORDS: dict[str, list[str]] = {
    "identification_parties": [
        "entre les soussign", "identification des parties", "les soussign", "comparution",
        "d'une part", "d'autre part", "بين الموقعين", "الطرف الأول", "الطرف الثاني", "الأطراف المتعاقدة",
        "الحاضرين", "بين كل من",
    ],
    "designation_bien": [
        "designation du bien", "designation de l'immeuble", "objet de la vente", "consistance",
        "titre foncier", "تعيين العقار", "وصف العقار", "تحديد العقار", "الرسم العقاري", "الملك موضوع",
    ],
    "prix_paiement": [
        "prix de vente", "modalites de paiement", "paiement du prix", "prix et modalites",
        "الثمن", "طريقة الأداء", "كيفية الأداء", "أداء الثمن",
    ],
    "financement_hypotheque": [
        "hypothec", "credit bancaire", "pret bancaire", "financement", "garantie bancaire",
        "mainlevee", "engagement hypothecaire", "رهن", "قرض", "تمويل", "ضمانة بنكية", "رفع اليد",
    ],
    "formalites_signatures": [
        "formalites", "lecture faite", "fait a", "signature", "dont acte", "التوقيع", "حرر بـ",
        "تلي ووقع", "وقع أدناه", "طي هذا",
    ],
    "pieces_jointes": [
        "pieces jointes", "annexe", "pieces annexees", "الوثائق المرفقة", "المرفقات", "الوثائق المدلى بها",
    ],
}

_HEADING_MAX_LEN = 90


def normalize_for_match(text: str) -> str:
    """Minuscule + suppression des accents latins (e.g. e->e, e->e), l'arabe reste intact."""
    lowered = text.strip().lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_heading_like(paragraph: str) -> bool:
    """Un paragraphe court, sans ponctuation finale de phrase, est probablement un titre/en-tete."""
    p = paragraph.strip()
    if not p or len(p) > _HEADING_MAX_LEN:
        return False
    if p.endswith((".", ",", ";")):
        return False
    # Beaucoup de majuscules (FR) ou tout en lettres arabes courtes -> probable titre
    letters = [c for c in p if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return upper_ratio > 0.6 or bool(re.match(r"^(ARTICLE|TITRE|CHAPITRE|SECTION)\b", p, re.IGNORECASE))


def detect_dossier_section(paragraph: str) -> tuple[str | None, float]:
    """Retourne (section_canonique, confidence) si le paragraphe correspond a un mot-cle connu."""
    norm = normalize_for_match(paragraph)
    for section, keywords in _DOSSIER_KEYWORDS.items():
        for kw in keywords:
            if kw in norm:
                confidence = 0.9 if is_heading_like(paragraph) else 0.6
                return section, confidence
    return None, 0.0


_TITLE_PATTERNS = [
    re.compile(r"^(ARTICLE|TITRE|CHAPITRE|SECTION)\s+", re.IGNORECASE),
    re.compile(r"^[IVXLCDM]+[.\-\)]\s+"),
    re.compile(r"^[0-9]+[.\-\)]\s+"),
]


def is_template_title(paragraph: str) -> bool:
    """Detection de titres/sous-titres/clauses dans un modele interne (FR ou AR)."""
    p = paragraph.strip()
    if not p or len(p) > _HEADING_MAX_LEN:
        return False
    for pat in _TITLE_PATTERNS:
        if pat.match(p):
            return True
    return is_heading_like(p)
