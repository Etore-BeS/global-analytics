"""Estimativas de tempo e formatação de progresso na UI."""

from __future__ import annotations

from depara.api.progress import coerce_progress
from depara.api.schemas import JobStatusResponse

POLL_INTERVAL_SEC = 2.0
MAX_WAIT_MINUTES = 30
MAX_JOB_POLLS = int(MAX_WAIT_MINUTES * 60 / POLL_INTERVAL_SEC)


def estimate_duration_seconds(
    *,
    regenerate_fase1: bool,
    skip_spacy: bool,
    run_llm: bool,
    subject_rows: int | None = None,
) -> tuple[int, int]:
    """Retorna (mínimo, máximo) em segundos para orientar o usuário."""
    rows = subject_rows or 400
    lo, hi = 60, 150

    if regenerate_fase1:
        if skip_spacy:
            lo += 90 + rows // 25
            hi += 240 + rows // 10
        else:
            lo += 420 + rows // 8
            hi += 1200 + rows // 3

    if run_llm:
        pending = max(40, rows // 4)
        lo += pending * 2
        hi += pending * 10

    lo = min(lo, MAX_WAIT_MINUTES * 60 - 30)
    hi = min(hi, MAX_WAIT_MINUTES * 60)
    return lo, max(lo + 30, hi)


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min" if secs == 0 else f"{minutes} min {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins} min" if mins else f"{hours}h"


def format_duration_range(lo: int, hi: int) -> str:
    if hi - lo <= 45:
        return f"~{format_duration((lo + hi) // 2)}"
    return f"{format_duration(lo)} – {format_duration(hi)}"


def estimate_caption(
    *,
    regenerate_fase1: bool,
    skip_spacy: bool,
    run_llm: bool,
    subject_rows: int | None = None,
) -> str:
    lo, hi = estimate_duration_seconds(
        regenerate_fase1=regenerate_fase1,
        skip_spacy=skip_spacy,
        run_llm=run_llm,
        subject_rows=subject_rows,
    )
    parts = [f"Tempo estimado: **{format_duration_range(lo, hi)}**."]
    if regenerate_fase1 and not skip_spacy:
        parts.append("Regenerar fase 1 com spaCy costuma ser a etapa mais longa (até ~20 min).")
    elif run_llm:
        parts.append("Match LLM depende do número de linhas pendentes e da API (até ~30 min).")
    else:
        parts.append("Sem LLM nem spaCy, costuma ficar pronto em poucos minutos.")
    parts.append(f"A tela acompanha por até **{MAX_WAIT_MINUTES} min**.")
    return " ".join(parts)


def _normalized_progress(job: JobStatusResponse):
    return coerce_progress(job.progress)


def progress_percent(job: JobStatusResponse) -> int:
    progress = _normalized_progress(job)
    if progress and progress.percent is not None:
        return max(0, min(100, progress.percent))
    if job.status == "completed":
        return 100
    return 0


def progress_label(job: JobStatusResponse) -> str:
    progress = _normalized_progress(job)
    if progress and progress.label:
        return progress.label
    if job.status == "queued":
        return "Na fila…"
    if job.status == "running":
        return "Processando…"
    return job.status


def progress_detail(job: JobStatusResponse) -> str | None:
    progress = _normalized_progress(job)
    if not progress:
        return None
    if progress.detail:
        return progress.detail
    if progress.current is not None and progress.total is not None:
        return f"{progress.current}/{progress.total}"
    return None


def elapsed_seconds(created_at: str | None, now_ts: float) -> int | None:
    if not created_at:
        return None
    try:
        from datetime import UTC, datetime

        started = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return max(0, int(now_ts - started.timestamp()))
    except (ValueError, TypeError):
        return None


def eta_seconds(elapsed: int | None, percent: int) -> int | None:
    if elapsed is None or percent < 8:
        return None
    remaining = int(elapsed * (100 - percent) / percent)
    return max(0, remaining)
