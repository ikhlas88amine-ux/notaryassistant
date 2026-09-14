"""Fiche métier d'un dossier sans détail technique."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from app.services.public_labels import (  # noqa: E402
    NOTARY_WARNING,
    TECHNICAL_DIFFICULTY_MESSAGE,
    ambigu_pricing_message,
    clean_value,
    format_amount,
    public_state_label,
    public_type_label,
    public_variant_label,
)
from app.ui import api_client as api  # noqa: E402

ATTENTION_BLOCANTE = "Attention requise : une incohérence doit être résolue avant la rédaction définitive."
VERIFICATION_RECOMMANDEE = "Vérification recommandée : les documents disponibles ne permettent pas de confirmer ce point automatiquement."
INFORMATION_COMPLEMENTAIRE = "Information : ce point reste à contrôler dans les pièces ou auprès des parties."

st.set_page_config(page_title="Détail dossier", page_icon="🗂️", layout="wide")
st.title("🗂️ Détail dossier")

try:
    dossiers = api.list_dossiers()
except Exception:  # noqa: BLE001
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
    st.stop()

ids = [d.get("dossier_id") for d in dossiers if d.get("dossier_id")]
defaut = st.session_state.get("dossier_id_selectionne")
index_defaut = ids.index(defaut) if defaut in ids else 0

dossier_id = st.selectbox("Dossier", ids, index=index_defaut if ids else 0)
if not dossier_id:
    st.stop()

st.session_state["dossier_id_selectionne"] = dossier_id

try:
    master = api.get_dossier(dossier_id)
    docs = api.get_dossier_documents(dossier_id)
    report = api.get_dossier_validation(dossier_id)
    checklist = api.get_dossier_document_checklist(dossier_id)
except Exception:  # noqa: BLE001
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
    st.stop()

validation_status = (report or {}).get("status")
public_type = public_type_label(master.get("type_dossier"))
public_variant = public_variant_label(master.get("type_dossier"), master.get("variante"))
public_state = public_state_label(validation_status)
donnees = master.get("donnees") if isinstance(master.get("donnees"), dict) else {}
parties = {
    "Vendeur": clean_value((donnees.get("vendeur") or {}).get("nom_fr") if isinstance(donnees.get("vendeur"), dict) else None),
    "Acquéreur": clean_value((donnees.get("acquereur") or {}).get("nom_fr") if isinstance(donnees.get("acquereur"), dict) else None),
    "Donateur": clean_value((donnees.get("donateur") or {}).get("nom_fr") if isinstance(donnees.get("donateur"), dict) else donnees.get("donateur")),
    "Donataire": clean_value((donnees.get("donataire") or {}).get("nom_fr") if isinstance(donnees.get("donataire"), dict) else donnees.get("donataire")),
    "Mandant": clean_value((donnees.get("mandant") or {}).get("nom_fr") if isinstance(donnees.get("mandant"), dict) else donnees.get("mandant")),
    "Mandataire": clean_value((donnees.get("mandataire") or {}).get("nom_fr") if isinstance(donnees.get("mandataire"), dict) else donnees.get("mandataire")),
    "Défunt": clean_value((donnees.get("defunt") or {}).get("nom_fr") if isinstance(donnees.get("defunt"), dict) else donnees.get("defunt")),
    "Héritiers": clean_value(donnees.get("heritiers") or donnees.get("héritiers")),
    "Banque bénéficiaire": clean_value(donnees.get("banque") or donnees.get("banque_beneficiaire")),
}
bien = donnees.get("bien") if isinstance(donnees.get("bien"), dict) else {}
conditions = {
    "Prix de vente": format_amount(donnees.get("prix_dhs") or donnees.get("prix_dhs_version_fr") or donnees.get("valeur_don")),
    "Paiement immédiat": format_amount(donnees.get("paiement_immediat_dhs") or donnees.get("acompte_dhs")),
    "Solde différé": format_amount(donnees.get("solde_differe_dhs")),
    "Délai de paiement": clean_value(donnees.get("delai_paiement") or donnees.get("echeance_solde")),
    "Crédit garanti": format_amount(donnees.get("credit_garanti_dhs") or donnees.get("montant_credit_dhs")),
    "Rang de l’hypothèque": clean_value(donnees.get("rang_hypotheque") or donnees.get("rang")),
}

st.subheader("Dossier")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Type d’acte", public_type)
col2.metric("Variante", public_variant)
col3.metric("Année", clean_value(master.get("annee")))
col4.metric("État", public_state)
st.caption(f"Référence / famille : {master.get('client_famille') or 'Non indiquée'}")
st.info(NOTARY_WARNING)

if (master.get("type_dossier") or "").upper() == "AMBIGU":
    st.warning(ambigu_pricing_message(master))

st.divider()
st.subheader("Parties")
left, right = st.columns(2)
party_items = list(parties.items())
for idx, (label, value) in enumerate(party_items):
    (left if idx % 2 == 0 else right).write(f"**{label}** : {value}")

st.divider()
st.subheader("Bien concerné")
st.write(f"**Titre foncier** : {clean_value(bien.get('tf'))}")
st.write(f"**Superficie** : {clean_value(bien.get('superficie_m2'))}")
st.write(f"**Nature** : {clean_value(bien.get('nature'))}")
st.write(f"**Adresse** : {clean_value(bien.get('adresse'))}")

st.divider()
st.subheader("Conditions financières")
for label, value in conditions.items():
    st.write(f"**{label}** : {value}")

st.divider()
st.subheader("Documents du dossier")
if docs:
    for doc in docs:
        st.markdown(f"- {doc}")
else:
    st.caption("Aucun document affichable pour le moment.")

st.divider()
st.subheader("Checklist documentaire")
manual_checks: list[str] = []
if not checklist:
    st.error(TECHNICAL_DIFFICULTY_MESSAGE)
elif not checklist.get("evaluable"):
    st.info(checklist.get("message") or "Aucune checklist spécifique n’est disponible pour ce dossier.")
else:
    synthese = checklist.get("synthese", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Documents repérés", synthese.get("presente", 0))
    c2.metric("Pièces à compléter", synthese.get("a_ajouter", 0))
    c3.metric("Points à vérifier", synthese.get("a_verifier", 0))
    manual_checks = list(checklist.get("manual_checks", []))

    mapping = {
        "presente": "Documents repérés",
        "a_ajouter": "Pièces à compléter",
        "a_verifier": "Points à vérifier",
        "non_applicable": "Non applicable",
    }
    for statut, titre in mapping.items():
        items = [item for item in checklist.get("items", []) if item.get("statut") == statut]
        if not items:
            continue
        st.markdown(f"#### {titre}")
        for item in items:
            with st.container(border=True):
                st.markdown(f"**{item.get('label', 'Pièce')}**")
                if item.get("explication"):
                    st.write(item["explication"])
                if item.get("fichiers_detectes"):
                    st.caption("Document(s) repéré(s) : " + ", ".join(item["fichiers_detectes"]))

st.divider()
st.subheader("Vérifications du dossier")
if not report:
    st.caption("Aucun résultat n’est disponible pour le moment.")
else:
    grouped = {"blocking": [], "warning": [], "info": []}
    for issue in report.get("issues", []):
        grouped.setdefault(issue.get("severity", "info"), []).append(issue)

    def render_issue(title: str, items: list[dict], color: str, intro: str) -> None:
        st.markdown(f"#### {title}")
        if not items:
            st.caption("Aucun point à signaler automatiquement.")
            return
        for issue in items:
            with st.container(border=True):
                st.caption(intro)
                st.markdown(f"**{issue.get('title') or title}**")
                st.write(issue.get("message") or "Vérification recommandée.")
                if issue.get("recommended_action"):
                    st.caption(f"Action recommandée : {issue.get('recommended_action')}")

    render_issue("Attention requise", grouped.get("blocking", []), "red", ATTENTION_BLOCANTE)
    render_issue("Vérification recommandée", grouped.get("warning", []), "orange", VERIFICATION_RECOMMANDEE)
    render_issue("Information", grouped.get("info", []), "blue", INFORMATION_COMPLEMENTAIRE)
    st.info(NOTARY_WARNING)

st.divider()
st.subheader("Points à vérifier manuellement")
if manual_checks:
    for item in manual_checks:
        st.markdown(f"- {item}")
else:
    st.caption("Aucun point complémentaire n’est listé pour ce dossier.")

if st.button("Voir les notifications"):
    st.session_state["dossier_id_selectionne"] = dossier_id
    st.switch_page("pages/6_Notifications.py")
