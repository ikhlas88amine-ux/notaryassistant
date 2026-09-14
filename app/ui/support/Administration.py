"""Page Administration : indexation, etat des services, informations sur les modeles locaux."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.core.config import get_settings  # noqa: E402
from app.ui import api_client as api  # noqa: E402

st.set_page_config(page_title="Administration", page_icon="⚙️", layout="wide")
st.title("⚙️ Administration / Indexation")
st.caption(
    "Reindexer les corpus met a jour la base vectorielle Qdrant. Cette operation appelle le "
    "modele d'embedding local (Ollama) pour chaque nouveau fragment de texte ; elle peut prendre "
    "plusieurs minutes sur les 22 dossiers reels."
)

try:
    h = api.health()
    m = api.models()
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend indisponible : {exc}")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Ollama", "disponible" if h.get("ollama_available") else "indisponible")
col2.metric("Modele de chat", m.get("chat_model", "?"))
col3.metric("Modele d'embedding", m.get("embedding_model", "?"))

st.divider()
st.subheader("Indexation")

c1, c2, c3, c4 = st.columns(4)
if c1.button("Indexer tout (lois + modeles + dossiers)"):
    with st.spinner("Indexation complete en cours..."):
        try:
            manifest = api.index_all()
            st.session_state["dernier_manifeste"] = manifest
            st.success("Indexation complete terminee.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erreur pendant l'indexation : {exc}")
for label, corpus, col in (("Lois", "lois", c2), ("Modeles", "modeles", c3), ("Dossiers", "dossiers", c4)):
    if col.button(f"Indexer {label}"):
        with st.spinner(f"Indexation de {label} en cours..."):
            try:
                resultat = api.index_source(corpus)
                st.session_state[f"dernier_resultat_{corpus}"] = resultat
                st.success(f"Indexation de {label} terminee.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Erreur pendant l'indexation de {label} : {exc}")

for key in ("dernier_manifeste",) + tuple(f"dernier_resultat_{c}" for c in ("lois", "modeles", "dossiers")):
    if key in st.session_state:
        with st.expander(key):
            st.json(st.session_state[key])

st.divider()
st.subheader("Dernier manifeste d'indexation enregistre sur disque")
settings = get_settings()
manifest_path = settings.output_path / "index_manifest.json"
if manifest_path.exists():
    st.json(json.loads(manifest_path.read_text(encoding="utf-8")))
else:
    st.info("Aucun manifeste d'indexation trouve encore sur disque.")

st.divider()
st.subheader("Rappels de securite et de confidentialite")
st.markdown(
    "- Aucune cle API distante n'est utilisee : tout le traitement (embeddings + generation) reste local via Ollama.\n"
    "- La recherche en perimetre `dossier` exige toujours un `dossier_id` — aucune recherche non filtree "
    "sur les documents clients n'est possible (regle imposee au niveau code, pas seulement au niveau prompt).\n"
    "- Les documents originaux (data/dossiers, data/modeles) ne sont jamais modifies par l'application, "
    "uniquement lus pour extraction et indexation.\n"
    "- data/lois est actuellement vide : aucun texte de loi n'a ete invente pour combler ce corpus."
)
