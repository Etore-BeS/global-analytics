"""Validação de mapeamento coluna→campo canônico antes do pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd
from depara.contract.ingest import _read_table, ingest_side_a, ingest_side_b
from depara.contract.models import Granularity, PricePolicy, SideConfig, StockFilter
from depara.contract.templates import resolve_columns

SideRole = Literal["subject", "reference"]


@dataclass
class MappingIssue:
    field: str
    message: str
    expected_column: str | None = None


@dataclass
class SideValidationResult:
    role: SideRole
    valid: bool
    granularity: Granularity | None = None
    issues: list[MappingIssue] = field(default_factory=list)
    preview: list[dict] = field(default_factory=list)
    row_count: int = 0


@dataclass
class MappingValidationResult:
    valid: bool
    subject: SideValidationResult
    reference: SideValidationResult

    @property
    def issues(self) -> list[MappingIssue]:
        return self.subject.issues + self.reference.issues


SUBJECT_IDENTITY_FIELDS = ("display_text", "product_code")
SUBJECT_PRICE_SINGLE = ("price_amount",)
SUBJECT_PRICE_DUAL = ("cost_real", "cost_last_entry")
REFERENCE_REQUIRED = ("canonical_id", "display_text", "price_amount")


def _resolved(side: SideConfig) -> dict[str, str]:
    return resolve_columns(side.template, side.columns)


def _physical_columns(path: Path) -> list[str]:
    return list(_read_table(path).columns)


def detect_granularity(df: pd.DataFrame, resolved: dict[str, str]) -> Granularity:
    display_src = resolved.get("display_text")
    product_src = resolved.get("product_code")
    if not display_src or display_src not in df.columns:
        return "clinical_line"
    if not product_src or product_src not in df.columns:
        return "clinical_line"
    grouped = df.groupby(display_src)[product_src].nunique()
    if (grouped > 1).any():
        return "sku"
    if len(df) > len(grouped):
        return "sku"
    return "clinical_line"


def effective_price_policy(side: SideConfig, resolved: dict[str, str]) -> PricePolicy:
    if side.price_policy is not None:
        return side.price_policy
    if "cost_real" in resolved and "cost_last_entry" in resolved:
        return PricePolicy(
            mode="dual",
            primary_field="cost_real",
            secondary_field="cost_last_entry",
            primary_aggregation="median",
            reference_aggregation="min",
            stock_filter=StockFilter(column="stock_qty", min=1),
        )
    return PricePolicy(mode="single", primary_field="price_amount", primary_aggregation="median")


def _missing_fields(
    resolved: dict[str, str],
    physical: list[str],
    required: tuple[str, ...],
) -> list[MappingIssue]:
    issues: list[MappingIssue] = []
    for canonical in required:
        src = resolved.get(canonical)
        if not src:
            issues.append(
                MappingIssue(
                    field=canonical,
                    message=f"Campo canônico '{canonical}' não mapeado",
                )
            )
        elif src not in physical:
            issues.append(
                MappingIssue(
                    field=canonical,
                    message=f"Coluna '{src}' não encontrada na planilha",
                    expected_column=src,
                )
            )
    return issues


def validate_subject_side(side: SideConfig) -> SideValidationResult:
    resolved = _resolved(side)
    physical = _physical_columns(side.path)
    issues = _missing_fields(resolved, physical, ("display_text",))

    policy = effective_price_policy(side, resolved)
    if policy.mode == "dual":
        issues.extend(_missing_fields(resolved, physical, SUBJECT_PRICE_DUAL))
        if policy.stock_filter:
            issues.extend(
                _missing_fields(resolved, physical, (policy.stock_filter.column,))
            )
    else:
        issues.extend(_missing_fields(resolved, physical, SUBJECT_PRICE_SINGLE))

    granularity = side.granularity
    preview: list[dict] = []
    row_count = 0

    if not issues:
        raw = _read_table(side.path)
        row_count = len(raw)
        if side.granularity == "auto":
            granularity = detect_granularity(raw, resolved)
        elif side.granularity != "auto":
            granularity = side.granularity
        if granularity == "sku":
            issues.extend(_missing_fields(resolved, physical, ("product_code",)))
        try:
            df = ingest_side_a(side)
            preview = df.head(5).fillna("").astype(str).to_dict(orient="records")
        except Exception as exc:  # noqa: BLE001
            issues.append(MappingIssue(field="ingest", message=str(exc)))

    return SideValidationResult(
        role="subject",
        valid=not issues,
        granularity=granularity if granularity != "auto" else None,
        issues=issues,
        preview=preview,
        row_count=row_count,
    )


def validate_reference_side(side: SideConfig) -> SideValidationResult:
    resolved = _resolved(side)
    physical = _physical_columns(side.path)
    issues = _missing_fields(resolved, physical, REFERENCE_REQUIRED)

    preview: list[dict] = []
    row_count = 0

    if not issues:
        raw = _read_table(side.path)
        row_count = len(raw)
        id_src = resolved["canonical_id"]
        dupes = raw[id_src].duplicated().sum()
        if dupes:
            issues.append(
                MappingIssue(
                    field="canonical_id",
                    message=f"{dupes} canonical_id duplicado(s) na planilha de referência",
                    expected_column=id_src,
                )
            )
        try:
            df = ingest_side_b(side)
            preview = df.head(5).fillna("").astype(str).to_dict(orient="records")
        except Exception as exc:  # noqa: BLE001
            issues.append(MappingIssue(field="ingest", message=str(exc)))

    return SideValidationResult(
        role="reference",
        valid=not issues,
        issues=issues,
        preview=preview,
        row_count=row_count,
    )


def validate_side_mapping(
    subject: SideConfig,
    reference: SideConfig,
) -> MappingValidationResult:
    subj = validate_subject_side(subject)
    ref = validate_reference_side(reference)
    if subj.granularity is None and subj.valid:
        subj.granularity = detect_granularity(
            _read_table(subject.path), _resolved(subject)
        )
    return MappingValidationResult(
        valid=subj.valid and ref.valid,
        subject=subj,
        reference=ref,
    )
