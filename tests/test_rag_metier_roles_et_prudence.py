"""Tests déterministes des rôles métier et des formulations prudentes."""
import json
from pathlib import Path

from app.core.schemas import SourceCitation
from app.services.fact_extraction import build_fact_response

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks_dossiers.jsonl"


def _citations(dossier_id):
    out = []
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("dossier_id") == dossier_id and row.get("indexable"):
            out.append(SourceCitation(
                source="client", dossier_id=dossier_id, fichier=row.get("fichier", ""),
                section=row.get("section"), chunk_id=row.get("chunk_id", ""),
                text=row.get("text", ""), excerpt=row.get("text", ""),
            ))
    return out


def _answer(dossier, question):
    result = build_fact_response(question, dossier, _citations(dossier))
    assert result.handled
    assert result.answer.strip()
    return result.answer


def test_hypotheque_statut_engagement():
    a = _answer("9-2024-191-HYPOTHEQUE-AMRANI", "Cette hypothèque est-elle déjà inscrite ou s’agit-il seulement d’un engagement du notaire ?")
    assert "engagement" in a.lower() and "30 jours" in a
    assert "déjà inscrite" in a.lower() and "ne démontre pas" in a.lower()
    assert "engagement_hypothecaire" in a


def test_vente_acceptation_apres_visite():
    a = _answer("17-2025-967-VENTE-ALAOUI", "Le bien a-t-il été accepté après visite par l’acquéreur ?")
    assert "Oui" in a and ("visite" in a.lower() or "inspection" in a.lower())
    assert "acte_de_vente" in a


def test_vente_role_notaire_prudent():
    a = _answer("17-2025-967-VENTE-ALAOUI", "Quel est le rôle du notaire dans cet acte ?")
    assert "forme authentique" in a.lower() and "conseils" in a.lower()
    assert "ne prouve pas" in a.lower() and "effectivement réalisée" in a.lower()
    assert "ne prouve pas à lui seul" in a.lower()
    assert "le document prouve que l'inscription a été effectivement réalisée" not in a.lower()


def test_vente_preuve_propriete():
    a = _answer("17-2025-967-VENTE-ALAOUI", "Le titre foncier prouve-t-il à lui seul que le vendeur est propriétaire ?")
    assert "Non, pas à lui seul" in a
    assert "certificat foncier" in a.lower() and "actualisée" in a.lower()
    assert "acte_de_vente" in a


def test_donation_donateur_sans_cin():
    a = _answer("11-2024-595-DONATION-AMRANI", "Qui est le donateur ?")
    assert "Donateur" in a and "Karim AMRANI" in a
    assert all(x not in a for x in ("Vendeur", "Acquéreur", "CIN"))


def test_donation_donataire_sans_cin():
    a = _answer("11-2024-595-DONATION-AMRANI", "Qui est le donataire ?")
    assert "Donataire" in a and "Ilyas AMRANI" in a and "fils du donateur" in a
    assert "Acquéreur" not in a and "CIN" not in a


def test_donation_valeur_declaree():
    a = _answer("11-2024-595-DONATION-AMRANI", "Quelle est la valeur déclarée du bien ?")
    assert "600.000 DHS" in a and "acte_de_donation" in a
    assert "extrait" not in a.lower() or "La valeur déclarée" in a


def test_succession_liste_heritiers():
    a = _answer("7-2025-605-SUCCESSION-ELYACOUBI", "Qui sont les héritiers désignés ?")
    for name in ("Fatima Zahra BENNANI", "Yasmine ELYACOUBI", "Adam ELYACOUBI"):
        assert name in a
    for role in ("épouse", "fille", "fils"):
        assert role in a
    assert "CIN" not in a and "acte_notoriete_successorale" in a


def test_succession_part_fatima():
    a = _answer("7-2025-605-SUCCESSION-ELYACOUBI", "Quelle est la part successorale de Fatima Zahra BENNANI ?")
    assert "1/8" in a and "épouse" in a
    assert all(x not in a for x in ("Vendeur", "Acquéreur", "Banque", "Prêteur"))


def test_procuration_mandant():
    a = _answer("4-2025-539-PROCURATION-ALAOUI", "Qui est le mandant ?")
    assert "Mandant" in a and "Hassan ALAOUI" in a
    assert all(x not in a for x in ("Vendeur", "Acquéreur", "CIN"))


def test_procuration_mandataire():
    a = _answer("4-2025-539-PROCURATION-ALAOUI", "Qui est le mandataire ?")
    assert "Mandataire" in a and "Younes ALAOUI" in a and "frère du mandant" in a
    assert a.strip() != "PARTIES :"


def test_reponse_prudente_parts_juridiques():
    a = _answer("7-2025-605-SUCCESSION-ELYACOUBI", "Les parts successorales mentionnées dans l’acte ont-elles été vérifiées juridiquement ?")
    assert "ne peut pas être déterminée" in a
    assert "validation" in a.lower() and "notaire" in a.lower()


def test_reponse_documentaire_ne_vide_pas():
    for dossier, question in [
        ("11-2024-595-DONATION-AMRANI", "Qui est le donateur ?"),
        ("7-2025-605-SUCCESSION-ELYACOUBI", "Qui sont les héritiers désignés ?"),
        ("4-2025-539-PROCURATION-ALAOUI", "Qui est le mandataire ?"),
    ]:
        a = _answer(dossier, question).strip()
        assert a not in {"Sources :", "Source :", "PARTIES :"}
