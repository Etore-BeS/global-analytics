"""Testes de estimativa e formatação de progresso na UI."""

from __future__ import annotations

from depara.api.progress import JobProgressInfo
from depara.api.schemas import JobStatusResponse
from depara.ui.job_progress import (
    MAX_JOB_POLLS,
    MAX_WAIT_MINUTES,
    estimate_caption,
    estimate_duration_seconds,
    format_duration_range,
    progress_label,
    progress_percent,
)


def test_max_polls_covers_30_minutes() -> None:
    assert MAX_JOB_POLLS * 2 >= MAX_WAIT_MINUTES * 60


def test_estimate_duration_increases_with_heavy_options() -> None:
    quick = estimate_duration_seconds(
        regenerate_fase1=False,
        skip_spacy=True,
        run_llm=False,
        subject_rows=200,
    )
    heavy = estimate_duration_seconds(
        regenerate_fase1=True,
        skip_spacy=False,
        run_llm=True,
        subject_rows=800,
    )
    assert heavy[1] > quick[1]


def test_format_duration_range() -> None:
    assert "min" in format_duration_range(90, 600)


def test_progress_percent_from_structured() -> None:
    job = JobStatusResponse(
        job_id="abc",
        status="running",
        progress=JobProgressInfo(
            phase="match_llm",
            label="Match LLM",
            percent=42,
            current=21,
            total=50,
        ),
    )
    assert progress_percent(job) == 42


def test_progress_percent_from_legacy_string() -> None:
    job = JobStatusResponse(
        job_id="abc",
        status="running",
        progress="pipeline",  # type: ignore[arg-type]
    )
    assert progress_percent(job) == 45
    assert progress_label(job) == "Processando pipeline…"


def test_estimate_caption_mentions_wait_limit() -> None:
    text = estimate_caption(
        regenerate_fase1=False,
        skip_spacy=True,
        run_llm=False,
        subject_rows=100,
    )
    assert "30 min" in text
    assert "Tempo estimado" in text
