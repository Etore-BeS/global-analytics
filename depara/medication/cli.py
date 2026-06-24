"""CLI for medication contract pilot."""

from __future__ import annotations

from pathlib import Path

import click
from depara.fase1_similarity import load_global_items, load_global_linhas
from depara.medication.enrich import enrich_linhas_with_hash, enrich_unimed_catalog_with_hash
from depara.medication.normalizer import normalize_clinical_text


@click.group()
def cli() -> None:
    """Medication hash pilot — normalize, enrich, benchmark signals."""


@cli.command("sample")
@click.option("--limit", default=10, show_default=True)
def sample_cmd(limit: int) -> None:
    """Print normalization samples from global linhas."""
    path = Path("data/depara-unimed/global_df.csv")
    linhas = load_global_linhas(str(path)).head(limit)
    for _, row in linhas.iterrows():
        pres = normalize_clinical_text(
            str(row["linha_produto"]),
            system="global",
            external_id=str(row["linha_produto"]).strip(),
        )
        click.echo(f"\n--- {row['linha_produto'][:70]}")
        click.echo(f"hash: {pres.medication_hash_id}")
        click.echo(f"pa: {pres.medication_normalized} | form: {pres.form_normalized}")
        click.echo(f"route: {pres.route_normalized} | skipped: {pres.skipped}")


@cli.command("enrich-linhas")
@click.option("--input", "input_path", default="data/depara-unimed/global_df.csv")
@click.option("--output", "output_path", default="exports/linhas_with_hash.csv")
def enrich_linhas_cmd(input_path: str, output_path: str) -> None:
    """Enrich Global clinical lines with medication hash columns."""
    linhas = load_global_linhas(input_path)
    out = enrich_linhas_with_hash(linhas)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, index=False)
    covered = out["medication_hash_id"].notna() & ~out["norm_skipped"]
    click.echo(f"Wrote {len(out)} rows → {dest}")
    click.echo(f"hash_coverage: {covered.mean():.1%}")


@cli.command("enrich-unimed")
@click.option("--input", "input_path", default="data/depara-unimed/Curva ABC - CD 05.26.xlsx")
@click.option("--output", "output_path", default="exports/unimed_with_hash.csv")
def enrich_unimed_cmd(input_path: str, output_path: str) -> None:
    """Enrich Unimed catalog with medication hash columns."""
    catalog = load_global_items(input_path)
    out = enrich_unimed_catalog_with_hash(catalog)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, index=False)
    covered = out["medication_hash_id"].notna() & ~out["norm_skipped"]
    click.echo(f"Wrote {len(out)} rows → {dest}")
    click.echo(f"unimed_hash_coverage: {covered.mean():.1%}")


@cli.command("benchmark-signals")
@click.option("--limit", default=0, help="Max linhas (0 = all)")
@click.option("--data-dir", default="data/depara-unimed")
@click.option("--exports-dir", default="exports")
def benchmark_signals_cmd(limit: int, data_dir: str, exports_dir: str) -> None:
    """Run offline signal quality benchmark."""
    from scripts.benchmark_signal_pilot import run_benchmark

    run_benchmark(
        data_dir=Path(data_dir),
        exports_dir=Path(exports_dir),
        limit=limit or None,
    )


if __name__ == "__main__":
    cli()
