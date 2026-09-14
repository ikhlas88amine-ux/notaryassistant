"""Extraction de texte a partir de fichiers DOCX, DOC (legacy), PDF (texte ou scanne) et JSON.

Regles :
- Les fichiers originaux ne sont jamais modifies (lecture seule).
- Toute erreur d'extraction est renvoyee sous forme d'ExtractionResult(error=...) et ne doit
  jamais interrompre un traitement par lots : c'est a l'appelant de journaliser et continuer.
- Le nettoyage du texte est volontairement minimal (voir clean_text) : on ne corrige jamais
  silencieusement des informations juridiques ou factuelles.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import docx  # python-docx
import pymupdf as fitz  # pymupdf (import moderne, evite l'avertissement de depreciation de 'fitz')

IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
IGNORED_PREFIXES = ("~$", ".")
IGNORED_SUFFIXES = (".tmp", ".temp", ".lock", ".crdownload")


def is_ignorable_file(path: Path) -> bool:
    """True si le fichier est un fichier technique/cache/verrou a ignorer lors de l'indexation."""
    name = path.name
    lname = name.lower()
    if lname in IGNORED_NAMES:
        return True
    if name.startswith(IGNORED_PREFIXES):
        return True
    if lname.endswith(IGNORED_SUFFIXES):
        return True
    return False


def clean_text(text: str) -> str:
    """Nettoyage technique minimal : espaces repetitifs, lignes vides excessives, caracteres de controle.

    Ne modifie JAMAIS noms, CIN, montants, titres fonciers ou dates presents dans le texte source.
    """
    if not text:
        return ""
    # Caracteres de controle (hors \n et \t)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ch.isprintable())
    # Espaces horizontaux repetitifs
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Plus de 2 lignes vides consecutives -> 1 ligne vide
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trim des lignes
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


@dataclass
class ExtractionResult:
    text: str = ""
    extraction_method: str = ""  # docx | doc_libreoffice | pdf_text | pdf_ocr | json_existing
    extraction_quality: str = "normal"  # verified | normal | a_verifier | failed
    page_count: Optional[int] = None
    error: Optional[str] = None
    quality_flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def _extract_docx_text(path: Path) -> str:
    document = docx.Document(str(path))
    parts: list[str] = []
    for para in document.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_docx(path: Path) -> ExtractionResult:
    try:
        text = _extract_docx_text(path)
        return ExtractionResult(text=clean_text(text), extraction_method="docx", extraction_quality="verified")
    except Exception as exc:  # noqa: BLE001 - on veut capturer toute erreur de parsing docx
        return ExtractionResult(error=f"Erreur d'extraction DOCX: {exc}", extraction_method="docx", extraction_quality="failed")


def soffice_available() -> bool:
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def extract_doc(path: Path) -> ExtractionResult:
    """Extrait le texte d'un .doc legacy via conversion LibreOffice headless -> .docx temporaire.

    `extraction_method="doc_libreoffice"` signifie que la conversion a reellement reussi
    ET produit du texte non vide. Dans tout autre cas (LibreOffice absent, conversion
    echouee, texte vide), `extraction_method="failed"` pour ne pas laisser croire a une
    extraction reussie.
    """
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        return ExtractionResult(
            error="LibreOffice indisponible : impossible de convertir ce fichier .doc",
            extraction_method="failed",
            extraction_quality="failed",
        )
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [binary, "--headless", "--convert-to", "docx", "--outdir", tmp, str(path)],
                capture_output=True,
                text=True,
                timeout=90,
            )
        except Exception as exc:  # noqa: BLE001
            return ExtractionResult(
                error=f"Echec de conversion LibreOffice: {exc}",
                extraction_method="failed",
                extraction_quality="failed",
            )
        converted = Path(tmp) / (path.stem + ".docx")
        if proc.returncode != 0 or not converted.exists():
            return ExtractionResult(
                error=f"Conversion LibreOffice echouee (code {proc.returncode}): {proc.stderr[:500]}",
                extraction_method="failed",
                extraction_quality="failed",
            )
        try:
            text = _extract_docx_text(converted)
        except Exception as exc:  # noqa: BLE001
            return ExtractionResult(
                error=f"Erreur de lecture apres conversion: {exc}",
                extraction_method="failed",
                extraction_quality="failed",
            )
    cleaned = clean_text(text)
    if not cleaned.strip():
        return ExtractionResult(
            error="Conversion LibreOffice reussie mais texte extrait vide.",
            extraction_method="failed",
            extraction_quality="failed",
        )
    return ExtractionResult(text=cleaned, extraction_method="doc_libreoffice", extraction_quality="normal")


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def extract_pdf(path: Path, ocr_if_empty: bool = True) -> ExtractionResult:
    """Extrait le texte d'un PDF. Si le texte natif est vide (PDF scanne), tente un OCR local optionnel."""
    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(error=f"Erreur d'ouverture PDF: {exc}", extraction_method="pdf_text", extraction_quality="failed")

    try:
        parts = [page.get_text("text") for page in doc]
        page_count = doc.page_count
        text = "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(error=f"Erreur d'extraction PDF: {exc}", extraction_method="pdf_text", extraction_quality="failed")
    finally:
        doc.close()

    if text.strip():
        return ExtractionResult(text=clean_text(text), extraction_method="pdf_text", extraction_quality="verified", page_count=page_count)

    # PDF probablement scanne : texte natif vide.
    if not ocr_if_empty:
        return ExtractionResult(
            text="", extraction_method="pdf_text", extraction_quality="a_verifier", page_count=page_count,
            quality_flags=["pdf_sans_texte_natif"],
        )

    if not tesseract_available():
        return ExtractionResult(
            error="PDF scanne sans texte natif et Tesseract indisponible pour l'OCR",
            extraction_method="pdf_text",
            extraction_quality="failed",
            page_count=page_count,
            quality_flags=["pdf_sans_texte_natif", "ocr_indisponible"],
        )

    try:
        ocr_text = _ocr_pdf(path)
        if ocr_text.strip():
            return ExtractionResult(
                text=clean_text(ocr_text), extraction_method="pdf_ocr", extraction_quality="a_verifier",
                page_count=page_count, quality_flags=["texte_issu_ocr"],
            )
        return ExtractionResult(
            text="", extraction_method="pdf_ocr", extraction_quality="failed", page_count=page_count,
            quality_flags=["ocr_vide"],
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(
            error=f"Erreur OCR: {exc}", extraction_method="pdf_ocr", extraction_quality="failed", page_count=page_count,
        )


def _ocr_pdf(path: Path, lang: str = "fra+ara") -> str:
    """OCR local via Tesseract (francais + arabe si les paquets de langue sont installes)."""
    doc = fitz.open(str(path))
    texts = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=300)
            img_path = Path(tmp) / f"page_{i}.png"
            pix.save(str(img_path))
            proc = subprocess.run(
                ["tesseract", str(img_path), "stdout", "-l", lang],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                texts.append(proc.stdout)
    doc.close()
    return "\n".join(texts)


def extract_any(path: Path) -> ExtractionResult:
    """Point d'entree generique : choisit l'extracteur selon l'extension du fichier."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".doc":
        return extract_doc(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    return ExtractionResult(error=f"Extension non geree: {suffix}", extraction_method="unknown", extraction_quality="failed")
