"""Audit qualité des chunks produits (Correctif 10).

Génère un rapport JSON mesurable sur un fichier chunks_*.jsonl :
total / indexables / exclus / notices techniques / fragments trop courts / artefacts de
tableaux / faible confiance / sections inférées / répartition par rôle / CIN extraites et
rejetées / faux positifs / montants / personnes / banques / TF / dates / rangs hypothécaires
/ exemples d'anomalies.

L'audit ré-applique les règles de validation locales sur le texte ET sur les entités déjà
stockées : les « faux positifs » sont donc détectés même sur des chunks générés avant les
correctifs (c'est le but de l'audit avant/après).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from app.chunking.quality import (
    CIN_STOPWORDS,
    _extract_mortgage_ranks,
    _valid_cin,
    extract_banks,
    extract_dates,
    is_degenerate_chunk,
)
from app.core.schemas import Chunk

# Pattern CIN « lâche » historique : c'est lui qui produisait les faux positifs ("le 2024").
LOOSE_CIN_RE = re.compile(r"\b[A-Za-z]{1,3}\s*[0-9]{4,10}\b")
_LOAN_FALSE_POSITIVES = {"est", "consenti", "accordé", "accordee", "de", "du", "le", "la", "sur"}


def _load_chunks(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not path.exists():
        return chunks
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            chunks.append(Chunk.model_validate(json.loads(line)))
        except Exception:  # noqa: BLE001 — un chunk illisible compte comme anomalie, pas un crash
            chunks.append(None)  # type: ignore[arg-type]
    return [c for c in chunks if c is not None]


def _examples(items: list[tuple[str, str]], limit: int = 8) -> list[dict]:
    return [{"chunk_id": cid, "value": val} for cid, val in items[:limit]]


def audit_chunks_file(path: Path) -> dict:
    chunks = _load_chunks(path)
    report: dict = {
        "source_file": str(path),
        "total_chunks": len(chunks),
        "indexable": 0,
        "excluded": 0,
        "technical_notices": 0,
        "fragments_too_short": 0,
        "table_artifacts": 0,
        "low_confidence_chunks": 0,
        "sections_inferred": 0,
        "chunks_by_role": {},
        "sections_by_name": {},
        "cin_extracted": 0,
        "cin_rejected": 0,
        "cin_false_positives_in_entities": 0,
        "loan_numbers_in_entities": 0,
        "loan_false_positives": 0,
        "mortgage_ranks_in_entities": 0,
        "empty_mortgage_rank_values": 0,
        "amounts_extracted": 0,
        "amount_format_nonstandard_count": 0,
        "amount_words_digits_mismatch_count": 0,
        "persons_structured": 0,
        "banks_extracted": 0,
        "land_titles_extracted": 0,
        "dates_extracted": 0,
        "anomaly_examples": [],
        "quality_flag_counts": {},
    }

    roles: Counter = Counter()
    sections: Counter = Counter()
    flag_counts: Counter = Counter()
    anomalies: list[tuple[str, str]] = []

    for chunk in chunks:
        roles[chunk.chunk_role] += 1
        sections[chunk.section or ""] += 1
        for flag in chunk.quality_flags:
            flag_counts[flag] += 1

        if chunk.indexable:
            report["indexable"] += 1
        if chunk.retrieval_excluded:
            report["excluded"] += 1

        text = chunk.text or ""
        if chunk.chunk_role == "technical_notice":
            report["technical_notices"] += 1

        degenerate, flag = is_degenerate_chunk(text)
        if degenerate:
            report["fragments_too_short"] += 1
            if "|" in text:
                report["table_artifacts"] += 1
            if len(anomalies) < 40:
                anomalies.append((chunk.chunk_id, text[:80]))

        if "table_artifact_or_fragment" in chunk.quality_flags:
            report["table_artifacts"] += 1

        if chunk.section_source == "inferred":
            report["sections_inferred"] += 1

        has_entities = bool(
            chunk.entities.cin or chunk.entities.land_titles or chunk.entities.amounts_dhs
            or chunk.entities.dates or chunk.entities.banks or chunk.entities.persons
        )
        if chunk.section_confidence < 0.5 and not has_entities:
            report["low_confidence_chunks"] += 1

        # --- CIN : ré-application des règles sur le texte ---
        for m in LOOSE_CIN_RE.finditer(text):
            candidate = m.group(0)
            normalized = candidate.replace(" ", "").replace(".", "")
            if _valid_cin(normalized):
                report["cin_extracted"] += 1
            else:
                report["cin_rejected"] += 1
                if len(anomalies) < 40:
                    anomalies.append((chunk.chunk_id, f"CIN rejeté: {candidate}"))

        # --- Entités stockées : faux positifs historiques ---
        for val in chunk.entities.cin:
            if not _valid_cin(val.replace(" ", "")):
                report["cin_false_positives_in_entities"] += 1
                if len(anomalies) < 40:
                    anomalies.append((chunk.chunk_id, f"Faux CIN stocké: {val}"))
        report["cin_extracted"] += len([v for v in chunk.entities.cin if _valid_cin(v.replace(" ", ""))])

        # --- Prêts ---
        report["loan_numbers_in_entities"] += len(chunk.entities.loan_numbers)
        for val in chunk.entities.loan_numbers:
            if val.lower() in _LOAN_FALSE_POSITIVES:
                report["loan_false_positives"] += 1
                if len(anomalies) < 40:
                    anomalies.append((chunk.chunk_id, f"Faux n° de prêt: {val}"))

        # --- Rangs hypothécaires : jamais de valeur vide ---
        report["mortgage_ranks_in_entities"] += len(chunk.entities.mortgage_ranks)
        report["empty_mortgage_rank_values"] += sum(1 for v in chunk.entities.mortgage_ranks if not str(v).strip())
        for v in chunk.entities.mortgage_ranks:
            if not str(v).strip() and len(anomalies) < 40:
                anomalies.append((chunk.chunk_id, "Rang hypothécaire vide"))

        # --- Montants ---
        report["amounts_extracted"] += len(chunk.entities.amounts_dhs)
        if "amount_format_nonstandard" in chunk.quality_flags:
            report["amount_format_nonstandard_count"] += 1
        if "amount_words_digits_mismatch" in chunk.quality_flags:
            report["amount_words_digits_mismatch_count"] += 1

        report["persons_structured"] += len(chunk.entities.persons)
        report["banks_extracted"] += len(chunk.entities.banks)
        report["land_titles_extracted"] += len(chunk.entities.land_titles)
        report["dates_extracted"] += len(chunk.entities.dates)

    report["chunks_by_role"] = dict(roles)
    report["sections_by_name"] = dict(sections)
    report["quality_flag_counts"] = dict(flag_counts)
    report["anomaly_examples"] = _examples(anomalies)
    return report


def audit_all(output_dir: Path) -> dict:
    """Audit agrégé des 3 corpus + détails par corpus."""
    corpora = {"dossiers": "chunks_dossiers.jsonl", "modeles": "chunks_modeles.jsonl", "lois": "chunks_lois.jsonl"}
    per: dict[str, dict] = {}
    totals = {
        "total_chunks": 0, "indexable": 0, "excluded": 0, "technical_notices": 0,
        "fragments_too_short": 0, "table_artifacts": 0, "cin_false_positives_in_entities": 0,
        "loan_false_positives": 0, "empty_mortgage_rank_values": 0,
        "persons_structured": 0, "banks_extracted": 0,
    }
    for corpus, fname in corpora.items():
        r = audit_chunks_file(output_dir / fname)
        per[corpus] = r
        for key in totals:
            totals[key] += r.get(key, 0)
    return {"corpora": per, "totals": totals}
