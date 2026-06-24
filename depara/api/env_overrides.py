"""Aplica overrides de env vars por job (ex.: valores vindos do Streamlit)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

# Chaves aceitas no JSON do job; vazio = manter valor do .env / ambiente.
ENV_OVERRIDE_KEYS = frozenset(
    {
        "DEPARA_MODEL",
        "DEPARA_REANALYZE_MODEL",
        "DEPARA_TOP_K_CANDIDATES",
        "DEPARA_REANALYZE_TOP_K",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEPARA_MAX_CONCURRENCY",
        "DEPARA_MODE",
    }
)


def normalize_env_overrides(raw: dict[str, str] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key not in ENV_OVERRIDE_KEYS:
            continue
        if value is None:
            continue
        stripped = str(value).strip()
        if stripped:
            out[key] = stripped
    return out


@contextmanager
def apply_env_overrides(overrides: dict[str, str] | None) -> Iterator[None]:
    """Sobrescreve env vars no thread atual; restaura ao sair."""
    effective = normalize_env_overrides(overrides)
    if not effective:
        yield
        return
    previous = {k: os.environ.get(k) for k in effective}
    try:
        os.environ.update(effective)
        yield
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
