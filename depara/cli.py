"""CLI para testar e rodar o depara LLM em produção."""

from __future__ import annotations

import asyncio
import json

import click
import pandas as pd

from depara.llm.candidates import LLM_ALL_CONFIDENCA
from depara.llm.config import DeparaLLMSettings
from depara.llm.matcher import LLMMatcher
from depara.llm.priority import build_priority_queue


def _resolve_confidence(
    *,
    confianca_filter: str | None,
    run_all: bool,
    default: str | None = "revisar",
) -> tuple[str | None, bool]:
    if run_all and confianca_filter:
        raise click.ClickException("--all e --filter são mutuamente exclusivos.")
    if run_all:
        return None, True
    return confianca_filter if confianca_filter is not None else default, False


@click.group()
def cli() -> None:
    """Depara Unimed ↔ Global via LLM (pydantic-ai)."""


@cli.command("test")
@click.option("--limit", default=5, show_default=True, help="Número de linhas clínicas")
@click.option(
    "--filter",
    "confianca_filter",
    type=click.Choice(["alta", "media", "baixa", "revisar"]),
    default=None,
    help="Filtrar por confiança da fase 1 (fuzzy)",
)
@click.option("--all", "run_all", is_flag=True, help="LLM em media+baixa+revisar (pula alta)")
@click.option("--no-cache", is_flag=True, help="Ignorar cache SQLite")
def test_match(
    limit: int,
    confianca_filter: str | None,
    run_all: bool,
    no_cache: bool,
) -> None:
    """Roda em modo test (TestModel, sem API) para validar pipeline."""
    cf, ca = _resolve_confidence(confianca_filter=confianca_filter, run_all=run_all, default=None)
    settings = DeparaLLMSettings(mode="test")
    matcher = LLMMatcher(settings)
    df = matcher.run_batch(
        limit=limit,
        confianca_filter=cf,
        confianca_all=ca,
        use_cache=not no_cache,
    )
    click.echo(f"Processadas {len(df)} linhas → {settings.output_path}")
    for _, row in df.iterrows():
        click.echo(
            f"\n  {row['linha_produto'][:60]}\n"
            f"  → {row['decision']} cod={row['cod_item']} conf={row['confidence']:.2f}\n"
            f"  {row['reasoning'][:100]}"
        )


