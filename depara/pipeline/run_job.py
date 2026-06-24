"""Orquestração end-to-end do depara (sem API)."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from depara.contract.config_loader import load_job_config
from depara.contract.ingest import apply_job_paths
from depara.contract.models import JobConfig
from depara.fase2_prices import export_price_report, readiness_summary
from depara.llm.config import DeparaLLMSettings
from depara.llm.matcher import LLMMatcher
from depara.pipeline.fase1 import regenerate_fase1
from depara.pipeline.progress import ProgressCallback, ProgressReporter, build_phase_plan
from depara.pipeline.summary import build_summary, write_summary
from depara.report_html import generate_html_report

logger = logging.getLogger(__name__)

DEFAULT_MATCHES = Path("data/depara-unimed/fase1_llm_matches.csv")


def ensure_matches_file(matches_path: Path) -> None:
    """Garante matches.csv — necessário mesmo com skip_match (reutiliza seed global)."""
    if matches_path.exists():
        return
    if DEFAULT_MATCHES.exists():
        matches_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_MATCHES, matches_path)
        logger.info("matches.csv ausente — copiado de %s", DEFAULT_MATCHES)
        return
    raise FileNotFoundError(
        f"matches.csv não encontrado em {matches_path} e seed {DEFAULT_MATCHES} "
        "também ausente. Rode match LLM ou forneça um CSV de matches."
    )


@dataclass(frozen=True)
class JobResult:
    output_dir: Path
    matches_path: Path
    price_report_csv: Path
    summary_path: Path
    readiness: dict


def _settings_from_config(config: JobConfig, paths: dict[str, Path]) -> DeparaLLMSettings:
    updates: dict = {
        "global_distribuidor_path": paths["side_a_path"],
        "unimed_catalogo_path": paths["side_b_path"],
        "output_path": paths["matches_path"],
    }
    if config.side_a.catalog_enrichment:
        updates["global_catalog_path"] = config.side_a.catalog_enrichment
    if config.match.model:
        updates["model"] = config.match.model
    return DeparaLLMSettings(mode="prod").model_copy(update=updates)


def run_job(config: JobConfig, *, on_progress: ProgressCallback | None = None) -> JobResult:
    paths = apply_job_paths(config)
    settings = _settings_from_config(config, paths)
    settings.ensure_dirs()

    reporter = ProgressReporter(
        build_phase_plan(
            regenerate_fase1=config.fase1.regenerate,
            skip_spacy=config.fase1.skip_spacy,
            run_llm=not config.match.skip_match,
        ),
        on_progress,
    )
    reporter.phase("starting")

    fase1_path = paths["fase1_path"]
    if config.fase1.regenerate:
        reporter.phase("fase1")
        regenerate_fase1(
            config,
            fase1_path,
            matches_long_path=paths["output_dir"] / "fase1_matches_long.csv",
        )
        reporter.phase_done("fase1")
    elif not fase1_path.exists():
        default_fase1 = Path("data/depara-unimed/fase1_comparison.csv")
        if default_fase1.exists():
            fase1_path = default_fase1
        else:
            raise FileNotFoundError(
                f"fase1_comparison.csv não encontrado em {fase1_path} "
                "— rode fase1, defina fase1.regenerate=true ou aponte fase1_path."
            )

    if not config.match.skip_match:
        matcher = LLMMatcher(settings)
        pending = matcher._select_linhas(
            limit=config.match.limit,
            confianca_filter=config.match.confianca_filter,
            confianca_all=config.match.run_all,
            order="priority",
        )
        n = len(pending)
        logger.info(
            "Match LLM: %s linha(s) pendente(s) · modelo=%s",
            n,
            settings.model,
        )
        reporter.phase("match_llm", detail=f"0/{n} linhas" if n else None)
        if n == 0:
            logger.info("Nenhuma linha pendente — pulando match.")
        else:

            def _llm_progress(done: int, total: int, _record) -> None:
                reporter.llm(done, total)

            matcher.run_batch(
                limit=config.match.limit,
                confianca_filter=config.match.confianca_filter,
                confianca_all=config.match.run_all,
                use_cache=config.match.use_cache,
                merge_into_output=True,
                _preselected=pending,
                on_progress=_llm_progress,
            )
        reporter.phase_done("match_llm")
        logger.info("Match concluído — gerando relatório de preços…")

    ensure_matches_file(paths["matches_path"])

    reporter.phase("price_report")
    catalog = (
        None
        if config.side_a.template == "global_cost_stock"
        else config.side_a.catalog_enrichment or settings.global_catalog_path
    )
    linha, _sku = export_price_report(
        settings.global_compras_path,
        settings.unimed_catalogo_path,
        fase1_path,
        paths["matches_path"],
        paths["price_report_base"],
        catalog_path=catalog if catalog and Path(catalog).exists() else None,
        side=config.side_a,
    )

    reporter.phase_done("price_report")

    reporter.phase("summary")
    html_path = paths["price_report_base"].with_suffix(".html")
    generate_html_report(
        paths["price_report_base"].with_suffix(".csv"),
        html_path,
        unimed_catalog_path=settings.unimed_catalogo_path,
    )

    readiness = readiness_summary(
        settings.global_compras_path,
        fase1_path,
        paths["matches_path"],
        side=config.side_a,
    )
    summary = build_summary(
        price_report=linha,
        matches_path=paths["matches_path"],
        global_compras_path=settings.global_compras_path,
        fase1_path=fase1_path,
        readiness=readiness,
    )
    summary_path = write_summary(paths["output_dir"] / "summary.json", summary)
    reporter.phase_done("summary")

    return JobResult(
        output_dir=paths["output_dir"],
        matches_path=paths["matches_path"],
        price_report_csv=paths["price_report_base"].with_suffix(".csv"),
        summary_path=summary_path,
        readiness=readiness,
    )


def run_job_from_config_path(config_path: Path) -> JobResult:
    return run_job(load_job_config(config_path))
