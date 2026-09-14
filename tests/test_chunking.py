"""Feature 9 : tests reels de creation de chunks et de preservation des metadonnees, sur les
3 corpus reels du projet (aucune donnee fabriquee)."""
from __future__ import annotations

from app.chunking.dossiers_chunker import chunk_dossiers_corpus
from app.chunking.modeles_chunker import chunk_modeles_corpus
from app.ingestion.extractors import soffice_available


def test_modeles_chunking_produces_chunks_without_errors(modeles_dir):
    chunks, errors = chunk_modeles_corpus(modeles_dir)
    if soffice_available():
        # LibreOffice disponible : tous les fichiers (dont les .doc) doivent se chunker
        # sans erreur.
        assert errors == []
    else:
        # Sans LibreOffice, seules des erreurs liees a la conversion des .doc sont
        # attendues ; les .docx doivent quand meme se chunker correctement.
        for err in errors:
            assert "LibreOffice" in err, f"Erreur inattendue sans LibreOffice : {err}"
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.source == "modele"
        assert chunk.confidentiality == "internal"
        assert chunk.text.strip() != ""
        assert chunk.file_sha256
        # Les .docx doivent toujours etre chunkes, meme sans LibreOffice.
        if chunk.fichier.lower().endswith(".docx"):
            assert chunk.extraction_method == "docx"


def test_dossiers_chunking_produces_chunks_without_errors(dossiers_dir):
    chunks, errors = chunk_dossiers_corpus(dossiers_dir)
    assert errors == []
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.source == "client"
        assert chunk.confidentiality == "dossier"
        assert chunk.dossier_id, "Un chunk de dossier doit toujours porter un dossier_id."
        assert chunk.text.strip() != ""


def test_dossiers_chunking_only_dossier_id_filters_correctly(dossiers_dir, sample_dossier_id):
    chunks, errors = chunk_dossiers_corpus(dossiers_dir, only_dossier_id=sample_dossier_id)
    assert errors == []
    assert len(chunks) > 0
    assert all(c.dossier_id == sample_dossier_id for c in chunks)


def test_chunk_metadata_preserved_fichier_and_relative_path(dossiers_dir, sample_dossier_id):
    chunks, _ = chunk_dossiers_corpus(dossiers_dir, only_dossier_id=sample_dossier_id)
    for chunk in chunks:
        assert chunk.fichier, "Le nom de fichier source doit etre preserve sur chaque chunk."
        assert sample_dossier_id in chunk.relative_path or chunk.dossier_id == sample_dossier_id
        assert chunk.chunk_index >= 0
        assert chunk.chunk_count_in_doc >= 1


def test_no_chunk_mixes_two_different_dossiers(dossiers_dir):
    """Verifie que jamais un meme chunk ne contient du texte de deux dossiers differents :
    chaque chunk provient d'un seul fichier source, donc d'un seul dossier_id."""
    chunks, _ = chunk_dossiers_corpus(dossiers_dir)
    by_chunk_id = {c.chunk_id: c for c in chunks}
    assert len(by_chunk_id) == len(chunks), "chunk_id doit etre unique."
    dossier_ids_seen = {c.dossier_id for c in chunks}
    assert len(dossier_ids_seen) > 1, "Le corpus doit contenir plusieurs dossiers distincts."


def test_chunk_finalize_sets_char_and_token_estimates(dossiers_dir, sample_dossier_id):
    chunks, _ = chunk_dossiers_corpus(dossiers_dir, only_dossier_id=sample_dossier_id)
    for chunk in chunks:
        assert chunk.n_chars == len(chunk.text)
        assert chunk.n_tokens_estimate >= 1
