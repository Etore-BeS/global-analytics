"""Testes de env overrides."""

from __future__ import annotations

import os

from depara.api.env_overrides import apply_env_overrides, normalize_env_overrides


def test_normalize_ignores_empty_and_unknown() -> None:
    assert normalize_env_overrides(
        {"DEPARA_MODEL": "openai:gpt-4o", "OPENAI_API_KEY": "  ", "FOO": "bar"}
    ) == {"DEPARA_MODEL": "openai:gpt-4o"}


def test_apply_env_overrides_restores() -> None:
    key = "DEPARA_MAX_CONCURRENCY"
    original = os.environ.get(key)
    os.environ[key] = "99"
    try:
        with apply_env_overrides({key: "1"}):
            assert os.environ[key] == "1"
        assert os.environ[key] == "99"
    finally:
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original
