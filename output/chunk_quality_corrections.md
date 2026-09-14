# Rapport des correctifs — pipeline RAG notarial local (`notary_rag_app`)

Date de génération : 2026-08-21T15:52:49Z

Périmètre : amélioration du pipeline d'extraction / chunking / classification / entités /
indexation RAG locale. **Aucun document source, modèle original, `dossier_master.json` ni texte
juridique n'a été modifié.** Tous les fichiers produits/corrigés sont écrits dans `output/`.
Les index Qdrant sont dérivés et régénérables (supprimés de l'archive ; à recréer par
`python -m app.cli index --all` sur le poste équipé d'Ollama).

## 1. Fichiers modifiés

| Fichier | Nature du changement |
|---|---|
| `app/chunking/quality.py` | Moteur local : classification prioritaire, entités validées (CIN, prêts, rangs, montants, dates, banques, personnes structurées), détection notice technique, règles arabes, filtres de fragments (Correctifs 1–7) |
| `app/chunking/section_detection.py` | Détection de sections FR/AR enrichie (en-têtes arabes, mots-clés canoniques) (Correctifs 2, 7) |
| `app/chunking/dossiers_chunker.py` | Notice technique sortie dans un chunk dédié non indexable ; corps métier indexé normalement (Correctif 1) |
| `app/chunking/modeles_chunker.py` | Même séparation de notice + exclusion des fragments de tableau (Correctifs 1, 3) |
| `app/chunking/augment.py` | Rôles secondaires, `chunk_roles`, indexabilité, flags qualité (Correctifs 2, 3, 6) |
| `app/chunking/audit.py` | **Nouveau** : audit qualité mesurable (Correctif 10) |
| `app/core/schemas.py` | `secondary_chunk_roles`, `chunk_roles`, `status`/`reason` (Correctifs 2, 6) |
| `app/core/config.py` | `OLLAMA_EMBED_BATCH_SIZE`, `OLLAMA_REQUEST_TIMEOUT`, `OLLAMA_MAX_RETRIES`, `OLLAMA_KEEP_ALIVE` (Correctif 8) |
| `.env.example` | Variables Ollama d'embedding par lots ajoutées (Correctif 8) |
| `app/retrieval/ollama_client.py` | `embed_many()` via `POST /api/embed` (ordre garanti), retry, réduction automatique du batch, journal d'erreurs, timeout `(180, connect=20)`, `trust_env=False`, `verify=False`, barre de progression (Correctif 8) |
| `app/retrieval/qdrant_store.py` | Upsert filtré `indexable & !retrieval_excluded`, `reset_collection()`, recherche exacte filtrée, voisins filtrés (Correctif 9) |
| `app/retrieval/hybrid.py` | `UnsafeSearchError` imposé aux recherches lexicale/exacte/RRF/voisins dès qu'un dossier client est présent sans `dossier_id` (Correctif 9) |
| `app/services/indexing_service.py` | Embeddings batchés, `--resume`, `--reset-collection`, compteurs exclus (Correctifs 8, 9) |
| `app/cli.py` | `audit-chunks --source …`, `diagnose`, `--resume`, `--reset-collection`, `--only-dossier` (Correctifs 8, 10) |
| `tests/test_correctifs.py` | **Nouveau** : 23 tests des correctifs (Correctifs 1–9) |

## 2. Nombre de chunks avant / après

| Indicateur | Avant | Après | Δ |
|---|---|---|---|
| Total chunks | 4560 | 4924 | +364 |
| Indexables | 4533 | 4794 | +261 |
| Exclus (hors index) | 27 | 130 | +103 |

Répartition après correction — **dossiers** : 250 chunks (173 indexables, 77 exclus) ;
**modèles** : 266 chunks (213 indexables, 53 exclus) ;
**lois** : 4408 chunks (tous indexables, texte préservé).

## 3. Correctifs détaillés (mesures réelles après régénération)

### Correctif 1 — Notice technique séparée du contenu utile
- 27 notices détachées dans un chunk dédié (`chunk_role=technical_notice`, `indexable=false`, `retrieval_excluded=true`).
- Le corps post-notice est découpé et indexé normalement : CIN, titres fonciers, montants, parties et clauses ne sont plus perdus
  (ex. `1-2024-843-AMBIGU` : chunk 0 = notice ; chunks 1–4 = acte indexé `parties` / `property` / `price`).
- Documents arabes/bilingues restent indexables après retrait de la notice (testé).

### Correctif 2 — Classification par sections et rôles
Ordre de priorité implémenté : Prix/Paiement → Désignation du bien → Hypothèque → Financement → Parties → Signatures →
Pièces jointes → clauses diverses ; titre explicite (« Article 2 - Prix ») toujours prioritaire. Champs `secondary_chunk_roles`, `chunk_roles`.
Répartition rôles (dossiers) : {"technical_notice": 27, "parties": 40, "property": 39, "price": 27, "mortgage": 6, "clause": 79, "payment": 10, "signatures": 20, "financing": 2}.
Répartition rôles (modèles) : {"clause": 90, "payment": 14, "price": 28, "property": 15, "signatures": 15, "financing": 27, "parties": 63, "mortgage": 14}.
Sections inférées (dossiers) : 79.

### Correctif 3 — Mini-chunks et artefacts de tableaux
Fragments courts / artefacts exclus : 50 (dossiers) + 53 (modèles),
dont 96 artefacts de tableau explicites (`LE |`, `OR |`, `RE |`, `DROIT RECU |`, `D.V | 600.000 درهم`).
Un fragment avec valeur reste disponible uniquement pour audit (jamais envoyé dans Qdrant), sauf continuité de tableau certaine.

### Correctif 4 — Entités : faux positifs éliminés
- CIN : faux positifs stockés **18 → 0**
  (« le 2024 », « du 2024 », « 2024-12-12 », « consenti », « est » rejetés ; règle : ≥1 lettre, ≥3 chiffres, sans espace, ni mot courant, ni date).
- Prêts : faux prêts **2 → 0** (déclencheurs explicites uniquement : `prêt n°`, `n° de prêt`, `numéro de crédit`, `loan number`, …).
- Rangs hypothécaires : valeurs vides **3 → 0** ; normalisation `1er rang→1`, `3er rang→3`, `premier rang→1`, arabe inclus.
- Montants : 50 extraits (dossiers) normalisés (`1,650,000 DHS→1650000`, `1.650.000 DHS→1650000`, `600.000 درهم→600000`) ;
  `amount_format_nonstandard` : 14 ; `amount_words_digits_mismatch` : 1.
- Dates : 56 formats variés (ISO, JJ/MM/AAAA, « 12 mai 2024 », « 3 نونبر 2024 », « 30 ماي 2025 »).
- Banques : **0 → 17** (BMCE Bank, AL BARID BANK, Attijariwafa Bank, BMCI, Wafa Immobilier, CDG, …).

### Correctif 5 — Personnes et rôles structurés
Personnes structurées `{name_fr, name_ar, role, cin, confidence}` : **0 → 12**.
Lien nom/rôle/CIN ambigu → aucune entité inventée. Rôles FR/AR : vendeur, acquéreur, donateur, donataire, mandant, mandataire,
débiteur, créancier, caution, représentant, notaire, comparant + équivalents arabes.

### Correctif 6 — Documents hypothécaires
Ex. `10-2024-542-HYPOTHEQUE-SQALLI` ch.1 : `chunk_role=mortgage`, `secondary_chunk_roles=['price','property','financing','parties','signatures']`,
banque AL BARID BANK, rang 3, montant 420000, TF 148.201/08.

### Correctif 7 — Support arabe
Règles : الثمن/مبلغ/درهم → `prix_paiement` ; تعيين العقار/الرسم العقاري → `designation_bien` ; رهن/رفع اليد/التشطيب →
`financement_hypotheque` ; قرض/بنك → `financing` ; حضر/الأطراف → `parties` ; حرر وأنجز/التوقيع → `signatures` ;
المرفقات → `pieces_jointes`. L'arabe n'est jamais traduit ni modifié.

### Correctif 8 — Indexation Ollama efficace
`embed_many(texts)` via `POST /api/embed` (`keep_alive=10m`), ordre garanti, batch=4, timeout 180 s, retry ×3 avec réduction
automatique du batch, journal d'erreurs, barre de progression, `--resume`, `--reset-collection`, `python -m app.cli diagnose`.
Plus aucun `embed()` par chunk.

### Correctif 9 — Qdrant et sécurité
Upsert filtré `indexable & !retrieval_excluded` (jamais de notice/fragment dans Qdrant — testé). `UnsafeSearchError` conservé ;
`dossier_id` obligatoire dans : recherche dense, BM25 (lexical), recherche exacte, hybride RRF, reranking et récupération de voisins.

### Correctif 10 — Audit qualité CLI
`python -m app.cli audit-chunks --source dossiers|modeles|lois` → `output/chunk_quality_audit_*.json` (+ `_before.json`, `_after.json`).

## 4. Résultats de tests (exécution réelle)

```
82 passed, 7 skipped, 1 warning in 9.97s
```

Les 7 skips exigent le serveur **Ollama local** (embed réel, recherche vectorielle avec vrai modèle) : Ollama n'est pas joignable dans
cet environnement isolé (`diagnose` → `ollama.available: false`), conformément à la convention du projet (skip explicite, jamais de mock).
Les mécanismes `embed_many` (ordre), retry/réduction de batch, `--resume`, isolation Qdrant réelle (embarqué, vecteurs 4D) et
refus sans `dossier_id` sont testés localement.

## 5. Résultat de `python -m app.cli diagnose` (réel)

- Ollama : `url_effective=http://127.0.0.1:11434`, **available = false** (aucun embedding exécuté, résultat non simulé) ;
- Qdrant : mode `embedded`, verrou instance unique OK, tailles de l'index existant avant nettoyage : `legal_public=0`, `templates_internal=35`, `case_documents=90` ;
- Disque libre : 19.6 Go ;
- Chunks (jsonl) : dossiers 250 (173 indexables / 77 exclus), modèles 266 (213 / 53), lois 4408 (4408 / 0).

## 6. Indexation du corpus dossiers

Chunking réel : `python -m app.cli index --source dossiers --no-embed` → 250 chunks dans `output/chunks_dossiers.jsonl`,
173 indexables, 77 exclus, `n_extraction_errors: 0`. L'indexation vectorielle complète (Ollama → Qdrant) n'a **pas été simulée** :
elle nécessite Ollama local, indisponible ici ; elle se lance sur le poste notaire par `python -m app.cli index --source dossiers`.

## 7. Isolation `dossier_id` — testée et conservée

- `test_19_real_qdrant_isolates_dossiers` : Qdrant embarqué réel (tmp), 2 dossiers + 1 notice ; upsert = 2 (notice exclue),
  recherche sans dossier_id → `UnsafeSearchError`, recherche D1 → uniquement D1 (le texte secret de D2 n'apparaît jamais), D2 → uniquement D2. **Passe.**
- `UnsafeSearchError` étendu à BM25/exact/RRF/voisins (tests 20–21). **Passe.**

## 8. Préservation du corpus juridique

Comparaison directe `data/lois/lois_chunks.json` ↔ `output/chunks_lois.jsonl` (4408 chunks) :
- **`chunk_id` identiques et ordre préservé : vrai** ;
- **`text` identique à l'octet : vrai** ;
- `law_id`, `law_name`, `article_num`, `chunk_index`, `page_start`, `page_end`, `n_chars`, `n_tokens` préservés : vrai.

## 9. Livrables écrits

- `output/chunk_quality_audit_before.json`
- `output/chunk_quality_audit_after.json`
- `output/chunk_quality_audit_dossiers.json` / `..._modeles.json` / `..._lois.json`
- `output/chunks_dossiers.jsonl` (250), `output/chunks_modeles.jsonl` (266), `output/chunks_lois.jsonl` (4408)
- `output/diagnose.json` (résultat réel)
- `output/chunk_quality_corrections.md` (ce rapport)
