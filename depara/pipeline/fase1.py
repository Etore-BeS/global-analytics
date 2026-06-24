"""Regeneração de fase1 a partir de SideConfig."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from depara.contract.ingest import ingest_side_a_linhas, ingest_side_b
from depara.contract.models import JobConfig
from depara.fase1_similarity import run_all_methods

logger = logging.getLogger(__name__)


def regenerate_fase1(
    config: JobConfig,
    fase1_path: Path,
    *,
    matches_long_path: Path | None = None,
) -> pd.DataFrame:
    """Gera fase1_comparison.csv usando ingest agnóstico de subject × reference."""
    global_linhas = ingest_side_a_linhas(config.side_a)
    unimed_items = ingest_side_b(config.side_b)

    matches_long, fase1 = run_all_methods(
        global_linhas=global_linhas,
        unimed_items=unimed_items,
        skip_spacy=config.fase1.skip_spacy,
    )

    fase1_path.parent.mkdir(parents=True, exist_ok=True)
    fase1.to_csv(fase1_path, index=False)
    logger.info("fase1 exportado: %s linhas → %s", len(fase1), fase1_path)

    if matches_long_path is not None:
        matches_long_path.parent.mkdir(parents=True, exist_ok=True)
        matches_long.to_csv(matches_long_path, index=False)
        logger.info("matches long: %s → %s", len(matches_long), matches_long_path)

    return fase1
