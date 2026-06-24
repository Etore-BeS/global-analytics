"""Sanidade de preço no depara e nos relatórios fase 2."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd
from depara.contract.unit_price import to_unit_price
from depara.price_units import infer_pack_qty, vl_por_unidade

INTERNAL_COL = {
    "cost_real": "CUSTOREAL",
    "cost_last_entry": "CUSTOULTENT",
    "stock_qty": "ESTOQUE_DISPONIVEL",
    "price_amount": "CUSTO_ENTRADA",
    "display_text": "LINHA_PRODUTO",
    "product_code": "COD_PRODUTO",
}

DEFAULT_MAX_PRICE_RATIO = 4.0
OUTLIER_ULTIMO_VS_MEDIANA = 3.0


def _internal_col(canonical: str, df: pd.DataFrame) -> str:
    internal = INTERNAL_COL.get(canonical, canonical)
    if internal in df.columns:
        return internal
    if canonical in df.columns:
        return canonical
    return internal


def _eligible_snapshot_rows(
    df: pd.DataFrame,
    *,
    cost_col: str = "CUSTOREAL",
    stock_col: str = "ESTOQUE_DISPONIVEL",
    stock_min: float = 1,
) -> pd.DataFrame:
    """Pool por linha: SKUs com estoque e custo > 0; fallback custo > 0."""
    work = df.copy()
    display_col = _internal_col("display_text", work)
    work["linha_key"] = work[display_col].str.strip()
    cost_col = _internal_col(cost_col, work) if cost_col not in work.columns else cost_col
    stock_col = _internal_col(stock_col, work) if stock_col not in work.columns else stock_col

    def pick_pool(g: pd.DataFrame) -> pd.DataFrame:
        has_stock = stock_col in g.columns
        if has_stock:
            in_stock = g[(g[stock_col].fillna(0) >= stock_min) & (g[cost_col].fillna(0) > 0)]
            if len(in_stock) > 0:
                return in_stock
        return g[g[cost_col].fillna(0) > 0]

    return work.groupby("linha_key", group_keys=False).apply(pick_pool, include_groups=False)


def parse_review_flags(val: object) -> list[str]:
    """Normaliza flags de revisão (CSV vazio → NaN → str 'nan' não conta)."""
    if val is None:
        return []
    try:
        if pd.isna(val):
            return []
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return []
    return [
        f.strip()
        for f in s.split(",")
        if f.strip() and f.strip().lower() != "nan"
    ]


def format_review_flags(flags: list[str]) -> str:
    return ",".join(dict.fromkeys(flags))


def has_review_flags(val: object) -> bool:
    return bool(parse_review_flags(val))


def price_ratio(global_cost: float, unimed_vl: float) -> float | None:
    if pd.isna(global_cost) or pd.isna(unimed_vl) or unimed_vl <= 0 or global_cost <= 0:
        return None
    return float(global_cost / unimed_vl)


def prices_compatible(
    global_cost: float,
    unimed_vl: float,
    *,
    max_ratio: float = DEFAULT_MAX_PRICE_RATIO,
) -> bool:
    ratio = price_ratio(global_cost, unimed_vl)
    if ratio is None:
        return True
    return (1.0 / max_ratio) <= ratio <= max_ratio


def price_proximity_score(
    global_cost: float,
    unimed_vl: float,
    *,
    max_ratio: float = DEFAULT_MAX_PRICE_RATIO,
) -> float:
    """1.0 = preços alinhados; decai até 0 quando ratio excede max_ratio."""
    ratio = price_ratio(global_cost, unimed_vl)
    if ratio is None:
        return 0.5
    if ratio < 1:
        ratio = 1 / ratio
    if ratio <= 1:
        return 1.0
    if ratio >= max_ratio:
        return 0.0
    return 1.0 - (ratio - 1) / (max_ratio - 1)


def _unit_price_row(
    row: pd.Series,
    amount: float,
    *,
    amount_basis: Literal["per_clinical_unit", "per_pack", "auto"],
) -> tuple[float | None, int, bool]:
    pack_desc = row.get("EMBALAGEM") or row.get("pack_description")
    up = to_unit_price(
        amount,
        amount_basis=amount_basis,
        pack_description=str(pack_desc) if pd.notna(pack_desc) else None,
        clinical_unit=str(row.get("UNIDADE") or row.get("clinical_unit") or "")
        if pd.notna(row.get("UNIDADE") or row.get("clinical_unit"))
        else None,
        sale_unit=str(row.get("UNIDADE_VENDA") or row.get("sale_unit") or "")
        if pd.notna(row.get("UNIDADE_VENDA") or row.get("sale_unit"))
        else None,
        display_text=str(row.get("DESCRICAO_PRODUTO", "")),
    )
    return up.unit_price, up.pack_qty, up.pack_inferred_low_confidence


def linha_cost_stats_from_skus(
    df: pd.DataFrame,
    *,
    amount_basis: Literal["per_clinical_unit", "per_pack", "auto"] = "per_clinical_unit",
    side: object | None = None,
) -> pd.DataFrame:
    """Custos Global por linha clínica a partir de snapshot custo/estoque (1 linha/SKU)."""
    from depara.contract.templates import resolve_columns
    from depara.contract.validation import effective_price_policy

    policy = effective_price_policy(
        side,
        resolve_columns(getattr(side, "template", "custom"), getattr(side, "columns", {})),
    ) if side is not None else None

    cost_col = "cost_real"
    ult_col = "cost_last_entry"
    stock_col = "stock_qty"
    stock_min = 1.0
    if policy is not None:
        cost_col = policy.primary_field
        ult_col = policy.secondary_field or "cost_last_entry"
        if policy.stock_filter:
            stock_col = policy.stock_filter.column
            stock_min = policy.stock_filter.min

    pool = _eligible_snapshot_rows(
        df, cost_col=cost_col, stock_col=stock_col, stock_min=stock_min
    )
    if pool.empty:
        return pd.DataFrame()

    display_col = _internal_col("display_text", df)
    product_col = _internal_col("product_code", df)
    cost_internal = _internal_col(cost_col, df)
    ult_internal = _internal_col(ult_col, df)

    if "linha_key" not in pool.columns:
        pool = pool.copy()
        pool["linha_key"] = pool[display_col].str.strip()

    real_prices: list[float | None] = []
    ult_prices: list[float | None] = []
    pack_qtys: list[int] = []
    pack_low_conf: list[bool] = []
    for _, row in pool.iterrows():
        real, pq, low = _unit_price_row(
            row, float(row[cost_internal]), amount_basis=amount_basis
        )
        real_prices.append(real)
        pack_qtys.append(pq)
        pack_low_conf.append(low)
        ult = float(row[ult_internal]) if pd.notna(row.get(ult_internal)) else 0.0
        if ult > 0:
            ult_norm, _, _ = _unit_price_row(row, ult, amount_basis=amount_basis)
            ult_prices.append(ult_norm)
        else:
            ult_prices.append(None)

    pool = pool.copy()
    pool["custo_real_unidade"] = real_prices
    pool["custo_ultimo_unidade"] = ult_prices
    pool["pack_qty_global"] = pack_qtys
    pool["pack_inferred_low_confidence"] = pack_low_conf

    all_skus = df.copy()
    all_skus["linha_key"] = all_skus[display_col].str.strip()
    n_skus = all_skus.groupby("linha_key", as_index=False).agg(
        n_skus=(product_col, "nunique"),
    )
    n_stock = pool.groupby("linha_key", as_index=False).agg(
        n_skus_com_estoque=(product_col, "nunique"),
    )

    stats = (
        pool.groupby("linha_key", as_index=False)
        .agg(
            linha_produto=(display_col, "first"),
            global_custo_min=("custo_real_unidade", "min"),
            global_custo_mediana=("custo_real_unidade", "median"),
            global_custo_medio=("custo_real_unidade", "mean"),
            global_custo_max=("custo_real_unidade", "max"),
            global_custo_ultimo=("custo_ultimo_unidade", "min"),
            pack_qty_global=("pack_qty_global", "median"),
            pack_inferred_low_confidence=("pack_inferred_low_confidence", "max"),
        )
        .merge(n_skus, on="linha_key", how="left")
        .merge(n_stock, on="linha_key", how="left")
    )
    return stats


def linha_cost_stats(
    compras_path: str | pd.PathLike,
    *,
    catalog_path: Path | None = None,
    side: object | None = None,
    amount_basis: Literal["per_clinical_unit", "per_pack", "auto"] = "per_clinical_unit",
) -> pd.DataFrame:
    """Custos Global por linha clínica (R$/unidade L2).

    Suporta histórico de compras (CUSTO_ENTRADA) ou snapshot custo/estoque (CUSTOREAL).
    """
    from depara.contract.models import SideConfig

    if side is not None and getattr(side, "template", None) == "global_cost_stock":
        from depara.contract.ingest import load_global_side_a

        df = load_global_side_a(side)
        return linha_cost_stats_from_skus(df, amount_basis=amount_basis, side=side)

    headers = pd.read_csv(compras_path, encoding="latin-1", nrows=0).columns
    if "CUSTOREAL" in headers:
        from depara.contract.ingest import load_global_side_a

        df = load_global_side_a(
            SideConfig(path=Path(compras_path), template="global_cost_stock")
        )
        return linha_cost_stats_from_skus(df, amount_basis=amount_basis)

    from depara.contract.catalog_join import enrich_purchases_with_catalog

    raw = pd.read_csv(compras_path, encoding="latin-1")
    if catalog_path is not None:
        raw = enrich_purchases_with_catalog(raw, catalog_path)

    raw["linha_key"] = raw["LINHA_PRODUTO"].str.strip()
    raw = raw.sort_values("DT_ENTRADA")
    positive = raw[raw["CUSTO_ENTRADA"] > 0].copy()

    unit_prices: list[float | None] = []
    pack_qtys: list[int] = []
    pack_low_conf: list[bool] = []
    for _, row in positive.iterrows():
        pack_desc = row.get("pack_description") or row.get("EMBALAGEM")
        up = to_unit_price(
            float(row["CUSTO_ENTRADA"]),
            amount_basis=amount_basis,
            pack_description=str(pack_desc) if pd.notna(pack_desc) else None,
            clinical_unit=str(row.get("clinical_unit") or row.get("UNIDADE_CLINICA") or "")
            if pd.notna(row.get("clinical_unit") or row.get("UNIDADE_CLINICA"))
            else None,
            sale_unit=str(row.get("sale_unit") or row.get("UNIDADE_VENDA") or "")
            if pd.notna(row.get("sale_unit") or row.get("UNIDADE_VENDA"))
            else None,
            display_text=str(row.get("DESCRICAO_PRODUTO", "")),
        )
        unit_prices.append(up.unit_price)
        pack_qtys.append(up.pack_qty)
        pack_low_conf.append(up.pack_inferred_low_confidence)

    positive["custo_por_unidade"] = unit_prices
    positive["pack_qty_global"] = pack_qtys
    positive["pack_inferred_low_confidence"] = pack_low_conf

    return (
        positive.groupby("linha_key", as_index=False)
        .agg(
            linha_produto=("LINHA_PRODUTO", "first"),
            global_custo_mediana=("custo_por_unidade", "median"),
            global_custo_medio=("custo_por_unidade", "mean"),
            global_custo_ultimo=("custo_por_unidade", "last"),
            global_custo_min=("custo_por_unidade", "min"),
            global_custo_max=("custo_por_unidade", "max"),
            pack_qty_global=("pack_qty_global", "median"),
            pack_inferred_low_confidence=("pack_inferred_low_confidence", "max"),
        )
    )


def effective_ref_price(
    unimed_vl: float,
    descricao: str | None = None,
    unidade: str | None = None,
    *,
    pack_description: str | None = None,
) -> float:
    """Preço Unimed comparável à unidade clínica L2 (VL Médio pode ser por embalagem)."""
    if descricao:
        vpu = vl_por_unidade(unimed_vl, descricao, unidade)
        if vpu is not None and vpu > 0:
            return vpu
    if pack_description:
        up = to_unit_price(
            unimed_vl,
            amount_basis="auto",
            pack_description=pack_description,
            clinical_unit=unidade,
            display_text=descricao,
        )
        if up.unit_price is not None and up.unit_price > 0:
            return up.unit_price
    return unimed_vl


def financial_projection_plausible(
    global_mediana: float,
    global_ultimo: float,
    unimed_ref: float,
    *,
    max_ratio: float = DEFAULT_MAX_PRICE_RATIO,
) -> tuple[bool, list[str]]:
    """Indica se oportunidade/risco podem ser somados sem distorção."""
    flags: list[str] = []
    if unimed_ref <= 0:
        flags.append("preco_unimed_indisponivel")
        return False, flags
    if global_mediana <= 0 and global_ultimo <= 0:
        flags.append("preco_global_indisponivel")
        return False, flags
    ref_global = global_mediana if global_mediana > 0 else global_ultimo
    if not prices_compatible(ref_global, unimed_ref, max_ratio=max_ratio):
        flags.append("preco_depara_incompativel")
        return False, flags
    if global_ultimo > 0 and global_mediana > 0:
        if global_ultimo / global_mediana >= OUTLIER_ULTIMO_VS_MEDIANA:
            if not prices_compatible(global_ultimo, unimed_ref, max_ratio=max_ratio):
                flags.append("projecao_financeira_bloqueada")
                return False, flags
    return True, flags


def unimed_pack_qty(descricao: str | None, unidade: str | None) -> int:
    if not descricao:
        return 1
    qty = infer_pack_qty(descricao, unidade)
    return max(qty, 1)


def depara_price_flags(
    global_mediana: float,
    global_ultimo: float,
    unimed_vl: float,
    *,
    max_ratio: float = DEFAULT_MAX_PRICE_RATIO,
    unimed_desc: str | None = None,
    unimed_unidade: str | None = None,
) -> list[str]:
    ref = effective_ref_price(unimed_vl, unimed_desc, unimed_unidade)
    flags: list[str] = []
    if ref > 0 and global_mediana > 0 and not prices_compatible(
        global_mediana, ref, max_ratio=max_ratio
    ):
        flags.append("preco_depara_incompativel")
    if (
        global_ultimo > 0
        and global_mediana > 0
        and global_ultimo / global_mediana >= OUTLIER_ULTIMO_VS_MEDIANA
    ):
        flags.append("outlier_custo_ultimo")
    if global_ultimo > 0 and ref > 0:
        ultimo_ratio = price_ratio(global_ultimo, ref)
        if ultimo_ratio is not None and ultimo_ratio > max_ratio:
            mediana_ratio = price_ratio(global_mediana, ref) if global_mediana > 0 else None
            if mediana_ratio is not None and mediana_ratio <= max_ratio:
                flags.append("gap_inflado_por_outlier")
    return flags


def _gap_pct_series(global_price: pd.Series, ref: pd.Series) -> pd.Series:
    """Positivo = Global acima da referência Unimed (por unidade)."""
    return ((global_price - ref) / ref * 100).where(ref > 0).round(1)


def enrich_price_report(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza refs. bilateral, recalcula gaps e métricas de oportunidade/risco."""
    out = df.copy()

    out["pack_qty_unimed"] = out.apply(
        lambda r: unimed_pack_qty(
            str(r.get("desc_item_unimed") or r.get("desc_unimed_match") or ""),
            str(r.get("unimed_un", "")) if pd.notna(r.get("unimed_un")) else None,
        ),
        axis=1,
    )
    if "pack_qty_global" not in out.columns:
        out["pack_qty_global"] = 1

    out["unimed_vl_por_unidade"] = out.apply(
        lambda r: effective_ref_price(
            float(r["unimed_vl_medio"] or 0),
            str(r.get("desc_item_unimed") or r.get("desc_unimed_match") or ""),
            str(r.get("unimed_un", "")) if pd.notna(r.get("unimed_un")) else None,
        ),
        axis=1,
    )
    if "global_custo_mediana_norm" not in out.columns:
        out["global_custo_mediana_norm"] = out["global_custo_mediana"]
    if "global_custo_ultimo_norm" not in out.columns:
        out["global_custo_ultimo_norm"] = out["global_custo_ultimo"]

    ref = out["unimed_vl_por_unidade"]
    mediana = out["global_custo_mediana_norm"]
    ultimo = out["global_custo_ultimo_norm"]
    medio = (
        out["global_custo_medio_norm"]
        if "global_custo_medio_norm" in out.columns
        else out["global_custo_medio"]
    )
    ref_global = (
        out["global_custo_min"]
        if "global_custo_min" in out.columns
        else mediana
    )
    ref_global = ref_global.where(ref_global.fillna(0) > 0, mediana)

    for col, src in (
        ("global_custo_ultimo", ultimo),
        ("global_custo_medio", medio),
        ("global_custo_mediana", mediana),
    ):
        out[f"gap_{col}_pct"] = _gap_pct_series(src, ref)

    out["gap_ultimo_rs"] = (ultimo - ref).round(4)
    out["economia_potencial_rs"] = ((ultimo - ref) * out["unimed_prev_mes_qtd"]).round(2)
    out["economia_potencial_mediana_rs"] = ((mediana - ref) * out["unimed_prev_mes_qtd"]).round(2)
    out["oportunidade_mensal_rs"] = (
        (ref - ref_global) * out["unimed_prev_mes_qtd"]
    ).clip(lower=0).round(2)
    out["risco_mensal_rs"] = (
        (ref_global - ref) * out["unimed_prev_mes_qtd"]
    ).clip(lower=0).round(2)

    plausible: list[bool] = []
    flags_col: list[str] = []
    for _, r in out.iterrows():
        med = float(r.get("global_custo_mediana_norm", r.get("global_custo_mediana", 0)) or 0)
        ult = float(r.get("global_custo_ultimo_norm", r.get("global_custo_ultimo", 0)) or 0)
        unimed_ref = float(r.get("unimed_vl_por_unidade", 0) or 0)
        existing = parse_review_flags(r.get("review_flags"))
        price_flags = depara_price_flags(
            med,
            ult,
            float(r.get("unimed_vl_medio", 0) or 0),
            unimed_desc=str(r.get("desc_item_unimed") or r.get("desc_unimed_match") or "") or None,
            unimed_unidade=str(r.get("unimed_un", "")) if pd.notna(r.get("unimed_un")) else None,
        )
        ok_proj, proj_flags = financial_projection_plausible(med, ult, unimed_ref)
        flags = existing + price_flags + proj_flags
        flags_col.append(format_review_flags(flags))
        plausible.append(ok_proj)

    out["projecao_financeira_plausivel"] = plausible
    mask = out["projecao_financeira_plausivel"]
    for col in (
        "oportunidade_mensal_rs",
        "risco_mensal_rs",
        "economia_potencial_rs",
        "economia_potencial_mediana_rs",
    ):
        if col in out.columns:
            out.loc[~mask, col] = 0.0

    out["review_flags"] = flags_col
    out["preco_depara_ok"] = ~out["review_flags"].apply(
        lambda s: "preco_depara_incompativel" in parse_review_flags(s)
    )

    return out
