"""Mode séparé et volontaire de recherche de situations similaires.

Distinct de l'Assistant documentaire d'un dossier : jamais utilisé comme fallback
automatique. Activé explicitement par le notaire, résultats anonymisés, accès aux
dossiers limité aux dossiers autorisés.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.core.config import get_settings  # noqa: E402
from app.services.public_labels import TECHNICAL_DIFFICULTY_MESSAGE  # noqa: E402
from app.services.similar_cases import (  # noqa: E402
    AVERTISSEMENT_SIMILARES,
    TYPE_OPTIONS,
    anonymized_catalog,
    search_similar,
)
from app.ui import api_client as api  # noqa: E402

st.set_page_config(page_title="Situations similaires", page_icon="🔎", layout="wide")
st.title("🔎 Situations similaires")
st.caption(AVERTISSEMENT_SIMILARES)

try:
    dossiers = api.list_dossiers()
    autorises = [d.get("dossier_id") for d in dossiers if d.get("dossier_id")]
except Exception:  # noqa: BLE001
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
    st.stop()

enabled = st.checkbox("Activer la recherche de situations similaires", value=False)
st.caption("Ce mode reste désactivé tant que vous ne l’activez pas volontairement.")

catalog = anonymized_catalog(get_settings().dossiers_dir, autorises)

annees = sorted({c["annee"] for c in catalog if c["annee"]})
variantes = sorted({c["variante_public"] for c in catalog if c["variante_public"] and c["variante_public"] != "Non précisée"})

query = st.text_input("Décrire la situation recherchée")
col1, col2, col3 = st.columns(3)
with col1:
    type_filtre = st.selectbox("Filtrer par type", TYPE_OPTIONS)
with col2:
    annee_filtre = st.selectbox("Filtrer par année", ["Toutes les années"] + annees)
with col3:
    variante_filtre = st.selectbox("Filtrer par variante", ["Toutes"] + variantes)

lancer = st.button("Rechercher", type="primary")

if lancer:
    if not enabled:
        st.info("Activez d’abord la recherche de situations similaires (activation volontaire).")
    elif not query:
        st.info("Décrivez la situation à rechercher.")
    else:
        resultats = search_similar(
            query,
            catalog,
            enabled=enabled,
            type_filter=type_filtre,
            annee_filter=None if annee_filtre == "Toutes les années" else annee_filtre,
            variante_filter=None if variante_filtre == "Toutes" else variante_filtre,
        )
        if not resultats:
            st.info("Aucune situation comparable n’a été trouvée avec ces critères.")
        for resultat in resultats:
            with st.container(border=True):
                st.markdown("**Situation comparable**")
                st.write(f"Type : {resultat['type_public']}")
                st.write(f"Année : {resultat['annee'] or 'Non indiquée'}")
                st.write(f"Variante : {resultat['variante_public']}")
                st.write(f"Point commun : {resultat['point_commun']}")
                if resultat["dossier_id"] in autorises:
                    if st.button("Ouvrir le dossier", key=f"ouvrir_{resultat['dossier_id']}"):
                        st.session_state["dossier_id_selectionne"] = resultat["dossier_id"]
                        st.switch_page("pages/2_Detail_dossier.py")
