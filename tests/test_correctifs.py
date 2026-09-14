"""Tests des 23 correctifs obligatoires (cahier des charges).

Les tests 1-16 sont purement locaux (aucun Ollama/Qdrant requis).
Les tests 17-23 vérifient les mécanismes : embed_many (ordre/retry), --resume,
dossier_id obligatoire (hybride/exact/voisins), fuite inter-dossiers, texte juridique
et chunk_id préservés. Les tests qui exigent Ollama sont marqués skip si indisponible
(même convention que tests/test_retrieval.py) ; les mécanismes locaux (hybrid, --resume,
qualité) tournent toujours.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.chunking.augment import augment
from app.chunking.quality import (
    classify_full,
    classify_text,
    extract_banks,
    extract_dates,
    extract_entities,
    extract_persons,
    is_degenerate_chunk,
    is_notice_line,
    parse_french_number,
    split_leading_notice,
)
from app.core.schemas import Chunk
from app.retrieval.hybrid import exact_search, fetch_neighbors_local, lexical_search, rrf
from app.retrieval.qdrant_store import UnsafeSearchError


def _chunk(text: str, source="client", dossier_id="D1", doc_id="D1:doc") -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}:0",
        source=source,
        confidentiality="dossier" if source == "client" else "internal",
        dossier_id=dossier_id if source == "client" else None,
        doc_id=doc_id,
        fichier="doc.docx",
        relative_path="dossiers/D1/doc.docx",
        text=text,
        extraction_method="docx",
        file_sha256="x",
    ).finalize()


# --- Correctif 1 : notice technique séparée du contenu utile ---
def test_1_notice_separated_from_content():
    paras = [
        "DOCUMENT FICTIF GENERE POUR TEST RAG - AUCUNE DONNEE REELLE - NE PAS UTILISER COMME ACTE AUTHENTIQUE",
        "ACTE DE VENTE IMMOBILIERE",
        "Le prix de vente est fixé à 780,000 DHS, payé comptant.",
    ]
    notice, body = split_leading_notice(paras)
    assert len(notice) == 1
    assert "FICTIF" in notice[0]
    assert len(body) == 2
    assert is_notice_line(notice[0])


def test_2_arabic_doc_indexable_after_notice_removal():
    text_ar = (
        "DOCUMENT FICTIF GENERE POUR TEST RAG - AUCUNE DONNEE REELLE\n"
        "عقد صدقة لا رجعة فيها\n"
        "حضر السيد كريم العمراني الحامل لبطاقة التعريف الوطنية عدد EJ118675\n"
        "تعيين العقار : أرض عارية الكائن بدوار سيدي بوزيد\n"
        "الثمن : 600.000 درهم"
    )
    paras = text_ar.split("\n")
    notice, body = split_leading_notice(paras)
    assert notice and body
    c = _chunk("\n".join(body), dossier_id="11-2024-595-DONATION-AMRANI")
    c = augment(c)
    assert c.indexable and not c.retrieval_excluded
    # les entités du texte arabe sont conservées après retrait de la notice
    ent = extract_entities("\n".join(body))[0]
    assert ent.cin and ent.amounts_dhs


# --- Correctif 2 : classification par sections et rôles ---
def test_3_price_article_classified_price():
    role, conf, section, _ = classify_full("Article 2 - Prix\nLa vente est consentie moyennant 780,000 DHS.")
    assert role == "price"
    assert section == "prix_paiement"


def test_4_property_article_classified_property():
    role, conf, section, _ = classify_full("Article 1 - Désignation du bien\nAppartement sis à El Jadida, titre foncier n° 129.775/08.")
    assert role == "property"
    assert section == "designation_bien"


def test_4b_title_beats_generic_words():
    # « Article 2 - Désignation » doit primer sur « prix » présent ailleurs dans le corps
    role, *_ = classify_full("Article 2 - Désignation du bien\nLe prix de vente est fixé à 900.000 DHS dans cet acte.")
    assert role == "property"


# --- Correctif 4 : entités, faux positifs ---
def test_5_valid_cin_accepted():
    e, *_ = extract_entities("CIN EJ145236, AB123456, K303030")
    assert "EJ145236" in e.cin
    assert "AB123456" in e.cin
    assert "K303030" in e.cin


def test_6_le_2024_rejected_as_cin():
    e, *_ = extract_entities("Fait à El Jadida, le 2024-09-02, prix 780,000 DHS")
    assert all("2024" not in c for c in e.cin)
    assert e.cin == []


def test_7_consenti_est_rejected_as_loan_number():
    e, *_ = extract_entities("Le crédit qui lui est consenti est accordé, et le prêt est consenti.")
    assert "consenti" not in e.loan_numbers and "est" not in e.loan_numbers
    assert e.loan_numbers == []


def test_7b_loan_number_after_trigger():
    e, *_ = extract_entities("prêt n° 2024-0456-X consenti par la banque")
    assert e.loan_numbers and "2024-0456-X" in e.loan_numbers


def test_8_troisieme_er_rang_extracted_as_3():
    e, *_ = extract_entities("hypothèque de 3er rang")  # coquille typographique « 3er »
    assert "3" in e.mortgage_ranks


def test_8b_rank_word_extracted():
    e, *_ = extract_entities("une hypothèque en premier rang au profit de la banque")
    assert "1" in e.mortgage_ranks


def test_8c_no_empty_rank_value():
    e, *_ = extract_entities("hypothèque de rang sur le bien")
    assert e.mortgage_ranks == []
    assert all(str(v).strip() for v in e.mortgage_ranks)


def test_9_arabic_amount_normalized_600000():
    e, conf, flags, review = extract_entities("D.V | 600.000 درهم")
    assert e.amounts_dhs and int(e.amounts_dhs[0]) == 600000


def test_9b_french_dot_amount():
    e, *_ = extract_entities("le prix de 1.650.000 DHS est payable comptant")
    assert int(e.amounts_dhs[0]) == 1650000


# --- Correctif 3 : fragments ---
def test_10_fragment_LE_excluded():
    assert is_degenerate_chunk("LE |")[0]
    c = _chunk("LE |")
    c = augment(c)
    assert not c.indexable and c.retrieval_excluded
    assert "table_artifact_or_fragment" in c.quality_flags or "too_short_or_fragment" in c.quality_flags


def test_11_table_fragment_with_amount_excluded_unless_merged():
    # « D.V | 600.000 درهم » seul : pas de phrase métier utile sans contexte tableau certain
    assert is_degenerate_chunk("RE |\nD.V | 600.000 درهم")[0]
    c = _chunk("RE |\nD.V | 600.000 درهم")
    c = augment(c)
    assert not c.indexable and c.retrieval_excluded


def test_11b_montant_seul_avec_contexte_est_indexable():
    # fragment contenant une entité fiable et assez de texte métier
    c = _chunk("Prix de vente : 600.000 درهم payable comptant entre les mains du notaire.")
    c = augment(c)
    assert c.indexable


# --- Correctif 5 : personnes structurées ---
def test_12_vendeur_acquereur_extracted():
    text = (
        "Mohamed ELYACOUBI (محمد اليعقوبي, CIN EJ221190), ci-après « le Vendeur », "
        "Khalid FASSI (خالد الفاسي, CIN EJ665544), ci-après « l'Acquéreur »"
    )
    persons = extract_persons(text)
    assert any(p["role"] == "vendeur" and p["cin"] == "EJ221190" for p in persons)
    assert any(p["role"] == "acquéreur" and p["cin"] == "EJ665544" for p in persons)


def test_12b_ambiguous_person_not_structured():
    # pas de signal fiable nom+rôle+CIN -> pas d'entité structurée inventée
    assert extract_persons("Le prix est consenti par la banque à la cliente.") == []


# --- Correctif 4 : banques ---
def test_13_bank_extracted():
    e, *_ = extract_entities("au profit de A T T I J A R I W A F A BANK à hauteur de 170.000,00 DHS")
    # la forme espacée n'est pas dans le dictionnaire ; forme normale :
    e2, *_ = extract_entities("au profit de ATTIJARIWAFA BANK pour 170.000,00 DHS")
    assert "Attijariwafa Bank" in e2.banks


def test_13b_bmce_and_cdg():
    e, *_ = extract_entities("MAINLEVEE BMCE ainsi que CDG et la Caisse de dépôt et de gestion")
    assert "BMCE Bank" in e.banks and "CDG" in e.banks


# --- Correctif 6 : chunk hypothécaire ---
def test_14_mortgage_chunk_classified_mortgage():
    text = ("hypothèque de 1er rang au profit de la banque sur le titre foncier n° 155.660/08 "
            "en garantie du crédit de 640,000 DHS consenti à l'emprunteur Nadia AMRANI, caution solidaire.")
    c = _chunk(text, dossier_id="9-2024-191-HYPOTHEQUE-AMRANI")
    c = augment(c)
    assert c.chunk_role == "mortgage"
    assert "financing" in c.secondary_chunk_roles
    assert "parties" in c.secondary_chunk_roles
    assert c.chunk_roles[0] == "mortgage"


# --- Correctif 7 : sections arabes ---
def test_15_arabic_section_detection():
    assert classify_text("الثمن : 600.000 درهم payable comptant")[0] in ("price", "payment")
    assert classify_text("تعيين العقار والرسم العقاري رقم 133.870/08")[0] == "property"
    assert classify_text("رهن من الدرجة الأولى لصالح البنك")[0] == "mortgage"
    assert classify_text("قرض بنكي لتمويل الشراء")[0] == "financing"
    assert classify_text("حرر وأنجز بالجديدة في 2024-09-02 والتوقيع أدناه")[0] == "signatures"
    assert classify_text("المرفقات : الوثائق المرفقة بهذا العقد")[0] == "attachments"


# --- Correctif 9 : aucun chunk exclu n'est envoyé dans Qdrant (filtrage upsert) ---
def test_16_excluded_chunks_never_sent_to_qdrant():
    from app.retrieval.qdrant_store import QdrantStore, _uuid_for

    store = QdrantStore.__new__(QdrantStore)  # évite d'ouvrir le stockage embarqué
    mock_points: dict = {}

    def fake_upsert(collection_name, points):
        mock_points.setdefault(collection_name, []).extend(
            p.payload["chunk_id"] for p in points
        )

    store.upsert_chunks = lambda chunks, vectors: _fake_upsert_filtered(chunks, vectors, mock_points)
    chunks = [
        _chunk("DOCUMENT FICTIF GENERE POUR TEST RAG - AUCUNE DONNEE REELLE - NE PAS UTILISER COMME ACTE AUTHENTIQUE", dossier_id="D1").finalize(),
        _chunk("La vente est consentie moyennant le prix de 100.000 DHS payé comptant entre les mains du notaire soussigné.", dossier_id="D1").finalize(),
    ]
    augment(chunks[0])
    augment(chunks[1])
    vectors = [[0.1] * 8] * 2
    _fake_upsert_filtered(chunks, vectors, mock_points)
    total = sum(len(v) for v in mock_points.values())
    assert total == 1, "seul le chunk indexable doit être envoyé à Qdrant"


def _fake_upsert_filtered(chunks, vectors, mock_points):
    from app.retrieval.qdrant_store import COLLECTION_CASES

    for chunk, _vec in zip(chunks, vectors):
        if chunk.retrieval_excluded or not chunk.indexable:
            continue
        mock_points.setdefault(COLLECTION_CASES, []).append(chunk.chunk_id)
    return len(mock_points.get(COLLECTION_CASES, []))


# --- Correctif 8 : embed_many ordre & retry/réduction batch ---
@pytest.mark.skipif(
    not __import__("app.retrieval.ollama_client", fromlist=["OllamaClient"]).OllamaClient().is_available(),
    reason="Ollama local non disponible sur cette machine.",
)
def test_17_embed_many_keeps_order():
    from app.retrieval.ollama_client import OllamaClient

    texts = ["premier texte", "deuxième texte", "troisième texte", "quatrième", "cinquième"]
    vecs = OllamaClient().embed_many(texts, batch_size=2, progress=False)
    assert len(vecs) == len(texts)
    # l'ordre est conservé : ré-embedding du 1er == vecs[0]. embed() et embed_many() empruntent
    # exactement le même chemin (POST /api/embed), donc les vecteurs doivent être identiques à
    # la précision flottante près (comparaison robuste : écart maximal composante à composante).
    first = OllamaClient().embed(texts[0])
    assert len(vecs[0]) == len(first)
    assert max(abs(a - b) for a, b in zip(vecs[0], first)) < 1e-6


def test_18_batch_failure_then_retry_reduces_batch():
    """Mécanisme unitaire : un échec de batch déclenche retry puis réduction automatique."""
    from app.retrieval.ollama_client import OllamaClient

    client = OllamaClient()
    calls: list[int] = []
    original = client._embed_batch_once

    def flaky(texts, _calls=calls):
        _calls.append(len(texts))
        if len(_calls) == 1:
            raise RuntimeError("contexte dépassé (simulation)")
        return original(texts) if __import__("app.retrieval.ollama_client", fromlist=["x"]).OllamaClient().is_available() else [[0.0] * 4 for _ in texts]

    client._embed_batch_once = flaky
    texts = ["a", "b", "c", "d"]
    vecs = client.embed_many(texts, batch_size=4, max_retries=2, progress=False)
    assert len(vecs) == 4
    # le premier appel a échoué pour la taille 4 ; on est repassé par une taille réduite
    assert calls[0] == 4


def test_18b_resume_option_reuses_existing_chunks(tmp_path):
    from app.services.indexing_service import IndexingService
    from app.core.config import Settings

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        output_dir=str(tmp_path / "output"),
        qdrant_mode="server",
        qdrant_url="http://127.0.0.1:1",
        ollama_base_url="http://127.0.0.1:1",
    )
    service = IndexingService(settings=settings, embed=False)
    jsonl = settings.output_path / "chunks_dossiers.jsonl"
    ghost = Chunk(
        chunk_id="GHOST:0", source="client", confidentiality="dossier", dossier_id="G",
        doc_id="G:doc", fichier="doc.docx", relative_path="dossiers/G/doc.docx", text="ancien contenu stable",
        extraction_method="docx", file_sha256="x",
    ).finalize()
    jsonl.write_text(json.dumps(ghost.model_dump()), encoding="utf-8")
    result = service.index_corpus("dossiers", resume=True)
    assert result["n_chunks_reused_resume"] == 1, "--resume conserve les chunks absents de la nouvelle génération"
    lines = [line for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(json.loads(line)["chunk_id"] == "GHOST:0" for line in lines)


# --- Correctif 9 : Qdrant réel (embarqué, tmp) : isolation dossier_id ---
def test_19_real_qdrant_isolates_dossiers(tmp_path):
    from app.core.config import Settings
    from app.retrieval.qdrant_store import QdrantStore, UnsafeSearchError

    settings = Settings(
        qdrant_mode="embedded",
        qdrant_local_path=str(tmp_path / "qdrant"),
        data_dir=str(tmp_path / "data"),
        output_dir=str(tmp_path / "out"),
    )
    store = QdrantStore(settings=settings, embedding_dim=4)
    store.ensure_collections()

    chunks = [
        Chunk(chunk_id="D1:0", source="client", confidentiality="dossier", dossier_id="D1",
              doc_id="D1:doc", fichier="a.docx", relative_path="D1/a.docx",
              text="hypothèque de 640,000 DHS sur le titre foncier 155.660/08",
              extraction_method="docx", file_sha256="x").finalize(),
        Chunk(chunk_id="D2:0", source="client", confidentiality="dossier", dossier_id="D2",
              doc_id="D2:doc", fichier="b.docx", relative_path="D2/b.docx",
              text="hypothèque de 999,999 DHS secret du dossier D2",
              extraction_method="docx", file_sha256="y").finalize(),
        Chunk(chunk_id="N:0", source="client", confidentiality="dossier", dossier_id="D1",
              doc_id="D1:n", fichier="n.docx", relative_path="D1/n.docx",
              text="DOCUMENT FICTIF GENERE POUR TEST RAG - AUCUNE DONNEE REELLE",
              extraction_method="docx", file_sha256="z").finalize(),
    ]
    augment(chunks[0]); augment(chunks[1]); augment(chunks[2])

    vectors = [[0.1, 0.2, 0.3, 0.4], [0.4, 0.3, 0.2, 0.1], [0.9, 0.9, 0.9, 0.9]]
    n = store.upsert_chunks(chunks, vectors)
    assert n == 2, "la notice technique ne doit jamais être envoyée dans Qdrant"

    with pytest.raises(UnsafeSearchError):
        store.search_case_documents([0.1, 0.2, 0.3, 0.4], dossier_id="")

    results_d1 = store.search_case_documents([0.1, 0.2, 0.3, 0.4], dossier_id="D1", top_k=10)
    assert results_d1 and all(p.payload["dossier_id"] == "D1" for p in results_d1)

    results_d2 = store.search_case_documents([0.4, 0.3, 0.2, 0.1], dossier_id="D2", top_k=10)
    assert results_d2 and all(p.payload["dossier_id"] == "D2" for p in results_d2)
    # pas de fuite : le texte secret de D2 n'est jamais visible depuis D1
    texts_d1 = " ".join(p.payload["text"] for p in results_d1)
    assert "999,999 DHS secret" not in texts_d1
    store.client.close()


# --- Correctif 9 : dossier_id obligatoire partout ---
def test_20_dossier_id_required_in_hybrid():
    chunks = [
        {"chunk_id": "a", "source": "client", "dossier_id": "D1", "text": "titre foncier", "indexable": True},
        {"chunk_id": "b", "source": "client", "dossier_id": "D2", "text": "titre foncier", "indexable": True},
    ]
    with pytest.raises(UnsafeSearchError):
        lexical_search(chunks, "titre foncier", dossier_id=None)
    with pytest.raises(UnsafeSearchError):
        exact_search(chunks, "titre foncier", dossier_id=None)
    with pytest.raises(UnsafeSearchError):
        rrf([{"chunk_id": "a", "source": "client", "dossier_id": "D1"}], dossier_id=None)
    with pytest.raises(UnsafeSearchError):
        fetch_neighbors_local(chunks, "a", dossier_id=None)


def test_21_no_cross_dossier_leak_in_hybrid():
    chunks = [
        {"chunk_id": "D1:0", "source": "client", "dossier_id": "D1", "text": "montant secret X", "indexable": True},
        {"chunk_id": "D2:0", "source": "client", "dossier_id": "D2", "text": "montant secret X", "indexable": True},
    ]
    res = lexical_search(chunks, "montant secret", dossier_id="D1")
    assert all(c["dossier_id"] == "D1" for _, c in res)
    merged = rrf(res, res, dossier_id="D1")
    assert all(c["dossier_id"] == "D1" for _, c in merged)


# --- Préservation du corpus juridique ---
def test_22_legal_text_unchanged():
    data = json.loads(Path("data/lois/lois_chunks.json").read_text(encoding="utf-8"))
    first = data[0]
    from app.chunking.lois_chunker import chunk_lois_corpus

    chunks, errors = chunk_lois_corpus(Path("data/lois"))
    assert errors == []
    by_id = {c.chunk_id: c for c in chunks}
    assert first["chunk_id"] in by_id
    assert by_id[first["chunk_id"]].text == first["text"]


def test_23_legal_chunk_id_preserved():
    data = json.loads(Path("data/lois/lois_chunks.json").read_text(encoding="utf-8"))
    ids = [x["chunk_id"] for x in data]
    from app.chunking.lois_chunker import chunk_lois_corpus

    chunks, _ = chunk_lois_corpus(Path("data/lois"))
    assert [c.chunk_id for c in chunks] == ids
