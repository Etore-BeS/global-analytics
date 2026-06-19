"""Fila de prioridade para rodar LLM com base em preço e incerteza fuzzy."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from depara.fase1_similarity import load_global_items


def _linha_costs(global_distribuidor_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(global_distribuidor_path, encoding="latin-1")
    prod = raw.drop_duplicates(subset=["COD_PRODUTO"])
    costs = (
        prod.groupby("LINHA_PRODUTO")
        .agg(
            custo_medio=("CUSTO_ENTRADA", "mean"),
            custo_min=("CUSTO_ENTRADA", "min"),
            custo_max=("CUSTO_ENTRADA", "max"),
        )
        .reset_index()
        .rename(columns={"LINHA_PRODUTO": "linha_produto"})
    )
    costs["linha_key"] = costs["linha_produto"].str.strip()
    return costs


def assign_confidence(row: pd.Series) -> str:
    primary = row.get("fuzz_token_set", 0)
    spacy = row.get("spacy", 0)
    score_mean = row.get("score_mean", 0)
    score_std = row.get("score_std", 0)
    cod_cols = [c for c in row.index if c.startswith("cod_item_")]
    n_unique = len({row[c] for c in cod_cols}) if cod_cols else 1

    if n_unique == 1 and primary >= 0.8:
        return "alta"
    if (
        cod_cols
        and row.get("cod_item_fuzz_token_set") == row.get("cod_item_spacy")
        and primary >= 0.75
    ):
        return "alta"
    if n_unique <= 2 and score_mean >= 0.75:
        return "media"
    if score_mean >= 0.6 and score_std < 0.2:
        return "baixa"
    return "revisar"


def build_priority_queue(
    global_distribuidor_path: Path,
    unimed_catalogo_path: Path,
    fase1_path: Path,
    *,
    already_done: set[str] | None = None,
) -> pd.DataFrame:
    fase1 = pd.read_csv(fase1_path)
    fase1["linha_key"] = fase1["linha_produto"].str.strip()
    if "confianca" not in fase1.columns:
        fase1["confianca"] = fase1.apply(assign_confidence, axis=1)

    costs = _linha_costs(global_distribuidor_path)
    unimed_items = load_global_items(str(unimed_catalogo_path))

    queue = fase1.merge(
        costs.drop(columns=["linha_produto"]),
        on="linha_key",
        how="left",
    )
    queue = queue.merge(
        unimed_items[["cod_item", "vl_medio", "abc", "desc_global"]].rename(
            columns={"desc_global": "desc_global_fuzzy", "cod_item": "cod_item_fuzzy"}
        ),
        left_on="best_cod_item",
        right_on="cod_item_fuzzy",
        how="left",
    )

    # Prev Mês vem do Excel original
    global_raw = pd.read_excel(unimed_catalogo_path)
    prev = global_raw.rename(
        columns={"Cod Item": "cod_item", "Prev Mês (R$)": "prev_mes_rs"}
    )[["cod_item", "prev_mes_rs"]]
    queue = queue.merge(prev, left_on="best_cod_item", right_on="cod_item", how="left")

    queue["incerteza"] = (1 - queue["fuzz_token_set"].clip(0, 1)).round(3)
    queue["prioridade"] = (queue["prev_mes_rs"].fillna(0) * queue["incerteza"]).round(0)
    queue["gap_custo_pct"] = (
        (queue["custo_medio"] - queue["vl_medio"]) / queue["vl_medio"] * 100
    ).round(1)

    if already_done:
        queue["ja_rodou_llm"] = queue["linha_key"].isin(already_done)
    else:
        queue["ja_rodou_llm"] = False

    return queue.sort_values(
        ["ja_rodou_llm", "prioridade"], ascending=[True, False]
    ).reset_index(drop=True)
