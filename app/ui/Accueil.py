"""Point d'entrée du parcours notaire : redirection vers Dossiers."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.services.public_labels import TECHNICAL_DIFFICULTY_MESSAGE  # noqa: E402

st.set_page_config(page_title="Dossiers", page_icon="🗂️", layout="wide")
st.title("🗂️ Dossiers")
st.caption("Ouverture de l’espace de travail du notaire…")

try:
    st.switch_page("pages/1_Dossiers.py")
except Exception:  # noqa: BLE001
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
