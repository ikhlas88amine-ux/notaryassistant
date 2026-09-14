"""Exécute réellement tests_questions.json sur un échantillon représentatif de dossiers.

Option --debug-retrieval : écrit, sous output/debug_retrieval/, un JSON par question contenant :
- chunks bruts récupérés ;
- chunks filtrés ;
- scores / motifs ;
- contexte envoyé à Ollama ;
- réponse ;
- citations ;
- raison d'échec éventuelle.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.services.rag_service import RagService

SAMPLE_DOSSIERS = [
    "9-2024-191-HYPOTHEQUE-AMRANI",
    "17-2025-967-VENTE-ALAOUI",
    "11-2024-595-DONATION-AMRANI",
    "7-2025-605-SUCCESSION-ELYACOUBI",
    "4-2025-539-PROCURATION-ALAOUI",
    "1-2024-843-AMBIGU",
]


def _slug(text: str) -> str:
    text = re.sub(r"[^\w\-]+", "_", text.strip().lower(), flags=re.UNICODE)
    return re.sub(r"_+", "_", text).strip("_")[:120] or "question"


def _serialise_citation(c) -> dict:
    return {
        "source": c.source,
        "dossier_id": c.dossier_id,
        "fichier": c.fichier,
        "section": c.section,
        "chunk_id": c.chunk_id,
        "score": c.score,
        "excerpt": c.excerpt,
        "text": c.text,
        "chunk_role": c.chunk_role,
        "secondary_chunk_roles": c.secondary_chunk_roles,
        "entities": c.entities,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug-retrieval", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    service = RagService()
    total_questions = 0
    total_passed = 0
    results = []
    debug_dir = settings.output_path / "debug_retrieval"
    if args.debug_retrieval:
        debug_dir.mkdir(parents=True, exist_ok=True)

    for dossier_id in SAMPLE_DOSSIERS:
        dossier_path = settings.dossiers_dir / dossier_id
        questions_path = dossier_path / "tests_questions.json"
        if not questions_path.exists():
            print(f"(pas de tests_questions.json pour {dossier_id}, ignoré)")
            continue
        questions_doc = json.loads(questions_path.read_text(encoding="utf-8"))
        questions_list = questions_doc.get("tests", questions_doc.get("questions", []))
        for idx, q in enumerate(questions_list, 1):
            total_questions += 1
            question_text = q.get("question")
            expected_source = q.get("expected_source_contains", "")
            expected_answer = q.get("expected_answer_contains", "")
            debug_payload = {
                "dossier_id": dossier_id,
                "question": question_text,
                "expected_source_contains": expected_source,
                "expected_answer_contains": expected_answer,
            }
            try:
                inspected = service.inspect_retrieval(question_text, scope="dossier", dossier_id=dossier_id, top_k=5)
                response = service.chat(question_text, scope="dossier", dossier_id=dossier_id, top_k=5)
                sources_ok = any(expected_source in (s.fichier or "") for s in response.sources) if expected_source else True
                dossier_isolated = all(s.dossier_id == dossier_id for s in response.sources if s.dossier_id)
                content_ok = any(expected_answer in ((s.text or s.excerpt) or "") for s in response.sources) if expected_answer else True
                passed = sources_ok and dossier_isolated and content_ok
                failure_reason = None if passed else {
                    "sources_ok": sources_ok,
                    "dossier_isolated": dossier_isolated,
                    "content_ok": content_ok,
                }
                debug_payload.update({
                    "intent": inspected["intent"],
                    "retrieval": inspected["retrieval"],
                    "raw_chunks": [_serialise_citation(c) for c in inspected["raw_citations"]],
                    "filtered_chunks": [_serialise_citation(c) for c in inspected["filtered_citations"]],
                    "context_chunks": [_serialise_citation(c) for c in inspected["context_citations"]],
                    "context_blocks": inspected["ctx_blocks"],
                    "response": {
                        "answer": response.answer,
                        "answer_type": response.answer_type,
                        "warnings": response.warnings,
                    },
                    "citations": [_serialise_citation(c) for c in response.sources],
                    "failure_reason": failure_reason,
                })
            except Exception as exc:  # noqa: BLE001
                passed = sources_ok = dossier_isolated = content_ok = False
                response = None
                failure_reason = str(exc)
                debug_payload.update({
                    "response": None,
                    "citations": [],
                    "failure_reason": str(exc),
                })
                print(f"  Erreur sur {dossier_id}: {exc}")

            total_passed += int(passed)
            print(f"[{dossier_id}] {'OK ' if passed else 'FAIL'} sources_ok={sources_ok} isole={dossier_isolated} contenu_ok={content_ok} :: {question_text}")
            results.append({
                "dossier_id": dossier_id,
                "question": question_text,
                "expected_source_contains": expected_source,
                "expected_answer_contains": expected_answer,
                "passed": passed,
                "sources_ok": sources_ok,
                "dossier_isolated": dossier_isolated,
                "content_ok": content_ok,
                "answer_type": response.answer_type if response else None,
                "generated_answer": response.answer if response else None,
                "failure_reason": failure_reason,
            })
            if args.debug_retrieval:
                out_name = f"{dossier_id}_{idx:02d}_{_slug(question_text)}.json"
                (debug_dir / out_name).write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    output = {
        "sample_dossiers": SAMPLE_DOSSIERS,
        "total_questions": total_questions,
        "total_passed": total_passed,
        "pass_rate": round(total_passed / total_questions, 3) if total_questions else 0,
        "results": results,
    }
    out_path = settings.output_path / "tests_run_results.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== {total_passed}/{total_questions} tests passes (critères : sources correctes + isolation dossier + extrait contient la valeur attendue) ===")
    print(f"Résultats sauvegardés dans {out_path}")
    if args.debug_retrieval:
        print(f"Debug retrieval sauvegardé dans {debug_dir}")


if __name__ == "__main__":
    main()
