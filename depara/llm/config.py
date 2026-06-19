"""Configuração via variáveis de ambiente (teste e produção)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeparaLLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEPARA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Modelo LLM — ex: openai:gpt-5-mini, anthropic:claude-sonnet-4-5
    model: str = "openai:gpt-4o-mini"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "DEPARA_OPENAI_API_KEY"),
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "DEPARA_ANTHROPIC_API_KEY"),
    )

    # Pipeline
    top_k_candidates: int = 12
    reanalyze_model: str = "openai:gpt-4o"
    reanalyze_top_k: int = 50
    max_concurrency: int = 5
    temperature: float = 0.0

    # Paths
    global_distribuidor_path: Path = Field(
        default=Path("data/depara-unimed/global_df.csv"),
        validation_alias=AliasChoices(
            "DEPARA_GLOBAL_DISTRIBUIDOR_PATH",
            "DEPARA_UNIMED_PATH",
        ),
    )
    unimed_catalogo_path: Path = Field(
        default=Path("data/depara-unimed/Curva ABC - CD 05.26.xlsx"),
        validation_alias=AliasChoices(
            "DEPARA_UNIMED_CATALOGO_PATH",
            "DEPARA_GLOBAL_PATH",
        ),
    )
    cache_path: Path = Path("data/depara-unimed/llm_cache.sqlite")
    output_path: Path = Path("data/depara-unimed/fase1_llm_matches.csv")

    # Modo: test usa TestModel (sem API); prod usa DEPARA_MODEL
    mode: Literal["test", "prod"] = "prod"

    def ensure_dirs(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def require_api_key(self) -> None:
        if self.mode == "test":
            return
        if self.model.startswith("openai:") and not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY não encontrada. Defina no .env ou exporte no shell."
            )
        if self.model.startswith("anthropic:") and not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY não encontrada. Defina no .env ou exporte no shell."
            )

    @property
    def global_compras_path(self) -> Path:
        """Preços Global distribuidor (global_df.csv)."""
        return self.global_distribuidor_path
