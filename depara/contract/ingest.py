"""Ingest de planilhas via templates + override de colunas."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from depara.contract.catalog_join import enrich_purchases_with_catalog
from depara.contract.models import JobConfig, SideConfig
from depara.contract.templates import resolve_columns
from depara.fase1_similarity import (
    load_global_items,
    load_global_linhas,
    normalize_text,
    principio_from_linha,
)


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="latin-1")


def _normalize_global_sku_columns(df: pd.DataFrame) -> pd.DataFrame:
    renames: dict[str, str] = {}
    for src, dst in (
        ("product_code", "COD_PRODUTO"),
        ("display_text", "LINHA_PRODUTO"),
        ("product_desc", "DESCRICAO_PRODUTO"),
        ("pack_description", "EMBALAGEM"),
        ("clinical_unit", "UNIDADE"),
        ("sale_unit", "UNIDADE_VENDA"),
        ("brand", "MARCA"),
        ("cost_real", "CUSTOREAL"),
        ("cost_last_entry", "CUSTOULTENT"),
        ("stock_qty", "ESTOQUE_DISPONIVEL"),
    ):
        if src in df.columns:
            renames[src] = dst
    out = df.rename(columns=renames)
    for src, dst in (("CODPROD", "COD_PRODUTO"), ("PRODUTO", "DESCRICAO_PRODUTO")):
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    if "PRINCIPIO_ATIVO" not in out.columns and "LINHA_PRODUTO" in out.columns:
        out["PRINCIPIO_ATIVO"] = out["LINHA_PRODUTO"].map(principio_from_linha)
    if "principio_ativo" not in out.columns and "PRINCIPIO_ATIVO" in out.columns:
        out["principio_ativo"] = out["PRINCIPIO_ATIVO"]
    return out


def ingest_global_cost_stock(side: SideConfig) -> pd.DataFrame:
    """Retorna 1 linha por SKU com custo/estoque atual (snapshot)."""
    cols = resolve_columns(side.template, side.columns)
    raw = _read_table(side.path)
    rename = {v: k for k, v in cols.items() if v in raw.columns}
    df = raw.rename(columns=rename)
    return _normalize_global_sku_columns(df)


def ingest_side_b(side: SideConfig) -> pd.DataFrame:
    """Ingest genérico do catálogo de referência (Side B)."""
    return ingest_unimed_catalog(side)


def ingest_side_a(side: SideConfig) -> pd.DataFrame:
    """Ingest genérico do catálogo sujeito (Side A)."""
    return load_global_side_a(side)


def load_global_side_a(side: SideConfig) -> pd.DataFrame:
    if side.template == "global_cost_stock":
        return ingest_global_cost_stock(side)
    return ingest_global_purchases(side)


def ingest_global_purchases(side: SideConfig) -> pd.DataFrame:
    """Retorna transações enriquecidas (1 linha por entrada ou por SKU)."""
    if side.template == "global_cost_stock":
        return ingest_global_cost_stock(side)
    cols = resolve_columns(side.template, side.columns)
    raw = _read_table(side.path)
    rename = {v: k for k, v in cols.items() if v in raw.columns}
    df = raw.rename(columns=rename)
    if "product_code" in df.columns:
        df = df.rename(columns={"product_code": "COD_PRODUTO"})
    if "display_text" in df.columns:
        df = df.rename(columns={"display_text": "LINHA_PRODUTO"})
    if "price_amount" in df.columns:
        df = df.rename(columns={"price_amount": "CUSTO_ENTRADA"})
    if "principio_ativo" not in df.columns and "PRINCIPIO_ATIVO" in raw.columns:
        df["principio_ativo"] = raw["PRINCIPIO_ATIVO"]
    elif "PRINCIPIO_ATIVO" in df.columns:
        df["principio_ativo"] = df["PRINCIPIO_ATIVO"]
    if "product_desc" in df.columns:
        df = df.rename(columns={"product_desc": "DESCRICAO_PRODUTO"})
    return enrich_purchases_with_catalog(df, side.catalog_enrichment)


def ingest_unimed_catalog(side: SideConfig) -> pd.DataFrame:
    cols = resolve_columns(side.template, side.columns)
    path = str(side.path)
    if side.template == "unimed_abc" and not side.columns:
        return load_global_items(path)

    raw = _read_table(side.path)
    rename = {v: k for k, v in cols.items() if v in raw.columns}
    df = raw.rename(columns=rename)
    out = df.rename(
        columns={
            "canonical_id": "cod_item",
            "display_text": "desc_global",
            "price_amount": "vl_medio",
            "clinical_unit": "unidade",
            "volume_previsto": "prev_mes_qtd",
            "abc_class": "abc",
            "policy": "politica",
        }
    )
    from depara.price_units import enrich_catalog_prices

    out["texto_match"] = out["desc_global"].map(normalize_text)
    out["texto_spacy"] = out["desc_global"].map(
        lambda t: normalize_text(t, aggressive=False)
    )
    return enrich_catalog_prices(out)


def ingest_side_a_linhas(side: SideConfig) -> pd.DataFrame:
    if side.template == "global_purchases" and not side.columns:
        return load_global_linhas(str(side.path), template="global_purchases")
    skus = load_global_side_a(side)
    produtos = skus.drop_duplicates(subset=["COD_PRODUTO"])
    pa_col = "principio_ativo" if "principio_ativo" in produtos.columns else "PRINCIPIO_ATIVO"
    desc_col = "DESCRICAO_PRODUTO" if "DESCRICAO_PRODUTO" in produtos.columns else "product_desc"
    agg: dict = {
        "principio_ativo": (pa_col, "first"),
        "n_skus": ("COD_PRODUTO", "nunique"),
        "descricoes": (desc_col, lambda x: list(x)[:3]),
    }
    if "MARCA" in produtos.columns:
        agg["marcas"] = ("MARCA", lambda x: sorted(set(x.dropna())))
    linhas = (
        produtos.groupby("LINHA_PRODUTO", as_index=False)
        .agg(**agg)
        .rename(columns={"LINHA_PRODUTO": "linha_produto"})
    )
    if "marcas" not in linhas.columns:
        linhas["marcas"] = [[] for _ in range(len(linhas))]
    linhas["texto_match"] = linhas["linha_produto"].map(normalize_text)
    linhas["texto_spacy"] = linhas["linha_produto"].map(
        lambda t: normalize_text(t, aggressive=False)
    )
    return linhas


def apply_job_paths(config: JobConfig) -> dict[str, Path]:
    """Resolve paths principais a partir do JobConfig."""
    out_dir = config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    fase1 = config.fase1_path or out_dir / "fase1_comparison.csv"
    matches = config.matches_path or out_dir / "matches.csv"
    return {
        "output_dir": out_dir,
        "side_a_path": config.side_a.path,
        "side_b_path": config.side_b.path,
        "catalog_path": config.side_a.catalog_enrichment,
        "fase1_path": fase1,
        "matches_path": matches,
        "price_report_base": out_dir / "price_report",
    }
