"""Add medication hash columns to Global / Unimed DataFrames."""

from __future__ import annotations

import pandas as pd
from depara.medication.normalizer import normalize_clinical_text

_HASH_COLS = [
    "medication_hash_id",
    "medication_normalized",
    "form_normalized",
    "route_normalized",
    "norm_skipped",
    "norm_skip_reason",
]


def _presentation_to_row(record) -> dict:
    return {
        "medication_hash_id": record.medication_hash_id,
        "medication_normalized": record.medication_normalized,
        "form_normalized": record.form_normalized,
        "route_normalized": record.route_normalized,
        "norm_skipped": record.skipped,
        "norm_skip_reason": record.skip_reason,
    }


def enrich_with_hash(
    df: pd.DataFrame,
    *,
    text_col: str,
    system: str,
    external_id_col: str | None = None,
) -> pd.DataFrame:
    out = df.copy()
    records = []
    for _, row in out.iterrows():
        text = row.get(text_col)
        ext = str(row[external_id_col]) if external_id_col else str(text).strip()
        records.append(
            normalize_clinical_text(
                str(text) if pd.notna(text) else "",
                system=system,
                external_id=ext,
            )
        )
    for col in _HASH_COLS:
        if col in ("norm_skipped",):
            out[col] = [r.skipped for r in records]
        elif col == "norm_skip_reason":
            out[col] = [r.skip_reason for r in records]
        else:
            out[col] = [getattr(r, col) for r in records]
    return out


def enrich_linhas_with_hash(df: pd.DataFrame, *, text_col: str = "linha_produto") -> pd.DataFrame:
    return enrich_with_hash(df, text_col=text_col, system="global")


def enrich_unimed_catalog_with_hash(
    df: pd.DataFrame,
    *,
    text_col: str = "desc_global",
    external_id_col: str = "cod_item",
) -> pd.DataFrame:
    return enrich_with_hash(
        df,
        text_col=text_col,
        system="unimed",
        external_id_col=external_id_col,
    )
