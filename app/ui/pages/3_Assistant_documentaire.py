"""Assistant documentaire métier pour le notaire."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.services.public_labels import TECHNICAL_DIFFICULTY_MESSAGE  # noqa: E402
from app.ui import api_client as api  # noqa: E402

st.set_page_config(page_title="Assistant documentaire", page_icon="💬", layout="wide")
st.title("💬 Assistant documentaire")
st.caption(
    "Questions-réponses à partir des documents disponibles dans le périmètre choisi. "
    "Toute réponse doit être vérifiée par le notaire avant usage."
)

try:
    dossiers = api.list_dossiers()
    ids = sorted(d.get("dossier_id") for d in dossiers if d.get("dossier_id"))
except Exception:  # noqa: BLE001
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
    st.stop()

perimetre = st.radio(
    "Périmètre",
    ["dossier", "template", "law"],
    horizontal=True,
    format_func=lambda s: {
        "dossier": "🗂️ Dossier",
        "template": "📄 Modèles internes",
        "law": "⚖️ Recherche juridique",
    }[s],
)

dossier_id = None
if perimetre == "dossier":
    dossier_id = st.selectbox("Dossier concerné", ids)

if "historique_chat" not in st.session_state:
    st.session_state["historique_chat"] = []

for tour in st.session_state["historique_chat"]:
    with st.chat_message("user"):
        st.markdown(tour["question"])
    with st.chat_message("assistant"):
        st.markdown(tour["reponse"].get("answer", ""))
        sources = tour["reponse"].get("sources") or []
        if sources:
            with st.expander("Sources consultées"):
                for source in sources:
                    fichier = source.get("fichier") or "Document"
                    st.markdown(f"- {fichier}")
                    if source.get("excerpt"):
                        st.caption(source["excerpt"])

question = st.chat_input("Votre question documentaire")
if question:
    if perimetre == "dossier" and not dossier_id:
        st.error(TECHNICAL_DIFFICULTY_MESSAGE)
    else:
        with st.spinner("Analyse en cours…"):
            try:
                reponse = api.chat(question, perimetre, dossier_id)
                st.session_state["historique_chat"].append({"question": question, "reponse": reponse})
                st.rerun()
            except Exception:  # noqa: BLE001
                st.error(TECHNICAL_DIFFICULTY_MESSAGE)

if st.button("Effacer la conversation"):
    st.session_state["historique_chat"] = []
    st.rerun()
