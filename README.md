# Assistant documentaire notarial local (RAG)

Application 100% locale (aucune cle API cloud, jamais) pour une etude notariale
marocaine : ingestion et indexation de trois corpus (`data/lois`, `data/modeles`,
`data/dossiers`), recherche/generation augmentee par recuperation (RAG) avec
isolation stricte par dossier client, validation automatique des dossiers, backend
FastAPI + CLI, et interface Streamlit a 8 pages.

> Outil strictement documentaire. Aucune reponse generee ne constitue un acte
> authentique, une signature notariale ou un conseil juridique definitif — toute
> information doit etre verifiee par le notaire avant usage.

## Sommaire

- [Architecture](#architecture)
- [Prerequis](#prerequis)
- [Installation](#installation)
- [Lancement pas a pas](#lancement-pas-a-pas)
- [Indexation](#indexation)
- [Validation des dossiers](#validation-des-dossiers)
- [Checklists des pieces](#checklists-des-pieces-dossier)
- [Watcher d'import de dossiers](#watcher-dimport-de-dossiers)
- [Audit de securite et d'integrite RAG](#audit-de-securite-et-dintegrite-rag)
- [Consultation securisee des modeles internes](#consultation-securisee-des-modeles-internes)
- [Sauvegarde et restauration](#sauvegarde-et-restauration)
- [Commandes Windows (PowerShell)](#commandes-windows-powershell)
- [Tests](#tests)
- [Utilisation](#utilisation-cli-api-interface)
- [Resultats reels obtenus pendant le developpement](#resultats-reels-obtenus-pendant-le-developpement)
- [Limites fonctionnelles connues](#limites-fonctionnelles-connues)
- [Regles de confidentialite et de securite](#regles-de-confidentialite-et-de-securite)
- [Arborescence du projet](#arborescence-du-projet)

## Architecture

```
Documents (.docx/.doc/.pdf/.json)
        │  extraction (python-docx / PyMuPDF / LibreOffice / Tesseract)
        ▼
   Chunking (par corpus : lois / modeles / dossiers)
        │  embeddings (Ollama, nomic-embed-text, local)
        ▼
   Qdrant (mode "embedded" par defaut : simple fichier local, pas de serveur)
        │  recherche vectorielle filtree par collection + dossier_id
        ▼
   RagService  ──►  Ollama (qwen2.5:1.5b, generation contrainte par schema JSON)
        │
        ▼
   FastAPI (app/api/main.py)  ◄──  CLI (app/cli.py)
        │  HTTP (jamais d'acces direct a Qdrant depuis l'UI)
        ▼
   Streamlit (app/ui/, 8 pages)
```

Trois collections Qdrant, jamais melangees :

| Collection | Corpus source | Filtre obligatoire |
|---|---|---|
| `legal_public` | `data/lois` | aucun (public par nature) |
| `templates_internal` | `data/modeles` | aucun (interne a l'etude, pas de donnee client) |
| `case_documents` | `data/dossiers` | **`dossier_id` obligatoire** — toute recherche sans `dossier_id` sur cette collection leve une `UnsafeSearchError` (HTTP 400), au niveau du code, pas seulement du prompt |

## Prerequis

- Python 3.11+ (teste avec 3.14 dans l'environnement de developpement)
- [Ollama](https://ollama.com) installe localement (teste avec la version 0.32.15, CPU uniquement — aucun GPU requis mais les temps de reponse sont plus longs)
- LibreOffice (`soffice`) — necessaire pour extraire les anciens fichiers `.doc` (Word 97-2003)
- Tesseract OCR (`tesseract`, packs `fra` et `ara`) — necessaire uniquement pour les PDF scannes sans texte natif
- ~4 Go d'espace disque libre pour les modeles Ollama

Sur Debian/Ubuntu :

```bash
sudo apt-get install libreoffice tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara
```

## Installation

```bash
cd notary_rag_app
python3 -m venv .venv && source .venv/bin/activate   # optionnel mais recommande
pip install -r requirements.txt
cp .env.example .env   # ajuster si besoin (voir commentaires dans le fichier)
```

## Lancement pas a pas

### 1. Demarrer Ollama et telecharger les modeles

```bash
# Le contexte etendu (8192 tokens) beneficie au modele de chat pour des extraits longs ;
# le modele d'embedding nomic-embed-text reste plafonne a 2048 tokens quoi qu'il arrive
# (voir la section Limites plus bas).
OLLAMA_CONTEXT_LENGTH=8192 ollama serve &

ollama pull qwen2.5:1.5b        # modele de generation (~1 Go)
ollama pull nomic-embed-text    # modele d'embedding (~270 Mo)
```

Verifier que le serveur repond :

```bash
curl http://localhost:11434/api/tags
```

### 2. Qdrant

Rien a faire par defaut : `QDRANT_MODE=embedded` (dans `.env`) stocke l'index dans
`output/qdrant_local/`, sans serveur ni Docker. **Un seul process a la fois peut
ouvrir ce dossier** (limitation du mode embarque de Qdrant, voir
[Limites](#limites-fonctionnelles-connues)) : ne lancez pas simultanement la CLI et
l'API sur le meme `output/qdrant_local/`.

Pour un usage multi-process (API + CLI + plusieurs postes), passez en mode serveur :

```bash
docker compose up -d qdrant
# puis dans .env : QDRANT_MODE=server et QDRANT_URL=http://localhost:6333
```

### 3. Indexer les corpus

```bash
python -m app.cli index --all
```

### 4. Lancer le backend API

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

Verifier : `curl http://localhost:8000/health`

### 5. Lancer l'interface Streamlit

Dans un autre terminal (l'API doit rester active — l'interface ne parle jamais
directement a Qdrant, uniquement a l'API, voir [Limites](#limites-fonctionnelles-connues)) :

```bash
streamlit run app/ui/Accueil.py
```

Ouvrir [http://localhost:8501](http://localhost:8501).

## Indexation

```bash
python -m app.cli index --all                     # les 3 corpus
python -m app.cli index --source dossiers         # un seul corpus
python -m app.cli index --source dossiers --no-embed   # chunking seul, sans appeler Ollama (rapide, pour deboguer l'extraction)
```

Produit dans `output/` : `chunks_lois.jsonl`, `chunks_modeles.jsonl`,
`chunks_dossiers.jsonl`, `extraction_errors.jsonl`, `index_manifest.json`.

## Validation des dossiers

```bash
python -m app.cli validate-dossiers                                  # les 22 dossiers
python -m app.cli validate-dossiers --dossier-id 9-2024-191-HYPOTHEQUE-AMRANI  # un seul
```

Ecrit un `validation_report_generated.json` **a cote de chaque dossier**, jamais dans
le dossier lui-meme modifie autrement. 7 regles de coherence implementees dans
`app/validation/rules.py` : `cin_presence`, `name_presence`,
`date_format_invalid`, `expected_document_missing`, `price_multiple_declared`,
`tf_multiple_declared`, `tf_text_mismatch`, `radiation_without_mainlevee`,
`company_identified_by_cin`, `price_breakdown_mismatch`.

## Checklists des pieces (dossier)

Des checklists structurees par `type + variante` vivent dans `data/checklists/`
(ex. `vente_tripartite_bancaire.json`). Chaque item precise : `id`, `label`,
`required`, `severity`, types et mots-cles de fichiers acceptes, mots-cles de
preuve par **contenu extrait**, statut (`present_confirmed | present_to_verify |
missing | not_applicable | not_evaluable`) et action recommandee. La preuve d'une
piece combine nom de fichier + type + contenu extrait : jamais le seul nom de
fichier.

- Sans checklist applicable, aucune conclusion automatique :
  « Aucune checklist structuree des pieces requises n'est disponible ; les
  pieces manquantes ne peuvent pas etre determinees automatiquement. »
- Le RAG n'invente jamais une piece manquante ; seul cet evaluateur deterministe
  fournit un statut, distinct de la validation de coherence.
- Regenerer les checklists : `python scripts/create_checklists.py` (ecrit
  UNIQUEMENT sous `data/checklists/`, jamais dans les dossiers sources).

API : `GET /dossiers/{id}/checklist`. Page Streamlit : Detail dossier →
« 📎 Checklist des pieces ».

## Watcher d'import de dossiers

`data/inbox_dossiers/` recoit des dossiers complets (`dossier_master.json` +
documents + marqueur `.ready` cree EN DERNIER). Le watcher :

1. pose le verrou `.processing` ;
2. verifie la stabilite des fichiers (tailles constantes) ;
3. valide `dossier_master.json` (`dossier_id` coherent avec le nom du dossier) ;
4. verifie l'unicite du `dossier_id` dans `data/dossiers` ;
5. deplace le dossier techniquement valide vers `data/dossiers` ;
6. lance la validation deterministe de CE SEUL dossier (jamais Ollama) ;
7. indexe CE SEUL dossier dans `case_documents` ;
8. ecrit `output/imports/<dossier_id>.json` et journalise ;
9. n'indexe jamais les modeles ni les lois ;
10. ne reinitialise jamais la collection.

- Echec technique (JSON invalide, dossier duplique, copie instable) →
  deplacement vers `data/rejected_dossiers/` + marqueur `.failed` (rien n'est
  supprime).
- Les alertes metier (`warnings`/`invalid`) ne bloquent jamais l'import technique.
- Un seul processus a la fois (Qdrant embedded) : verrou via
  `app/services/locks.py` + marqueurs `.ready/.processing/.failed/.done`.
- CLI : `python -m app.cli watcher --once`. API : `POST /watcher/run-once`.
  Page Streamlit : Administration.

## Audit de securite et d'integrite RAG

```bash
python -m app.cli audit-integrity [--source dossiers|modeles|lois] [--json] [--fail-on-high] [--no-qdrant]
```

Compare fichiers sources, chunks JSONL, manifests d'integrite et (optionnellement)
compteurs Qdrant. Codes detectes : `SOURCE_ADDED`, `SOURCE_REMOVED`,
`SOURCE_MODIFIED`, `SOURCE_RENAMED_POSSIBLE`, `CHUNK_ADDED`, `CHUNK_REMOVED`,
`CHUNK_HASH_MISMATCH`, `CHUNK_ORPHANED`, `QDRANT_VECTOR_COUNT_MISMATCH`,
`QDRANT_UNKNOWN_POINT`, `QDRANT_MISSING_POINT`, `EMBEDDING_DIMENSION_MISMATCH`,
`MANIFEST_MISSING`.

- **Lecture seule** : l'audit ne corrige jamais rien ; il produit
  `output/audit/last_audit.json` et journalise (append-only).
- Les manifests sont ecrits en fin d'indexation dans
  `output/audit/manifests/` (`dossiers_latest.json`, `modeles_latest.json`,
  `lois_latest.json`, `history/`).
- Decisions de suivi (autorise / resolu / ignore avec justification) :
  `POST /audit/decisions` ; le constat original est conserve.
- Page Streamlit : « 🛡️ Audit securite RAG » (dernier audit, compteurs par
  gravite, filtres corpus/gravite/statut, tableau d'anomalies, ancien/nouveau
  hash, actions locales de suivi).

## Consultation securisee des modeles internes

L'endpoint `GET /modeles/open?relative_path=modeles/originaux/...` sert
UNIQUEMENT des fichiers sous `data/modeles`, en lecture seule :

- refuse `..`, les chemins absolus, les extensions hors `.doc/.docx/.pdf/.txt`,
  les fichiers absents et tout chemin hors de la racine `data/modeles` ;
- resout depuis le `relative_path` indexe (jamais un chemin genere par Ollama) ;
- repond avec `FileResponse` (modele jamais modifie) ;
- dans l'interface, un bouton « Ouvrir le modele original » par fichier UNIQUE
  (deduplique par fichier, pas par chunk).

## Sauvegarde et restauration

`python -m app.cli backup` (ou `POST /backup/create`) : archive zip locale de
`data/`, `output/qdrant_local/`, manifests d'audit, rapports de validation,
journaux et configuration `.env`. Indication de la derniere sauvegarde :
`GET /backup/last`. Restauration exclusivement depuis l'administration Streamlit,
avec confirmation explicite. Les modeles originaux ne sont jamais modifies par
une sauvegarde/restauration.

## Commandes Windows (PowerShell)

```powershell
$PY = "C:\Users\ikhla\anaconda3\envs\notary-rag\python.exe"

# 1. Indexer les trois corpus (Ollama requis pour les embeddings)
& $PY -m app.cli index --all

# 2. Backend API
uvicorn app.api.main:app --host 0.0.0.0 --port 8000

# 3. Interface Streamlit
streamlit run app/ui/Accueil.py

# 4. Watcher d'import (mode --once)
& $PY -m app.cli watcher --once

# 5. Audit d'integrite RAG
& $PY -m app.cli audit-integrity --source dossiers --json

# 6. Tests
& $PY -m pytest tests/ -q
```

## Tests

```bash
pytest tests/ -v
```

121 tests (ingestion, chunking, validation, schemas Pydantic, API FastAPI via
`TestClient`, retrieval Qdrant/Ollama, RAG deterministe, endpoint securise des
modeles, checklists, watcher, audit d'integrite). Les tests marques
`requires_ollama` sont ignores automatiquement si Ollama n'est pas joignable au
moment du run (7 skips dans l'environnement sandbox).

Pour rejouer un echantillon **reel** de questions-reponses RAG (pas seulement des
assertions unitaires) sur des dossiers varies :

```bash
python scripts/run_representative_tests.py
```

Ecrit `output/tests_run_results.json` avec le detail de chaque question, la reponse
generee et les criteres reussis/echoues (voir les vrais resultats obtenus ci-dessous).

## Utilisation (CLI, API, interface)

**CLI** : `python -m app.cli --help` pour la liste complete (`index`,
`validate-dossiers`, `run-tests`, `audit-integrity`, `watcher`, `backup`).

**API** (voir aussi `http://localhost:8000/docs` genere automatiquement par
FastAPI) : `GET /health`, `POST /index/all`, `POST /index/{source}`, `GET
/dossiers`, `GET /dossiers/{id}`, `GET /dossiers/{id}/documents`, `GET
/dossiers/{id}/validation`, `GET /dossiers/{id}/checklist`, `POST
/dossiers/{id}/validate`, `POST /dossiers/{id}/explain-alert`, `POST /search`,
`POST /chat`, `GET /models`, `GET /laws/search`, `GET /modeles/open`, `GET
/alerts`, `POST /alerts/review`, `GET /audit/last`, `POST /audit/run`, `POST
/audit/decisions`, `GET /journal`, `POST /watcher/run-once`, `GET /backup/last`,
`POST /backup/create`.

**Interface Streamlit**, 8 pages : Tableau de bord (`Accueil.py`), Dossiers, Detail
dossier, Assistant RAG, Recherche juridique, Modeles, Alertes, Administration,
Audit securite RAG (`8_Audit_RAG.py`). Chaque page appelle l'API en HTTP
(`app/ui/api_client.py`) — jamais Qdrant/Ollama directement.

## Resultats reels obtenus pendant le developpement

Ces chiffres proviennent d'executions reelles de la CLI sur ce depot, pas de valeurs
estimees ou inventees. Ils seront differents chez vous si vous ajoutez ou modifiez
des documents.

**Indexation** (`python -m app.cli index --all`) :

| Corpus | Documents | Chunks | Chunks indexes | Erreurs d'extraction |
|---|---|---|---|---|
| `lois` | 0 | 0 | 0 | 0 |
| `modeles` | 23 | 181 | 181 | 0 |
| `dossiers` | 27 (dans 22 dossiers) | 117 | 117 | 0 |

**Validation** (`python -m app.cli validate-dossiers`), 22 dossiers : **18 valides,
2 avertissements, 2 invalides**.

- `16-2023-882-VENTE-SQALLI`, `21-2026-549-VENTE-SMIRI` : avertissement (RC/ICE
  manquant pour une partie identifiee comme societe).
- `1-2024-843-AMBIGU` : invalide (1 anomalie bloquante — deux prix distincts
  declares dans le meme dossier).
- `15-2024-824-AMBIGU` : invalide (2 anomalies bloquantes + 1 haute — deux titres
  fonciers distincts declares, et une societe identifiee sans RC/ICE/CIN gerant).

Ces deux dossiers "AMBIGU" sont **intentionnellement** incoherents (donnees de test
pour la validation) — ce ne sont pas des bugs de l'application.

**Tests RAG reels** (`python scripts/run_representative_tests.py`, 6 dossiers de
types varies, 34 questions) : **22/34 reussies** selon trois criteres cumules —
bonnes sources citees, isolation stricte du dossier, et presence litterale de la
valeur attendue dans l'extrait cite. Les 34/34 questions ont retourne des sources
correctement isolees par dossier (aucune fuite inter-dossier observee). Les echecs
concernent uniquement le critere le plus strict (`content_ok`) : soit la valeur
attendue n'apparait pas dans les 280 premiers caracteres de l'extrait cite, soit le
petit modele de generation (1,5 milliard de parametres, CPU) repond de facon
imprecise ou dit "information insuffisante" malgre une source pertinente
recuperee. Voir [Limites](#limites-fonctionnelles-connues).

## Limites fonctionnelles connues

Ce projet est honnete sur ses limites plutot que de les masquer.

1. **`data/lois` est vide.** Aucun texte de loi marocain reel n'a ete fourni
   pendant le developpement, et **aucun contenu de remplacement n'a ete invente**
   pour ne jamais risquer de faire passer un texte fictif pour une reference
   legale reelle. Voir `data/lois/README.md` pour le format JSON attendu et
   deposer vos textes reels avant de reindexer.
2. **Un document de modele reference dans les dossiers est absent** :
   `Demande-d-attestation.docx` est cite par au moins un dossier mais n'a pas ete
   fourni parmi les modeles reels de l'etude ; le dossier concerne fonctionne
   normalement, ce document n'est simplement pas indexable.
3. **Qualite des reponses generees limitee par la petite taille du modele local.**
   `qwen2.5:1.5b` tourne sans GPU pour rester utilisable sur un poste notaire
   standard, mais c'est un modele de 1,5 milliard de parametres : il repond parfois
   de facon imprecise, incomplete, ou dit "information insuffisante" alors que le
   bon extrait a ete recupere (voir chiffres reels ci-dessus). Utiliser
   `qwen2.5:7b` ou un modele plus grand dans `.env` (`OLLAMA_CHAT_MODEL=...`)
   ameliore nettement la qualite si le materiel le permet, au prix d'un temps de
   reponse plus long.
4. **Limite architecturale reelle de `nomic-embed-text` a 2048 tokens.** Ce plafond
   ne peut pas etre releve via `options.num_ctx`/`num_batch` sur l'appel, ni via un
   `Modelfile` personnalise avec `PARAMETER num_ctx 8192`, ni via
   `OLLAMA_CONTEXT_LENGTH` au demarrage du serveur — le process `llama-server`
   sous-jacent reste lance avec `-c 2048` quoi qu'il arrive. L'estimation
   caracteres-par-token du chunker (4 car/token) sous-estime parfois la
   tokenisation reelle sur du texte juridique/numerique dense francais (observe :
   un chunk de 2792 caracteres produisant 2156 tokens reels, soit ~1,3
   car/token). `app/retrieval/ollama_client.py::embed()` intercepte cette erreur
   et retente jusqu'a 4 fois en tronquant le texte a 60% de sa longueur precedente
   — **seul le vecteur embedding peut representer une version tronquee dans ce cas
   rare** ; le texte integral stocke pour citation/generation n'est jamais modifie.
5. **Qdrant en mode "embedded" verrouille son dossier de stockage a un seul
   process a la fois.** Deux instances (par exemple la CLI et l'API lancees en
   meme temps sur le meme `output/qdrant_local/`) se bloquent mutuellement avec
   `RuntimeError: Storage folder ... already accessed`. Ce projet mitige le
   probleme a l'interieur d'un meme process via un singleton partage
   (`get_qdrant_store()` dans `app/retrieval/qdrant_store.py`, reutilise par
   `RagService` et `IndexingService`), et l'interface Streamlit ne touche jamais
   Qdrant directement — uniquement l'API HTTP. Mais entre deux process
   independants (CLI + API en parallele), la seule solution est le mode
   `QDRANT_MODE=server` via `docker compose up -d qdrant`.
6. **Extraction des `.doc` et OCR dependent de binaires systeme**, pas de paquets
   pip : LibreOffice (`soffice`) et Tesseract. Sans eux, ces cas particuliers
   degradent proprement (`extraction_quality="degraded"`, texte vide) plutot que
   de faire echouer toute l'indexation, mais le contenu concerne ne sera pas
   recherchable.
7. **Le critere `content_ok` des tests RAG est volontairement strict** (correspondance
   litterale dans les 280 premiers caracteres de l'extrait cite) : un echec sur ce
   critere ne signifie pas toujours une mauvaise recuperation, parfois seulement
   que la valeur exacte attendue se trouve plus loin dans le chunk cite.

## Regles de confidentialite et de securite

- Aucune cle API ni aucun appel reseau vers un service cloud, a aucun moment.
- La recherche/generation sur la collection `case_documents` (dossiers clients)
  **exige toujours un `dossier_id`** : c'est une regle de code
  (`UnsafeSearchError`), pas une simple instruction de prompt — impossible de
  contourner via l'API ou l'interface.
- Les fichiers originaux (`data/dossiers`, `data/modeles`) ne sont **jamais**
  modifies par l'application, uniquement lus pour extraction/indexation. Les
  rapports de validation et les index sont ecrits a cote (`output/`,
  `validation_report_generated.json`), jamais a la place des documents source.
- Aucun contenu juridique ou documentaire n'a ete fabrique pour combler des
  lacunes (`data/lois` vide, document de modele manquant) — ces limites sont
  documentees ci-dessus plutot que masquees par un contenu invente.

## Arborescence du projet

```
notary_rag_app/
├── app/
│   ├── api/main.py            # Backend FastAPI
│   ├── cli.py                 # CLI (index, validate-dossiers, run-tests)
│   ├── core/                  # Settings (pydantic-settings) + schemas Pydantic
│   ├── ingestion/              # Extraction (.docx/.doc/.pdf/.json), hash, langue
│   ├── chunking/               # Chunking par corpus (lois / modeles / dossiers)
│   ├── validation/             # Regles de coherence + rapport JSON
│   ├── retrieval/               # Client Ollama + store Qdrant (singleton partage) + relevance (filtre par intention)
│   ├── services/                # IndexingService, RagService, db (SQLite alertes), checklists,
│   │                            #   watcher, audit_integrity, manifests, backup, journal, locks, secure_files
│   └── ui/                      # Interface Streamlit (Accueil + 8 pages)
├── data/
│   ├── lois/                    # VIDE par design (voir Limites) + schema attendu
│   ├── modeles/                  # Modeles reels de l'etude (jamais modifies)
│   ├── dossiers/                 # 22 dossiers fictifs (jamais modifies)
│   ├── checklists/               # Checklists structurees des pieces par type + variante
│   ├── inbox_dossiers/           # Depot d'entree du watcher (dossier + .ready)
│   └── rejected_dossiers/        # Dossiers techniquement invalides (jamais supprimes)
├── tests/                        # 121 tests pytest
├── scripts/                      # consolidate_modeles.py, run_representative_tests.py
├── output/                       # Genere : index, rapports de validation, sqlite (ignore par git)
├── requirements.txt
├── Dockerfile / docker-compose.yml   # Optionnel — voir section Lancement
├── .env.example
└── README.md
```
