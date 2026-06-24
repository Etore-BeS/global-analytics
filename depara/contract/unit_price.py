"""Motor de preço unitário L2 (bilateral)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from depara.contract.models import PriceBasis
from depara.price_units import infer_pack_qty, parse_pack

PackSource = Literal["structured", "regex", "default"]
AmountBasis = Literal["per_clinical_unit", "per_pack", "auto"]


@dataclass(frozen=True)
class UnitPriceResult:
    unit_price: float | None
    pack_qty: int
    price_basis: PriceBasis
    pack_inferred_low_confidence: bool
    clinical_unit: str | None = None
    sale_unit: str | None = None


def infer_price_basis(
    *,
    sale_unit: str | None,
    pack_qty: int,
    pack_description: str | None,
) -> PriceBasis:
    su = (sale_unit or "").strip().upper()
    if su in {"CX", "PC", "KIT", "PCT", "PACOTE"} and pack_qty > 1:
        return "per_pack"
    if pack_qty > 1 and pack_description:
        return "per_pack"
    return "per_clinical_unit"


def to_unit_price(
    amount: float | None,
    *,
    amount_basis: AmountBasis = "auto",
    pack_description: str | None = None,
    clinical_unit: str | None = None,
    sale_unit: str | None = None,
    display_text: str | None = None,
) -> UnitPriceResult:
    if amount is None or amount <= 0:
        return UnitPriceResult(
            unit_price=None,
            pack_qty=1,
            price_basis="unknown",
            pack_inferred_low_confidence=False,
            clinical_unit=clinical_unit,
            sale_unit=sale_unit,
        )

    structured = parse_pack(pack_description) if pack_description else None
    if structured and structured.source == "structured" and structured.pack_qty > 1:
        pack_qty = structured.pack_qty
        low_conf = False
        cu = structured.clinical_unit or clinical_unit
        su = structured.sale_unit or sale_unit
    else:
        text = " ".join(
            x for x in (pack_description, display_text, clinical_unit or "") if x
        )
        pack_qty = infer_pack_qty(text, clinical_unit)
        low_conf = pack_qty == 1 and bool(pack_description)
        cu = clinical_unit
        su = sale_unit

    if amount_basis == "per_clinical_unit":
        return UnitPriceResult(
            unit_price=float(amount),
            pack_qty=pack_qty,
            price_basis="per_clinical_unit",
            pack_inferred_low_confidence=low_conf,
            clinical_unit=cu,
            sale_unit=su,
        )

    basis = infer_price_basis(
        sale_unit=su,
        pack_qty=pack_qty,
        pack_description=pack_description,
    )
    if amount_basis == "per_pack" or (basis == "per_pack" and pack_qty > 1):
        return UnitPriceResult(
            unit_price=float(amount / pack_qty),
            pack_qty=pack_qty,
            price_basis=basis,
            pack_inferred_low_confidence=low_conf,
            clinical_unit=cu,
            sale_unit=su,
        )
    return UnitPriceResult(
        unit_price=float(amount),
        pack_qty=1,
        price_basis="per_clinical_unit",
        pack_inferred_low_confidence=low_conf,
        clinical_unit=cu,
        sale_unit=su,
    )
