"""Service RAG : sélection exclusive du corpus, récupération élargie, reranking par intention,
prompt de sécurité documentaire et abstention déterministe.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from qdrant_client.http.models import ScoredPoint

from app.core.config import Settings, get_settings
from app.core.schemas import ChatResponse, SourceCitation
from app.retrieval.guardrails import dedupe_citations, target_context_size
from app.retrieval.hybrid import exact_search, fetch_neighbors_local, lexical_search, load_chunks
from app.retrieval.ollama_client import OllamaClient
from app.retrieval.qdrant_store import UnsafeSearchError, get_qdrant_store
from app.retrieval.relevance import (
    INTENT_ACCOUNTING,
    INTENT_AREA,
    INTENT_BORROWER,
    INTENT_DONATION,
    INTENT_FINANCING,
    INTENT_LEGAL,
    INTENT_LAND_TITLE,
    INTENT_MISSING_DOCUMENTS,
    INTENT_MODELS,
    INTENT_OTHER,
    INTENT_PARTIES,
    INTENT_PRICE,
    INTENT_PROCURATION,
    INTENT_RESUME,
    INTENT_RISKS,
    INTENT_SUCCESSION,
    detect_intent,
    filter_chunks,
    format_guidance,
)
from app.services import checklists
from app.services.fact_extraction import build_fact_response, detect_fact_intents
from app.services.response_fidelity import validate_answer_fidelity
from app.services.dossier_validation import get_validation_report_path

RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "answer_type": {
            "type": "string",
            "enum": ["documentary_answer", "legal_answer", "draft", "insufficient_context"],
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "answer_type"],
}

_SOURCES_ONLY_RE = re.compile(r"^sources?\s*:\s*$", re.IGNORECASE)
_FILES_ONLY_RE = re.compile(r"^-\s*[^\n]*\.(?:docx|doc|pdf|json|txt)\s*\.?\s*$", re.IGNORECASE)


def _guard_documentary_answer(answer: str) -> str:
    """Garde de non-régression : aucune réponse documentaire vide ni réduite à une liste de sources.

    Si la réponse ne contient aucune ligne « métier » (uniquement des lignes Sources / des noms de
    fichiers), on retombe sur l'abstention explicite au lieu de renvoyer une réponse vide.
    """
    if not (answer or "").strip():
        return "Cette information ne peut pas être déterminée à partir des sources disponibles."
    meaningful = [
        line for line in (answer or "").splitlines()
        if line.strip()
        and not _SOURCES_ONLY_RE.match(line.strip())
        and not _FILES_ONLY_RE.match(line.strip())
        and not line.strip().lower().startswith("source")
    ]
    if not meaningful:
        return "Cette information ne peut pas être déterminée à partir des sources disponibles."
    return answer


SCOPES = ("dossier", "template", "law")
_COLLECTION_FOR_SCOPE = {
    "dossier": "case_documents",
    "template": "templates_internal",
    "law": "legal_public",
}
_JSONL_FOR_SCOPE = {
    "dossier": "chunks_dossiers.jsonl",
    "template": "chunks_modeles.jsonl",
    "law": "chunks_lois.jsonl",
}

_LETTER_AMOUNT_RE = re.compile(
    r"(?i)\b(?:un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|"
    r"seize|vingt|trente|quarante|cinquante|soixante|cent|mille|million|millions)"
    r"[a-zà-ÿ\s\-]{0,60}\b(?:dirhams?|dhs|dh)\b"
)
_DOSSIER_ID_RE = re.compile(r"\b\d{1,2}-\d{4}-\d{3,4}-[A-ZÀ-ÿ_]+(?:-[A-ZÀ-ÿ_]+)*\b", re.IGNORECASE)


def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(n)


def _excerpt(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text[:limit]


def _payload_entities(payload: dict) -> dict:
    entities = payload.get("entities") or {}
    if hasattr(entities, "model_dump"):
        return entities.model_dump()
    return entities if isinstance(entities, dict) else {}


def _point_to_citation(point: ScoredPoint) -> SourceCitation:
    payload = point.payload or {}
    text = payload.get("text", "") or ""
    return SourceCitation(
        source=payload.get("source", "client"),
        dossier_id=payload.get("dossier_id"),
        fichier=payload.get("fichier", ""),
        section=payload.get("section"),
        chunk_id=payload.get("chunk_id", str(point.id)),
        article_num=payload.get("article_num"),
        page_start=payload.get("page_start"),
        score=float(point.score or 0.0),
        excerpt=_excerpt(text),
        relative_path=payload.get("relative_path"),
        doc_id=payload.get("doc_id"),
        file_sha256=payload.get("file_sha256"),
        chunk_role=payload.get("chunk_role"),
        text=text,
        secondary_chunk_roles=payload.get("secondary_chunk_roles") or [],
        entities=_payload_entities(payload),
        chunk_index=payload.get("chunk_index"),
        chunk_count_in_doc=payload.get("chunk_count_in_doc"),
    )


def _dict_to_citation(d: dict, score: float = 0.0) -> SourceCitation:
    text = d.get("text", "") or ""
    return SourceCitation(
        source=d.get("source", "client"),
        dossier_id=d.get("dossier_id"),
        fichier=d.get("fichier", ""),
        section=d.get("section"),
        chunk_id=d.get("chunk_id", ""),
        article_num=d.get("article_num"),
        page_start=d.get("page_start"),
        score=float(score or 0.0),
        excerpt=_excerpt(text),
        relative_path=d.get("relative_path"),
        doc_id=d.get("doc_id"),
        file_sha256=d.get("file_sha256"),
        chunk_role=d.get("chunk_role"),
        text=text,
        secondary_chunk_roles=d.get("secondary_chunk_roles") or [],
        entities=_payload_entities(d),
        chunk_index=d.get("chunk_index"),
        chunk_count_in_doc=d.get("chunk_count_in_doc"),
    )


@lru_cache(maxsize=8)
def _load_jsonl_cached(path_str: str) -> list[dict]:
    return load_chunks(Path(path_str))


class RagService:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.ollama = OllamaClient(self.settings)
        self.store = get_qdrant_store()

    def _corpus_jsonl(self, scope: str) -> Path:
        return self.settings.output_path / _JSONL_FOR_SCOPE[scope]

    def _load_scope_chunks(self, scope: str) -> list[dict]:
        return _load_jsonl_cached(str(self._corpus_jsonl(scope).resolve()))

    def _sanitize_query(self, query: str, dossier_id: Optional[str]) -> str:
        cleaned = query or ""
        if dossier_id:
            cleaned = cleaned.replace(dossier_id, " ")
        cleaned = _DOSSIER_ID_RE.sub(" ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or (query or "")

    def _merge_citations(self, citations: list[SourceCitation]) -> list[SourceCitation]:
        merged: dict[str, SourceCitation] = {}
        for citation in citations:
            key = citation.chunk_id or f"{citation.fichier}:{citation.section}:{citation.page_start}"
            if key not in merged or citation.score > merged[key].score:
                merged[key] = citation
        return sorted(merged.values(), key=lambda c: c.score, reverse=True)

    def _search_local_candidates(self, scope: str, dossier_id: Optional[str], query: str, search_k: int) -> list[SourceCitation]:
        rows = self._load_scope_chunks(scope)
        lexical_query = self._sanitize_query(query, dossier_id)
        candidates: list[SourceCitation] = []
        for score, row in lexical_search(rows, lexical_query, top_k=search_k, dossier_id=dossier_id if scope == "dossier" else None):
            candidates.append(_dict_to_citation(row, score=score + 0.20))
        for rank, row in enumerate(exact_search(rows, lexical_query, top_k=search_k, dossier_id=dossier_id if scope == "dossier" else None), 1):
            candidates.append(_dict_to_citation(row, score=2.0 - (rank * 0.01)))
        if scope == "dossier" and dossier_id:
            fallback_rows = [r for r in rows if r.get("source") == "client" and r.get("dossier_id") == dossier_id]
            for idx, row in enumerate(sorted(fallback_rows, key=lambda x: (x.get("fichier", ""), x.get("chunk_index", 0)))):
                candidates.append(_dict_to_citation(row, score=0.05 - (idx * 0.0001)))
        return self._merge_citations(candidates)

    def _search_vector_candidates(self, scope: str, dossier_id: Optional[str], query_vector: list[float], search_k: int) -> list[SourceCitation]:
        if scope == "law":
            points = self.store.search_legal(query_vector, top_k=search_k)
        elif scope == "template":
            points = self.store.search_templates(query_vector, top_k=search_k)
        else:
            points = self.store.search_case_documents(query_vector, dossier_id=dossier_id, top_k=search_k)
        return [_point_to_citation(p) for p in points]

    def _neighbor_citations(self, scope: str, dossier_id: Optional[str], citations: list[SourceCitation], window: int = 1) -> list[SourceCitation]:
        if scope != "dossier" or not dossier_id:
            return []
        rows = self._load_scope_chunks(scope)
        neighbors: list[SourceCitation] = []
        for citation in citations:
            for row in fetch_neighbors_local(rows, citation.chunk_id, dossier_id=dossier_id, window=window):
                neighbors.append(_dict_to_citation(row, score=max(citation.score - 0.001, 0.0)))
        return self._merge_citations(neighbors)

    def _context_label(self, citation: SourceCitation) -> str:
        return {
            "loi": f"[Référence juridique - {citation.fichier}, art. {citation.article_num}]",
            "modele": f"[Modèle interne - {citation.fichier}, section {citation.section}]",
            "client": f"[Dossier {citation.dossier_id} - {citation.fichier}, section {citation.section}]",
        }[citation.source]

    def _build_context_blocks(self, context_citations: list[SourceCitation]) -> list[str]:
        blocks = []
        for citation in context_citations:
            body = citation.text or citation.excerpt
            blocks.append(f"{self._context_label(citation)}\n{body}")
        return blocks

    # ------------------------------------------------------------------ recherche
    def search(self, query: str, scope: str, dossier_id: Optional[str], top_k: int = 5) -> dict[str, list[SourceCitation]]:
        """Sélection EXCLUSIVE du corpus. Jamais de mélange ni de fallback inter-corpus."""
        if scope not in SCOPES:
            raise UnsafeSearchError("Sélection invalide : choisissez UN SEUL corpus (dossier, template ou law).")
        if scope == "dossier" and not dossier_id:
            raise UnsafeSearchError("Le scope 'dossier' requiert un dossier_id explicite (isolation stricte).")

        search_k = max(top_k * 3, 12)
        candidates = self._search_local_candidates(scope, dossier_id, query, search_k)
        try:
            query_vector = self.ollama.embed(query)
            candidates = self._merge_citations(candidates + self._search_vector_candidates(scope, dossier_id, query_vector, search_k))
        except Exception:
            pass
        return {_COLLECTION_FOR_SCOPE[scope]: candidates[: max(search_k, 24)]}

    # -------------------------------------------------------------- contexte dossier
    def _load_master(self, dossier_id: str) -> Optional[dict]:
        path = self.settings.dossiers_dir / dossier_id / "dossier_master.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _master_context(self, dossier_id: str) -> Optional[str]:
        master = self._load_master(dossier_id)
        if not master:
            return None
        return json.dumps(master, ensure_ascii=False, indent=1)

    def _validation_context(self, dossier_id: str) -> Optional[str]:
        path = get_validation_report_path(dossier_id, settings=self.settings)
        if path.exists():
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                report = None
        else:
            report = None
        if report is None:
            from app.validation.validator import validate_dossier  # import local pour éviter une dépendance circulaire au chargement
            computed = validate_dossier(self.settings.dossiers_dir / dossier_id)
            report = computed.model_dump()
        lines = [f"Statut global : {report.get('status')}"]
        for issue in report.get("issues", []):
            lines.append(
                f"- [{issue.get('severity')}] {issue.get('title') or issue.get('rule_id')} : {issue.get('message')}"
                + (f" | Action recommandée : {issue.get('recommended_action')}" if issue.get("recommended_action") else "")
            )
        return "\n".join(lines)

    def _master_citation(self, dossier_id: str) -> Optional[SourceCitation]:
        master = self._load_master(dossier_id)
        if not master:
            return None
        blob = json.dumps(master, ensure_ascii=False)
        return SourceCitation(
            source="client",
            dossier_id=dossier_id,
            fichier="dossier_master.json",
            section="metadonnees_dossier",
            chunk_id=f"{dossier_id}:dossier_master",
            excerpt=_excerpt(blob),
            relative_path=f"dossiers/{dossier_id}/dossier_master.json",
            text=blob,
        )

    # ----------------------------------------------------- réponse déterministe (sans Ollama)
    def _deterministic_answer(self, intent: str, dossier_id: str, citations: list[SourceCitation]) -> str:
        master = self._load_master(dossier_id)
        donnees = (master or {}).get("donnees", {})
        if intent == INTENT_PARTIES:
            vendeur = donnees.get("vendeur", {})
            acquereurs = [v for k, v in donnees.items() if k.startswith("acquereur")]
            banque = donnees.get("banque")
            lines = ["Vendeur :"]
            lines.append(f"- {vendeur.get('nom_fr', 'Non indiqué dans les sources disponibles.')}" if isinstance(vendeur, dict) else "- Non indiqué dans les sources disponibles.")
            lines.append("Représentant du vendeur :")
            gerant = vendeur.get("gerant") if isinstance(vendeur, dict) else None
            lines.append(f"- {gerant}, gérant" if gerant else "- Non indiqué dans les sources disponibles.")
            lines.append("Acquéreur(s) :")
            if acquereurs:
                for a in acquereurs:
                    lines.append(f"- {a.get('nom_fr', '')}".rstrip())
            else:
                lines.append("- Non indiqué dans les sources disponibles.")
            lines.append("Représentant(s) des acquéreurs :")
            lines.append("- Non indiqué dans les sources disponibles.")
            lines.append("Banque / prêteur :")
            lines.append(f"- {banque}" if banque else "- Non indiqué dans les sources disponibles.")
            lines.append("Autres intervenants :")
            lines.append("- Notaire : " + str((master or {}).get("notaire", {}).get("nom", "Non indiqué.")))
            return "\n".join(lines)
        if intent == INTENT_PRICE:
            prix = donnees.get("prix_dhs")
            lines = ["Prix de vente :", f"- {_fmt(prix)} DHS" if prix is not None else "- Non indiqué dans les sources disponibles."]
            banque = donnees.get("banque")
            lines += ["Banque / prêteur :", f"- {banque}" if banque else "- Non indiqué dans les sources disponibles."]
            return "\n".join(lines)
        if intent in (INTENT_FINANCING, INTENT_BORROWER):
            banque = donnees.get("banque")
            credits = []
            total = 0
            for k, v in donnees.items():
                m = re.match(r"credit_(\d+)_dhs", k)
                if m and v is not None:
                    idx = m.group(1)
                    taux = donnees.get(f"credit_{idx}_taux")
                    acqu = donnees.get(f"acquereur_{idx}")
                    personne = donnees.get(f"credit_{idx}_personne")
                    if not personne and isinstance(acqu, dict):
                        personne = acqu.get("nom_fr")
                    credits.append((personne or f"Crédit {idx}", v, taux))
                    total += int(v)
            lines = ["Prix de vente :", f"- {_fmt(donnees.get('prix_dhs'))} DHS" if donnees.get("prix_dhs") is not None else "- Non indiqué."]
            lines += ["Banque / prêteur :", f"- {banque}" if banque else "- Non indiqué dans les sources disponibles."]
            lines.append("Crédits identifiés :")
            for personne, montant, taux in credits:
                taux_txt = f", taux {taux}" if taux else ""
                lines.append(f"- {personne} : {_fmt(montant)} DHS{taux_txt}.")
            if credits:
                lines.append("Total calculé à partir des crédits cités :")
                lines.append(f"- {_fmt(total)} DHS.")
            else:
                lines.append("- Aucun crédit explicitement cité dans les données du dossier.")
            mc = donnees.get("montant_credit_dhs")
            if mc is not None:
                lines.append("Crédit garanti :")
                lines.append(f"- {_fmt(mc)} DHS.")
            rang = donnees.get("rang_hypotheque")
            if rang is not None:
                lines.append("Rang de l'hypothèque :")
                lines.append(f"- {rang}e rang.")
            return "\n".join(lines)
        if intent == INTENT_RISKS:
            path = get_validation_report_path(dossier_id, settings=self.settings)
            if path.exists():
                report = json.loads(path.read_text(encoding="utf-8"))
            else:
                from app.validation.validator import validate_dossier  # import local pour éviter une dépendance circulaire au chargement
                report = validate_dossier(self.settings.dossiers_dir / dossier_id).model_dump()
            lines = ["Risques établis par les sources :"]
            for issue in report.get("issues", []):
                titre = issue.get('title') or issue.get('rule_id')
                lines.append(f"- [{issue.get('severity')}] {issue.get('rule_id')} — {titre} : {issue.get('message')}")
                evidence = issue.get("evidence") or {}
                fields = evidence.get("fields") if isinstance(evidence, dict) else None
                if fields:
                    lines.append(f"  Valeurs constatées : {json.dumps(fields, ensure_ascii=False)}")
                if issue.get("recommended_action"):
                    lines.append(f"  Action recommandée : {issue['recommended_action']}")
            lines.append("Points à vérifier :")
            lines.append("- Tout élément marqué 'à vérifier' doit être confirmé par le notaire.")
            lines.append("Aucune autre incohérence ne peut être établie à partir des sources disponibles.")
            return "\n".join(lines)
        if intent == INTENT_RESUME:
            lines = ["Parties"] + self._deterministic_answer(INTENT_PARTIES, dossier_id, citations).split("\n")
            lines += ["", "Montants"] + self._deterministic_answer(INTENT_PRICE, dossier_id, citations).split("\n")
            lines += ["", "Financement et garanties"] + self._deterministic_answer(INTENT_FINANCING, dossier_id, citations).split("\n")
            return "\n".join(lines)
        if intent == INTENT_MODELS:
            return "Aucun modèle correspondant n'a été identifié dans les sources internes disponibles. Une validation par le notaire est nécessaire."
        if intent == INTENT_LEGAL:
            return "Réponse fondée sur les extraits juridiques disponibles :\n" + "\n".join(f"- {c.excerpt}" for c in citations)
        lines = ["Réponse fondée uniquement sur les sources fournies :"]
        for c in citations[:8]:
            lines.append(f"- {c.fichier} : {(c.text or c.excerpt)[:240]}")
        return "\n".join(lines)

    def _letter_amount_warning(self, answer: str, citations: list[SourceCitation], dossier_id: str) -> Optional[str]:
        hay = " ".join([(c.text or c.excerpt or "") for c in citations])
        master = self._load_master(dossier_id)
        if master:
            hay += " " + json.dumps(master, ensure_ascii=False)
        for m in _LETTER_AMOUNT_RE.finditer(answer):
            phrase = m.group(0)
            if _LETTER_AMOUNT_RE.search(hay) or phrase.lower() not in hay.lower():
                return f"Un montant en lettres présent dans la réponse ('{phrase.strip()}') ne figure pas explicitement dans les sources : à vérifier."
        return None

    def inspect_retrieval(self, query: str, scope: str, dossier_id: Optional[str], top_k: int = 5) -> dict:
        intent = detect_intent(query, scope)
        grouped = self.search(query, scope, dossier_id, top_k=top_k)
        raw_citations = [c for group in grouped.values() for c in group]
        filtered = filter_chunks(raw_citations, intent, top_n=max(max(top_k * 3, 12), 12))
        neighbors = self._neighbor_citations(scope, dossier_id, filtered[:8], window=1)
        combined = dedupe_citations(filtered + neighbors)
        display_sources = dedupe_citations(filtered, max_items=3)
        context_citations = combined[:target_context_size(intent, len(combined))]
        retrieval = {
            "intent": intent,
            "scope": scope,
            "dossier_id": dossier_id,
            "collections": list(grouped.keys()),
            "search_k": max(top_k * 3, 12),
            "raw_count": len(raw_citations),
            "filtered_count": len(filtered),
            "neighbor_count": len(neighbors),
            "context_count": len(context_citations),
        }
        return {
            "intent": intent,
            "grouped": grouped,
            "raw_citations": raw_citations,
            "filtered_citations": filtered,
            "neighbor_citations": neighbors,
            "context_citations": context_citations,
            "display_sources": display_sources,
            "ctx_blocks": self._build_context_blocks(context_citations),
            "retrieval": retrieval,
        }

    def _finalize(self, response: ChatResponse) -> ChatResponse:
        """Applique la garde anti-réponse vide / réduite aux sources à toute réponse retournée."""
        guarded = _guard_documentary_answer(response.answer)
        if guarded != response.answer:
            response.answer = guarded
            response.answer_type = "insufficient_context"
        else:
            response.answer = guarded
        return response

    # ------------------------------------------------------------------ chat
    def chat(self, query: str, scope: str, dossier_id: Optional[str], top_k: int = 5) -> ChatResponse:
        prepared = self.inspect_retrieval(query, scope, dossier_id, top_k=top_k)
        intent = prepared["intent"]
        filtered = prepared["filtered_citations"]
        context_citations = prepared["context_citations"]
        display_sources = prepared["display_sources"]
        retrieval = prepared["retrieval"]
        warnings: list[str] = []

        if scope == "dossier" and dossier_id:
            fact_intents = detect_fact_intents(query)
            if fact_intents:
                fact_result = build_fact_response(query, dossier_id, prepared.get("raw_citations", []))
                if fact_result.handled:
                    ok, fidelity_warnings = validate_answer_fidelity(fact_result.answer, fact_result.sources, fact_result.answer_type)
                    return self._finalize(ChatResponse(
                        answer=fact_result.answer,
                        answer_type=fact_result.answer_type,
                        warnings=[] if ok else fidelity_warnings,
                        sources=fact_result.sources,
                        retrieval={**retrieval, "fact_intents": fact_intents},
                    ))

        if scope == "dossier" and intent == INTENT_MISSING_DOCUMENTS:
            result = checklists.evaluate_dossier(dossier_id, self.settings)
            if not result.get("evaluable"):
                return ChatResponse(
                    answer="Les documents manquants ne peuvent pas être déterminés à partir des sources disponibles.",
                    answer_type="insufficient_context",
                    warnings=[result.get("message", "Aucune checklist structurée des pièces requises n'est disponible.")],
                    sources=[],
                    retrieval=retrieval,
                )
            lines = ["Pièces requises (checklist structurée) :"]
            for item in result["items"]:
                picto = {"present_confirmed": "✅", "present_to_verify": "🔶", "missing": "❌", "not_applicable": "➖", "not_evaluable": "❔"}.get(item["statut"], "❔")
                lines.append(f"- {picto} [{item['statut']}] {item['label']} : {item['raison']}")
                if item.get("fichier_candidat"):
                    lines.append(f"  Fichier candidat : {item['fichier_candidat']}")
                if item.get("action_recommandee"):
                    lines.append(f"  Action : {item['action_recommandee']}")
            checklist_cit = SourceCitation(
                source="client", dossier_id=dossier_id, fichier=f"checklists/{result['checklist']}",
                section="checklist_des_pieces", chunk_id=f"{dossier_id}:checklist",
                excerpt="; ".join(f"{i['label']}={i['statut']}" for i in result["items"])[:280],
            )
            return ChatResponse(
                answer="\n".join(lines),
                answer_type="documentary_answer",
                warnings=[],
                sources=[checklist_cit] + display_sources[:2],
                retrieval=retrieval,
            )

        if intent == INTENT_MODELS:
            if scope == "template":
                modele_cits = [c for c in filtered if c.source == "modele"]
                if not modele_cits:
                    return ChatResponse(
                        answer="Aucun modèle correspondant n'a été identifié dans les sources internes disponibles. Une validation par le notaire est nécessaire.",
                        answer_type="insufficient_context",
                        warnings=["Aucun document de templates_internal ne prouve explicitement un modèle adapté à cette demande."],
                        sources=[],
                        retrieval=retrieval,
                    )
                filtered = modele_cits
            elif not filtered:
                return ChatResponse(
                    answer="L'information relative à un modèle de l'étude ne peut pas être déterminée à partir du dossier seul.",
                    answer_type="insufficient_context",
                    warnings=["Aucun fallback vers templates_internal n'est autorisé depuis un dossier client."],
                    sources=[],
                    retrieval=retrieval,
                )
            display_sources = dedupe_citations(filtered, max_items=3)

        if intent == INTENT_LEGAL:
            loi_cits = [c for c in filtered if c.source == "loi"]
            if not loi_cits:
                return ChatResponse(
                    answer="Cette information ne peut pas être déterminée à partir des sources juridiques disponibles.",
                    answer_type="insufficient_context",
                    warnings=["Aucun extrait pertinent trouvé dans legal_public."],
                    sources=[],
                    retrieval=retrieval,
                )
            filtered = loi_cits
            display_sources = dedupe_citations(filtered, max_items=3)

        if not filtered and intent == INTENT_RISKS:
            vctx = self._validation_context(dossier_id) if scope == "dossier" else None
            if vctx:
                return ChatResponse(
                    answer=self._deterministic_answer(INTENT_RISKS, dossier_id, []),
                    answer_type="documentary_answer",
                    warnings=["Réponse fondée sur le rapport de validation déterministe."],
                    sources=[self._master_citation(dossier_id)] if self._master_citation(dossier_id) else [],
                    retrieval=retrieval,
                )

        if not filtered:
            abstention = {
                INTENT_PARTIES: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_PRICE: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_FINANCING: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_BORROWER: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_LAND_TITLE: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_AREA: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_DONATION: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_SUCCESSION: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_PROCURATION: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_ACCOUNTING: "Cette information ne peut pas être déterminée à partir des sources disponibles.",
                INTENT_LEGAL: "Cette information ne peut pas être déterminée à partir des sources juridiques disponibles.",
                INTENT_MODELS: "Aucun modèle correspondant n'a été identifié dans les sources internes disponibles. Une validation par le notaire est nécessaire.",
            }.get(intent, "Cette information ne peut pas être déterminée à partir des sources disponibles.")
            return ChatResponse(
                answer=abstention,
                answer_type="insufficient_context",
                warnings=["Aucun extrait pertinent n'a été retenu après filtrage par intention."],
                sources=[],
                retrieval=retrieval,
            )

        ctx_blocks = prepared["ctx_blocks"]
        if scope == "dossier":
            mctx = self._master_context(dossier_id)
            if mctx:
                ctx_blocks.append("[Fiche du dossier - dossier_master.json]\n" + mctx)
            if intent == INTENT_RISKS:
                vctx = self._validation_context(dossier_id)
                if vctx:
                    ctx_blocks.append("[Rapport de validation déterministe]\n" + vctx)

        guidance = format_guidance(intent)

        if not self.ollama.is_available():
            answer = self._deterministic_answer(intent, dossier_id, context_citations or filtered)
            warnings.append("Ollama local non disponible : réponse déterministe construite à partir des données structurées et des chunks récupérés. À faire vérifier par le notaire.")
            return self._finalize(ChatResponse(
                answer=answer,
                answer_type="documentary_answer",
                warnings=warnings,
                sources=display_sources,
                retrieval=retrieval,
            ))

        raw = self.ollama.chat(f"{query}\n\n{guidance}", ctx_blocks, json_schema=RESPONSE_JSON_SCHEMA)
        try:
            parsed = json.loads(raw)
            answer = parsed.get("answer", raw)
            answer_type = parsed.get("answer_type", "documentary_answer")
            model_warnings = parsed.get("warnings", [])
        except (json.JSONDecodeError, AttributeError):
            answer = raw
            answer_type = "documentary_answer"
            model_warnings = []

        if scope == "dossier":
            lw = self._letter_amount_warning(answer, context_citations or filtered, dossier_id)
            if lw:
                warnings.append(lw)

        ok, fidelity_warnings = validate_answer_fidelity(answer, display_sources, answer_type)
        if not ok:
            fallback = self._deterministic_answer(intent, dossier_id, context_citations or filtered) if scope == "dossier" and dossier_id else answer
            return self._finalize(ChatResponse(
                answer=fallback,
                answer_type="documentary_answer" if fallback != answer else answer_type,
                warnings=warnings + fidelity_warnings,
                sources=display_sources,
                retrieval=retrieval,
            ))

        return self._finalize(ChatResponse(
            answer=answer,
            answer_type=answer_type,
            warnings=warnings + model_warnings,
            sources=display_sources,
            retrieval=retrieval,
        ))

    # --------------------------------------------------------------- explication d'alerte
    def explain_alert(self, dossier_id: str, rule_id: str, severity: str, message: str,
                      evidence: Optional[dict] = None, recommended_action: str = "") -> ChatResponse:
        evidence = evidence or {}
        ctx_blocks = []
        mctx = self._master_context(dossier_id)
        if mctx:
            ctx_blocks.append(f"[Contexte figé - dossier {dossier_id} - dossier_master.json]\n{mctx}")
        vctx = self._validation_context(dossier_id)
        if vctx:
            ctx_blocks.append(f"[Rapport de validation déterministe - dossier {dossier_id}]\n{vctx}")
        alerte = (
            f"Règle de validation : {rule_id} ({severity})\n"
            f"Message : {message}\n"
            f"Valeurs constatées : {json.dumps(evidence, ensure_ascii=False) if evidence else 'non renseignées'}\n"
            f"Action recommandée : {recommended_action or 'non renseignée'}"
        )
        ctx_blocks.append("[Alerte à expliquer]\n" + alerte)
        verdict = (
            "Le statut du dossier (valid/warnings/invalid) est calculé exclusivement par le "
            "validateur déterministe. Cette explication ne modifie, ne crée ni ne résout aucune alerte."
        )
        retrieval = {"scope": "dossier", "dossier_id": dossier_id, "objet": "expliquer_alerte"}

        if not self.ollama.is_available():
            answer = (
                f"Explication de l'alerte **{rule_id}** ({severity}) :\n\n"
                f"- Message : {message}\n"
                f"- Valeurs constatées : {json.dumps(evidence, ensure_ascii=False) if evidence else 'aucune valeur explicite'}\n"
                f"- Action recommandée : {recommended_action or 'aucune'}\n\n"
                f"{verdict}"
            )
            return ChatResponse(
                answer=answer,
                answer_type="documentary_answer",
                warnings=["Ollama local indisponible : explication déterministe basée sur le contexte figé."],
                sources=[self._master_citation(dossier_id)] if self._master_citation(dossier_id) else [],
                retrieval=retrieval,
            )

        raw = self.ollama.chat(
            f"Explique cette alerte de validation au notaire, en reprenant les valeurs constatées, "
            f"sans changer le verdict et sans ajouter de conseil juridique externe.\n\n{alerte}",
            ctx_blocks,
            json_schema=RESPONSE_JSON_SCHEMA,
        )
        warnings: list[str] = []
        try:
            parsed = json.loads(raw)
            answer = parsed.get("answer", raw)
            warnings = parsed.get("warnings", [])
        except (json.JSONDecodeError, AttributeError):
            answer = raw
        answer = answer + "\n\n" + verdict
        return ChatResponse(
            answer=answer,
            answer_type="documentary_answer",
            warnings=warnings,
            sources=[self._master_citation(dossier_id)] if self._master_citation(dossier_id) else [],
            retrieval=retrieval,
        )
