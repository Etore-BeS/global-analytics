"""Testes de sanidade de preço e projeções financeiras."""

from __future__ import annotations

import pandas as pd
from depara.price_sanity import enrich_price_report, financial_projection_plausible


def test_financial_projection_plausible_compatible() -> None:
    ok, flags = financial_projection_plausible(0.775, 0.75, 0.79)
    assert ok is True
    assert flags == []


def test_financial_projection_blocked_incompatible() -> None:
    ok, flags = financial_projection_plausible(10.0, 10.0, 0.79)
    assert ok is False
    assert "preco_depara_incompativel" in flags


def test_enrich_zeros_oportunidade_when_implausible() -> None:
    df = pd.DataFrame(
        [
            {
                "linha_produto": "LINHA TEST",
                "global_custo_mediana": 10.0,
                "global_custo_ultimo": 10.0,
                "global_custo_medio": 10.0,
                "unimed_vl_medio": 0.79,
                "desc_item_unimed": "dexametasona amp 2,5 ml",
                "unimed_un": "Ampola",
                "unimed_prev_mes_qtd": 100.0,
            }
        ]
    )
    out = enrich_price_report(df)
    assert out.iloc[0]["oportunidade_mensal_rs"] == 0.0
    assert out.iloc[0]["risco_mensal_rs"] == 0.0
    assert out.iloc[0]["projecao_financeira_plausivel"] == False  # noqa: E712


def test_enrich_abaixador_plausible_oportunidade() -> None:
    df = pd.DataFrame(
        [
            {
                "linha_produto": "ABAIXADOR",
                "global_custo_mediana": 0.0845,
                "global_custo_ultimo": 0.129,
                "global_custo_medio": 0.086,
                "unimed_vl_medio": 7.09,
                "desc_item_unimed": "abaixador de lingua em madeira (pct c/100)",
                "unimed_un": "Pacote",
                "unimed_prev_mes_qtd": 59.6,
            }
        ]
    )
    out = enrich_price_report(df)
    row = out.iloc[0]
    assert row["projecao_financeira_plausivel"] == True  # noqa: E712
    assert row["unimed_vl_por_unidade"] < 0.1
    assert row["oportunidade_mensal_rs"] == 0.0
    assert row["risco_mensal_rs"] > 0
