"""Testes do motor de preço unitário L2."""

from __future__ import annotations

from depara.contract.unit_price import to_unit_price
from depara.price_units import parse_pack


def test_parse_pack_structured_cx() -> None:
    info = parse_pack("CX C/ 50 AP")
    assert info is not None
    assert info.pack_qty == 50
    assert info.clinical_unit == "AP"
    assert info.sale_unit == "CX"
    assert info.source == "structured"


def test_to_unit_price_per_pack() -> None:
    result = to_unit_price(
        7.09,
        pack_description="PC C/ 100 UN",
        clinical_unit="UN",
        sale_unit="PC",
    )
    assert result.price_basis == "per_pack"
    assert result.pack_qty == 100
    assert result.unit_price is not None
    assert abs(result.unit_price - 0.0709) < 0.0001


def test_to_unit_price_clinical_unit_direct() -> None:
    result = to_unit_price(0.79, pack_description="", clinical_unit="Ampola")
    assert result.unit_price == 0.79
    assert result.price_basis == "per_clinical_unit"


def test_global_custo_per_clinical_unit_not_divided_by_pack() -> None:
    """CUSTO_ENTRADA já é R$/ampola — não dividir por CX C/ 120."""
    result = to_unit_price(
        0.75,
        amount_basis="per_clinical_unit",
        pack_description="CX C/ 120 AP",
        sale_unit="CX",
    )
    assert result.unit_price == 0.75
    assert result.pack_qty == 120


def test_dexametasona_linha_mediana_with_catalog() -> None:
    from pathlib import Path

    from depara.price_sanity import linha_cost_stats

    stats = linha_cost_stats(
        "data/depara-unimed/global_df.csv",
        catalog_path=Path("data/depara-unimed/BASE_LINHA_PRODUTOS.csv"),
    )
    row = stats[
        stats.linha_produto.str.contains("DEXAMETASONA.*4MG/ML", na=False, regex=True)
    ].iloc[0]
    assert 0.5 < row.global_custo_mediana < 1.0
