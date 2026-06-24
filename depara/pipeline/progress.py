"""Progresso estruturado do pipeline — consumido pela API e UI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

ProgressCallback = Callable[["JobProgress"], None]


@dataclass(frozen=True)
class JobProgress:
    phase: str
    label: str
    percent: int = 0
    current: int | None = None
    total: int | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "phase": self.phase,
            "label": self.label,
            "percent": max(0, min(100, self.percent)),
        }
        if self.current is not None:
            out["current"] = self.current
        if self.total is not None:
            out["total"] = self.total
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class PhaseStep:
    phase: str
    label: str
    start: int
    end: int


def build_phase_plan(*, regenerate_fase1: bool, skip_spacy: bool, run_llm: bool) -> list[PhaseStep]:
    """Faixas de percentual por etapa, conforme opções do job."""
    steps: list[PhaseStep] = [PhaseStep("starting", "Iniciando pipeline…", 0, 3)]
    cursor = 3

    if regenerate_fase1:
        if skip_spacy:
            label = "Similaridade (fase 1, sem spaCy)…"
            span = 18
        else:
            label = "Similaridade (fase 1 + spaCy) — etapa mais lenta…"
            span = 32
        steps.append(PhaseStep("fase1", label, cursor, cursor + span))
        cursor += span

    if run_llm:
        steps.append(PhaseStep("match_llm", "Match clínico LLM…", cursor, cursor + 55))
        cursor += 55

    report_end = min(cursor + 10, 98)
    steps.append(PhaseStep("price_report", "Comparativo de preços…", cursor, report_end))
    steps.append(PhaseStep("summary", "Relatório HTML e resumo…", report_end, 100))
    return steps


def _lerp(start: int, end: int, ratio: float) -> int:
    return int(start + (end - start) * max(0.0, min(1.0, ratio)))


class ProgressReporter:
    """Mapeia eventos do pipeline para percentual global."""

    def __init__(
        self,
        plan: list[PhaseStep],
        callback: ProgressCallback | None = None,
    ) -> None:
        self._plan = {s.phase: s for s in plan}
        self._callback = callback

    def _emit(self, progress: JobProgress) -> None:
        if self._callback is not None:
            self._callback(progress)

    def phase(self, phase: str, *, detail: str | None = None) -> None:
        step = self._plan.get(phase)
        if step is None:
            return
        self._emit(
            JobProgress(
                phase=phase,
                label=step.label,
                percent=step.start,
                detail=detail,
            )
        )

    def phase_done(self, phase: str) -> None:
        step = self._plan.get(phase)
        if step is None:
            return
        self._emit(JobProgress(phase=phase, label=step.label, percent=step.end))

    def llm(self, done: int, total: int) -> None:
        step = self._plan.get("match_llm")
        if step is None or total <= 0:
            return
        pct = _lerp(step.start, step.end, done / total)
        detail = f"{done}/{total} linhas processadas"
        self._emit(
            JobProgress(
                phase="match_llm",
                label=step.label,
                percent=pct,
                current=done,
                total=total,
                detail=detail,
            )
        )
