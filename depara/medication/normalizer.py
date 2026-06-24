"""Facade over ray-dw medication normalization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from depara.medication.models import NORMALIZATION_VERSION, CatalogReference, ClinicalPresentation
from depara.medication.ray_dw import ensure_ray_dw_path

if TYPE_CHECKING:
    from normalization.medication.models import NormalizationResult
    from normalization.service import MedicationNormalizationService

_SVC: MedicationNormalizationService | None = None


def get_service() -> MedicationNormalizationService:
    global _SVC
    if _SVC is None:
        ensure_ray_dw_path()
        from normalization.service import build_default_normalization_service

        _SVC = build_default_normalization_service()
    return _SVC


def _route_from_form(form_normalized: str | None) -> str | None:
    if not form_normalized:
        return None
    ensure_ray_dw_path()
    from normalization.via_administrativa import normalize_via_from_forma_farmaceutica

    route = normalize_via_from_forma_farmaceutica(form_normalized)
    return route or None


def _components_from_result(norm: NormalizationResult) -> list[dict]:
    if norm.component_array:
        return list(norm.component_array)
    return []


def normalize_clinical_text(
    text: str,
    *,
    system: str,
    external_id: str,
) -> ClinicalPresentation:
    raw = (text or "").strip()
    ref = CatalogReference(
        system=system,
        external_id=external_id,
        display_name=raw or None,
    )
    if not raw:
        return ClinicalPresentation(
            display_text=raw,
            catalog_ref=ref,
            skipped=True,
            skip_reason="empty_text",
        )

    try:
        norm = get_service().normalize_unstructured(raw)
    except Exception as exc:
        return ClinicalPresentation(
            display_text=raw,
            catalog_ref=ref,
            skipped=True,
            skip_reason=f"normalize_error:{exc.__class__.__name__}",
        )

    if norm is None or norm.skipped:
        return ClinicalPresentation(
            display_text=raw,
            catalog_ref=ref,
            skipped=True,
            skip_reason=norm.skip_reason if norm else "normalize_returned_none",
        )

    route = _route_from_form(norm.form_normalized)
    return ClinicalPresentation(
        medication_hash_id=norm.medication_hash_id,
        normalization_version=NORMALIZATION_VERSION,
        medication_normalized=norm.medication_normalized,
        form_normalized=norm.form_normalized,
        route_normalized=route,
        display_text=raw,
        catalog_ref=ref,
        components=_components_from_result(norm),
        skipped=False,
    )
