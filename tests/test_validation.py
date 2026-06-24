"""Testes de validação de mapeamento."""

from __future__ import annotations

from pathlib import Path

from depara.contract.models import SideConfig
from depara.contract.templates import resolve_columns
from depara.contract.validation import (
    detect_granularity,
    validate_reference_side,
    validate_side_mapping,
    validate_subject_side,
)


def test_detect_granularity_sku() -> None:
    import pandas as pd

    df = pd.DataFrame(
        {
            "LINHA_PRODUTO": ["A", "A", "B"],
            "CODPROD": ["1", "2", "3"],
        }
    )
    resolved = {"display_text": "LINHA_PRODUTO", "product_code": "CODPROD"}
    assert detect_granularity(df, resolved) == "sku"


def test_validate_subject_cost_stock_valid() -> None:
    side = SideConfig(
        path=Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv"),
        template="global_cost_stock",
    )
    result = validate_subject_side(side)
    assert result.valid
    assert result.granularity == "sku"
    assert result.row_count > 0
    assert result.preview


def test_validate_reference_unimed_valid() -> None:
    side = SideConfig(
        path=Path("data/depara-unimed/Curva ABC - CD 05.26.xlsx"),
        template="unimed_abc",
    )
    result = validate_reference_side(side)
    assert result.valid
    assert result.row_count > 0


def test_validate_side_mapping_pair() -> None:
    subject = SideConfig(
        path=Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv"),
        template="global_cost_stock",
    )
    reference = SideConfig(
        path=Path("data/depara-unimed/Curva ABC - CD 05.26.xlsx"),
        template="unimed_abc",
    )
    result = validate_side_mapping(subject, reference)
    assert result.valid


def test_validate_subject_missing_column() -> None:
    side = SideConfig(
        path=Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv"),
        template="custom",
        columns={"display_text": "COLUNA_INEXISTENTE"},
    )
    result = validate_subject_side(side)
    assert not result.valid
    assert any(i.field == "display_text" for i in result.issues)


def test_effective_price_policy_dual_from_template() -> None:
    from depara.contract.validation import effective_price_policy

    side = SideConfig(
        path=Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv"),
        template="global_cost_stock",
    )
    policy = effective_price_policy(side, resolve_columns(side.template, side.columns))
    assert policy.mode == "dual"
    assert policy.primary_field == "cost_real"
