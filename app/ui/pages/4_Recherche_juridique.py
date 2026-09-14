"""Recherche juridique présentée sans détail technique, avec historique de session."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.services.presentation import carte_juridique, partition_juridique_results  # noqa: E402
from app.services.public_labels import TECHNICAL_DIFFICULTY_MESSAGE  # noqa: E402
from app.ui import api_client as api  # noqa: E402
from app.ui.history import add_entry, clear_entries, relance_question, resultat_label  # noqa: E402

st.set_page_config(page_title="Recherche juridique", page_icon="⚖️", layout="wide")
st.title("⚖️ Recherche juridique")
st.caption("Recherche dans les références juridiques disponibles pour l’étude.")

with st.expander("Recherches récentes", expanded=False):
    historique = st.session_state.get("historique_juridique", [])
    if not historique:
        st.caption("Aucune recherche enregistrée pour le moment.")
    for entree in historique:
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"**{entree.get('question', '')}**")
            st.caption(f"{entree.get('horodatage', '')} · {resultat_label(entree.get('nb_resultats', 0))}")
        with col2:
            if st.button("Relancer", key=f"relance_juridique_{entree.get('question')}"):
                st.session_state["q_juridique"] = relance_question(entree)
                st.rerun()
    if historique and st.button("Effacer l’historique"):
        st.session_state["historique_juridique"] = clear_entries(historique)
        st.session_state["q_juridique"] = ""
        st.rerun()

query = st.text_input("Recherche", key="q_juridique")
top_k = st.slider("Nombre de résultats", 1, 10, 5)

if query:
    with st.spinner("Recherche en cours…"):
        try:
            resultats = api.search_laws(query, top_k=top_k)
        except Exception:  # noqa: BLE001
            st.error(TECHNICAL_DIFFICULTY_MESSAGE)
            st.stop()

    st.session_state["historique_juridique"] = add_entry(
        st.session_state.get("historique_juridique", []), query, len(resultats)
    )

    if not resultats:
        st.info("Aucun résultat n’a été trouvé pour cette recherche.")
    else:
        principal, autres = partition_juridique_results(resultats)
        if principal:
            with st.container(border=True):
                st.markdown(f"### {principal['titre']}")
                if principal["article"]:
                    st.markdown(f"**{principal['article']}**")
                st.write(principal["extrait"])
                st.markdown("**Réponse documentaire :**")
                st.write(principal["reponse"])
                st.caption(principal["a_verifier"])
        if autres:
            with st.expander("Autres articles potentiellement utiles"):
                for carte in autres:
                    with st.container(border=True):
                        st.markdown(f"**{carte['titre']}**" + (f" — {carte['article']}" if carte["article"] else ""))
                        st.write(carte["extrait"])
                        st.markdown("**Réponse documentaire :**")
                        st.write(carte["reponse"])
                        st.caption(carte["a_verifier"])
