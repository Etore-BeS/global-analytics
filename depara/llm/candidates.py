"""Recuperação de candidatos Global (top-K) antes do LLM."""

from __future__ import annotations

import pandas as pd
from thefuzz import fuzz, process

from depara.fase1_similarity import load_global_items, normalize_text
from depara.llm.schemas import GlobalCandidate, UnimedLinhaInput
from depara.price_sanity import DEFAULT_MAX_PRICE_RATIO, price_proximity_score

# Confianças incluídas em --all (pula só alta)
LLM_ALL_CONFIDENCA = frozenset({"media", "baixa", "revisar"})

_PRINCIPIO_STOP = frozenset(
    {
        "de",
        "da",
        "do",
        "dos",
        "das",
        "e",
        "com",
        "para",
        "uso",
        "oral",
        "cloridrato",
        "sodio",
        "produtos",
        "suplemento",
        "alimentar",
        "saude",
    }
)


def build_global_linhas(global_distribuidor_path: str) -> pd.DataFrame:
    from depara.fase1_similarity import load_global_linhas

    return load_global_linhas(global_distribuidor_path)


def build_unimed_linhas(path: str) -> pd.DataFrame:
    """Alias legado — use build_global_linhas."""
    return build_global_linhas(path)


def _principio_tokens(principio: str) -> set[str]:
    text = normalize_text(principio)
    tokens: set[str] = set()
    for part in text.replace(",", " ").split():
        if len(part) >= 4 and part not in _PRINCIPIO_STOP:
            tokens.add(part)
    return tokens


def filter_global_by_principio(
    global_items: pd.DataFrame,
    principio_ativo: str,
    *,
    min_pool: int = 5,
) -> pd.DataFrame:
    """Restringe catálogo Global a itens cujo texto contém token do princípio ativo."""
    tokens = _principio_tokens(principio_ativo)
    if not tokens:
        return global_items

    def _matches(desc: object) -> bool:
        norm = normalize_text(desc)
        return any(tok in norm for tok in tokens)

    filtered = global_items[global_items["desc_global"].apply(_matches)]
    if len(filtered) >= min_pool:
        return filtered
    return global_items


