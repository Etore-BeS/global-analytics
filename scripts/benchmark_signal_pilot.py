"""Offline benchmark: quality of hash/fuzzy/price signals for agent context."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from depara.fase1_similarity import load_global_items, load_global_linhas
from depara.llm.priority import assign_confidence
from depara.medication.candidate_signals import build_enriched_candidates
from depara.medication.enrich import enrich_linhas_with_hash, enrich_unimed_catalog_with_hash
from depara.medication.normalizer import normalize_clinical_text
from depara.medication.prompt_enrich import context_to_jsonl_record, dump_jsonl_record
from depara.price_sanity import linha_cost_stats


@dataclass
class BenchmarkMetrics:
    n_linhas: int = 0
    hash_coverage: float = 0.0
    unimed_hash_coverage: float = 0.0
    n_with_truth: int = 0
    truth_in_topk: float = 0.0
    truth_has_hash_signal: float = 0.0
    truth_has_all_three: float = 0.0
    false_hash_signal_rate: float = 0.0
    fuzzy_alta_agent_ready: float = 0.0
    n_fuzzy_alta: int = 0
    blocking_failures: list[str] = field(default_factory=list)
    go: bool = False


def _ground_truth(fase1: pd.DataFrame, llm: pd.DataFrame) -> dict[str, int]:
    truth: dict[str, int] = {}
    llm_ok = llm[llm["decision"] == "match"]
    for _, row in llm_ok.iterrows():
        key = str(row["linha_produto"]).strip()
        cod = row.get("cod_item")
        if pd.notna(cod):
            truth[key] = int(cod)

    if "confianca" not in fase1.columns:
        fase1 = fase1.copy()
        fase1["confianca"] = fase1.apply(assign_confidence, axis=1)

    alta = fase1[fase1["confianca"] == "alta"]
    for _, row in alta.iterrows():
        key = str(row["linha_produto"]).strip()
        if key in truth:
            continue
        cod = row.get("best_cod_item")
        if pd.notna(cod):
            truth[key] = int(cod)
    return truth


def _global_cost_for_linha(costs: pd.DataFrame, linha_key: str) -> float | None:
    row = costs[costs["linha_key"] == linha_key]
    if row.empty:
        return None
    med = row.iloc[0]["global_custo_mediana"]
    if pd.notna(med) and med > 0:
        return float(med)
    mean = row.iloc[0]["global_custo_medio"]
    if pd.notna(mean) and mean > 0:
        return float(mean)
    return None


def run_benchmark(
    *,
    data_dir: Path,
    exports_dir: Path,
    limit: int | None = None,
    top_k: int = 12,
    jsonl_sample_size: int = 50,
) -> BenchmarkMetrics:
    exports_dir.mkdir(parents=True, exist_ok=True)

    global_path = data_dir / "global_df.csv"
    catalog_path = data_dir / "Curva ABC - CD 05.26.xlsx"
    fase1_path = data_dir / "fase1_comparison.csv"
    llm_path = data_dir / "fase1_llm_matches.csv"

    linhas = load_global_linhas(str(global_path))
    if limit:
        linhas = linhas.head(limit)
    linhas = enrich_linhas_with_hash(linhas)
    catalog = enrich_unimed_catalog_with_hash(load_global_items(str(catalog_path)))
    fase1 = pd.read_csv(fase1_path)
    llm = pd.read_csv(llm_path)
    costs = linha_cost_stats(global_path)
    costs["linha_key"] = costs["linha_produto"].str.strip()

    truth_map = _ground_truth(fase1, llm)
    if "confianca" not in fase1.columns:
        fase1 = fase1.copy()
        fase1["confianca"] = fase1.apply(assign_confidence, axis=1)

    fase1_index = fase1.set_index(fase1["linha_produto"].str.strip())
    hints = {
        str(r["linha_produto"]).strip(): int(r["best_cod_item"])
        for _, r in fase1.iterrows()
        if pd.notna(r.get("best_cod_item"))
    }

    metrics = BenchmarkMetrics(n_linhas=len(linhas))
    metrics.hash_coverage = float(
        (linhas["medication_hash_id"].notna() & ~linhas["norm_skipped"]).mean()
    )
    metrics.unimed_hash_coverage = float(
        (catalog["medication_hash_id"].notna() & ~catalog["norm_skipped"]).mean()
    )

    detail_rows: list[dict] = []
    jsonl_records: list[dict] = []
    truth_in_topk = 0
    truth_hash = 0
    truth_all_three = 0
    truth_with_hash_available = 0
    false_hash = 0
    total_hash_signals = 0
    fuzzy_alta_ready = 0
    fuzzy_alta_n = 0

    for _, row in linhas.iterrows():
        linha = str(row["linha_produto"]).strip()
        linha_key = linha
        truth = truth_map.get(linha)
        source_hash = row.get("medication_hash_id")
        if pd.isna(source_hash):
            source_hash = None
        else:
            source_hash = str(source_hash)

        cost = _global_cost_for_linha(costs, linha_key)
        confianca = None
        if linha in fase1_index.index:
            confianca = fase1_index.loc[linha, "confianca"]
            if isinstance(confianca, pd.Series):
                confianca = confianca.iloc[0]

        candidates = build_enriched_candidates(
            linha_produto=linha,
            principio_ativo=str(row.get("principio_ativo", "")),
            source_hash=source_hash,
            global_cost=cost,
            catalog=catalog,
            top_k=top_k,
            hint_cod_item=hints.get(linha),
            hint_fuzzy_alta=(confianca == "alta"),
        )

        cod_set = {c.cod_item for c in candidates}
        truth_in_pool = truth is not None and truth in cod_set
        if truth is not None:
            metrics.n_with_truth += 1
            if truth_in_pool:
                truth_in_topk += 1
            truth_cand = next((c for c in candidates if c.cod_item == truth), None)
            if truth_cand:
                if truth_cand.hash_match:
                    truth_hash += 1
                if truth_cand.hash_match and truth_cand.fuzzy_alta and truth_cand.preco_ok:
                    truth_all_three += 1
                if source_hash:
                    truth_with_hash_available += 1

        for c in candidates:
            if c.hash_match:
                total_hash_signals += 1
                if truth is None or c.cod_item != truth:
                    false_hash += 1

        if confianca == "alta":
            fuzzy_alta_n += 1
            best = hints.get(linha)
            tagged = any(
                c.cod_item == best and c.fuzzy_alta for c in candidates if best is not None
            )
            if tagged:
                fuzzy_alta_ready += 1

        detail_rows.append(
            {
                "linha_produto": linha,
                "truth_cod_item": truth,
                "truth_in_topk": truth_in_pool,
                "n_candidates": len(candidates),
                "source_hash": source_hash,
                "confianca": confianca,
            }
        )

        if len(jsonl_records) < jsonl_sample_size:
            pres = normalize_clinical_text(linha, system="global", external_id=linha)
            jsonl_records.append(
                context_to_jsonl_record(linha, pres, candidates, truth_cod_item=truth)
            )

    if metrics.n_with_truth:
        metrics.truth_in_topk = truth_in_topk / metrics.n_with_truth
        metrics.truth_has_hash_signal = (
            truth_hash / truth_with_hash_available if truth_with_hash_available else 0.0
        )
        metrics.truth_has_all_three = truth_all_three / metrics.n_with_truth

    metrics.false_hash_signal_rate = (
        false_hash / total_hash_signals if total_hash_signals else 0.0
    )
    metrics.n_fuzzy_alta = fuzzy_alta_n
    metrics.fuzzy_alta_agent_ready = (
        fuzzy_alta_ready / fuzzy_alta_n if fuzzy_alta_n else 1.0
    )

    metrics.blocking_failures = _blocking_checks(metrics)
    metrics.go = not metrics.blocking_failures

    pd.DataFrame(detail_rows).to_csv(exports_dir / "signal_benchmark_detail.csv", index=False)
    with (exports_dir / "enriched_candidates_sample.jsonl").open("w", encoding="utf-8") as f:
        for rec in jsonl_records:
            f.write(dump_jsonl_record(rec) + "\n")

    _write_report(exports_dir / "medication_pilot_report.md", metrics)
    return metrics


def _blocking_checks(m: BenchmarkMetrics) -> list[str]:
    failures: list[str] = []
    if m.hash_coverage < 0.85:
        failures.append(f"hash_coverage {m.hash_coverage:.1%} < 85%")
    if m.truth_in_topk < 0.90:
        failures.append(f"truth_in_topk {m.truth_in_topk:.1%} < 90%")
    if m.false_hash_signal_rate > 0.05:
        failures.append(f"false_hash_signal_rate {m.false_hash_signal_rate:.1%} > 5%")
    if m.fuzzy_alta_agent_ready < 1.0:
        failures.append(
            f"fuzzy_alta_agent_ready {m.fuzzy_alta_agent_ready:.1%} < 100%"
        )
    return failures


def _write_report(path: Path, m: BenchmarkMetrics) -> None:
    decision = "**GO**" if m.go else "**NO-GO**"
    failures = "\n".join(f"- {f}" for f in m.blocking_failures) or "- (nenhuma)"
    body = f"""# Medication pilot — signal benchmark report

