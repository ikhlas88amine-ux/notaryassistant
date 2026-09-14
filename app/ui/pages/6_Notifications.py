"""Centre de notifications métier."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.services.public_labels import TECHNICAL_DIFFICULTY_MESSAGE  # noqa: E402
from app.ui import api_client as api  # noqa: E402

st.set_page_config(page_title="Notifications", page_icon="🔔", layout="wide")

selected_dossier = st.session_state.get("dossier_id_selectionne")
try:
    payload = api.list_notifications(dossier_id=selected_dossier)
except Exception:  # noqa: BLE001
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
    st.stop()

badge = payload.get("badge_count", 0)
st.title(f"🔔 Notifications ({badge})")
notifications = payload.get("notifications", [])

if not notifications:
    st.success("Aucune notification à afficher pour le moment.")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    level_filter = st.multiselect(
        "Niveau",
        ["Attention requise", "Vérification recommandée", "Information"],
        default=["Attention requise", "Vérification recommandée", "Information"],
    )
with col2:
    state_filter = st.multiselect(
        "État",
        ["nouvelle", "lue", "traitée"],
        default=["nouvelle", "lue", "traitée"],
    )

visible = [
    notification for notification in notifications
    if notification.get("level_label") in level_filter and notification.get("state_label") in state_filter
]

for notification in visible:
    with st.container(border=True):
        st.markdown(f"**{notification.get('level_label')}** — {notification.get('dossier_reference')}" )
        st.write(f"**{notification.get('title')}**")
        st.write(notification.get("message") or "")
        st.caption(f"Action recommandée : {notification.get('recommended_action') or 'Vérifier le dossier.'}")
        st.caption(f"État : {notification.get('state_label')} · Date/heure : {notification.get('event_at', '')}")

        buttons = st.columns(4)
        if buttons[0].button("Voir le dossier", key=f"open_{notification.get('notification_key')}"):
            st.session_state["dossier_id_selectionne"] = notification.get("dossier_id")
            st.switch_page("pages/2_Detail_dossier.py")
        if notification.get("action_target", "").startswith("checklist:"):
            if buttons[1].button("Voir la checklist", key=f"check_{notification.get('notification_key')}"):
                st.session_state["dossier_id_selectionne"] = notification.get("dossier_id")
                st.switch_page("pages/2_Detail_dossier.py")
        elif notification.get("action_target", "").startswith("document:"):
            buttons[1].button("Voir le document", key=f"doc_{notification.get('notification_key')}", disabled=True)
        else:
            buttons[1].empty()

        if notification.get("state") == "new":
            if buttons[2].button("Marquer comme lue", key=f"read_{notification.get('notification_key')}"):
                try:
                    api.mark_notification_read(notification.get("notification_key"), notification.get("dossier_id"))
                    st.rerun()
                except Exception:  # noqa: BLE001
                    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
        if notification.get("state") != "treated":
            if buttons[3].button("Marquer comme traitée", key=f"done_{notification.get('notification_key')}"):
                try:
                    api.mark_notification_treated(notification.get("notification_key"), notification.get("dossier_id"))
                    st.rerun()
                except Exception:  # noqa: BLE001
                    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
