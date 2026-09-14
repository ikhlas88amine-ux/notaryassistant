# Corpus `data/lois/`

Ce corpus est **actuellement vide**. Aucun texte juridique marocain reel n'a ete
fourni dans les sessions ayant precede la construction de cette application : ce
dossier est cree pour recevoir ce contenu, mais **aucun contenu de remplacement
ou fictif n'a ete genere** pour ne jamais risquer de faire passer un texte
invente pour une reference legale reelle.

## Format attendu

Deposez un fichier JSON par loi (ou par regroupement coherent de lois), decoupe
par article, au format suivant :

```json
{
  "law_id": "dahir-1913-08-12-immatriculation-fonciere",
  "law_name": "Dahir du 9 ramadan 1331 (12 aout 1913) sur l'immatriculation fonciere",
  "language": "fr",
  "articles": [
    {
      "article_num": "1",
      "titre": "Titre I - De l'immatriculation",
      "chapitre": "Chapitre I",
      "section": null,
      "page": 1,
      "text": "Texte integral de l'article, tel que publie au Bulletin Officiel."
    }
  ]
}
```

Champs minimum requis par article : `article_num`, `text`. Les champs
`titre`, `chapitre`, `section`, `page` sont optionnels mais recommandes pour
la citation precise dans les reponses du RAG.

Le pipeline d'indexation (`python -m app.cli index --source lois`) lit tout
fichier `*.json` present dans ce dossier (recursivement), sans jamais modifier
le fichier source, et produit `output/chunks_lois.jsonl`.

## Pourquoi ce dossier est vide pour l'instant

Le cahier des charges de l'application suppose que ce corpus est deja
prepare, mais l'inspection de l'espace de travail au moment de la
construction du projet n'a retrouve aucun fichier de ce type. Deposez vos
textes reels ici (ou dans des sous-dossiers, ex. `data/lois/cgi/`,
`data/lois/code_famille/`, `data/lois/doc/`) puis relancez l'indexation :

```bash
python -m app.cli index --source lois
```

Aucune action supplementaire n'est necessaire : l'absence de fichiers dans ce
dossier ne bloque pas l'indexation des deux autres corpus (`modeles`,
`dossiers`), elle produit simplement un `chunks_lois.jsonl` vide et un
avertissement explicite dans le rapport d'indexation.
