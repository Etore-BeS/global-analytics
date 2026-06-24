"""Mapeamento de colunas por template de planilha."""

from __future__ import annotations

from depara.contract.models import TemplateId

TEMPLATE_COLUMNS: dict[TemplateId, dict[str, str]] = {
    "custom": {},
    "global_purchases": {
        "display_text": "LINHA_PRODUTO",
        "price_amount": "CUSTO_ENTRADA",
        "principio_ativo": "PRINCIPIO_ATIVO",
        "product_code": "COD_PRODUTO",
        "product_desc": "DESCRICAO_PRODUTO",
        "entry_date": "DT_ENTRADA",
    },
    "global_catalog": {
        "display_text": "LINHA_PRODUTO",
        "product_code": "CODPROD",
        "product_desc": "PRODUTO",
        "pack_description": "EMBALAGEM",
        "clinical_unit": "UNIDADE",
        "sale_unit": "UNIDADE_VENDA",
    },
    "global_cost_stock": {
        "display_text": "LINHA_PRODUTO",
        "product_code": "CODPROD",
        "product_desc": "PRODUTO",
        "pack_description": "EMBALAGEM",
        "clinical_unit": "UNIDADE",
        "sale_unit": "UNIDADE_VENDA",
        "cost_real": "CUSTOREAL",
        "cost_last_entry": "CUSTOULTENT",
        "stock_qty": "ESTOQUE_DISPONIVEL",
        "brand": "MARCA",
    },
    "unimed_abc": {
        "canonical_id": "Cod Item",
        "display_text": "Desc Item",
        "price_amount": "VL Médio (R$)",
        "clinical_unit": "Un",
        "volume_previsto": "Prev Mês",
        "abc_class": "ABC",
        "policy": "Política",
    },
}


def resolve_columns(template: TemplateId, overrides: dict[str, str]) -> dict[str, str]:
    base = dict(TEMPLATE_COLUMNS[template])
    base.update(overrides)
    return base
