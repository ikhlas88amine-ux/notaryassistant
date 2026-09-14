"""CLI de l'application RAG notariale locale."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.retrieval.qdrant_store import ALL_COLLECTIONS, get_qdrant_store
from app.services import audit_integrity, backup, watcher
from app.services.indexing_service import CORPORA, IndexingService
from app.validation.validator import validate_and_write


def cmd_index(args: argparse.Namespace) -> int:
    service = IndexingService(embed=not args.no_embed)
    if args.all:
        manifest = service.index_all()
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if not args.source:
        print("Erreur: precisez --source lois|modeles|dossiers, ou utilisez --all", file=sys.stderr)
        return 1
    result = service.index_corpus(args.source, resume=args.resume)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_validate_dossiers(args: argparse.Namespace) -> int:
    settings = get_settings()
    dossiers_dir = settings.dossiers_dir
    if args.dossier_id:
        path = dossiers_dir / args.dossier_id
        if not path.exists():
            print(f"Erreur: dossier introuvable: {args.dossier_id}", file=sys.stderr)
            return 1
        report = validate_and_write(path)
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
        return 0

    total = {"valid": 0, "warnings": 0, "invalid": 0}
    for path in sorted(dossiers_dir.iterdir()):
        if path.is_dir():
            report = validate_and_write(path)
            total[report.status] += 1
            print(f"{path.name:45s} | {report.status:10s} | {report.summary}")
    print(f"\nRecapitulatif: {total}")
    return 0


def cmd_run_tests(args: argparse.Namespace) -> int:
    settings = get_settings()
    dossiers_dir = settings.dossiers_dir
    from app.services.rag_service import RagService

    service = RagService()
    total_questions = 0
    total_passed = 0
    results = []

    targets = [dossiers_dir / args.dossier_id] if args.dossier_id else sorted(dossiers_dir.iterdir())
    for dossier_path in targets:
        if not dossier_path.is_dir():
            continue
        questions_path = dossier_path / "tests_questions.json"
        if not questions_path.exists():
            continue
        questions_doc = json.loads(questions_path.read_text(encoding="utf-8"))
        questions_list = questions_doc.get("tests", questions_doc.get("questions", []))
        for q in questions_list:
            total_questions += 1
            question_text = q.get("question") if isinstance(q, dict) else str(q)
            expected_source = q.get("expected_source_contains", "") if isinstance(q, dict) else ""
            expected_answer = q.get("expected_answer_contains", "") if isinstance(q, dict) else ""
            try:
                response = service.chat(question_text, scope="dossier", dossier_id=dossier_path.name, top_k=5)
                sources_ok = any(expected_source in (s.fichier or "") for s in response.sources) if expected_source else True
                dossier_isolated = all(s.dossier_id == dossier_path.name for s in response.sources if s.dossier_id)
                content_ok = any(expected_answer in ((s.text or s.excerpt) or "") for s in response.sources) if expected_answer else True
                passed = sources_ok and dossier_isolated and content_ok
            except Exception as exc:  # noqa: BLE001
                passed = False
                response = None
                sources_ok = False
                dossier_isolated = False
                content_ok = False
                print(f"  Erreur sur {dossier_path.name}: {exc}", file=sys.stderr)

            total_passed += int(passed)
            results.append({
                "dossier_id": dossier_path.name,
                "question": question_text,
                "expected_source_contains": expected_source,
                "expected_answer_contains": expected_answer,
                "passed": passed,
                "sources_ok": sources_ok,
                "dossier_isolated": dossier_isolated,
                "content_ok": content_ok,
                "generated_answer": response.answer if response else None,
            })

    print(json.dumps({"total_questions": total_questions, "total_passed": total_passed, "results": results}, ensure_ascii=False, indent=2))
    return 0 if total_passed == total_questions else 1


def cmd_audit_integrity(args: argparse.Namespace) -> int:
    sources = ("dossiers", "modeles", "lois") if not args.source else (args.source,)
    all_anomalies = []
    counts = {"blocking": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for source in sources:
        report = audit_integrity.run_audit(include_qdrant=not args.no_qdrant)
        anomalies = [a for a in report["anomalies"] if a["corpus"] == source]
        all_anomalies.extend(anomalies)
        for a in anomalies:
            counts[a.get("severity", "info")] = counts.get(a.get("severity", "info"), 0) + 1
        if not args.json:
            print(f"\n=== {source} : {len(anomalies)} anomalie(s) ===")
            for a in anomalies:
                print(f"  [{a.get('severity')}] {a.get('code')} : {a.get('message')}")
    if args.json:
        print(json.dumps({"anomalies": all_anomalies, "counts_by_severity": counts}, ensure_ascii=False, indent=2))
    else:
        print(f"\nRecapitulatif par gravite : {counts}")
    if args.fail_on_high and (counts.get("high", 0) > 0 or counts.get("blocking", 0) > 0):
        return 1
    return 0


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _ollama_diagnosis(settings) -> dict:
    result = {
        "base_url": settings.ollama_base_url,
        "available": False,
        "version": None,
        "models": [],
        "chat_model": settings.ollama_chat_model,
        "embed_model": settings.ollama_embed_model,
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            version = client.get(f"{settings.ollama_base_url}/api/version")
            result["available"] = version.status_code == 200
            if version.status_code == 200:
                result["version"] = version.json().get("version")
            tags = client.get(f"{settings.ollama_base_url}/api/tags")
            if tags.status_code == 200:
                result["models"] = [m.get("name") for m in tags.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


def _libreoffice_diagnosis() -> dict:
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    out = {"available": bool(binary), "binary": binary}
    if not binary:
        return out
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
        out["version"] = (proc.stdout or proc.stderr).strip() or None
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def cmd_diagnose(args: argparse.Namespace) -> int:
    """Diagnostic lecture seule : n'écrit rien, n'indexe rien, ne modifie aucune donnée."""
    settings = get_settings()
    usage = shutil.disk_usage(settings.output_path)
    qdrant = get_qdrant_store()
    collections = {}
    try:
        collections = qdrant.collection_sizes()
    except Exception as exc:  # noqa: BLE001
        collections = {name: None for name in ALL_COLLECTIONS}
        collections["error"] = str(exc)

    report = {
        "mode": "read_only_diagnose",
        "paths": {
            "data_dir": str(settings.data_path),
            "output_dir": str(settings.output_path),
            "qdrant_local_path": str(Path(settings.qdrant_local_path).resolve()),
        },
        "ollama": _ollama_diagnosis(settings),
        "embeddings": {
            "model": settings.ollama_embed_model,
            "batch_size": settings.ollama_embed_batch_size,
            "keep_alive": settings.ollama_keep_alive,
            "timeout_seconds": settings.ollama_request_timeout,
        },
        "qdrant": {
            "mode": settings.qdrant_mode,
            "url": settings.qdrant_url,
            "collections": collections,
        },
        "chunks": {
            "dossiers": _count_jsonl_lines(settings.output_path / "chunks_dossiers.jsonl"),
            "modeles": _count_jsonl_lines(settings.output_path / "chunks_modeles.jsonl"),
            "lois": _count_jsonl_lines(settings.output_path / "chunks_lois.jsonl"),
        },
        "disk": {
            "output_total_bytes": usage.total,
            "output_used_bytes": usage.used,
            "output_free_bytes": usage.free,
        },
        "libreoffice": _libreoffice_diagnosis(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_watcher(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.once:
        results = watcher.process_inbox_once(settings)
        print(json.dumps({"mode": "once", "results": results}, ensure_ascii=False, indent=2))
        return 0
    print("Watcher en boucle non demande : utilisez --once (Qdrant embedded = un seul process a la fois).", file=sys.stderr)
    return 1


def cmd_backup(args: argparse.Namespace) -> int:
    settings = get_settings()
    result = backup.create_backup(settings, include_qdrant=not args.no_qdrant)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Indexer un ou tous les corpus")
    p_index.add_argument("--source", choices=CORPORA, help="Corpus a indexer")
    p_index.add_argument("--all", action="store_true", help="Indexer les 3 corpus")
    p_index.add_argument("--no-embed", action="store_true", help="Ne pas appeler Ollama / Qdrant (chunking seul)")
    p_index.add_argument("--resume", action="store_true", help="Conserver les chunks existants dont le fichier source n'a pas change")
    p_index.set_defaults(func=cmd_index)

    p_validate = sub.add_parser("validate-dossiers", help="Valider la coherence des dossiers")
    p_validate.add_argument("--dossier-id", help="Valider un seul dossier (sinon: tous)")
    p_validate.set_defaults(func=cmd_validate_dossiers)

    p_tests = sub.add_parser("run-tests", help="Executer les tests_questions.json de chaque dossier")
    p_tests.add_argument("--dossier-id", help="Executer les tests d'un seul dossier (sinon: tous)")
    p_tests.set_defaults(func=cmd_run_tests)

    p_audit = sub.add_parser("audit-integrity", help="Audit d'integrite RAG (lecture seule)")
    p_audit.add_argument("--source", choices=CORPORA, help="Corpus a auditer (sinon: les 3)")
    p_audit.add_argument("--json", action="store_true", help="Sortie JSON")
    p_audit.add_argument("--fail-on-high", action="store_true", help="Code retour 1 si une anomalie high/blocking est detectee")
    p_audit.add_argument("--no-qdrant", action="store_true", help="Ne pas lire Qdrant pendant l'audit")
    p_audit.set_defaults(func=cmd_audit_integrity)

    p_diag = sub.add_parser("diagnose", help="Diagnostic lecture seule de l'environnement local")
    p_diag.set_defaults(func=cmd_diagnose)

    p_watcher = sub.add_parser("watcher", help="Watcher d'import de dossiers")
    p_watcher.add_argument("--once", action="store_true", help="Traiter une seule fois le contenu de data/inbox_dossiers")
    p_watcher.set_defaults(func=cmd_watcher)

    p_backup = sub.add_parser("backup", help="Sauvegarde locale (zip de data/, qdrant_local/, audit/, imports/, journal, config)")
    p_backup.add_argument("--no-qdrant", action="store_true", help="Exclure l'index vectoriel de la sauvegarde")
    p_backup.set_defaults(func=cmd_backup)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
