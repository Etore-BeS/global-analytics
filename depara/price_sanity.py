"""Sanidade de preço no depara e nos relatórios fase 2."""

from __future__ import annotations

import pandas as pd

from depara.price_units import vl_por_unidade

# Global vs Unimed ref: ratio fora desta faixa → depara ou agregação suspeita
DEFAULT_MAX_PRICE_RATIO = 4.0
OUTLIER_ULTIMO_VS_MEDIANA = 3.0


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


def linha_cost_stats(compras_path: str | pd.PathLike) -> pd.DataFrame:
    """Custos Global por linha clínica (todas as entradas, não só último SKU)."""
    raw = pd.read_csv(compras_path, encoding="latin-1")
    raw["linha_key"] = raw["LINHA_PRODUTO"].str.strip()
    raw = raw.sort_values("DT_ENTRADA")
    positive = raw[raw["CUSTO_ENTRADA"] > 0]
    return (
        positive.groupby("linha_key", as_index=False)
        .agg(
            linha_produto=("LINHA_PRODUTO", "first"),
            global_custo_mediana=("CUSTO_ENTRADA", "median"),
            global_custo_medio=("CUSTO_ENTRADA", "mean"),
            global_custo_ultimo=("CUSTO_ENTRADA", "last"),
            global_custo_min=("CUSTO_ENTRADA", "min"),
            global_custo_max=("CUSTO_ENTRADA", "max"),
        )
    )


def effective_ref_price(
    unimed_vl: float,
    descricao: str | None = None,
    unidade: str | None = None,
) -> float:
    """Preço Unimed comparável à unidade Global (normaliza caixa/kit)."""
    if descricao:
        vpu = vl_por_unidade(unimed_vl, descricao, unidade)
        if vpu is not None and vpu > 0:
            return vpu
    return unimed_vl


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
    """Normaliza ref. Unimed, recalcula gaps e métricas de oportunidade/risco."""
    out = df.copy()

    out["unimed_vl_por_unidade"] = out.apply(
        lambda r: effective_ref_price(
            float(r["unimed_vl_medio"] or 0),
            str(r.get("desc_item_unimed") or r.get("desc_unimed_match") or ""),
            str(r.get("unimed_un", "")) if pd.notna(r.get("unimed_un")) else None,
        ),
        axis=1,
    )
    ref = out["unimed_vl_por_unidade"]
    mediana = out["global_custo_mediana"]

    for col in ("global_custo_ultimo", "global_custo_medio", "global_custo_mediana"):
        out[f"gap_{col}_pct"] = _gap_pct_series(out[col], ref)

    out["gap_ultimo_rs"] = (out["global_custo_ultimo"] - ref).round(4)
    out["economia_potencial_mediana_rs"] = ((mediana - ref) * out["unimed_prev_mes_qtd"]).round(2)
    out["oportunidade_mensal_rs"] = ((ref - mediana) * out["unimed_prev_mes_qtd"]).clip(lower=0).round(2)
    out["risco_mensal_rs"] = ((mediana - ref) * out["unimed_prev_mes_qtd"]).clip(lower=0).round(2)

    flags_col: list[str] = []
    for _, r in out.iterrows():
        existing = parse_review_flags(r.get("review_flags"))
        flags = existing + depara_price_flags(
            float(r.get("global_custo_mediana", 0) or 0),
            float(r.get("global_custo_ultimo", 0) or 0),
            float(r.get("unimed_vl_medio", 0) or 0),
            unimed_desc=str(r.get("desc_item_unimed") or r.get("desc_unimed_match") or "") or None,
            unimed_unidade=str(r.get("unimed_un", "")) if pd.notna(r.get("unimed_un")) else None,
        )
        flags_col.append(format_review_flags(flags))

    out["review_flags"] = flags_col
    out["preco_depara_ok"] = ~out["review_flags"].apply(
        lambda s: "preco_depara_incompativel" in parse_review_flags(s)
    )

    return out
