"""Reanálise LLM de linhas com depara incompatível com preço."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd

from depara.fase1_similarity import load_global_items
from depara.llm.cache import MatchCache
from depara.llm.candidates import (
    build_global_linhas,
    format_candidates_prompt,
    format_reanalyze_prompt,
    retrieve_candidates,
)
from depara.llm.config import DeparaLLMSettings
from depara.llm.matcher import LLMMatcher
from depara.llm.reanalyze_agent import build_reanalyze_agent, build_reanalyze_user_prompt
from depara.llm.schemas import (
    LLMMatchOutput,
    MatchDecision,
    MatchRecord,
    UnimedLinhaInput,
    output_cod_item,
    parse_list_field,
)
from depara.price_sanity import enrich_price_report
from depara.sources import csv_to_internal


def load_price_incompatible_lines(
    price_report_path: Path,
    *,
    limit: int | None = None,
) -> pd.DataFrame:
    df = enrich_price_report(csv_to_internal(pd.read_csv(price_report_path)))
    bad = df[~df["preco_depara_ok"]].copy()
    bad = bad.sort_values("unimed_prev_mes_rs", ascending=False, na_position="last")
    if limit is not None:
        bad = bad.head(limit)
    return bad


class PriceReanalyzer:
    def __init__(self, settings: DeparaLLMSettings | None = None) -> None:
        self.settings = settings or DeparaLLMSettings()
        self.settings.ensure_dirs()
        self.agent = build_reanalyze_agent(self.settings)
        self.cache = MatchCache(self.settings.cache_path)
        self._matcher = LLMMatcher(self.settings)
        self._global_items: pd.DataFrame | None = None
        self._global_linhas: pd.DataFrame | None = None

    @property
    def global_items(self) -> pd.DataFrame:
        if self._global_items is None:
            self._global_items = load_global_items(str(self.settings.unimed_catalogo_path))
        return self._global_items

    @property
    def global_linhas(self) -> pd.DataFrame:
        if self._global_linhas is None:
            self._global_linhas = build_global_linhas(
                str(self.settings.global_distribuidor_path)
            )
        return self._global_linhas

    @property
    def unimed_linhas(self) -> pd.DataFrame:
        """Alias legado — linhas clínicas Global."""
        return self.global_linhas

    def _row_to_reanalyze_input(self, row: pd.Series) -> UnimedLinhaInput:
        linha = str(row["linha_produto"]).strip()
        urow = self.global_linhas[self.global_linhas["linha_produto"] == linha]
        if urow.empty:
            urow = self.global_linhas[
                self.global_linhas["linha_produto"].str.strip() == linha
            ]
        base = urow.iloc[0] if not urow.empty else row
        cost = self._matcher.linha_costs
        cost_row = cost[cost["linha_key"] == linha]
        custo_mediano = float(row["global_custo_mediana"]) if pd.notna(row.get("global_custo_mediana")) else None
        custo_medio = float(row["global_custo_medio"]) if pd.notna(row.get("global_custo_medio")) else None
        custo_min = float(row["global_custo_min"]) if pd.notna(row.get("global_custo_min")) else None
        custo_max = float(row["global_custo_max"]) if pd.notna(row.get("global_custo_max")) else None
        if not cost_row.empty:
            if custo_mediano is None:
                custo_mediano = float(cost_row.iloc[0]["global_custo_mediana"])
            if custo_min is None:
                custo_min = float(cost_row.iloc[0]["global_custo_min"])
            if custo_max is None:
                custo_max = float(cost_row.iloc[0]["global_custo_max"])
        prev_cod = row.get("unimed_cod_item")
        return UnimedLinhaInput(
            linha_produto=linha,
            principio_ativo=str(base.get("principio_ativo", row.get("principio_ativo", ""))),
            n_skus=int(base.get("n_skus", row.get("n_skus", 1))),
            marcas=parse_list_field(base.get("marcas", row.get("marcas"))),
            descricoes_amostra=parse_list_field(base.get("descricoes")),
            custo_mediano=custo_mediano,
            custo_medio=custo_medio,
            custo_min=custo_min,
            custo_max=custo_max,
            match_anterior_cod_item=int(prev_cod) if pd.notna(prev_cod) else None,
            match_anterior_desc=str(row.get("desc_item_unimed") or row.get("desc_unimed_match") or ""),
            match_anterior_vl_medio=(
                float(row["unimed_vl_medio"]) if pd.notna(row.get("unimed_vl_medio")) else None
            ),
        )

    async def reanalyze_one(
        self,
        item: UnimedLinhaInput,
        *,
        top_k: int | None = None,
        use_cache: bool = True,
    ) -> MatchRecord:
        k = top_k or self.settings.reanalyze_top_k
        exclude = (
            frozenset({item.match_anterior_cod_item})
            if item.match_anterior_cod_item is not None
            else frozenset()
        )
        candidates = retrieve_candidates(
            item,
            self.global_items,
            top_k=k,
            hint_cod_item=self._matcher.fase1_hints.get(item.linha_produto.strip()),
            expand_by_price=True,
            exclude_cod_items=exclude,
        )
        candidate_ids = [c.cod_item for c in candidates]
        model = self.settings.reanalyze_model
        cache_key = MatchCache.make_key(
            f"reanalyze|{item.linha_produto}", candidate_ids, model
        )

        cached = False
        llm_out: LLMMatchOutput | None = None
        error: str | None = None

        if use_cache:
            llm_out = self.cache.get(cache_key)
            if llm_out is not None:
                cached = True

        if llm_out is None:
            if not candidates:
                llm_out = LLMMatchOutput(
                    decision=MatchDecision.NO_MATCH,
                    confidence=0.0,
                    reasoning="Nenhum candidato recuperado (fuzzy + preço).",
                )
            else:
                from depara.llm.reanalyze_agent import MatchDeps

                prompt = build_reanalyze_user_prompt(
                    format_reanalyze_prompt(item),
                    format_candidates_prompt(candidates, detailed=True),
                )
                deps = MatchDeps(valid_cod_items=frozenset(candidate_ids))
                try:
                    async with self.agent:
                        result = await self.agent.run(prompt, deps=deps)
                    llm_out = result.output
                    if use_cache:
                        self.cache.set(cache_key, item.linha_produto, model, llm_out)
                except Exception as exc:
                    error = str(exc)
                    llm_out = LLMMatchOutput(
                        decision=MatchDecision.NO_MATCH,
                        confidence=0.0,
                        reasoning=f"Erro na reanálise LLM: {exc}",
                    )

        cod_item = output_cod_item(llm_out)
        desc_global = None
        if cod_item is not None:
            match_row = self.global_items[self.global_items["cod_item"] == cod_item]
            if not match_row.empty:
                desc_global = str(match_row.iloc[0]["desc_global"])

        return MatchRecord(
            linha_produto=item.linha_produto,
            principio_ativo=item.principio_ativo,
            n_skus=item.n_skus,
            marcas=item.marcas,
            decision=llm_out.decision,
            cod_item=cod_item,
            desc_global=desc_global,
            confidence=llm_out.confidence,
            reasoning=llm_out.reasoning,
            n_candidates=len(candidates),
            candidate_cod_items=candidate_ids,
            model=model,
            cached=cached,
            error=error,
            run_pass="reanalyze_price",
        )

    async def reanalyze_many(
        self,
        items: list[UnimedLinhaInput],
        *,
        top_k: int | None = None,
        use_cache: bool = True,
    ) -> list[MatchRecord]:
        sem = asyncio.Semaphore(self.settings.max_concurrency)

        async def _run(item: UnimedLinhaInput) -> MatchRecord:
            async with sem:
                return await self.reanalyze_one(item, top_k=top_k, use_cache=use_cache)

        return await asyncio.gather(*[_run(i) for i in items])

    def run_batch(
        self,
        price_report_path: Path,
        *,
        limit: int | None = None,
        top_k: int | None = None,
        use_cache: bool = True,
        output_path: Path | None = None,
        merge_into_matches: bool = True,
    ) -> pd.DataFrame:
        lines = load_price_incompatible_lines(price_report_path, limit=limit)
        items = [self._row_to_reanalyze_input(row) for _, row in lines.iterrows()]
        records = asyncio.run(
            self.reanalyze_many(items, top_k=top_k, use_cache=use_cache)
        )
        df = pd.DataFrame([r.model_dump() for r in records])
        df = self._matcher._enrich_with_prices(df)

        out = output_path or self.settings.output_path.parent / "fase1_llm_reanalyze.csv"
        df.to_csv(out, index=False)

        if merge_into_matches:
            main = self.settings.output_path
            if main.exists():
                prev = pd.read_csv(main)
                if "run_pass" not in prev.columns:
                    prev["run_pass"] = "initial"
                combined = pd.concat([prev, df], ignore_index=True).drop_duplicates(
                    subset=["linha_produto"], keep="last"
                )
            else:
                combined = df
            combined.to_csv(main, index=False)

        return df
