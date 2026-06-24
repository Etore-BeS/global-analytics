"""Gate automático pós-agente para matches de depara."""

from __future__ import annotations

from dataclasses import dataclass

from depara.llm.schemas import MatchDecision
from depara.medication.models import EnrichedCandidate
from depara.price_sanity import prices_compatible

MIN_AGENT_CONFIDENCE = 0.75


@dataclass(frozen=True)
class AuditResult:
    passed: bool
    flags: list[str]
    reason: str | None = None


def audit_match(
    *,
    decision: MatchDecision,
    cod_item: int | None,
    confidence: float,
    source_skipped: bool,
    global_cost: float | None,
    unimed_price: float | None,
    chosen: EnrichedCandidate | None,
) -> AuditResult:
    if decision != MatchDecision.MATCH:
        return AuditResult(passed=False, flags=[], reason="agent_no_match")

    flags: list[str] = []
    if source_skipped:
        return AuditResult(
            passed=False,
            flags=["norm_skipped"],
            reason="Linha Global não normalizada como medicamento",
        )
    if confidence < MIN_AGENT_CONFIDENCE:
        return AuditResult(
            passed=False,
            flags=["low_confidence"],
            reason=f"Confiança do agente {confidence:.2f} < {MIN_AGENT_CONFIDENCE}",
        )
    if global_cost and unimed_price and not prices_compatible(global_cost, unimed_price):
        flags.append("preco_depara_incompativel")
    if chosen and chosen.hash_match:
        flags.append("hash_match_signal")
    if chosen and chosen.fuzzy_alta:
        flags.append("fuzzy_alta_signal")
    if chosen and chosen.preco_ok:
        flags.append("preco_ok_signal")

    return AuditResult(passed=True, flags=flags)
