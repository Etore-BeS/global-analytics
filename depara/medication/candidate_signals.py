"""Build candidate lists with hash, fuzzy and price signals for the agent."""

from __future__ import annotations

import pandas as pd
from depara.fase1_similarity import normalize_text
from depara.llm.candidates import filter_global_by_principio
from depara.medication.models import FUZZY_ALTA_THRESHOLD, EnrichedCandidate
from depara.price_sanity import prices_compatible
from thefuzz import fuzz


def fuzzy_score(query_norm: str, candidate_norm: str) -> float:
    if not query_norm or not candidate_norm:
        return 0.0
    return fuzz.token_set_ratio(query_norm, candidate_norm) / 100.0


def build_enriched_candidates(
    *,
    linha_produto: str,
    principio_ativo: str,
    source_hash: str | None,
    global_cost: float | None,
    catalog: pd.DataFrame,
    top_k: int = 12,
    hint_cod_item: int | None = None,
    hint_fuzzy_alta: bool = False,
) -> list[EnrichedCandidate]:
    """Return Unimed candidates tagged with hash_match, fuzzy_alta, preco_ok."""
    query_norm = normalize_text(linha_produto)
    if not query_norm:
        return []

    pool = filter_global_by_principio(catalog, principio_ativo, min_pool=top_k)
    seen: set[int] = set()
    rows: list[tuple[pd.Series, float]] = []

    def _consider(row: pd.Series, fuzzy: float) -> None:
        cod = int(row["cod_item"])
        if cod in seen:
            return
        seen.add(cod)
        rows.append((row, fuzzy))

    if hint_cod_item is not None:
        hint = catalog[catalog["cod_item"] == hint_cod_item]
        if not hint.empty:
            hr = hint.iloc[0]
            _consider(hr, fuzzy_score(query_norm, str(hr.get("texto_match", ""))))

    for _, row in pool.iterrows():
        cand_norm = str(row.get("texto_match", ""))
        score = fuzzy_score(query_norm, cand_norm)
        _consider(row, score)

    if len(rows) < top_k:
        for _, row in catalog.iterrows():
            cod = int(row["cod_item"])
            if cod in seen:
                continue
            score = fuzzy_score(query_norm, str(row.get("texto_match", "")))
            _consider(row, score)
            if len(rows) >= top_k * 2:
                break

    rows.sort(key=lambda x: x[1], reverse=True)
    rows = rows[:top_k]

    ref_cost = global_cost if global_cost and global_cost > 0 else None
    out: list[EnrichedCandidate] = []
    for row, fscore in rows:
        cand_hash = row.get("medication_hash_id")
        if pd.isna(cand_hash):
            cand_hash = None
        else:
            cand_hash = str(cand_hash)

        vpu = row.get("vl_por_unidade")
        vl = row.get("vl_medio")
        price_ref = None
        if pd.notna(vpu) and float(vpu) > 0:
            price_ref = float(vpu)
        elif pd.notna(vl) and float(vl) > 0:
            price_ref = float(vl)

        preco_ok = False
        if ref_cost and price_ref:
            preco_ok = prices_compatible(ref_cost, price_ref)

        hash_match = bool(
            source_hash and cand_hash and source_hash == cand_hash and not row.get("norm_skipped")
        )

        cod = int(row["cod_item"])
        fuzzy_alta = fscore >= FUZZY_ALTA_THRESHOLD
        if hint_fuzzy_alta and hint_cod_item is not None and cod == hint_cod_item:
            fuzzy_alta = True

        out.append(
            EnrichedCandidate(
                cod_item=cod,
                desc_global=str(row["desc_global"]),
                medication_hash_id=cand_hash,
                hash_match=hash_match,
                fuzzy_score=round(fscore, 4),
                fuzzy_alta=fuzzy_alta,
                preco_ok=preco_ok,
                vl_medio=float(vl) if pd.notna(vl) else None,
                vl_por_unidade=float(vpu) if pd.notna(vpu) else None,
                unidade=str(row["unidade"]) if pd.notna(row.get("unidade")) else None,
                abc=str(row["abc"]) if pd.notna(row.get("abc")) else None,
                medication_normalized=(
                    str(row["medication_normalized"])
                    if pd.notna(row.get("medication_normalized"))
                    else None
                ),
                form_normalized=(
                    str(row["form_normalized"]) if pd.notna(row.get("form_normalized")) else None
                ),
                route_normalized=(
                    str(row["route_normalized"]) if pd.notna(row.get("route_normalized")) else None
                ),
            )
        )
    return out