## Decisão: {decision}

## Métricas

| Métrica | Valor | Meta bloqueante |
|---------|-------|-----------------|
| hash_coverage (Global) | {m.hash_coverage:.1%} | ≥ 85% |
| unimed_hash_coverage | {m.unimed_hash_coverage:.1%} | — |
| truth_in_topk_with_signals | {m.truth_in_topk:.1%} | ≥ 90% |
| truth_has_hash_signal | {m.truth_has_hash_signal:.1%} | — |
| truth_has_all_three_signals | {m.truth_has_all_three:.1%} | — |
| false_hash_signal_rate | {m.false_hash_signal_rate:.1%} | ≤ 5% |
| fuzzy_alta_agent_ready | {m.fuzzy_alta_agent_ready:.1%} | 100% |

## Amostra

- Linhas avaliadas: {m.n_linhas}
- Linhas com ground truth: {m.n_with_truth}
- Linhas fuzzy alta na amostra: {m.n_fuzzy_alta}

## Falhas bloqueantes

{failures}

## Artefatos

- `signal_benchmark_detail.csv`
- `enriched_candidates_sample.jsonl`
"""
    path.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    run_benchmark(
        data_dir=Path("data/depara-unimed"),
        exports_dir=Path("exports"),
        limit=200,
    )