@cli.command("estimate")
@click.option("--limit", default=None, type=int, help="N linhas (default: todas revisar)")
@click.option(
    "--filter",
    "confianca_filter",
    type=click.Choice(["alta", "media", "baixa", "revisar"]),
    default=None,
    show_default="revisar",
)
@click.option("--all", "run_all", is_flag=True, help="Estimar media+baixa+revisar (pula alta)")
@click.option("--model", default=None, help="Override DEPARA_MODEL para precificação")
def estimate_cost(
    limit: int | None,
    confianca_filter: str | None,
    run_all: bool,
    model: str | None,
) -> None:
    """Estima consumo de tokens e custo USD antes de rodar o LLM."""
    cf, ca = _resolve_confidence(confianca_filter=confianca_filter, run_all=run_all)
    import statistics

    from depara.fase1_similarity import load_global_items, load_global_linhas
    from depara.llm.agent import SYSTEM_PROMPT, build_user_prompt
    from depara.llm.candidates import (
        format_candidates_prompt,
        format_unimed_prompt,
        retrieve_candidates,
    )
    from depara.llm.priority import assign_confidence
    from depara.llm.schemas import UnimedLinhaInput, parse_list_field

    settings = DeparaLLMSettings()
    model_name = (model or settings.model).split(":")[-1]

    prices = {
        "gpt-5-nano": (0.05, 0.40),
        "gpt-5-mini": (0.25, 2.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
    }
    if model_name not in prices:
        click.echo(f"Modelo {model_name!r} sem tabela de preço — usando gpt-5-mini.")
        model_name = "gpt-5-mini"

    try:
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        count = lambda s: len(enc.encode(s))
    except ImportError:
        count = lambda s: len(s) // 4

    global_linhas = load_global_linhas(str(settings.global_distribuidor_path))
    unimed_items = load_global_items(str(settings.unimed_catalogo_path))
    fase1 = pd.read_csv(settings.output_path.parent / "fase1_comparison.csv")
    if "confianca" not in fase1.columns:
        fase1["confianca"] = fase1.apply(assign_confidence, axis=1)
    unimed = global_linhas.merge(fase1[["linha_produto", "confianca"]], on="linha_produto")
    if ca:
        unimed = unimed[unimed["confianca"].isin(LLM_ALL_CONFIDENCA)]
    elif cf:
        unimed = unimed[unimed["confianca"] == cf]

    hints = {
        str(r["linha_produto"]).strip(): int(r["best_cod_item"])
        for _, r in fase1.iterrows()
        if pd.notna(r.get("best_cod_item"))
    }

    scope = "all (media+baixa+revisar)" if ca else (cf or "revisar")

    if limit is not None:
        unimed = unimed.head(limit)

    n = len(unimed)
    system_toks = count(SYSTEM_PROMPT)
    user_toks = []
    for _, row in unimed.iterrows():
        item = UnimedLinhaInput(
            linha_produto=str(row["linha_produto"]),
            principio_ativo=str(row["principio_ativo"]),
            n_skus=int(row["n_skus"]),
            marcas=parse_list_field(row["marcas"]),
        )
        cands = retrieve_candidates(
            item,
            unimed_items,
            top_k=settings.top_k_candidates,
            hint_cod_item=hints.get(item.linha_produto.strip()),
        )
        prompt = build_user_prompt(
            format_unimed_prompt(item), format_candidates_prompt(cands)
        )
        user_toks.append(count(prompt))

    out_toks = 240  # JSON estruturado + overhead tool calling
    avg_in = system_toks + statistics.mean(user_toks)
    total_in = avg_in * n
    total_out = out_toks * n

    pin, pout = prices[model_name]
    cost_usd = total_in / 1e6 * pin + total_out / 1e6 * pout
    cost_retries = cost_usd * 2  # agent retries=2

    click.echo(
        f"Modelo: {model_name}  |  escopo: {scope}  |  linhas: {n}  |  "
        f"top_k: {settings.top_k_candidates}"
    )
    click.echo(f"Tokens/linha: ~{avg_in + out_toks:.0f}  (in ~{avg_in:.0f} + out ~{out_toks})")
    click.echo(f"Total estimado: ~{total_in + total_out:,.0f} tokens")
    click.echo(f"Custo estimado: ~${cost_usd:.3f} USD  (com retries: ~${cost_retries:.3f})")
    click.echo(f"\nReferência rápida ({model_name}):")
    for ref_n in [10, 25, 50, 100]:
        ref_cost = (avg_in * ref_n / 1e6 * pin) + (out_toks * ref_n / 1e6 * pout)
        click.echo(f"  {ref_n:>3} linhas ≈ ${ref_cost:.3f}")


@cli.command("priority")
@click.option("--filter", "confianca_filter", type=click.Choice(["alta", "media", "baixa", "revisar"]), default=None)
@click.option("--limit", default=30, show_default=True)
def show_priority(confianca_filter: str | None, limit: int) -> None:
    """Lista fila de execução com preços (Prev Mês Global × incerteza fuzzy)."""
    settings = DeparaLLMSettings()
    fase1_path = settings.output_path.parent / "fase1_comparison.csv"
    done = LLMMatcher._completed_linhas(settings.output_path)

    queue = build_priority_queue(
        settings.global_distribuidor_path,
        settings.unimed_catalogo_path,
        fase1_path,
        already_done=done,
    )
    if confianca_filter:
        queue = queue[queue["confianca"] == confianca_filter]
    pending = queue[~queue["ja_rodou_llm"]].head(limit)

    out = settings.output_path.parent / "fase1_llm_priority.csv"
    queue.to_csv(out, index=False)
    click.echo(f"Fila completa → {out} ({len(queue)} linhas)\n")
    click.echo(f"Top {len(pending)} pendentes por prioridade:\n")
    for _, r in pending.iterrows():
        click.echo(
            f"  prio={r['prioridade']:>8,.0f}  R${r['prev_mes_rs']:>8,.0f} ABC={r['abc']}  "
            f"fuzz={r['fuzz_token_set']:.2f}  U R${r['custo_medio']:.2f}  "
            f"{r['linha_key'][:50]}"
        )


@cli.command("clear-cache")
def clear_cache() -> None:
    """Limpa cache SQLite (necessário após falhas de validação)."""
    settings = DeparaLLMSettings()
    if settings.cache_path.exists():
        settings.cache_path.unlink()
        click.echo(f"Cache removido: {settings.cache_path}")
    else:
        click.echo("Cache não existe.")


@cli.command("run")
@click.option("--limit", default=None, type=int, help="Limitar linhas (None = todas)")
@click.option(
    "--filter",
    "confianca_filter",
    type=click.Choice(["alta", "media", "baixa", "revisar"]),
    default=None,
    show_default="revisar",
)
@click.option("--all", "run_all", is_flag=True, help="LLM em media+baixa+revisar (pula alta)")
@click.option("--model", default=None, help="Override DEPARA_MODEL")
@click.option("--no-cache", is_flag=True, help="Ignorar cache SQLite")
@click.option("--order", type=click.Choice(["priority", "alpha"]), default="priority", show_default=True)
def run_match(
    limit: int | None,
    confianca_filter: str | None,
    run_all: bool,
    model: str | None,
    no_cache: bool,
    order: str,
) -> None:
    """Roda match LLM em produção (requer API key configurada)."""
    cf, ca = _resolve_confidence(confianca_filter=confianca_filter, run_all=run_all)
    settings = DeparaLLMSettings(mode="prod")
    if model:
        settings = settings.model_copy(update={"model": model})
    matcher = LLMMatcher(settings)
    df = matcher.run_batch(
        limit=limit,
        confianca_filter=cf,
        confianca_all=ca,
        use_cache=not no_cache,
        order=order,
    )
    batch_n = limit if limit is not None else len(df)
    batch = df.tail(batch_n)
    matched = (batch["decision"] == "match").sum()
    scope = "all (media+baixa+revisar)" if ca else (cf or "revisar")
    click.echo(
        f"Concluído [{scope}]: {len(batch)} linhas neste batch | {matched} matches | "
        f"export → {settings.output_path}"
    )


@cli.command("one")
@click.argument("linha_produto")
@click.option("--model", default=None)
def match_one(linha_produto: str, model: str | None) -> None:
    """Testa uma linha clínica específica (modo prod)."""
    settings = DeparaLLMSettings(mode="prod")
    if model:
        settings = settings.model_copy(update={"model": model})
    matcher = LLMMatcher(settings)

    row = matcher.unimed_linhas[
        matcher.unimed_linhas["linha_produto"].str.contains(
            linha_produto, case=False, na=False
        )
    ].head(1)
    if row.empty:
        raise click.ClickException(f"Linha não encontrada: {linha_produto!r}")

    item = matcher._row_to_input(row.iloc[0])
    record = asyncio.run(matcher.match_one(item, use_cache=False))
    click.echo(json.dumps(record.model_dump(), indent=2, ensure_ascii=False))


@cli.command("prices")
@click.option(
    "--output",
    default="data/depara-unimed/fase2_price_report",
    show_default=True,
    help="Path base (gera .csv, .xlsx e fase2_price_sku.csv)",
)
def price_report(output: str) -> None:
    """Fase 2: comparativo preço Global (distribuidor) vs Unimed (compras)."""
    from pathlib import Path

    from depara.fase2_prices import export_price_report, readiness_summary
    from depara.sources import GLOBAL_DISTRIBUIDOR, UNIMED_COMPRAS

    settings = DeparaLLMSettings()
    base = settings.output_path.parent
    summary = readiness_summary(
        settings.global_compras_path,
        base / "fase1_comparison.csv",
        settings.output_path,
    )

    click.echo("=== Prontidão fase 2 ===")
    click.echo(f"  Global (distribuidor): {GLOBAL_DISTRIBUIDOR['arquivo']} [{GLOBAL_DISTRIBUIDOR['coluna_preco']}]")
    click.echo(f"  Unimed (compras):      {UNIMED_COMPRAS['arquivo']} [{UNIMED_COMPRAS['coluna_preco']}]")
    for k, v in summary.items():
        click.echo(f"  {k}: {v}")

    if summary["faltando_processar"] > 0:
        click.echo(
            f"\n⚠ {summary['faltando_processar']} linha(s) sem LLM nem fuzzy alta — "
            "seguindo com cobertura parcial."
        )

    out = Path(output)
    linha, sku = export_price_report(
        settings.global_compras_path,
        settings.unimed_catalogo_path,
        base / "fase1_comparison.csv",
        settings.output_path,
        out,
    )

    global_mais_caro = (linha["gap_global_custo_ultimo_pct"] > 0).sum()
    global_mais_barato = (linha["gap_global_custo_ultimo_pct"] < 0).sum()
    med_gap = linha["gap_global_custo_ultimo_pct"].median()

    click.echo(f"\n=== Relatório gerado ===")
    click.echo(f"  Linhas Global (dist.) com depara Unimed: {len(linha)}")
    click.echo(f"  SKUs/marcas Global detalhados:          {len(sku)}")
    click.echo(f"  Global > Unimed (último):               {global_mais_caro}")
    click.echo(f"  Global < Unimed (último):               {global_mais_barato}")
    click.echo(f"  Gap mediano (último):                   {med_gap:.1f}%")
    click.echo(f"\n  → {out.with_suffix('.csv')} (colunas legíveis + fonte)")
    click.echo(f"  → {out.with_suffix('.xlsx')} (aba Legenda + preços)")
    click.echo(f"  → {out.parent / 'fase2_price_sku.csv'}")


@cli.command("reanalyze-prices")
@click.option(
    "--input",
    "price_report",
    default="data/depara-unimed/fase2_price_report.csv",
    show_default=True,
)
@click.option("--limit", default=None, type=int, help="Limitar linhas (default: todas incompatíveis)")
@click.option("--top-k", default=None, type=int, help="Override DEPARA_REANALYZE_TOP_K")
@click.option("--model", default=None, help="Override DEPARA_REANALYZE_MODEL (default: gpt-4o)")
@click.option("--no-cache", is_flag=True, help="Ignorar cache SQLite")
@click.option("--no-merge", is_flag=True, help="Não atualizar fase1_llm_matches.csv")
@click.option("--regenerate-report", is_flag=True, help="Rodar prices + report ao final")
def reanalyze_prices(
    price_report: str,
    limit: int | None,
    top_k: int | None,
    model: str | None,
    no_cache: bool,
    no_merge: bool,
    regenerate_report: bool,
) -> None:
    """Reanalisa depara de linhas com preço incompatível (modelo/prompt/top_k maiores)."""
    from pathlib import Path

    from depara.llm.reanalyze import PriceReanalyzer, load_price_incompatible_lines
    from depara.price_sanity import enrich_price_report

    settings = DeparaLLMSettings(mode="prod")
    if model:
        settings = settings.model_copy(update={"reanalyze_model": model})
    if top_k:
        settings = settings.model_copy(update={"reanalyze_top_k": top_k})

    path = Path(price_report)
    pending = load_price_incompatible_lines(path, limit=limit)
    click.echo(
        f"Reanálise de preço: {len(pending)} linhas | modelo={settings.reanalyze_model} | "
        f"top_k={settings.reanalyze_top_k}"
    )

    reanalyzer = PriceReanalyzer(settings)
    df = reanalyzer.run_batch(
        path,
        limit=limit,
        top_k=top_k,
        use_cache=not no_cache,
        merge_into_matches=not no_merge,
    )

    matched = (df["decision"] == "match").sum()
    no_match = (df["decision"] == "no_match").sum()
    click.echo(f"Concluído: {matched} match | {no_match} no_match → fase1_llm_reanalyze.csv")
    if not no_merge:
        click.echo("  fase1_llm_matches.csv atualizado (run_pass=reanalyze_price)")

    base = settings.output_path.parent
    if regenerate_report:
        from depara.fase2_prices import export_price_report
        from depara.report_html import generate_html_report

        out = base / "fase2_price_report"
        export_price_report(
            settings.global_compras_path,
            settings.unimed_catalogo_path,
            base / "fase1_comparison.csv",
            settings.output_path,
            out,
        )
        generate_html_report(out.with_suffix(".csv"), out.with_suffix(".html"))
        click.echo("  fase2_price_report.csv/.html regenerados")
        check = enrich_price_report(pd.read_csv(out.with_suffix(".csv")))
        still = int((~check["preco_depara_ok"]).sum())
        click.echo(f"  Depara incompatível restante: {still}")


@cli.command("report")
@click.option(
    "--input",
    "csv_path",
    default="data/depara-unimed/fase2_price_report.csv",
    show_default=True,
)
@click.option(
    "--output",
    default="data/depara-unimed/fase2_price_report.html",
    show_default=True,
)
def html_report(csv_path: str, output: str) -> None:
    """Gera relatório HTML interativo a partir do CSV de preços."""
    from pathlib import Path

    from depara.report_html import generate_html_report

    out = generate_html_report(Path(csv_path), Path(output))
    click.echo(f"Relatório HTML → {out}")


if __name__ == "__main__":
    cli()
