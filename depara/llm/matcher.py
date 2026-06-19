"""Orquestração do match LLM: candidatos → agent → cache → export."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

import pandas as pd
from pydantic_ai import Agent

from depara.fase1_similarity import load_global_items
from depara.llm.agent import MatchDeps, build_agent, build_user_prompt
from depara.llm.cache import MatchCache
from depara.llm.candidates import (
    LLM_ALL_CONFIDENCA,
    build_global_linhas,
    format_candidates_prompt,
    format_unimed_prompt,
    retrieve_candidates,
)
from depara.llm.config import DeparaLLMSettings
from depara.llm.priority import build_priority_queue
from depara.llm.schemas import (
    GlobalCandidate,
    LLMMatchOutput,
    MatchDecision,
    MatchRecord,
    UnimedLinhaInput,
    output_cod_item,
    parse_list_field,
)

class LLMMatcher:
    def __init__(self, settings: DeparaLLMSettings | None = None) -> None:
        self.settings = settings or DeparaLLMSettings()
        self.settings.ensure_dirs()
        self.agent = build_agent(self.settings)
        self.cache = MatchCache(self.settings.cache_path)
        self._global_items: pd.DataFrame | None = None
        self._global_linhas: pd.DataFrame | None = None
        self._fase1_hints: dict[str, int] | None = None
        self._linha_costs: pd.DataFrame | None = None

    @property
    def linha_costs(self) -> pd.DataFrame:
        if self._linha_costs is None:
            from depara.price_sanity import linha_cost_stats

            self._linha_costs = linha_cost_stats(self.settings.global_compras_path)
            self._linha_costs["linha_key"] = self._linha_costs["linha_produto"].str.strip()
        return self._linha_costs

    @property
    def fase1_hints(self) -> dict[str, int]:
        if self._fase1_hints is None:
            path = self.settings.output_path.parent / "fase1_comparison.csv"
            hints: dict[str, int] = {}
            if path.exists():
                fase1 = pd.read_csv(path)
                for _, row in fase1.iterrows():
                    key = str(row["linha_produto"]).strip()
                    cod = row.get("best_cod_item")
                    if pd.notna(cod):
                        hints[key] = int(cod)
            self._fase1_hints = hints
        return self._fase1_hints

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

    def _row_to_input(self, row: pd.Series) -> UnimedLinhaInput:
        linha = row.get("linha_produto")
        if pd.isna(linha):
            linha = row.get("linha_key", "")
        linha_key = str(linha).strip()
        cost_row = self.linha_costs[self.linha_costs["linha_key"] == linha_key]
        custo_mediano = None
        custo_medio = None
        if not cost_row.empty:
            med = cost_row.iloc[0]["global_custo_mediana"]
            mean = cost_row.iloc[0]["global_custo_medio"]
            custo_mediano = float(med) if pd.notna(med) and med > 0 else None
            custo_medio = float(mean) if pd.notna(mean) and mean > 0 else None
        return UnimedLinhaInput(
            linha_produto=str(linha),
            principio_ativo=str(row.get("principio_ativo", "")),
            n_skus=int(row.get("n_skus", 0)),
            marcas=parse_list_field(row.get("marcas")),
            descricoes_amostra=parse_list_field(row.get("descricoes")),
            custo_mediano=custo_mediano,
            custo_medio=custo_medio,
        )

    async def match_one(
        self,
        item: UnimedLinhaInput,
        *,
        use_cache: bool = True,
    ) -> MatchRecord:
        candidates = retrieve_candidates(
            item,
            self.global_items,
            top_k=self.settings.top_k_candidates,
            hint_cod_item=self.fase1_hints.get(item.linha_produto.strip()),
        )
        candidate_ids = [c.cod_item for c in candidates]
        cache_key = MatchCache.make_key(
            item.linha_produto, candidate_ids, self.settings.model
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
                    reasoning="Nenhum candidato recuperado pelo retriever.",
                )
            else:
                prompt = build_user_prompt(
                    format_unimed_prompt(item),
                    format_candidates_prompt(candidates),
                )
                deps = MatchDeps(valid_cod_items=frozenset(candidate_ids))
                try:
                    async with self.agent:
                        result = await self.agent.run(prompt, deps=deps)
                    llm_out = result.output
                    if use_cache:
                        self.cache.set(
                            cache_key, item.linha_produto, self.settings.model, llm_out
                        )
                except Exception as exc:
                    error = str(exc)
                    llm_out = LLMMatchOutput(
                        decision=MatchDecision.NO_MATCH,
                        confidence=0.0,
                        reasoning=f"Erro na chamada LLM: {exc}",
                    )

        cod_item = output_cod_item(llm_out)
        desc_global = None
        if cod_item is not None:
            match_row = self.global_items[
                self.global_items["cod_item"] == cod_item
            ]
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
            model=self.settings.model,
            cached=cached,
            error=error,
            run_pass="initial",
        )

    async def match_many(
        self,
        items: Iterable[UnimedLinhaInput],
        *,
        use_cache: bool = True,
    ) -> list[MatchRecord]:
        sem = asyncio.Semaphore(self.settings.max_concurrency)

        async def _run(item: UnimedLinhaInput) -> MatchRecord:
            async with sem:
                return await self.match_one(item, use_cache=use_cache)

        return await asyncio.gather(*[_run(i) for i in items])

    @staticmethod
    def _completed_linhas(output_path: Path) -> set[str]:
        if not output_path.exists():
            return set()
        prev = pd.read_csv(output_path)
        if "error" in prev.columns:
            no_error = prev["error"].isna() | (prev["error"] == "")
        else:
            no_error = True
        ok = (prev["decision"] == "match") | (
            (prev["decision"] == "no_match") & (prev["confidence"] > 0) & no_error
        )
        return set(prev.loc[ok, "linha_produto"].str.strip())

    @staticmethod
    def _apply_confidence_filter(
        df: pd.DataFrame,
        *,
        confianca_filter: str | None,
        confianca_all: bool,
    ) -> pd.DataFrame:
        if confianca_all:
            return df[df["confianca"].isin(LLM_ALL_CONFIDENCA)]
        if confianca_filter:
            return df[df["confianca"] == confianca_filter]
        return df

    def _select_linhas(
        self,
        *,
        limit: int | None,
        confianca_filter: str | None,
        confianca_all: bool = False,
        order: str,
    ) -> pd.DataFrame:
        fase1_path = self.settings.output_path.parent / "fase1_comparison.csv"
        done = self._completed_linhas(self.settings.output_path)

        if order == "priority" and fase1_path.exists():
            queue = build_priority_queue(
                self.settings.global_distribuidor_path,
                self.settings.unimed_catalogo_path,
                fase1_path,
                already_done=done,
            )
            queue = self._apply_confidence_filter(
                queue,
                confianca_filter=confianca_filter,
                confianca_all=confianca_all,
            )
            queue = queue[~queue["ja_rodou_llm"]]
            if limit is not None:
                queue = queue.head(limit)
            enrich = ["principio_ativo", "n_skus", "marcas", "descricoes"]
            queue = queue.drop(columns=[c for c in enrich if c in queue.columns])
            linhas = queue.merge(
                self.global_linhas[["linha_produto", *enrich]],
                on="linha_produto",
                how="left",
            )
            return linhas

        linhas = self.global_linhas.copy()
        if (confianca_filter or confianca_all) and fase1_path.exists():
            fase1 = pd.read_csv(fase1_path)
            if "confianca" not in fase1.columns:
                from depara.llm.priority import assign_confidence

                fase1["confianca"] = fase1.apply(assign_confidence, axis=1)
            linhas = linhas.merge(fase1[["linha_produto", "confianca"]], on="linha_produto")
            linhas = self._apply_confidence_filter(
                linhas,
                confianca_filter=confianca_filter,
                confianca_all=confianca_all,
            )
        if limit is not None:
            linhas = linhas.head(limit)
        return linhas

    def _enrich_with_prices(self, df: pd.DataFrame) -> pd.DataFrame:
        from depara.llm.priority import _linha_costs

        costs = _linha_costs(self.settings.global_distribuidor_path)
        costs["linha_key"] = costs["linha_produto"].str.strip()
        df["linha_key"] = df["linha_produto"].str.strip()
        if "cod_item" in df.columns:
            df["cod_item"] = pd.to_numeric(df["cod_item"], errors="coerce")
        df = df.merge(
            costs[["linha_key", "custo_medio", "custo_min", "custo_max"]],
            on="linha_key",
            how="left",
        )
        global_raw = pd.read_excel(self.settings.unimed_catalogo_path)
        gp = global_raw.rename(
            columns={
                "Cod Item": "cod_item",
                "VL Médio (R$)": "vl_medio_global",
                "Prev Mês (R$)": "prev_mes_rs",
                "ABC": "abc_global",
            }
        )
        df = df.merge(
            gp[["cod_item", "vl_medio_global", "prev_mes_rs", "abc_global"]],
            left_on="cod_item",
            right_on="cod_item",
            how="left",
        )
        return df.drop(columns=["linha_key"])

    def run_batch(
        self,
        *,
        limit: int | None = None,
        confianca_filter: str | None = None,
        confianca_all: bool = False,
        use_cache: bool = True,
        order: str = "priority",
    ) -> pd.DataFrame:
        linhas = self._select_linhas(
            limit=limit,
            confianca_filter=confianca_filter,
            confianca_all=confianca_all,
            order=order,
        )

        items = [self._row_to_input(row) for _, row in linhas.iterrows()]
        records = asyncio.run(self.match_many(items, use_cache=use_cache))
        df = pd.DataFrame([r.model_dump() for r in records])
        df = self._enrich_with_prices(df)

        out = self.settings.output_path
        if out.exists():
            prev = pd.read_csv(out)
            df = pd.concat([prev, df], ignore_index=True).drop_duplicates(
                subset=["linha_produto"], keep="last"
            )
        df.to_csv(out, index=False)
        return df
