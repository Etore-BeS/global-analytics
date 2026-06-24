"""Pydantic models for medication contract pilot (L0 + L2)."""

from __future__ import annotations

from pydantic import BaseModel, Field

NORMALIZATION_VERSION = "v2_canonical"
FUZZY_ALTA_THRESHOLD = 0.75  # alinhado a assign_confidence (primary >= 0.75 + acordo métodos)


class CatalogReference(BaseModel):
    system: str
    entity_type: str = "clinical_presentation"
    external_id: str
    display_name: str | None = None


class ClinicalPresentation(BaseModel):
    medication_hash_id: str | None = None
    normalization_version: str = NORMALIZATION_VERSION
    medication_normalized: str | None = None
    form_normalized: str | None = None
    route_normalized: str | None = None
    display_text: str
    catalog_ref: CatalogReference
    components: list[dict] = Field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None
    pack_inferred_low_confidence: bool = False


class EnrichedCandidate(BaseModel):
    cod_item: int
    desc_global: str
    medication_hash_id: str | None = None
    hash_match: bool = False
    fuzzy_score: float | None = None
    fuzzy_alta: bool = False
    preco_ok: bool = False
    vl_medio: float | None = None
    vl_por_unidade: float | None = None
    unidade: str | None = None
    abc: str | None = None
    medication_normalized: str | None = None
    form_normalized: str | None = None
    route_normalized: str | None = None
