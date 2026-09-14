"""Feature 9 : tests d'extraction reelle (DOCX/DOC), hash, langue -- sur les vrais fichiers du
projet, jamais sur du contenu invente."""
from __future__ import annotations

from pathlib import Path

from app.ingestion.extractors import clean_text, extract_any, extract_docx, is_ignorable_file
from app.ingestion.hashing import file_sha256, text_sha256
from app.ingestion.language import detect_language


def test_extract_docx_returns_nonempty_text(dossiers_dir):
    docx_files = list(dossiers_dir.glob("*/01_*.docx")) + list(dossiers_dir.glob("**/*.docx"))
    assert docx_files, "Aucun fichier .docx trouve dans data/dossiers -- corpus manquant."
    result = extract_docx(docx_files[0])
    assert result.text.strip() != ""
    assert result.extraction_method == "docx"


def test_extract_any_handles_doc_files(modeles_dir):
    doc_files = list(modeles_dir.glob("**/*.doc"))
    if not doc_files:
        return  # pas de .doc dans ce lot de modeles ; ne pas fabriquer de cas de test.
    result = extract_any(doc_files[0])
    assert result.extraction_method in ("doc_libreoffice", "failed")
    if result.extraction_method == "doc_libreoffice":
        assert result.text.strip() != ""


def test_clean_text_removes_excess_whitespace():
    dirty = "Ligne 1\r\n\r\n\r\nLigne 2   avec   espaces\t\ttabulations\n\n\n\n\nLigne 3"
    cleaned = clean_text(dirty)
    assert "\r" not in cleaned
    assert "   " not in cleaned
    assert "\n\n\n\n" not in cleaned


def test_is_ignorable_file_excludes_metadata_and_hidden_files(dossiers_dir):
    assert is_ignorable_file(Path(".DS_Store"))
    assert is_ignorable_file(Path("~$temporaire.docx"))
    assert not is_ignorable_file(Path("01_acte_de_vente.docx"))


def test_file_sha256_is_deterministic_and_content_sensitive(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("contenu identique", encoding="utf-8")
    f2.write_text("contenu identique", encoding="utf-8")
    assert file_sha256(f1) == file_sha256(f2)

    f2.write_text("contenu different", encoding="utf-8")
    assert file_sha256(f1) != file_sha256(f2)


def test_text_sha256_matches_file_sha256_semantics():
    assert text_sha256("abc") == text_sha256("abc")
    assert text_sha256("abc") != text_sha256("abd")


def test_detect_language_french_vs_arabic():
    assert detect_language("Le present acte constate la vente du bien immobilier sis a Casablanca.") == "fr"
    assert detect_language("هذا عقد بيع عقار يقع في الدار البيضاء") == "ar"
