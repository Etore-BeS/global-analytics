"""Testes de env settings da UI."""

from __future__ import annotations

from depara.api.env_overrides import normalize_env_overrides
from depara.ui.env_settings import ENV_FIELDS, env_field_placeholder, load_env_defaults


def test_load_env_defaults_includes_pipeline_fields() -> None:
    defaults = load_env_defaults()
    assert "DEPARA_MODEL" in defaults
    assert "DEPARA_REANALYZE_MODEL" in defaults
    assert "DEPARA_TOP_K_CANDIDATES" in defaults
    assert "DEPARA_REANALYZE_TOP_K" in defaults


def test_env_field_placeholder_uses_defaults() -> None:
    defaults = {
        "DEPARA_MODEL": "openai:gpt-5-mini",
        "DEPARA_TOP_K_CANDIDATES": "25",
    }
    model_field = next(f for f in ENV_FIELDS if f.env_key == "DEPARA_MODEL")
    assert env_field_placeholder(model_field, defaults) == "openai:gpt-5-mini"


def test_normalize_accepts_new_pipeline_keys() -> None:
    out = normalize_env_overrides(
        {
            "DEPARA_REANALYZE_MODEL": "openai:gpt-5",
            "DEPARA_TOP_K_CANDIDATES": "25",
            "DEPARA_REANALYZE_TOP_K": "40",
        }
    )
    assert out["DEPARA_REANALYZE_MODEL"] == "openai:gpt-5"
    assert out["DEPARA_TOP_K_CANDIDATES"] == "25"
    assert out["DEPARA_REANALYZE_TOP_K"] == "40"
