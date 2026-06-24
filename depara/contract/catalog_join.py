"""Join global_df com BASE_LINHA_PRODUTOS para embalagem estruturada."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_base_linha_catalog(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xls", ".xlsx"}:
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path, encoding="latin-1")
    return df.rename(
        columns={
            "CODPROD": "COD_PRODUTO",
            "PRODUTO": "DESCRICAO_PRODUTO",
            "EMBALAGEM": "EMBALAGEM",
            "UNIDADE": "UNIDADE_CLINICA",
            "UNIDADE_VENDA": "UNIDADE_VENDA",
            "LINHA_PRODUTO": "LINHA_PRODUTO",
        }
    )


def enrich_purchases_with_catalog(
    purchases: pd.DataFrame,
    catalog_path: Path | None,
) -> pd.DataFrame:
    """Anexa EMBALAGEM/UNIDADE por COD_PRODUTO quando catálogo disponível."""
    if catalog_path is None or not catalog_path.exists():
        return purchases.copy()

    catalog = load_base_linha_catalog(catalog_path)
    if "COD_PRODUTO" not in purchases.columns:
        return purchases.copy()

    cat_slim = catalog.drop_duplicates(subset=["COD_PRODUTO"])[
        ["COD_PRODUTO", "EMBALAGEM", "UNIDADE_CLINICA", "UNIDADE_VENDA"]
    ]
    out = purchases.merge(cat_slim, on="COD_PRODUTO", how="left")
    if "EMBALAGEM" in out.columns:
        out["pack_description"] = out["EMBALAGEM"].fillna("")
    if "UNIDADE_CLINICA" in out.columns:
        out["clinical_unit"] = out["UNIDADE_CLINICA"]
    if "UNIDADE_VENDA" in out.columns:
        out["sale_unit"] = out["UNIDADE_VENDA"]
    return out
