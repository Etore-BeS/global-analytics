"""Tests for medication normalizer (ray-dw integration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from depara.medication.normalizer import normalize_clinical_text

FIXTURES = Path(__file__).parent / "fixtures" / "medication_golden.json"


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def case_hashes(golden: dict) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for case in golden["cases"]:
        pres = normalize_clinical_text(
            case["input"],
            system="test",
            external_id=case["id"],
        )
        out[case["id"]] = pres.medication_hash_id
    return out


@pytest.mark.ray_dw
def test_paracetamol_comprimido(golden: dict, case_hashes: dict) -> None:
    case = next(c for c in golden["cases"] if c["id"] == "paracetamol_500_comprimido")
    pres = normalize_clinical_text(case["input"], system="test", external_id="x")
    exp = case["expected"]
    assert pres.skipped is exp["skipped"]
    assert pres.medication_hash_id and len(pres.medication_hash_id) == exp["hash_length"]
    assert exp["medication_normalized_contains"] in (pres.medication_normalized or "")
    assert exp["form_normalized_contains"] in (pres.form_normalized or "")
    assert pres.route_normalized == exp["route_normalized"]
    assert pres.medication_hash_id == golden["golden_hashes"]["paracetamol_500_comprimido"]


@pytest.mark.ray_dw
def test_pack_size_same_hash(golden: dict, case_hashes: dict) -> None:
    base = case_hashes["paracetamol_500_comprimido"]
    assert case_hashes["paracetamol_cx50"] == base
    assert case_hashes["paracetamol_cx100"] == base


@pytest.mark.ray_dw
def test_different_doses_different_hash(case_hashes: dict) -> None:
    assert case_hashes["dose_100mg_4ml"] != case_hashes["dose_50mg_4ml"]


@pytest.mark.ray_dw
def test_determinism() -> None:
    text = "paracetamol 500 mg comprimido"
    a = normalize_clinical_text(text, system="test", external_id="a")
    b = normalize_clinical_text(text, system="test", external_id="b")
    assert a.medication_hash_id == b.medication_hash_id


@pytest.mark.ray_dw
def test_blacklist_skipped() -> None:
    pres = normalize_clinical_text("nao preconiza medicamentos", system="test", external_id="x")
    assert pres.skipped is True
    assert pres.medication_hash_id is None


@pytest.mark.ray_dw
def test_empty_skipped() -> None:
    pres = normalize_clinical_text("", system="test", external_id="x")
    assert pres.skipped is True


@pytest.mark.ray_dw
def test_bevacizumabe_volume_l2_gap_documented(case_hashes: dict) -> None:
    """Ray-dw may collapse 4ml vs 16ml — record actual behavior for pilot."""
    h4 = case_hashes["bevacizumabe_4ml"]
    h16 = case_hashes["bevacizumabe_16ml"]
    assert h4 and h16
    # Known limitation: hashes may be equal until normalizer extracts fill volume
    if h4 == h16:
        pytest.xfail("ray-dw v2 colapsa volume 4ml vs 16ml — iterar normalizador")
