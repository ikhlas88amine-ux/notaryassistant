"""Tests de l'audit d'integrite RAG (cahier des charges §9) : tout est LECTURE SEULE.

Verifie les codes : SOURCE_ADDED / SOURCE_MODIFIED / SOURCE_REMOVED / MANIFEST_MISSING,
et qu'un audit ne corrige jamais un fichier source.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.config import Settings
from app.core.schemas import Chunk
from app.ingestion.hashing import file_sha256
from app.services import audit_integrity
from app.services.manifests import write_corpus_manifest


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path / "data"),
        output_dir=str(tmp_path / "output"),
        qdrant_mode="server",
        qdrant_url="http://127.0.0.1:1",
        ollama_base_url="http://127.0.0.1:1",
    )


def _setup_corpus(tmp_path: Path) -> Settings:
    st = _settings(tmp_path)
    dossier = st.dossiers_dir / "D1"
    dossier.mkdir(parents=True, exist_ok=True)
    src = Path("data/dossiers/19-2024-613-VENTE-ELFASSI/01_acte_de_vente.docx")
    shutil.copy2(str(src), str(dossier / "01_acte_de_vente.docx"))
    (dossier / "dossier_master.json").write_text(json.dumps({"dossier_id": "D1"}), encoding="utf-8")

    doc = dossier / "01_acte_de_vente.docx"
    chunk = Chunk(
        chunk_id="D1:01:0", source="client", confidentiality="dossier", dossier_id="D1",
        doc_id="D1:01", fichier="01_acte_de_vente.docx",
        relative_path="dossiers/D1/01_acte_de_vente.docx",
        text="Vente d'un bien immobilier.", extraction_method="docx",
        file_sha256=file_sha256(doc),
    ).finalize()
    jsonl = st.output_path / "chunks_dossiers.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n", encoding="utf-8")
    write_corpus_manifest("dossiers", jsonl, st)
    return st


def test_audit_manifeste_absent(tmp_path):
    st = _settings(tmp_path)
    report = audit_integrity.run_audit(st, include_qdrant=False)
    codes = {a["code"] for a in report["anomalies"]}
    assert "MANIFEST_MISSING" in codes


def test_audit_etat_normal(tmp_path):
    st = _setup_corpus(tmp_path)
    report = audit_integrity.run_audit(st, include_qdrant=False)
    codes = {a["code"] for a in report["anomalies"]}
    assert "SOURCE_MODIFIED" not in codes
    assert "SOURCE_REMOVED" not in codes


def test_audit_detecte_fichier_modifie(tmp_path):
    st = _setup_corpus(tmp_path)
    doc = st.dossiers_dir / "D1" / "01_acte_de_vente.docx"
    doc.write_bytes(doc.read_bytes() + b"MODIFIED")
    report = audit_integrity.run_audit(st, include_qdrant=False)
    codes = {a["code"] for a in report["anomalies"]}
    assert "SOURCE_MODIFIED" in codes
    # l'audit n'a rien corrige : le fichier est toujours modifie
    assert doc.read_bytes().endswith(b"MODIFIED")


def test_audit_detecte_fichier_supprime(tmp_path):
    st = _setup_corpus(tmp_path)
    (st.dossiers_dir / "D1" / "01_acte_de_vente.docx").unlink()
    report = audit_integrity.run_audit(st, include_qdrant=False)
    codes = {a["code"] for a in report["anomalies"]}
    assert "SOURCE_REMOVED" in codes or "CHUNK_ORPHANED" in codes


def test_audit_detecte_fichier_ajoute(tmp_path):
    st = _setup_corpus(tmp_path)
    (st.dossiers_dir / "D1" / "02_attestation_fiscale.docx").write_bytes(b"nouveau fichier")
    report = audit_integrity.run_audit(st, include_qdrant=False)
    codes = {a["code"] for a in report["anomalies"]}
    assert "SOURCE_ADDED" in codes


def test_audit_lecture_seule_conserve_le_constat(tmp_path):
    """Un audit ne modifie jamais les sources ni les chunks."""
    st = _setup_corpus(tmp_path)
    doc = st.dossiers_dir / "D1" / "01_acte_de_vente.docx"
    sha_before = file_sha256(doc)
    jsonl = st.output_path / "chunks_dossiers.jsonl"
    jsonl_before = jsonl.read_bytes()
    audit_integrity.run_audit(st, include_qdrant=False)
    assert file_sha256(doc) == sha_before
    assert jsonl.read_bytes() == jsonl_before
