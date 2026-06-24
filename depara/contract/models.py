"""Modelos canônicos para ingest de planilhas A×B."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PriceBasis = Literal["per_clinical_unit", "per_pack", "unknown"]
Granularity = Literal["auto", "sku", "clinical_line"]
PriceMode = Literal["single", "dual"]
Aggregation = Literal["min", "max", "mean", "median", "last"]
TemplateId = Literal[
    "custom",
    "global_purchases",
    "global_catalog",
    "global_cost_stock",
    "unimed_abc",
]


class StockFilter(BaseModel):
    column: str = "stock_qty"
    min: float = 1


class PricePolicy(BaseModel):
    mode: PriceMode = "single"
    primary_field: str = "price_amount"
    secondary_field: str | None = "cost_last_entry"
    primary_aggregation: Aggregation = "median"
    reference_aggregation: Aggregation = "min"
    stock_filter: StockFilter | None = None


class SideConfig(BaseModel):
    path: Path
    template: TemplateId = "global_purchases"
    columns: dict[str, str] = Field(default_factory=dict)
    catalog_enrichment: Path | None = None
    granularity: Granularity = "auto"
    price_policy: PricePolicy | None = None


class MatchConfig(BaseModel):
    limit: int | None = None
    model: str | None = None
    confianca_filter: str | None = None
    run_all: bool = False
    skip_match: bool = False
    use_cache: bool = True


class Fase1Config(BaseModel):
    regenerate: bool = False
    skip_spacy: bool = False


class JobConfig(BaseModel):
    side_a: SideConfig
    side_b: SideConfig
    match: MatchConfig = Field(default_factory=MatchConfig)
    fase1: Fase1Config = Field(default_factory=Fase1Config)
    env_overrides: dict[str, str] = Field(default_factory=dict)
    output_dir: Path = Path("exports/run")
    fase1_path: Path | None = None
    matches_path: Path | None = None


class CanonicalRow(BaseModel):
    canonical_id: str
    display_text: str
    price_amount: float | None = None
    price_basis: PriceBasis = "unknown"
    pack_qty: int | None = None
    clinical_unit: str | None = None
    pack_description: str | None = None
    sale_unit: str | None = None
    principio_ativo: str | None = None
    volume_previsto: float | None = None
    abc_class: str | None = None
    pack_inferred_low_confidence: bool = False
