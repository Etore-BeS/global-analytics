"""Fontes de dados — Global (distribuidor) e Unimed (compras / Curva ABC)."""

from __future__ import annotations

# Global = distribuidora; preços/custos de entrada (timeseries)
GLOBAL_DISTRIBUIDOR = {
    "entidade": "Global (distribuidor)",
    "arquivo": "global_df.csv",
    "coluna_preco": "CUSTO_ENTRADA",
    "descricao": (
        "Preços da Global como distribuidora de medicamentos e materiais "
        "(histórico de entradas por SKU/marca)."
    ),
}

# Unimed = operadora; referência de compras (Curva ABC)
UNIMED_COMPRAS = {
    "entidade": "Unimed",
    "arquivo": "Curva ABC - CD 05.26.xlsx",
    "coluna_preco": "VL Médio (R$)",
    "descricao": (
        "Referência de compras/preços Unimed (Curva ABC): VL Médio, "
        "Prev Mês e classificação ABC."
    ),
}

LEGENDA_LINHAS: list[tuple[str, str]] = [
    ("Objetivo", "Comparar preço Global (distribuidor) vs preço Unimed (compras) após depara clínico."),
    ("Global — entidade", GLOBAL_DISTRIBUIDOR["entidade"]),
    ("Global — arquivo", GLOBAL_DISTRIBUIDOR["arquivo"]),
    ("Global — coluna de preço na origem", GLOBAL_DISTRIBUIDOR["coluna_preco"]),
    ("Global — significado", GLOBAL_DISTRIBUIDOR["descricao"]),
    ("Unimed — entidade", UNIMED_COMPRAS["entidade"]),
    ("Unimed — arquivo", UNIMED_COMPRAS["arquivo"]),
    ("Unimed — coluna de preço na origem", UNIMED_COMPRAS["coluna_preco"]),
    ("Unimed — significado", UNIMED_COMPRAS["descricao"]),
    (
        "Gap %",
        "Positivo = Global cobra/paga MAIS que VL Médio Unimed. "
        "Negativo = Global abaixo da referência Unimed.",
    ),
    (
        "Depara",
        "linha_clinica_global (CSV Global) → cod_item Unimed (Curva ABC). "
        "Códigos de produto NÃO são iguais entre os sistemas.",
    ),
]

# Renomeação para exportação (CSV/XLSX legível)
REPORT_EXPORT_RENAME: dict[str, str] = {
    "linha_produto": "linha_clinica_global",
    "principio_ativo": "principio_ativo",
    "marcas": "marcas_global",
    "n_skus": "qtd_skus_global",
    "n_compras": "qtd_entradas_global",
    "global_custo_ultimo": "preco_global_ultimo_r_un",
    "global_custo_medio": "preco_global_media_r_un",
    "global_custo_mediana": "preco_global_mediana_r_un",
    "global_custo_min": "preco_global_min_r_un",
    "global_custo_max": "preco_global_max_r_un",
    "global_dt_ultima_compra": "global_dt_ultima_entrada",
    "unimed_cod_item": "unimed_cod_item",
    "desc_unimed_match": "unimed_desc_depara",
    "desc_item_unimed": "unimed_desc_item",
    "unimed_un": "unimed_unidade_venda",
    "unimed_vl_medio": "preco_unimed_vl_medio_r_un",
    "unimed_vl_por_unidade": "preco_unimed_normalizado_r_un",
    "pack_qty_global": "pack_qty_global",
    "pack_qty_unimed": "pack_qty_unimed",
    "global_custo_mediana_norm": "preco_global_normalizado_r_un",
    "unimed_prev_mes_qtd": "unimed_prev_mes_qtd",
    "unimed_prev_mes_rs": "unimed_prev_mes_rs",
    "unimed_abc": "unimed_abc",
    "unimed_politica": "unimed_politica",
    "gap_global_custo_ultimo_pct": "gap_pct_ultimo_global_vs_unimed",
    "gap_global_custo_medio_pct": "gap_pct_media_global_vs_unimed",
    "gap_global_custo_mediana_pct": "gap_pct_mediana_global_vs_unimed",
    "gap_ultimo_rs": "gap_rs_ultimo_global_menos_unimed",
    "economia_potencial_rs": "economia_pot_mensal_rs_ultimo",
    "economia_potencial_mediana_rs": "economia_pot_mensal_rs_mediana",
    "oportunidade_mensal_rs": "oportunidade_mensal_rs",
    "risco_mensal_rs": "risco_mensal_rs",
    "match_source": "depara_origem",
    "match_confidence": "depara_confianca",
    "preco_depara_ok": "depara_ok_preco",
    "review_flags": "flags_revisao",
    "fonte_preco_global": "fonte_preco_global",
    "fonte_preco_unimed": "fonte_preco_unimed",
}

