"""Tests for candidate signal tagging."""

from __future__ import annotations

import pandas as pd
from depara.medication.candidate_signals import build_enriched_candidates, fuzzy_score
from depara.medication.models import FUZZY_ALTA_THRESHOLD


def _catalog_row(
    cod: int,
    desc: str,
    *,
    h: str | None = "hash_a",
    vl: float = 100.0,
) -> dict:
    return {
        "cod_item": cod,
        "desc_global": desc,
        "texto_match": desc.lower(),
        "medication_hash_id": h,
        "vl_medio": vl,
        "vl_por_unidade": vl,
        "unidade": "un",
        "abc": "A",
        "norm_skipped": False,
        "medication_normalized": None,
        "form_normalized": None,
        "route_normalized": None,
    }


def test_fuzzy_score_range() -> None:
    assert fuzzy_score("paracetamol 500", "paracetamol 500 mg") > 0.5


def test_hash_match_only_when_equal_hash() -> None:
    catalog = pd.DataFrame(
        [
            _catalog_row(1, "paracetamol 500 mg comprimido", h="hash_a"),
            _catalog_row(2, "paracetamol 250 mg comprimido", h="hash_b"),
        ]
    )
    cands = build_enriched_candidates(
        linha_produto="PARACETAMOL 500 MG COMPRIMIDO",
        principio_ativo="PARACETAMOL",
        source_hash="hash_a",
        global_cost=10.0,
        catalog=catalog,
        top_k=5,
    )
    by_cod = {c.cod_item: c for c in cands}
    assert by_cod[1].hash_match is True
    assert by_cod[2].hash_match is False


def test_fuzzy_alta_threshold() -> None:
    catalog = pd.DataFrame([_catalog_row(1, "paracetamol 500 mg comprimido")])
    cands = build_enriched_candidates(
        linha_produto="PARACETAMOL 500 MG COMPRIMIDO",
        principio_ativo="PARACETAMOL",
        source_hash=None,
        global_cost=None,
        catalog=catalog,
        top_k=5,
    )
    assert len(cands) == 1
    c = cands[0]
    assert c.fuzzy_alta == (c.fuzzy_score is not None and c.fuzzy_score >= FUZZY_ALTA_THRESHOLD)


def test_preco_ok_in_band() -> None:
    catalog = pd.DataFrame([_catalog_row(1, "item a", vl=100.0)])
    cands = build_enriched_candidates(
        linha_produto="ITEM A",
        principio_ativo="ITEM",
        source_hash=None,
        global_cost=80.0,
        catalog=catalog,
        top_k=5,
    )
    assert cands[0].preco_ok is True

    cands_bad = build_enriched_candidates(
        linha_produto="ITEM A",
        principio_ativo="ITEM",
        source_hash=None,
        global_cost=500.0,
        catalog=catalog,
        top_k=5,
    )
    assert cands_bad[0].preco_ok is False
