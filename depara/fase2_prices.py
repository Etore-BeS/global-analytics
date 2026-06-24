"""Fase 2: preços Global (distribuidor) vs Unimed (compras / Curva ABC).

Fontes:
  global_df.csv           → Global distribuidor (CUSTO_ENTRADA)
  Curva ABC *.xlsx        → Unimed compras (VL Médio de referência)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from depara.contract.models import SideConfig
from depara.fase1_similarity import detect_global_source_mode, load_global_linhas
from depara.llm.priority import assign_confidence
from depara.price_sanity import enrich_price_report


def _is_snapshot_global(
    global_compras_path: Path,
    *,
    side: SideConfig | None = None,
) -> bool:
    if side is not None and side.template == "global_cost_stock":
        return True
    return detect_global_source_mode(str(global_compras_path)) == "global_cost_stock"


def _load_global_skus(
    global_compras_path: Path,
    *,
    side: SideConfig | None = None,
) -> pd.DataFrame:
    from depara.contract.ingest import load_global_side_a

    if side is not None:
        return load_global_side_a(side)
    if _is_snapshot_global(global_compras_path):
        return load_global_side_a(
            SideConfig(path=global_compras_path, template="global_cost_stock")
        )
    return pd.read_csv(global_compras_path, encoding="latin-1")


def build_depara(
    global_compras_path: Path,
    fase1_path: Path,
    llm_matches_path: Path,
) -> pd.DataFrame:
    """Consolida depara: linha clínica Global → cod_item Unimed (somente agente aprovado)."""
    llm = pd.read_csv(llm_matches_path)
    llm_ok = llm[llm["decision"] == "match"].copy()
    if "review_passed" in llm_ok.columns:
        llm_ok = llm_ok[llm_ok["review_passed"].fillna(True).astype(bool)]
    llm_ok["unimed_cod_item"] = pd.to_numeric(llm_ok["cod_item"], errors="coerce")
    llm_ok = llm_ok.dropna(subset=["unimed_cod_item"])
    llm_ok["unimed_cod_item"] = llm_ok["unimed_cod_item"].astype(int)
    llm_ok["linha_key"] = llm_ok["linha_produto"].str.strip()
    depara = llm_ok[
        ["linha_key", "linha_produto", "unimed_cod_item", "desc_global", "confidence", "model"]
    ].rename(
        columns={
            "desc_global": "desc_unimed_match",
            "confidence": "match_confidence",
            "model": "match_model",
        }
    )
    depara["match_source"] = "agent"

    return depara.drop_duplicates(subset=["linha_key"], keep="first")


def _global_compra_linha_stats(
    global_compras_path: Path,
    *,
    catalog_path: Path | None = None,
    side: SideConfig | None = None,
) -> pd.DataFrame:
    """Estatísticas de custo por linha clínica Global (R$/unidade L2 quando catálogo disponível)."""
    from depara.price_sanity import linha_cost_stats

    stats = linha_cost_stats(
        global_compras_path, catalog_path=catalog_path, side=side
    )
    if _is_snapshot_global(global_compras_path, side=side):
        raw = _load_global_skus(global_compras_path, side=side)
        raw["linha_key"] = raw["LINHA_PRODUTO"].str.strip()
        pa_col = "principio_ativo" if "principio_ativo" in raw.columns else "PRINCIPIO_ATIVO"
        meta = raw.groupby("linha_key", as_index=False).agg(
            principio_ativo=(pa_col, "first"),
            marcas=("MARCA", lambda x: sorted(set(x.dropna()))),
        )
        return stats.merge(meta, on="linha_key", how="left")

    raw = pd.read_csv(global_compras_path, encoding="latin-1")
    raw["linha_key"] = raw["LINHA_PRODUTO"].str.strip()
    meta = raw.groupby("linha_key", as_index=False).agg(
        principio_ativo=("PRINCIPIO_ATIVO", "first"),
        n_skus=("COD_PRODUTO", "nunique"),
        marcas=("MARCA", lambda x: sorted(set(x.dropna()))),
        n_compras=("CUSTO_ENTRADA", "count"),
    )
    raw["DT_ENTRADA"] = pd.to_datetime(raw["DT_ENTRADA"])
    dates = (
        raw.sort_values("DT_ENTRADA")
        .groupby("linha_key", as_index=False)
        .agg(global_dt_ultima_compra=("DT_ENTRADA", "last"))
    )
    return stats.merge(meta, on="linha_key").merge(dates, on="linha_key")


def _global_compra_sku_stats(
    global_compras_path: Path,
    *,
    side: SideConfig | None = None,
) -> pd.DataFrame:
    if _is_snapshot_global(global_compras_path, side=side):
        raw = _load_global_skus(global_compras_path, side=side)
        raw["linha_key"] = raw["LINHA_PRODUTO"].str.strip()
        pa_col = "principio_ativo" if "principio_ativo" in raw.columns else "PRINCIPIO_ATIVO"
        return (
            raw.rename(columns={"COD_PRODUTO": "global_cod_produto"})
            .assign(
                descricao_produto=raw["DESCRICAO_PRODUTO"],
                marca=raw["MARCA"],
                principio_ativo=raw[pa_col],
                global_custo_ultimo=raw["CUSTOULTENT"],
                global_custo_medio=raw["CUSTOREAL"],
                global_custo_mediana=raw["CUSTOREAL"],
                global_custo_min=raw["CUSTOREAL"],
                global_custo_max=raw["CUSTOREAL"],
            )[
                [
                    "linha_key",
                    "LINHA_PRODUTO",
                    "global_cod_produto",
                    "descricao_produto",
                    "marca",
                    "principio_ativo",
                    "global_custo_ultimo",
                    "global_custo_medio",
                    "global_custo_mediana",
                    "global_custo_min",
                    "global_custo_max",
                    "ESTOQUE_DISPONIVEL",
                ]
            ]
            .rename(columns={"LINHA_PRODUTO": "linha_produto"})
        )

    raw = pd.read_csv(global_compras_path, encoding="latin-1")
    raw["DT_ENTRADA"] = pd.to_datetime(raw["DT_ENTRADA"])
    raw["linha_key"] = raw["LINHA_PRODUTO"].str.strip()
    raw = raw.sort_values("DT_ENTRADA")

    return (
        raw.groupby(["linha_key", "COD_PRODUTO"], as_index=False)
        .agg(
            linha_produto=("LINHA_PRODUTO", "first"),
            descricao_produto=("DESCRICAO_PRODUTO", "first"),
            marca=("MARCA", "first"),
            principio_ativo=("PRINCIPIO_ATIVO", "first"),
            n_compras=("CUSTO_ENTRADA", "count"),
            global_custo_ultimo=("CUSTO_ENTRADA", "last"),
            global_dt_ultima_compra=("DT_ENTRADA", "last"),
            global_custo_medio=("CUSTO_ENTRADA", "mean"),
            global_custo_mediana=("CUSTO_ENTRADA", "median"),
            global_custo_min=("CUSTO_ENTRADA", "min"),
            global_custo_max=("CUSTO_ENTRADA", "max"),
        )
        .rename(columns={"COD_PRODUTO": "global_cod_produto"})
    )


def _unimed_catalog_prices(unimed_catalog_path: Path) -> pd.DataFrame:
    """Preços de referência Unimed (Curva ABC)."""
    catalog = pd.read_excel(unimed_catalog_path)
    return catalog.rename(
        columns={
            "Cod Item": "unimed_cod_item",
            "Desc Item": "desc_item_unimed",
            "Un": "unimed_un",
            "VL Médio (R$)": "unimed_vl_medio",
            "Prev Mês": "unimed_prev_mes_qtd",
            "Prev Mês (R$)": "unimed_prev_mes_rs",
            "ABC": "unimed_abc",
            "Política": "unimed_politica",
        }
    )[
        [
            "unimed_cod_item",
            "desc_item_unimed",
            "unimed_un",
            "unimed_vl_medio",
            "unimed_prev_mes_qtd",
            "unimed_prev_mes_rs",
            "unimed_abc",
            "unimed_politica",
        ]
    ]


def _gap_pct(global_price: pd.Series, unimed_ref: pd.Series) -> pd.Series:
    """Positivo = Global paga mais que referência Unimed."""
    return ((global_price - unimed_ref) / unimed_ref * 100).round(1)


def build_price_report_linha(
    global_compras_path: Path,
    unimed_catalog_path: Path,
    fase1_path: Path,
    llm_matches_path: Path,
    *,
    catalog_path: Path | None = None,
    side: SideConfig | None = None,
) -> pd.DataFrame:
    """Relatório por linha clínica Global vs preço referência Unimed."""
    depara = build_depara(global_compras_path, fase1_path, llm_matches_path)
    linha = _global_compra_linha_stats(
        global_compras_path, catalog_path=catalog_path, side=side
    )
    unimed_p = _unimed_catalog_prices(unimed_catalog_path)

    report = depara.merge(linha, on="linha_key", how="left", suffixes=("", "_linha"))
    if "linha_produto_linha" in report.columns:
        report["linha_produto"] = report["linha_produto"].fillna(report["linha_produto_linha"])
        report = report.drop(columns=["linha_produto_linha"])
    report = report.merge(unimed_p, on="unimed_cod_item", how="left")
    report["global_custo_mediana_norm"] = report["global_custo_mediana"]
    report["global_custo_ultimo_norm"] = report["global_custo_ultimo"]
    report["global_custo_medio_norm"] = report["global_custo_medio"]

    for col in ("global_custo_ultimo", "global_custo_medio", "global_custo_mediana"):
        report[f"gap_{col}_pct"] = _gap_pct(report[col], report["unimed_vl_medio"])

    report["gap_ultimo_rs"] = (
        report["global_custo_ultimo"] - report["unimed_vl_medio"]
    ).round(4)
    report["economia_potencial_rs"] = (
        (report["global_custo_ultimo"] - report["unimed_vl_medio"])
        * report["unimed_prev_mes_qtd"]
    ).round(2)

    cols = [
        "linha_produto",
        "principio_ativo",
        "marcas",
        "n_skus",
        "n_compras",
        "global_custo_ultimo",
        "global_custo_medio",
        "global_custo_mediana",
        "global_custo_min",
        "global_custo_max",
        "global_dt_ultima_compra",
        "unimed_cod_item",
        "desc_unimed_match",
        "desc_item_unimed",
        "unimed_un",
        "unimed_vl_medio",
        "unimed_prev_mes_qtd",
        "unimed_prev_mes_rs",
        "unimed_abc",
        "unimed_politica",
        "gap_global_custo_ultimo_pct",
        "gap_global_custo_medio_pct",
        "gap_global_custo_mediana_pct",
        "gap_ultimo_rs",
        "economia_potencial_rs",
        "match_source",
        "match_confidence",
    ]
    report = report[[c for c in cols if c in report.columns]].sort_values(
        "unimed_prev_mes_rs", ascending=False, na_position="last"
    )
    enriched = enrich_price_report(report)
    extra = [
        "unimed_vl_por_unidade",
        "pack_qty_global",
        "pack_qty_unimed",
        "global_custo_mediana_norm",
        "economia_potencial_mediana_rs",
        "oportunidade_mensal_rs",
        "risco_mensal_rs",
        "preco_depara_ok",
        "projecao_financeira_plausivel",
        "review_flags",
    ]
    return enriched[[c for c in list(report.columns) + extra if c in enriched.columns]]


def build_price_report_sku(
    global_compras_path: Path,
    unimed_catalog_path: Path,
    fase1_path: Path,
    llm_matches_path: Path,
    *,
    side: SideConfig | None = None,
) -> pd.DataFrame:
    """Detalhe por COD_PRODUTO/marca Global vs referência Unimed."""
    depara = build_depara(global_compras_path, fase1_path, llm_matches_path)
    sku = _global_compra_sku_stats(global_compras_path, side=side)
    unimed_p = _unimed_catalog_prices(unimed_catalog_path)

    depara_slim = depara[
        ["linha_key", "unimed_cod_item", "desc_unimed_match", "match_source", "match_confidence"]
    ]
    report = sku.merge(depara_slim, on="linha_key", how="inner")
    report = report.merge(unimed_p, on="unimed_cod_item", how="left")

    report["gap_ultimo_pct"] = _gap_pct(report["global_custo_ultimo"], report["unimed_vl_medio"])
    report["gap_ultimo_rs"] = (
        report["global_custo_ultimo"] - report["unimed_vl_medio"]
    ).round(4)

    cols = [
        "linha_produto",
        "global_cod_produto",
        "descricao_produto",
        "marca",
        "principio_ativo",
        "n_compras",
        "global_custo_ultimo",
        "global_custo_medio",
        "global_custo_mediana",
        "global_custo_min",
        "global_custo_max",
        "global_dt_ultima_compra",
        "unimed_cod_item",
        "desc_unimed_match",
        "desc_item_unimed",
        "unimed_un",
        "unimed_vl_medio",
        "unimed_abc",
        "unimed_prev_mes_rs",
        "gap_ultimo_pct",
        "gap_ultimo_rs",
        "match_source",
        "match_confidence",
    ]
    return report[[c for c in cols if c in report.columns]].sort_values(
        ["unimed_prev_mes_rs", "linha_produto", "marca"],
        ascending=[False, True, True],
        na_position="last",
    )


def export_price_report(
    global_compras_path: Path,
    unimed_catalog_path: Path,
    fase1_path: Path,
    llm_matches_path: Path,
    output_path: Path,
    *,
    catalog_path: Path | None = None,
    side: SideConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    linha = build_price_report_linha(
        global_compras_path,
        unimed_catalog_path,
        fase1_path,
        llm_matches_path,
        catalog_path=catalog_path,
        side=side,
    )
    sku = build_price_report_sku(
        global_compras_path,
        unimed_catalog_path,
        fase1_path,
        llm_matches_path,
        side=side,
    )

    from depara.sources import (
        REPORT_EXPORT_RENAME,
        SKU_EXPORT_RENAME,
        export_csv_readable,
        export_with_legend,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_csv_readable(linha, output_path.with_suffix(".csv"), REPORT_EXPORT_RENAME)
    export_csv_readable(sku, output_path.parent / "fase2_price_sku.csv", SKU_EXPORT_RENAME)

    export_with_legend(linha, sku, output_path.with_suffix(".xlsx"))

    return linha, sku


def readiness_summary(
    global_compras_path: Path,
    fase1_path: Path,
    llm_matches_path: Path,
    *,
    side: SideConfig | None = None,
) -> dict:
    template = side.template if side is not None else None
    u = load_global_linhas(str(global_compras_path), template=template)
    all_linhas = set(u["linha_produto"].str.strip())

    fase1 = pd.read_csv(fase1_path)
    if "confianca" not in fase1.columns:
        fase1["confianca"] = fase1.apply(assign_confidence, axis=1)

    llm = pd.read_csv(llm_matches_path)
    llm_linhas = set(llm["linha_produto"].str.strip())
    missing = all_linhas - llm_linhas

    depara = build_depara(global_compras_path, fase1_path, llm_matches_path)
    reviewed_match = int((llm["decision"] == "match").sum())
    if "review_passed" in llm.columns:
        reviewed_match = int(
            ((llm["decision"] == "match") & llm["review_passed"].fillna(True)).sum()
        )
    return {
        "total_linhas_global": len(all_linhas),
        "llm_processadas": len(llm_linhas),
        "depara_consolidado": len(depara),
        "cobertura_pct": round(len(depara) / len(all_linhas) * 100, 1),
        "sem_depara": len(all_linhas) - len(depara),
        "faltando_processar": len(missing),
        "llm_match": reviewed_match,
        "llm_no_match": int((llm["decision"] == "no_match").sum()),
    }
