"""Tests de l'endpoint securise de consultation des modeles internes (cahier des charges §5).

Refuse : '..', chemin absolu, extension non autorisee, fichier absent.
Accepte : un fichier reel sous data/modeles.
Le lien est deduplique par fichier (jamais un bouton par chunk).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_refuse_parent_directory():
    resp = client.get("/modeles/open", params={"relative_path": "modeles/../dossiers/1-2024-843-AMBIGU/01_acte_de_vente.docx"})
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert ".." in detail or "interdit" in detail


def test_refuse_chemin_absolu():
    resp = client.get("/modeles/open", params={"relative_path": "/etc/passwd"})
    assert resp.status_code == 400
    assert "absolu" in resp.json()["detail"].lower()


def test_refuse_chemin_absolu_windows_lettre_lecteur():
    resp = client.get("/modeles/open", params={"relative_path": r"C:\Windows\System32\drivers\etc\hosts"})
    assert resp.status_code == 400
    assert "absolu" in resp.json()["detail"].lower()


def test_refuse_chemin_unc_windows():
    resp = client.get("/modeles/open", params={"relative_path": r"\\serveur\partage\fichier.docx"})
    assert resp.status_code == 400
    assert "absolu" in resp.json()["detail"].lower()


def test_refuse_parent_directory_style_windows():
    resp = client.get("/modeles/open", params={"relative_path": r"..\secret.docx"})
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert ".." in detail or "interdit" in detail


def test_ordre_controle_absolu_avant_extension():
    """Un chemin absolu doit etre rejete pour 'absolu', pas pour son extension (meme sans
    extension autorisee, ex: /etc/passwd)."""
    resp = client.get("/modeles/open", params={"relative_path": "/etc/passwd"})
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "absolu" in detail
    assert "extension" not in detail


def test_refuse_extension_non_autorisee():
    resp = client.get("/modeles/open", params={"relative_path": "modeles/modeles.json"})
    assert resp.status_code == 400
    assert "extension" in resp.json()["detail"].lower()


def test_refuse_fichier_absent():
    resp = client.get("/modeles/open", params={"relative_path": "modeles/originaux/fichier-inexistant.pdf"})
    assert resp.status_code == 400
    assert "introuvable" in resp.json()["detail"].lower()


def test_accepte_fichier_reel():
    resp = client.get("/modeles/open", params={"relative_path": "modeles/originaux/immobilier/vefa.doc"})
    assert resp.status_code == 200
    assert resp.content  # le fichier est servi (lecture seule)


def test_chemin_hors_racine_refuse():
    resp = client.get("/modeles/open", params={"relative_path": "dossiers/1-2024-843-AMBIGU/01_acte_de_vente.docx"})
    assert resp.status_code == 400