def retrieve_candidates(
    item: UnimedLinhaInput,
    global_items: pd.DataFrame,
    *,
    top_k: int = 12,
    hint_cod_item: int | None = None,
    expand_by_price: bool = False,
    exclude_cod_items: frozenset[int] | None = None,
) -> list[GlobalCandidate]:
    query = normalize_text(item.linha_produto)
    if not query:
        return []

    pool = filter_global_by_principio(global_items, item.principio_ativo, min_pool=top_k)
    pool_from_principio = len(pool) < len(global_items)

    seen: set[int] = set()
    candidates: list[GlobalCandidate] = []
    text_to_row = global_items.set_index("texto_match")

    exclude = exclude_cod_items or frozenset()

    def _append_row(row: pd.Series) -> None:
        cod = int(row["cod_item"])
        if cod in seen or cod in exclude:
            return
        seen.add(cod)
        candidates.append(
            GlobalCandidate(
                cod_item=cod,
                desc_global=str(row["desc_global"]),
                abc=str(row["abc"]) if pd.notna(row.get("abc")) else None,
                vl_medio=float(row["vl_medio"]) if pd.notna(row.get("vl_medio")) else None,
                unidade=str(row["unidade"]) if pd.notna(row.get("unidade")) else None,
                vl_por_unidade=(
                    float(row["vl_por_unidade"])
                    if pd.notna(row.get("vl_por_unidade"))
                    else None
                ),
            )
        )

    def _append_by_price(
        ref_cost: float,
        source: pd.DataFrame,
        *,
        limit: int = 15,
    ) -> None:
        if ref_cost <= 0:
            return
        scored: list[tuple[float, pd.Series]] = []
        for _, row in source.iterrows():
            cod = int(row["cod_item"])
            if cod in seen or cod in exclude:
                continue
            vpu = row.get("vl_por_unidade")
            if pd.isna(vpu) or vpu <= 0:
                continue
            ratio = max(vpu / ref_cost, ref_cost / vpu)
            if ratio <= DEFAULT_MAX_PRICE_RATIO * 1.5:
                scored.append((ratio, row))
        scored.sort(key=lambda x: x[0])
        for _, row in scored[:limit]:
            _append_row(row)

    ref_cost = item.custo_mediano or item.custo_medio

    if hint_cod_item is not None and hint_cod_item not in exclude:
        hint_rows = global_items[global_items["cod_item"] == hint_cod_item]
        if not hint_rows.empty:
            _append_row(hint_rows.iloc[0])

    if expand_by_price and ref_cost and ref_cost > 0:
        _append_by_price(ref_cost, pool, limit=max(15, top_k // 3))
        if len(candidates) < top_k // 2:
            _append_by_price(ref_cost, global_items, limit=max(10, top_k // 4))

    def _fuzzy_append(source: pd.DataFrame) -> None:
        choices = list(source["texto_match"].unique())
        if not choices:
            return
        scored = process.extract(
            query,
            choices,
            scorer=fuzz.token_set_ratio,
            limit=top_k + 15,
        )
        for text, _score in scored:
            if text not in text_to_row.index:
                continue
            row = text_to_row.loc[text]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            _append_row(row)
            if len(candidates) >= top_k * 2:
                break

    _fuzzy_append(pool)
    if len(candidates) < top_k and pool_from_principio:
        _fuzzy_append(global_items)

    ref_cost = item.custo_mediano or item.custo_medio
    if ref_cost and ref_cost > 0 and len(candidates) > 1:
        candidates.sort(
            key=lambda c: price_proximity_score(
                ref_cost, c.vl_por_unidade or c.vl_medio or 0
            ),
            reverse=True,
        )

    return candidates[:top_k]


def format_candidates_prompt(
    candidates: list[GlobalCandidate],
    *,
    detailed: bool = False,
) -> str:
    lines = []
    for i, c in enumerate(candidates, 1):
        abc = f" | ABC={c.abc}" if c.abc else ""
        un = f" | Un={c.unidade}" if c.unidade else ""
        vl = f" | VL Médio R$={c.vl_medio:.2f}" if c.vl_medio is not None else ""
        vpu = ""
        if detailed and c.vl_por_unidade is not None:
            vpu = f" | VL/un R$={c.vl_por_unidade:.4f}"
        lines.append(f"{i}. cod_item={c.cod_item}{abc}{un}{vl}{vpu} | {c.desc_global}")
    return "\n".join(lines)


def format_unimed_prompt(item: UnimedLinhaInput) -> str:
    marcas = ", ".join(item.marcas[:5]) if item.marcas else "—"
    descs = "\n".join(f"  - {d}" for d in item.descricoes_amostra[:3])
    desc_block = f"\nDescrições comerciais (amostra):\n{descs}" if descs else ""
    price_block = ""
    if item.custo_mediano and item.custo_mediano > 0:
        price_block = (
            f"\nPreço Global (compras): mediana R$ {item.custo_mediano:.2f}/un"
        )
        if item.custo_medio and item.custo_medio > 0:
            price_block += f", média R$ {item.custo_medio:.2f}/un"
        price_block += (
            f"\n→ Prefira candidato cujo VL Médio Unimed esteja na faixa "
            f"~0,25× a 4× desse valor. Ratio >4× ou <0,25× indica produto "
            f"ou unidade errada — use no_match."
        )
    return (
        f"Linha clínica Global (compras): {item.linha_produto}\n"
        f"Princípio ativo: {item.principio_ativo}\n"
        f"SKUs/marcas Global: {item.n_skus} ({marcas})"
        f"{desc_block}{price_block}"
    )


def format_reanalyze_prompt(item: UnimedLinhaInput) -> str:
    base = format_unimed_prompt(item)
    prev_block = ""
    if item.match_anterior_cod_item is not None:
        vl = item.match_anterior_vl_medio
        vl_txt = f"R$ {vl:.2f}" if vl is not None else "?"
        prev_block = (
            f"\n\n⚠ MATCH ANTERIOR REJEITADO (preço incompatível):\n"
            f"  cod_item={item.match_anterior_cod_item} | {item.match_anterior_desc or '?'}\n"
            f"  VL Médio Unimed: {vl_txt}\n"
            f"  → NÃO repita este cod_item salvo se normalizar unidade e preço bater."
        )
    if item.custo_min and item.custo_max and item.custo_min != item.custo_max:
        base += f"\nFaixa de compra Global: R$ {item.custo_min:.2f} – R$ {item.custo_max:.2f}/un"
    return base + prev_block
