"""Tests for post-agent reviewer gate."""

from __future__ import annotations

from depara.llm.schemas import MatchDecision
from depara.medication.models import EnrichedCandidate
from depara.medication.reviewer import audit_match


def _chosen(**kwargs) -> EnrichedCandidate:
    base = dict(
        cod_item=1,
        desc_global="test",
        hash_match=False,
        fuzzy_alta=False,
        preco_ok=True,
        vl_medio=100.0,
        vl_por_unidade=100.0,
    )
    base.update(kwargs)
    return EnrichedCandidate(**base)


def test_rejects_low_confidence() -> None:
    result = audit_match(
        decision=MatchDecision.MATCH,
        cod_item=1,
        confidence=0.5,
        source_skipped=False,
        global_cost=10.0,
        unimed_price=12.0,
        chosen=_chosen(),
    )
    assert result.passed is False
    assert "low_confidence" in result.flags


def test_rejects_price_incompatible() -> None:
    result = audit_match(
        decision=MatchDecision.MATCH,
        cod_item=1,
        confidence=0.9,
        source_skipped=False,
        global_cost=10.0,
        unimed_price=100.0,
        chosen=_chosen(preco_ok=False),
    )
    assert result.passed is True
    assert "preco_depara_incompativel" in result.flags


def test_passes_with_signals() -> None:
    result = audit_match(
        decision=MatchDecision.MATCH,
        cod_item=1,
        confidence=0.95,
        source_skipped=False,
        global_cost=10.0,
        unimed_price=11.0,
        chosen=_chosen(hash_match=True, fuzzy_alta=True, preco_ok=True),
    )
    assert result.passed is True
    assert "hash_match_signal" in result.flags
