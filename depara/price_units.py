"""Normalização de preço por unidade de embalagem (caixa, kit, etc.)."""

from __future__ import annotations

import re

import pandas as pd

_PACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"cx\s*c/\s*(\d+)", re.I),
    re.compile(r"kit\s*c/\s*(\d+)", re.I),
    re.compile(r"pct\s*c/\s*(\d+)", re.I),
    re.compile(r"pacote\s*c/\s*(\d+)", re.I),
    re.compile(r"c/\s*(\d+)\s*(?:und|un|pares|pulseiras|fr|fa)", re.I),
    re.compile(r"c/\s*(\d+)", re.I),
)

_UNIT_SINGULAR = frozenset(
    {
        "unidade",
        "seringa",
        "ampola",
        "frasco ampola",
        "rolo",
        "par",
        "ml",
        "litro",
        "l",
    }
)


def infer_pack_qty(descricao: str, unidade: str | None) -> int:
    """Quantidade de unidades por embalagem inferida da descrição/Un."""
    text = descricao or ""
    for pat in _PACK_PATTERNS:
        m = pat.search(text)
        if m:
            qty = int(m.group(1))
            if qty > 1:
                return qty
    unit = (unidade or "").strip().lower()
    if unit in _UNIT_SINGULAR:
        return 1
    return 1


def vl_por_unidade(vl_medio: float, descricao: str, unidade: str | None) -> float | None:
    if pd.isna(vl_medio) or vl_medio <= 0:
        return None
    qty = infer_pack_qty(descricao, unidade)
    return float(vl_medio / qty)


def enrich_catalog_prices(catalog: pd.DataFrame) -> pd.DataFrame:
    """Adiciona vl_por_unidade ao catálogo Unimed."""
    out = catalog.copy()
    out["vl_por_unidade"] = out.apply(
        lambda r: vl_por_unidade(
            r.get("vl_medio"),
            str(r.get("desc_global", "")),
            str(r.get("unidade", "")) if pd.notna(r.get("unidade")) else None,
        ),
        axis=1,
    )
    return out