SKU_EXPORT_RENAME: dict[str, str] = {
    "linha_produto": "linha_clinica_global",
    "global_cod_produto": "global_cod_produto",
    "descricao_produto": "global_desc_produto",
    "marca": "global_marca",
    "principio_ativo": "principio_ativo",
    "n_compras": "qtd_entradas_global",
    "global_custo_ultimo": "preco_global_ultimo_r_un",
    "global_custo_medio": "preco_global_media_r_un",
    "global_custo_mediana": "preco_global_mediana_r_un",
    "global_custo_min": "preco_global_min_r_un",
    "global_custo_max": "preco_global_max_r_un",
    "global_dt_ultima_compra": "global_dt_ultima_entrada",
    "unimed_cod_item": "unimed_cod_item",
    "desc_unimed_match": "unimed_desc_depara",
    "desc_item_unimed": "unimed_desc_item",
    "unimed_vl_medio": "preco_unimed_vl_medio_r_un",
    "unimed_abc": "unimed_abc",
    "unimed_prev_mes_rs": "unimed_prev_mes_rs",
    "gap_ultimo_pct": "gap_pct_ultimo_global_vs_unimed",
    "gap_ultimo_rs": "gap_rs_ultimo_global_menos_unimed",
    "match_source": "depara_origem",
    "match_confidence": "depara_confianca",
    "fonte_preco_global": "fonte_preco_global",
    "fonte_preco_unimed": "fonte_preco_unimed",
}


def annotate_report_sources(df):
    """Colunas constantes indicando origem dos preços."""
    import pandas as pd

    out = df.copy()
    g = f"{GLOBAL_DISTRIBUIDOR['arquivo']} ({GLOBAL_DISTRIBUIDOR['entidade']})"
    u = f"{UNIMED_COMPRAS['arquivo']} ({UNIMED_COMPRAS['entidade']})"
    out["fonte_preco_global"] = g
    out["fonte_preco_unimed"] = u
    return out


def export_with_legend(linha: "pd.DataFrame", sku: "pd.DataFrame", xlsx_path) -> None:
    """Excel com abas legíveis + aba Legenda."""
    import pandas as pd

    linha = annotate_report_sources(linha)
    sku = annotate_report_sources(sku)

    linha_out = linha.rename(
        columns={k: v for k, v in REPORT_EXPORT_RENAME.items() if k in linha.columns}
    )
    sku_out = sku.rename(
        columns={k: v for k, v in SKU_EXPORT_RENAME.items() if k in sku.columns}
    )
    legenda = pd.DataFrame(LEGENDA_LINHAS, columns=["campo", "descricao"])

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        legenda.to_excel(writer, sheet_name="Legenda", index=False)
        linha_out.to_excel(writer, sheet_name="precos_por_linha_global", index=False)
        sku_out.to_excel(writer, sheet_name="precos_por_sku_global", index=False)


def csv_to_internal(df: "pd.DataFrame") -> "pd.DataFrame":
    """Aceita CSV com nomes legíveis ou nomes internos do pipeline."""
    inv = {v: k for k, v in REPORT_EXPORT_RENAME.items()}
    rename = {c: inv[c] for c in df.columns if c in inv}
    if rename:
        return df.rename(columns=rename)
    return df


def export_csv_readable(df, path, rename_map: dict[str, str]) -> None:
    from depara.price_sanity import format_review_flags, parse_review_flags

    out = annotate_report_sources(df)
    out = out.rename(columns={k: v for k, v in rename_map.items() if k in out.columns})
    for col in ("review_flags", "flags_revisao"):
        if col in out.columns:
            out[col] = out[col].apply(
                lambda v: format_review_flags(parse_review_flags(v))
            )
    out.to_csv(path, index=False)
