"""Gerenciamento de configuração global do NEXUS V2.

Carrega variáveis de ambiente do arquivo `.env` (na raiz do projeto) usando
pydantic-settings. Expõe caminhos absolutos derivados da raiz do repositório
para que os módulos não dependam do diretório de trabalho atual.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz do projeto = pasta que contém `app/`, `scripts/`, `Dados Brutos/`, etc.
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Variáveis globais e chaves de API via `.env`."""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- LLM (Gemma, OpenAI-compatible) ----
    llm_base_url: str = Field(default="http://localhost:11434/v1")
    llm_api_key: str = Field(default="ollama")
    llm_model: str = Field(default="gemma")
    # Modelo alternativo acionado quando o principal está sobrecarregado (503/429).
    llm_fallback_model: str = Field(default="gemma-4-26b-a4b-it")

    # ---- Caminhos de dados (relativos à raiz, resolvidos abaixo) ----
    dados_brutos_dir: str = Field(default="Dados Brutos")
    dados_processados_dir: str = Field(default="dados_processados")

    # ---- Servidor ----
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)

    # ---- Caminhos absolutos derivados ----
    @property
    def dados_brutos(self) -> Path:
        return ROOT_DIR / self.dados_brutos_dir

    @property
    def dados_processados(self) -> Path:
        return ROOT_DIR / self.dados_processados_dir

    @property
    def nodes_csv(self) -> Path:
        return self.dados_processados / "nodes_empresas.csv"

    @property
    def edges_csv(self) -> Path:
        return self.dados_processados / "edges_socios.csv"

    @property
    def duckdb_path(self) -> Path:
        return self.dados_processados / "nexus.duckdb"


@lru_cache
def get_settings() -> Settings:
    """Instância única (cacheada) das configurações."""
    return Settings()


settings = get_settings()
