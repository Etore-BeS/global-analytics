"""Testes do plano de fases do pipeline."""

from __future__ import annotations

from depara.pipeline.progress import ProgressReporter, build_phase_plan


def test_build_phase_plan_skips_optional_steps() -> None:
    plan = build_phase_plan(regenerate_fase1=False, skip_spacy=True, run_llm=False)
    phases = [s.phase for s in plan]
    assert "fase1" not in phases
    assert "match_llm" not in phases
    assert phases[-1] == "summary"


def test_progress_reporter_llm_updates_percent() -> None:
    seen: list[int] = []
    plan = build_phase_plan(regenerate_fase1=False, skip_spacy=True, run_llm=True)
    reporter = ProgressReporter(plan, callback=lambda p: seen.append(p.percent))
    reporter.phase("match_llm")
    reporter.llm(5, 10)
    assert seen[-1] > seen[0]
