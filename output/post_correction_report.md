# Rapport post-correction

## Fichiers modifiés/créés
- `data/lois/lois_chunks.json` : corpus fourni, copié sans modification depuis la pièce jointe; 4 408 chunks JSON validés.
- `app/core/schemas.py` : `LegalChunk`, `chunk_role`, `entities`, métadonnées d’embedding, citations et alertes enrichies.
- `app/chunking/lois_chunker.py` : liste JSON, objet `chunks` et JSONL; conservation des identifiants, hiérarchie, pages et texte.
- `app/chunking/quality.py`, `augment.py` : classification déterministe, notices exclues, extraction locale des entités/montants.
- `app/chunking/dossiers_chunker.py`, `modeles_chunker.py` : enrichissement rétrocompatible des chunks.
- `app/retrieval/hybrid.py` : recherche lexicale/exacte et fusion RRF locale avec filtre dossier.
- `app/retrieval/qdrant_store.py` : exclusion Qdrant des chunks `retrieval_excluded`.
- `app/services/db.py`, `.env.example`, `README.md` : revue SQLite et modes Qdrant documentés.
- `output/pre_correction_audit.md`, `rag_failure_analysis.json`, `rag_before_after_metrics.json`, `post_correction_report.md`.

## Vérifications réelles
- Tests finaux : **51 passés, 6 ignorés, 0 échec** (`pytest -q`).
- Réindexation sans embedding : lois **4 408 chunks**, modèles **181**, dossiers **117**, erreurs d’extraction **0**.
- Validations : **18 valid**, **2 warnings**, **2 invalid**; les deux dossiers ambigus restent des anomalies fictives intentionnelles.
- RAG avant/après : voir `output/rag_before_after_metrics.json`; les deux exécutions historiques ont été faites sans Ollama joignable, donc les 34 questions n’ont pas pu obtenir de réponse générée. Aucune amélioration RAG ne doit être prétendue sans exécution Ollama réelle.

## Sécurité
L’isolation `case_documents` par `dossier_id` reste obligatoire au niveau du store et est couverte par un test anti-fuite. Une recherche dossier sans identifiant doit échouer explicitement. Les notices techniques sont conservées dans les fichiers de sortie mais exclues de la récupération normale. Les sources originales et `dossier_master.json` n’ont pas été modifiés.

## Modèles absents
Aucun faux modèle n’a été créé. Un modèle source absent reste indisponible et non indexable; l’interface conserve le message `Fichier source introuvable : indexation impossible.`

## Limites restantes
- Ollama n’était pas joignable lors du run final; embeddings Qdrant et génération locale n’ont donc pas été mesurés.
- La comparaison chiffre/lettres dépend de la présence d’une forme française détectable; les cas ambigus restent à revue humaine.
- La recherche lexicale locale est disponible et filtrée, mais le jeu de questions historique doit être relancé avec Ollama pour une métrique avant/après complète.

## Lancement
```bash
cp .env.example .env
python -m app.cli index --all
python -m app.cli validate-dossiers
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
streamlit run app/ui/Accueil.py
```
Qdrant embedded : `QDRANT_MODE=embedded`, FastAPI seul. Multi-processus : `docker compose up -d qdrant`, puis `QDRANT_MODE=server` et `QDRANT_URL=http://localhost:6333`.
