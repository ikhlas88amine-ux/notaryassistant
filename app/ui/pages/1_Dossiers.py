"""Vue métier des dossiers pour le notaire."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.services.public_labels import TECHNICAL_DIFFICULTY_MESSAGE  # noqa: E402
from app.ui import api_client as api  # noqa: E402

st.set_page_config(page_title="Dossiers", page_icon="🗂️", layout="wide")
st.title("🗂️ Dossiers")

try:
    dossiers = api.list_dossiers()
except Exception:  # noqa: BLE001
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
    st.stop()

try:
    badge = api.list_notifications().get("badge_count", 0)
except Exception:  # noqa: BLE001
    badge = 0

menu_cols = st.columns([2, 1])
menu_cols[0].caption("Suivi des dossiers et contrôles documentaires")
menu_cols[1].metric("Notifications", badge)

types = [
    "Vente immobilière",
    "Hypothèque",
    "Mainlevée",
    "Donation",
    "Succession",
    "Procuration",
    "VEFA",
    "Vente de fonds de commerce",
    "Création de société",
    "Gérance libre",
    "Demande administrative",
]
state_options = [
    "Tous",
    "Attention requise",
    "Vérification recommandée",
    "Conforme selon les contrôles automatiques",
]

col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    selected_types = st.multiselect("Type d’acte", [t for t in types if t in {d.get('public_type') for d in dossiers}], default=[])
with col2:
    selected_state = st.selectbox("État", state_options)
with col3:
    search_term = st.text_input("Référence / famille")

filtered = dossiers
if selected_types:
    filtered = [d for d in filtered if d.get("public_type") in selected_types]
if selected_state != "Tous":
    filtered = [d for d in filtered if d.get("public_state") == selected_state]
if search_term:
    needle = search_term.lower()
    filtered = [
        d for d in filtered
        if needle in str(d.get("dossier_id", "")).lower()
        or needle in str(d.get("client_famille", "")).lower()
        or needle in str(d.get("public_reference", "")).lower()
    ]

st.caption(f"{len(filtered)} dossier(s) affiché(s) sur {len(dossiers)}")

for dossier in sorted(filtered, key=lambda x: x.get("dossier_id", "")):
    with st.container(border=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown(f"**{dossier.get('dossier_id', 'Dossier')}**")
            st.write(
                f"Type d’acte : {dossier.get('public_type', 'Dossier')} · "
                f"Variante : {dossier.get('public_variant', 'Non précisée')} · "
                f"État : {dossier.get('public_state', 'Vérification recommandée')}"
            )
            st.caption(
                f"Année : {dossier.get('annee', 'Non indiquée')} · "
                f"Référence / famille : {dossier.get('client_famille') or 'Non indiquée'}"
            )
        with c2:
            if st.button("Voir le dossier", key=f"open_{dossier.get('dossier_id')}"):
                st.session_state["dossier_id_selectionne"] = dossier.get("dossier_id")
                st.switch_page("pages/2_Detail_dossier.py")
