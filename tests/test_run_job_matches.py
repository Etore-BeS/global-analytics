"""Garantia de matches.csv quando skip_match ou regenerate fase1."""

from __future__ import annotations

from pathlib import Path

import pytest
from depara.api.schemas import JobCreateConfig, SideRequest
from depara.api.storage import create_job
from depara.pipeline.run_job import DEFAULT_MATCHES, ensure_matches_file

COST_STOCK = Path("data/depara-unimed/Base_PRODUTOS_CUSTO_ESTOQUE_23062026.csv")
UNIMED = Path("data/depara-unimed/Curva ABC - CD 05.26.xlsx")

pytestmark = pytest.mark.skipif(
    not COST_STOCK.exists() or not UNIMED.exists() or not DEFAULT_MATCHES.exists(),
    reason="Fixtures Global×Unimed ausentes",
)


def test_ensure_matches_file_copies_seed(tmp_path: Path) -> None:
    dest = tmp_path / "job" / "matches.csv"
    ensure_matches_file(dest)
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == DEFAULT_MATCHES.read_text(encoding="utf-8")


def test_create_job_regenerate_skip_match_seeds_matches(tmp_path: Path, monkeypatch) -> None:
    jobs_root = tmp_path / "jobs"
    monkeypatch.setattr("depara.api.storage.JOBS_ROOT", jobs_root)
    cfg = JobCreateConfig(
        subject=SideRequest(template="global_cost_stock"),
        reference=SideRequest(template="unimed_abc"),
        match={"skip_match": True},
        fase1={"regenerate": True, "skip_spacy": True},
    )
    record = create_job(cfg, COST_STOCK, UNIMED)
    matches = record.job_dir / "matches.csv"
    assert matches.exists(), "regenerate fase1 + skip_match deve copiar matches seed"
