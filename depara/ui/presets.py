"""Presets de mapeamento para o wizard Streamlit."""

from __future__ import annotations

from dataclasses import dataclass

from depara.api.schemas import JobCreateConfig, SideRequest
from depara.contract.models import Fase1Config, Granularity, MatchConfig, PricePolicy, StockFilter


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    description: str
    needs_catalog: bool
    subject: SideRequest
    reference: SideRequest


PRESETS: dict[str, Preset] = {
    "cost_stock_unimed": Preset(
        id="cost_stock_unimed",
        label="Global custo/estoque × Unimed ABC",
        description="Snapshot de custo/estoque Global comparado com Curva ABC Unimed.",
        needs_catalog=False,
        subject=SideRequest(
            template="global_cost_stock",
            granularity="auto",
            price_policy=PricePolicy(
                mode="dual",
                primary_field="cost_real",
                secondary_field="cost_last_entry",
                primary_aggregation="median",
                reference_aggregation="min",
                stock_filter=StockFilter(column="stock_qty", min=1),
            ),
        ),
        reference=SideRequest(template="unimed_abc"),
    ),
    "purchases_unimed": Preset(
        id="purchases_unimed",
        label="Global compras históricas × Unimed ABC",
        description="Histórico de compras Global; catálogo BASE_LINHA_PRODUTOS recomendado.",
        needs_catalog=True,
        subject=SideRequest(template="global_purchases", granularity="auto"),
        reference=SideRequest(template="unimed_abc"),
    ),
    "custom": Preset(
        id="custom",
        label="Personalizado",
        description="Mapeamento manual de colunas canônicas.",
        needs_catalog=False,
        subject=SideRequest(template="custom", granularity="auto"),
        reference=SideRequest(template="custom"),
    ),
}

DEFAULT_PRESET_ID = "cost_stock_unimed"

SUBJECT_CANONICAL_FIELDS = (
    "display_text",
    "product_code",
    "price_amount",
    "cost_real",
    "cost_last_entry",
    "stock_qty",
    "pack_description",
    "clinical_unit",
    "sale_unit",
    "principio_ativo",
    "brand",
    "entry_date",
)

REFERENCE_CANONICAL_FIELDS = (
    "canonical_id",
    "display_text",
    "price_amount",
    "clinical_unit",
    "volume_previsto",
    "abc_class",
    "policy",
)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def build_job_config(
    preset: Preset,
    *,
    subject_columns: dict[str, str] | None = None,
    reference_columns: dict[str, str] | None = None,
    granularity: Granularity = "auto",
    skip_match: bool = True,
    regenerate_fase1: bool = False,
    skip_spacy: bool = True,
    env_overrides: dict[str, str] | None = None,
) -> JobCreateConfig:
    subject = preset.subject.model_copy(deep=True)
    reference = preset.reference.model_copy(deep=True)
    if preset.id == "custom":
        subject.columns = subject_columns or {}
        reference.columns = reference_columns or {}
        subject.granularity = granularity
    elif subject_columns:
        subject.columns = {**subject.columns, **subject_columns}
    if reference_columns and preset.id != "custom":
        reference.columns = {**reference.columns, **reference_columns}
    return JobCreateConfig(
        subject=subject,
        reference=reference,
        match=MatchConfig(skip_match=skip_match),
        fase1=Fase1Config(regenerate=regenerate_fase1, skip_spacy=skip_spacy),
        env_overrides=env_overrides or {},
    )
