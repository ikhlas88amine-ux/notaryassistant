"""Page Audit sécurité RAG (cahier des charges §9).

Surveille les modifications et incoherences entre fichiers sources, chunks JSONL, collections
Qdrant et manifests. L'audit est en LECTURE SEULE : il ne corrige jamais rien ; le notaire
enregistre uniquement une decision de suivi (authorized / resolved / ignored) avec justification,
en conservant le constat original.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.ui import api_client as api  # noqa: E402

st.set_page_config(page_title="Audit sécurité RAG", page_icon="🛡️", layout="wide")
st.title("🛡️ Audit sécurité RAG")
st.caption(
    "Vérifie la cohérence entre fichiers sources, chunks JSONL, Qdrant et manifests d'intégrité. "
    "Un audit ne modifie JAMAIS les sources, chunks ou vecteurs ; une différence de hash signifie "
    "« modification détectée », pas automatiquement « attaque »."
)

try:
    api.health()
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend indisponible : {exc}")
    st.stop()

if st.button("▶️ Lancer un audit maintenant"):
    with st.spinner("Audit en cours (lecture seule)..."):
        try:
            st.session_state["audit"] = api.run_audit()
            st.success("Audit terminé.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erreur pendant l'audit : {exc}")

audit = st.session_state.get("audit") or api.last_audit()
if not audit:
    st.info("Aucun audit exécuté pour l'instant. Lancez-en un pour afficher le rapport.")
    st.stop()

st.subheader("Dernier audit")
st.caption(f"Exécuté le : {audit.get('run_at')} — mode : {audit.get('modele')}")
counts = audit.get("counts_by_severity", {})
c1, c2, c3, c4 = st.columns(4)
c1.metric("Bloquantes", counts.get("blocking", 0))
c2.metric("Élevées", counts.get("high", 0))
c3.metric("Moyennes", counts.get("medium", 0))
c4.metric("Basses / info", counts.get("low", 0) + counts.get("info", 0))

anomalies = audit.get("anomalies", [])
if not anomalies:
    st.success("Aucune anomalie détectée (état normal).")
    st.stop()

corpus_options = ["tous"] + sorted({a.get("corpus") for a in anomalies})
f_corpus = st.selectbox("Filtrer par corpus", corpus_options)
severite_options = ["toutes"] + ["blocking", "high", "medium", "low", "info"]
f_sev = st.selectbox("Filtrer par gravité", severite_options)

decisions = {d.get("anomaly_key"): d for d in api.audit_decisions()}

visibles = [
    a for a in anomalies
    if (f_corpus == "tous" or a.get("corpus") == f_corpus)
    and (f_sev == "toutes" or a.get("severity") == f_sev)
]
st.caption(f"{len(visibles)} anomalie(s) affichée(s) sur {len(anomalies)}")

icone = {"blocking": "🛑", "high": "🔴", "medium": "🟠", "low": "🟡", "info": "ℹ️"}
for i, a in enumerate(visibles):
    key = a.get("anomaly_key") or f"{a.get('corpus')}:{a.get('fichier')}:{a.get('code')}"
    decision = decisions.get(key)
    with st.container(border=True):
        st.markdown(f"{icone.get(a.get('severity'), 'ℹ️')} **[{a.get('severity')}] {a.get('code')}** — {a.get('corpus')}")
        st.write(a.get("message"))
        c1, c2 = st.columns(2)
        c1.caption(f"Ancien hash : {a.get('ancien_hash')}")
        c2.caption(f"Nouveau hash : {a.get('nouveau_hash')}")
        if decision:
            st.info(f"Décision : {decision.get('action')} — {decision.get('justification')} ({decision.get('decided_at')})")
        else:
            col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
            just = st.text_input("Justification (obligatoire pour suivre)", key=f"just_{key}", placeholder="Ex : mise à jour autorisée du modèle J le ...")
            if col1.button("Autoriser", key=f"auth_{key}"):
                if just.strip():
                    api.audit_record_decision(key, "authorized", just)
                    st.rerun()
                else:
                    st.warning("Justification requise.")
            if col2.button("Résolue", key=f"res_{key}"):
                if just.strip():
                    api.audit_record_decision(key, "resolved", just)
                    st.rerun()
                else:
                    st.warning("Justification requise.")
            if col3.button("Ignorer", key=f"ign_{key}"):
                if just.strip():
                    api.audit_record_decision(key, "ignored", just)
                    st.rerun()
                else:
                    st.warning("Justification requise.")

st.divider()
st.markdown("**Rappel** : aucune action de cet écran ne modifie les fichiers sources, les chunks ou les vecteurs. Le constat original de l'audit est toujours conservé (output/audit/last_audit.json et manifests).")
