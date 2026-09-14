"""Consultation des modèles internes de l’étude, présentée sans détail technique,
avec historique de session et avertissement métier permanent."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.services.presentation import (  # noqa: E402
    carte_modele,
    partition_modele_results,
)
from app.services.public_labels import TECHNICAL_DIFFICULTY_MESSAGE  # noqa: E402
from app.ui import api_client as api  # noqa: E402
from app.ui.history import add_entry, clear_entries, relance_question, resultat_label  # noqa: E402

st.set_page_config(page_title="Modèles internes", page_icon="📄", layout="wide")
st.title("📄 Modèles internes")
st.caption("Recherche et consultation des modèles internes disponibles pour l’étude.")

with st.expander("Recherches récentes", expanded=False):
    historique = st.session_state.get("historique_modeles", [])
    if not historique:
        st.caption("Aucune recherche enregistrée pour le moment.")
    for entree in historique:
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"**{entree.get('question', '')}**")
            st.caption(f"{entree.get('horodatage', '')} · {resultat_label(entree.get('nb_resultats', 0))}")
        with col2:
            if st.button("Relancer", key=f"relance_modele_{entree.get('question')}"):
                st.session_state["q_modeles"] = relance_question(entree)
                st.rerun()
    if historique and st.button("Effacer l’historique"):
        st.session_state["historique_modeles"] = clear_entries(historique)
        st.session_state["q_modeles"] = ""
        st.rerun()

query = st.text_input("Recherche", key="q_modeles")
top_k = st.slider("Nombre de résultats", 1, 15, 8)


def _synthese_refinee(question: str, extrait: str):
    """Courte reformulation validée (facultative). En cas d'échec ou de non-fidélité,
    la page affiche la présentation déterministe construite depuis le fichier et l'extrait."""
    try:
        from app.retrieval.ollama_client import OllamaClient
        from app.services.refinement import refine_summary
        return refine_summary(
            question,
            OllamaClient(),
            [extrait],
            "Résume en une phrase courte et factuelle l’extrait de modèle fourni, sans rien ajouter.",
        )
    except Exception:  # noqa: BLE001
        return None


if query:
    with st.spinner("Recherche en cours…"):
        try:
            resultats = api.search(query, scope="template", top_k=top_k)["results"].get("templates_internal", [])
        except Exception:  # noqa: BLE001
            st.error(TECHNICAL_DIFFICULTY_MESSAGE)
            st.stop()

    st.session_state["historique_modeles"] = add_entry(
        st.session_state.get("historique_modeles", []), query, len(resultats)
    )

    if not resultats:
        st.info("Aucun modèle correspondant n’a été identifié.")
    else:
        principaux, secondaires = partition_modele_results(resultats)
        for resultat in principaux:
            carte = carte_modele(resultat)
            with st.container(border=True):
                st.markdown(f"### {carte['titre']}")
                st.markdown(f"**Document source :** {carte['source']}")
                extrait = resultat.get("text") or resultat.get("excerpt") or ""
                synthese = _synthese_refinee(query, extrait)
                st.write(synthese or carte["description"])
                st.markdown("**Éléments mentionnés :**")
                for element in carte["elements"]:
                    st.markdown(f"- {element}")
                st.caption(carte["avertissement"])
        if secondaires:
            with st.expander("Autres résultats potentiels"):
                for resultat in secondaires:
                    carte = carte_modele(resultat)
                    with st.container(border=True):
                        st.markdown(f"**{carte['titre']}**")
                        st.markdown(f"Document source : {carte['source']}")
                        st.write(carte["description"])
                        st.caption(carte["avertissement"])
else:
    st.info("Saisissez une recherche pour consulter les modèles internes.")
