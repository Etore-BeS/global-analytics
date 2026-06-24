"""Gera summary.json com totais deduplicados."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from depara.fase2_prices import readiness_summary


def build_summary(
    *,
    price_report: pd.DataFrame,
    matches_path: Path,
    global_compras_path: Path,
    fase1_path: Path,
    readiness: dict | None = None,
) -> dict:
    readiness = readiness or readiness_summary(global_compras_path, fase1_path, matches_path)

    dedup = price_report.groupby("unimed_cod_item", as_index=False).agg(
        oportunidade_mensal_rs=("oportunidade_mensal_rs", "max"),
        risco_mensal_rs=("risco_mensal_rs", "max"),
    )
    plausible = price_report
    if "projecao_financeira_plausivel" in price_report.columns:
        plausible = price_report[price_report["projecao_financeira_plausivel"]]
        dedup_plaus = plausible.groupby("unimed_cod_item", as_index=False).agg(
            oportunidade_mensal_rs=("oportunidade_mensal_rs", "max"),
            risco_mensal_rs=("risco_mensal_rs", "max"),
        )
    else:
        dedup_plaus = dedup
    return {
        **readiness,
        "report_linhas": len(price_report),
        "report_linhas_projecao_plausivel": len(plausible),
        "oportunidade_mensal_rs_bruto": round(
            float(price_report["oportunidade_mensal_rs"].sum()), 2
        ),
        "risco_mensal_rs_bruto": round(float(price_report["risco_mensal_rs"].sum()), 2),
        "oportunidade_mensal_rs_plausivel": round(
            float(plausible["oportunidade_mensal_rs"].sum()), 2
        ),
        "risco_mensal_rs_plausivel": round(float(plausible["risco_mensal_rs"].sum()), 2),
        "oportunidade_mensal_rs_deduplicada": round(
            float(dedup["oportunidade_mensal_rs"].sum()), 2
        ),
        "risco_mensal_rs_deduplicado": round(float(dedup["risco_mensal_rs"].sum()), 2),
        "oportunidade_mensal_rs_deduplicada_plausivel": round(
            float(dedup_plaus["oportunidade_mensal_rs"].sum()), 2
        ),
        "risco_mensal_rs_deduplicado_plausivel": round(
            float(dedup_plaus["risco_mensal_rs"].sum()), 2
        ),
        "depara_ok_preco_true": int((price_report["preco_depara_ok"] == True).sum()),  # noqa: E712
        "depara_ok_preco_false": int((price_report["preco_depara_ok"] == False).sum()),  # noqa: E712
    }


def write_summary(path: Path, summary: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
