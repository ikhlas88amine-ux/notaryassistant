"""Configuration centrale de l'application, chargée depuis les variables d'environnement (.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Ollama (local uniquement - jamais de cle API cloud)
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen2.5:7b"  # petit modele demo local (CPU only) ; utiliser qwen2.5:7b en production si le materiel le permet
    ollama_embed_model: str = "nomic-embed-text"

    # Embedding par lots (POST /api/embed) : taille de lot et persistance du modele en memoire
    ollama_embed_batch_size: int = 4
    ollama_keep_alive: str = "10m"
    ollama_request_timeout: int = 180

    # Qdrant (mode embarque local par defaut - pas de Docker requis)
    qdrant_url: str = "http://localhost:6333"
    qdrant_local_path: str = "./output/qdrant_local"
    qdrant_mode: str = "embedded"  # "embedded" (fichier local) ou "server" (http://...)

    # Repertoires de donnees
    data_dir: str = "./data"
    output_dir: str = "./output"

    # SQLite metadonnees applicatives
    sqlite_path: str = "./output/app_metadata.sqlite3"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).resolve()

    @property
    def output_path(self) -> Path:
        p = Path(self.output_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def lois_dir(self) -> Path:
        return self.data_path / "lois"

    @property
    def modeles_dir(self) -> Path:
        return self.data_path / "modeles"

    @property
    def dossiers_dir(self) -> Path:
        return self.data_path / "dossiers"

    @property
    def checklists_dir(self) -> Path:
        return self.data_path / "checklists"

    # Fichier de configuration versionne des checklists documentaires metier
    # (cf. app/config/document_checklists.yaml). Chemin relatif a la racine du projet,
    # distinct de data_dir : il s'agit d'une configuration d'application, pas d'une donnee
    # de dossier, et il est donc versionne dans le depot avec le code.
    document_checklists_path_str: str = "./app/config/document_checklists.yaml"
    validation_rules_path_str: str = "./app/config/validation_rules.yaml"

    @property
    def document_checklists_path(self) -> Path:
        return Path(self.document_checklists_path_str).resolve()

    @property
    def validation_rules_path(self) -> Path:
        return Path(self.validation_rules_path_str).resolve()

    @property
    def inbox_dir(self) -> Path:
        return self.data_path / "inbox_dossiers"

    @property
    def rejected_dir(self) -> Path:
        return self.data_path / "rejected_dossiers"

    @property
    def validation_reports_dir(self) -> Path:
        p = self.output_path / "validation_reports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def audit_dir(self) -> Path:
        p = self.output_path / "audit"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def manifests_dir(self) -> Path:
        p = self.audit_dir / "manifests"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def imports_dir(self) -> Path:
        p = self.output_path / "imports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def backups_dir(self) -> Path:
        p = self.output_path / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def journal_path(self) -> Path:
        return self.output_path / "journal.jsonl"


@lru_cache
def get_settings() -> Settings:
    return Settings()
