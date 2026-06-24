"""Regressão numérica contra piloto exportado."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

PILOT_REPORT = Path("exports/fase2_price_report_pilot.csv")
PILOT_MATCHES = Path("exports/fase1_pilot.csv")


@pytest.mark.skipif(not PILOT_REPORT.exists(), reason="piloto não gerado localmente")
def test_pilot_gaps_recalculate() -> None:
    pilot = pd.read_csv(PILOT_REPORT)
    for _, row in pilot.iterrows():
        med = row.get("preco_global_mediana_r_un", row.get("global_custo_mediana"))
        ref = row["preco_unimed_normalizado_r_un"]
        gap_csv = row["gap_pct_mediana_global_vs_unimed"]
        if pd.isna(med) or pd.isna(ref) or ref <= 0:
            continue
        gap_calc = round((float(med) - float(ref)) / float(ref) * 100, 1)
        assert gap_calc == gap_csv, row["linha_clinica_global"]


@pytest.mark.skipif(not PILOT_REPORT.exists(), reason="piloto não gerado localmente")
def test_pilot_oportunidade_risco() -> None:
    pilot = pd.read_csv(PILOT_REPORT)
    for _, row in pilot.iterrows():
        med = float(row.get("preco_global_mediana_r_un", 0))
        ref = float(row["preco_unimed_normalizado_r_un"])
        qtd = float(row["unimed_prev_mes_qtd"])
        oport_calc = round(max(0, ref - med) * qtd, 2)
        risco_calc = round(max(0, med - ref) * qtd, 2)
        assert oport_calc == row["oportunidade_mensal_rs"]
        assert risco_calc == row["risco_mensal_rs"]


@pytest.mark.skipif(not PILOT_REPORT.exists(), reason="piloto não gerado localmente")
def test_summary_deduplicacao() -> None:
    from depara.pipeline.summary import build_summary

    pilot = pd.read_csv(PILOT_REPORT)
    pilot_internal = pilot.rename(
        columns={
            "linha_clinica_global": "linha_produto",
            "preco_global_mediana_r_un": "global_custo_mediana",
            "preco_global_ultimo_r_un": "global_custo_ultimo",
            "preco_unimed_vl_medio_r_un": "unimed_vl_medio",
            "preco_unimed_normalizado_r_un": "unimed_vl_por_unidade",
            "depara_ok_preco": "preco_depara_ok",
        }
    )
    if not PILOT_MATCHES.exists():
        pytest.skip("fase1_pilot.csv ausente")
    summary = build_summary(
        price_report=pilot_internal,
        matches_path=PILOT_MATCHES,
        global_compras_path=Path("data/depara-unimed/global_df.csv"),
        fase1_path=Path("data/depara-unimed/fase1_comparison.csv"),
        readiness={"cobertura_pct": 0},
    )
    assert summary["oportunidade_mensal_rs_deduplicada"] <= summary["oportunidade_mensal_rs_bruto"]


@pytest.mark.skipif(not PILOT_REPORT.exists(), reason="piloto não gerado localmente")
def test_economia_ultimo_usa_preco_normalizado() -> None:
    from depara.price_sanity import enrich_price_report

    df = pd.DataFrame(
        [
            {
                "linha_produto": "ABAIXADOR TEST",
                "global_custo_ultimo": 0.0845,
                "global_custo_medio": 0.0845,
                "global_custo_mediana": 0.0845,
                "global_custo_mediana_norm": 0.0845,
                "global_custo_ultimo_norm": 0.0845,
                "unimed_vl_medio": 7.09,
                "unimed_prev_mes_qtd": 59.6,
                "desc_item_unimed": "ABAIXADOR pct c/100",
                "unimed_un": "Pacote",
            }
        ]
    )
    out = enrich_price_report(df)
    econ = float(out.iloc[0]["economia_potencial_rs"])
    assert -10 < econ < 10
