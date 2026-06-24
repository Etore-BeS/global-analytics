"""Defaults e merge de variáveis de ambiente para a UI Streamlit."""

from __future__ import annotations

from dataclasses import dataclass

from depara.api.env_overrides import normalize_env_overrides
from depara.llm.config import DeparaLLMSettings


@dataclass(frozen=True)
class EnvField:
    env_key: str
    label: str
    help_text: str
    secret: bool = False
    placeholder: str = ""


ENV_FIELDS: tuple[EnvField, ...] = (
    EnvField(
        env_key="DEPARA_MODEL",
        label="Modelo LLM (match)",
        help_text="Modelo principal do agente de depara. Ex.: openai:gpt-5-mini.",
    ),
    EnvField(
        env_key="DEPARA_REANALYZE_MODEL",
        label="Modelo reanalyze",
        help_text="Modelo usado na reanálise de preço (segunda passada). Ex.: openai:gpt-5.",
    ),
    EnvField(
        env_key="DEPARA_TOP_K_CANDIDATES",
        label="Top-K candidatos",
        help_text="Quantos candidatos Unimed enviar ao LLM por linha Global.",
    ),
    EnvField(
        env_key="DEPARA_REANALYZE_TOP_K",
        label="Top-K reanalyze",
        help_text="Limite de linhas candidatas à reanálise de preço.",
    ),
    EnvField(
        env_key="DEPARA_MAX_CONCURRENCY",
        label="Concorrência máxima (LLM)",
        help_text="Quantas linhas processar em paralelo no match LLM.",
    ),
    EnvField(
        env_key="OPENAI_API_KEY",
        label="OpenAI API Key",
        help_text="Obrigatória se algum modelo começar com openai:. "
        "Deixe vazio para usar o valor do arquivo .env.",
        secret=True,
    ),
    EnvField(
        env_key="ANTHROPIC_API_KEY",
        label="Anthropic API Key",
        help_text="Obrigatória se algum modelo começar com anthropic:. "
        "Deixe vazio para usar o valor do .env.",
        secret=True,
    ),
)


def load_env_defaults() -> dict[str, str]:
    """Valores atuais do .env / ambiente — usados como placeholder na UI."""
    settings = DeparaLLMSettings()
    defaults: dict[str, str] = {
        "DEPARA_MODEL": settings.model,
        "DEPARA_REANALYZE_MODEL": settings.reanalyze_model,
        "DEPARA_TOP_K_CANDIDATES": str(settings.top_k_candidates),
        "DEPARA_REANALYZE_TOP_K": str(settings.reanalyze_top_k),
        "DEPARA_MAX_CONCURRENCY": str(settings.max_concurrency),
        "DEPARA_MODE": settings.mode,
    }
    if settings.openai_api_key:
        defaults["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.anthropic_api_key:
        defaults["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    return defaults


def env_field_placeholder(field: EnvField, defaults: dict[str, str]) -> str:
    """Placeholder visível no campo — espelha o .env quando conhecido."""
    val = defaults.get(field.env_key, "")
    if field.secret and val:
        return mask_secret(val)
    if val:
        return val
    return field.placeholder or f"({field.env_key} não definido no .env)"


def env_default_caption(field: EnvField, defaults: dict[str, str]) -> str | None:
    """Texto auxiliar abaixo do campo quando vazio (= usa .env)."""
    val = defaults.get(field.env_key, "")
    if not val:
        return None
    if field.secret:
        return "Padrão (.env): chave configurada"
    return f"Padrão (.env): `{val}`"


def merge_env_overrides(ui_values: dict[str, str | None]) -> dict[str, str]:
    """Só envia overrides não vazios; vazio = servidor usa .env."""
    raw = {k: (v or "") for k, v in ui_values.items()}
    return normalize_env_overrides(raw)


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return value[:4] + "…" + value[-4:]
