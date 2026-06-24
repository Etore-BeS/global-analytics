#!/usr/bin/env python3
"""Regenera fase1_comparison.csv a partir da base Global custo/estoque.

Substitui o fase1 gerado sobre global_df.csv (~1.424 linhas) pelo universo
completo da planilha Base_PRODUTOS_CUSTO_ESTOQUE (~2.215 linhas clínicas),
habilitando match LLM nas linhas que ainda não passaram pelo agente.

Depois de rodar:
  uv run depara job --config configs/job_cost_stock_full.yaml
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from depara.fase1_similarity import detect_global_source_mode, method_summary, run_all_methods


def _compare_with_previous(fase1: pd.DataFrame, previous_path: Path) -> None:
    old = pd.read_csv(previous_path)
    old_keys = set(old["linha_produto"].str.strip())
    new_keys = set(fase1["linha_produto"].str.strip())
    added = new_keys - old_keys
    removed = old_keys - new_keys
    print(f"\nComparado com {previous_path.name}:")
    print(f"  linhas anteriores: {len(old_keys):,}")
    print(f"  linhas novas:      {len(new_keys):,}")
    print(f"  adicionadas:       {len(added):,}")
    print(f"  removidas:         {len(removed):,}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenera fase1_comparison.csv usando base custo/estoque Global",
    )
    parser.add_argument(
        "--global",
        dest="global_path",
        default="data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv",
        help="CSV/XLS Global (default: base custo/estoque 23062026)",
    )
    parser.add_argument(
        "--unimed",
        dest="unimed_path",
        default="data/depara-unimed/Curva ABC - CD 05.26.xlsx",
        help="Curva ABC Unimed",
    )
    parser.add_argument(
        "--output",
        default="data/depara-unimed/fase1_comparison.csv",
        help="Destino do pivot fase1",
    )
    parser.add_argument(
        "--matches-long",
        default="data/depara-unimed/fase1_matches_long.csv",
        help="Destino do CSV longo (1 linha por método × linha)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Copia o fase1 existente para .bak.<timestamp> antes de sobrescrever",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só conta linhas Global/Unimed, não roda similaridade",
    )
    parser.add_argument(
        "--skip-spacy",
        action="store_true",
        help="Pula match_spacy (só fuzz + tfidf; mais rápido, sem modelo pt_core_news_md)",
    )
    args = parser.parse_args()

    global_path = Path(args.global_path)
    if not global_path.exists():
        raise SystemExit(f"Arquivo Global não encontrado: {global_path}")

    mode = detect_global_source_mode(str(global_path))
    print(f"Global: {global_path} ({mode})")
    print(f"Unimed: {args.unimed_path}")

    out = Path(args.output)
    previous: Path | None = out if out.exists() else None
    if args.backup and previous is not None:
        bak = out.with_name(f"{out.stem}.bak.{datetime.now():%Y%m%d_%H%M%S}{out.suffix}")
        bak.write_bytes(out.read_bytes())
        print(f"Backup: {bak}")

    if args.dry_run:
        from depara.fase1_similarity import load_global_linhas, load_unimed_catalog_items

        n_global = len(load_global_linhas(str(global_path)))
        n_unimed = len(load_unimed_catalog_items(str(args.unimed_path)))
        print(f"\n[dry-run] {n_global:,} linhas Global × {n_unimed:,} itens Unimed")
        if previous is not None:
            linhas = load_global_linhas(str(global_path))
            _compare_with_previous(
                pd.DataFrame({"linha_produto": linhas["linha_produto"]}),
                previous,
            )
        return

    methods = "fuzz + tfidf" + ("" if args.skip_spacy else " + spacy")
    print(f"Rodando similaridade ({methods}) — pode levar alguns minutos…")
    matches_long, fase1 = run_all_methods(
        str(global_path),
        str(args.unimed_path),
        skip_spacy=args.skip_spacy,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    fase1.to_csv(out, index=False)

    matches_path = Path(args.matches_long)
    matches_path.parent.mkdir(parents=True, exist_ok=True)
    matches_long.to_csv(matches_path, index=False)

    print(f"\nExportado: {len(fase1):,} linhas → {out}")
    print(f"Matches long: {len(matches_long):,} → {matches_path}")
    print("\nConfiança:")
    print(fase1["confianca"].value_counts().to_string())
    print("\nResumo por método:")
    print(method_summary(fase1).to_string(index=False))

    if previous is not None and not args.backup:
        _compare_with_previous(fase1, previous)
    elif previous is not None:
        bak_guess = sorted(out.parent.glob(f"{out.stem}.bak.*{out.suffix}"))[-1]
        _compare_with_previous(fase1, bak_guess)

    print(
        "\nPróximo passo:\n"
        "  uv run depara job --config configs/job_cost_stock_full.yaml"
    )


if __name__ == "__main__":
    main()
